"""Per-run knowledge graph (molecules + reactions) and AND/OR route search."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import networkx as nx
from rdkit.Chem import Descriptors

from .chem import rdkit_utils as rd
from .chem.critic import CriticResult
from .models import Evidence, Route, RouteStep


@dataclass
class Molecule:
    id: str                        # InChIKey, or "unresolved:<name>"
    name: str
    smiles: str | None
    names: set[str] = field(default_factory=set)
    cid: int | None = None
    purchasable: bool = False
    purchasable_basis: str = "none"
    purchasable_reason: str = ""
    is_target: bool = False

    @property
    def resolved(self) -> bool:
        return self.smiles is not None

    def to_event(self) -> dict:
        status = ("target" if self.is_target else "unresolved" if not self.resolved
                  else "purchasable" if self.purchasable else "intermediate")
        return {"id": self.id, "smiles": self.smiles or "", "name": self.name, "status": status,
                "purchasable": self.purchasable, "depth": None}


@dataclass
class Reaction:
    id: str
    reactants: list[str]
    product: str
    byproducts: list[str] = field(default_factory=list)
    reagents: list[str] = field(default_factory=list)            # names
    reagent_smiles: dict[str, str] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)
    critic: CriticResult | None = None
    label: str | None = None                                     # literature | proposed | rejected
    confidence: float | None = None
    origin: str = "literature"                                   # literature | proposed

    def to_event(self) -> dict:
        return {"id": self.id, "reactants": self.reactants, "products": [self.product] + self.byproducts,
                "reagents": self.reagents, "evidence_ids": self.evidence, "label": self.label,
                "critic": self.critic.verdict if self.critic else None, "confidence": self.confidence}


GAP_COST = 10.0


class RunGraph:
    def __init__(self):
        self.molecules: dict[str, Molecule] = {}
        self.reactions: dict[str, Reaction] = {}
        self.evidence: dict[str, Evidence] = {}
        self.citation_status: dict[str, str] = {}                 # evidence id -> pass/warn/fail

    # ---------------------------------------------------------- queries
    def producers(self, mol_id: str, include_rejected: bool = False) -> list[Reaction]:
        return [r for r in self.reactions.values()
                if r.product == mol_id and (include_rejected or r.label != "rejected")]

    def independent_sources(self, rx: Reaction) -> int:
        return len({urlsplit(self.evidence[e].source_url).netloc for e in rx.evidence if e in self.evidence})

    def nx_graph(self) -> nx.DiGraph:
        g = nx.DiGraph()
        for m in self.molecules.values():
            g.add_node(m.id, kind="molecule")
        for r in self.reactions.values():
            g.add_node(r.id, kind="reaction")
            for x in r.reactants:
                g.add_edge(x, r.id, kind="reactant_of")
            g.add_edge(r.id, r.product, kind="produces")
        return g

    # ---------------------------------------------------------- route search
    def step_cost(self, r: Reaction) -> float:
        warns = sum(1 for c in (r.critic.checks if r.critic else []) if c.status == "warn")
        verified = sum(1 for e in r.evidence if self.citation_status.get(e) == "pass")
        cost = 1.0 - 0.2 * min(self.independent_sources(r), 3) - 0.15 * min(verified, 2) + 0.3 * warns
        if r.origin == "proposed":
            cost += 0.8
        return max(cost, 0.15)

    def _best(self, mol_id: str, depth: int, max_depth: int, visiting: frozenset,
              exclude_first: str | None = None) -> tuple[float, dict]:
        m = self.molecules.get(mol_id)
        if m and m.purchasable:
            return 0.0, {"mol": mol_id, "leaf": "purchasable"}
        if depth >= max_depth:
            return GAP_COST, {"mol": mol_id, "leaf": "gap", "why": "max depth"}
        best: tuple[float, dict] = (GAP_COST, {"mol": mol_id, "leaf": "gap", "why": "no known synthesis"})
        for r in self.producers(mol_id):
            if r.id == exclude_first or any(x in visiting for x in r.reactants):
                continue
            total, kids = self.step_cost(r), []
            for x in r.reactants:
                c, sub = self._best(x, depth + 1, max_depth, visiting | {mol_id})
                total += c
                kids.append(sub)
            if total < best[0]:
                best = (total, {"mol": mol_id, "rxn": r.id, "children": kids})
        return best

    def find_routes(self, target_id: str, max_depth: int = 6, k: int = 3) -> list[Route]:
        candidates: list[tuple[float, dict]] = []
        for r in self.producers(target_id):
            total, kids = self.step_cost(r), []
            for x in r.reactants:
                c, sub = self._best(x, 1, max_depth, frozenset({target_id}))
                total += c
                kids.append(sub)
            candidates.append((total, {"mol": target_id, "rxn": r.id, "children": kids}))
        if not candidates:
            candidates = [(GAP_COST, {"mol": target_id, "leaf": "gap", "why": "no known synthesis"})]
        candidates.sort(key=lambda c: c[0])
        routes, seen = [], set()
        for cost, tree in candidates:
            steps, leaves, gaps = self._flatten(tree)
            sig = tuple(s.reaction_id for s in steps)
            if sig in seen:
                continue
            seen.add(sig)
            routes.append(Route(route_id=f"route-{len(routes) + 1}", rank=len(routes) + 1, steps=steps,
                                score=round(1 / (1 + cost), 4), complete=not gaps, leaves=leaves, gaps=gaps,
                                metrics=self.metrics(steps, tree)))
            if len(routes) >= k:
                break
        return routes

    def _flatten(self, tree: dict) -> tuple[list[RouteStep], list[str], list[str]]:
        steps: list[RouteStep] = []
        leaves: list[str] = []
        gaps: list[str] = []

        def visit(n: dict):
            if "rxn" not in n:
                (gaps if n["leaf"] == "gap" else leaves).append(n["mol"])
                return
            for c in n["children"]:
                visit(c)
            r = self.reactions[n["rxn"]]
            if r.id not in {s.reaction_id for s in steps}:
                steps.append(RouteStep(reaction_id=r.id, product=r.product, reactants=r.reactants,
                                       label=r.label or "literature",
                                       critic=r.critic.verdict if r.critic else "pending",
                                       evidence_ids=r.evidence))
        visit(tree)
        return steps, list(dict.fromkeys(leaves)), list(dict.fromkeys(gaps))

    def metrics(self, steps: list[RouteStep], tree: dict) -> dict:
        def depth(n):
            return 0 if "rxn" not in n else 1 + max((depth(c) for c in n["children"]), default=0)
        ae = []
        for s in steps:
            p = self.molecules.get(s.product)
            rs = [self.molecules.get(x) for x in s.reactants]
            if p and p.smiles and all(r and r.smiles for r in rs):
                mw_p = Descriptors.MolWt(rd.parse(p.smiles))
                mw_r = sum(Descriptors.MolWt(rd.parse(r.smiles)) for r in rs)
                ae.append(min(1.0, mw_p / mw_r) if mw_r else None)
        ae = [a for a in ae if a is not None]
        return {"steps": len(steps), "longest_linear_sequence": depth(tree),
                "atom_economy_per_step": [round(a, 3) for a in ae],
                "mean_atom_economy": round(sum(ae) / len(ae), 3) if ae else None,
                "overall_atom_economy": round(math.prod(ae), 3) if ae else None}
