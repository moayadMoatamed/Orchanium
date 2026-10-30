"""Per-run knowledge graph.

Nodes
  Molecule   id = InChIKey; roles: target | precursor | clue
  Reaction   kind = hypothesis (a proposed cut) | observed (built from clues)
  Clue       the raw observation (any source), attached to one observed reaction
Edges
  reactant_of / produces      molecule <-> reaction
  evidence_for                clue -> observed reaction
  precedent_for (scored)      observed reaction -> hypothesis reaction
  similar_to (Tanimoto)       query molecule <-> clue molecule
Everything an agent or the UI needs is derived from these."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from pydantic import BaseModel, Field
from rdkit.Chem import Descriptors

from .chem import rdkit_utils as rd
from .chem.critic import CriticResult
from .chem.similarity import PrecedentScore, precedent_score, tanimoto
from .models import Clue

GRADE_COST = {"direct": 0.2, "analog": 0.5, "weak": 1.2, "none": 2.5}
GAP_COST = 4.0


@dataclass
class Molecule:
    id: str
    smiles: str
    name: str
    roles: set[str] = field(default_factory=set)
    known: bool = False
    cid: int | None = None
    purchasable: bool = False
    purchasable_basis: str = "none"
    purchasable_reason: str = ""

    def to_event(self) -> dict:
        return {"id": self.id, "smiles": self.smiles, "name": self.name, "roles": sorted(self.roles),
                "known": self.known, "cid": self.cid, "purchasable": self.purchasable,
                "purchasable_basis": self.purchasable_basis}


@dataclass
class Reaction:
    id: str
    kind: str                                     # hypothesis | observed
    reactants: list[str]
    product: str
    byproducts: list[str] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)
    origin: str = ""                              # template | agent | <clue source>
    clue_ids: list[str] = field(default_factory=list)
    depth: int | None = None
    critic: CriticResult | None = None

    def to_event(self) -> dict:
        return {"id": self.id, "kind": self.kind, "reactants": self.reactants,
                "products": [self.product] + self.byproducts, "classes": self.classes, "origin": self.origin,
                "clue_ids": self.clue_ids, "depth": self.depth,
                "critic": self.critic.verdict if self.critic else None}


@dataclass
class Precedent:
    observed_id: str
    hypothesis_id: str
    score: PrecedentScore
    outcome: str                                  # success | failure


class RouteStep(BaseModel):
    hypothesis_id: str
    grade: str
    best_precedent: str | None = None
    precedent_score: float | None = None
    failures: int = 0


class Route(BaseModel):
    route_id: str
    rank: int
    steps: list[RouteStep]                        # starting materials -> target
    cost: float
    leaves: list[str]
    gaps: list[str] = Field(default_factory=list)
    metrics: dict = Field(default_factory=dict)


class KnowledgeGraph:
    def __init__(self):
        self.molecules: dict[str, Molecule] = {}
        self.reactions: dict[str, Reaction] = {}
        self.clues: dict[str, Clue] = {}
        self.clue_reaction: dict[str, str] = {}
        self.citation_status: dict[str, str] = {}
        self.precedents: dict[str, list[Precedent]] = {}
        self.target_id: str | None = None

    # ------------------------------------------------------------- lookups
    def hypotheses(self) -> list[Reaction]:
        return [r for r in self.reactions.values() if r.kind == "hypothesis"]

    def observed(self) -> list[Reaction]:
        return [r for r in self.reactions.values() if r.kind == "observed"]

    def producers(self, mol_id: str, kind: str = "hypothesis") -> list[Reaction]:
        return [r for r in self.reactions.values() if r.product == mol_id and r.kind == kind]

    def smiles(self, mol_id: str) -> str:
        return self.molecules[mol_id].smiles

    # ------------------------------------------------------------- precedents
    def link_precedents(self, hyp_ids: list[str] | None = None, keep: int = 12) -> None:
        """(Re)score every observed reaction against the given hypotheses."""
        hyps = [self.reactions[h] for h in hyp_ids] if hyp_ids else self.hypotheses()
        obs = self.observed()
        for h in hyps:
            hr = [self.smiles(x) for x in h.reactants]
            scored = []
            for o in obs:
                s = precedent_score([self.smiles(x) for x in o.reactants], self.smiles(o.product), o.classes,
                                    hr, self.smiles(h.product), h.classes)
                if s.grade != "none":
                    outcome = ("failure" if o.clue_ids and all(self.clues[c].outcome == "failure"
                                                               for c in o.clue_ids) else "success")
                    scored.append(Precedent(o.id, h.id, s, outcome))
            scored.sort(key=lambda p: p.score.score, reverse=True)
            self.precedents[h.id] = scored[:keep]

    def grade(self, hyp_id: str) -> RouteStep:
        h = self.reactions[hyp_id]
        if h.critic and h.critic.verdict == "block":
            return RouteStep(hypothesis_id=hyp_id, grade="blocked")
        precs = self.precedents.get(hyp_id, [])
        good = [p for p in precs if p.outcome == "success"]
        fails = sum(1 for p in precs if p.outcome == "failure" and p.score.grade in ("direct", "analog"))
        best = good[0] if good else None
        return RouteStep(hypothesis_id=hyp_id, grade=best.score.grade if best else "none",
                         best_precedent=best.observed_id if best else None,
                         precedent_score=best.score.score if best else None, failures=fails)

    def similar_molecules(self, mol_id: str, min_sim: float = 0.4, k: int = 8) -> list[tuple[str, float]]:
        s = self.smiles(mol_id)
        sims = [(m.id, tanimoto(s, m.smiles)) for m in self.molecules.values() if m.id != mol_id]
        return sorted([x for x in sims if x[1] >= min_sim], key=lambda x: -x[1])[:k]

    # ------------------------------------------------------------- routes (AND/OR search over hypotheses)
    def _best(self, mol_id: str, visiting: frozenset, depth: int, max_depth: int) -> tuple[float, dict]:
        m = self.molecules[mol_id]
        if m.purchasable and m.id != self.target_id:
            return 0.0, {"mol": mol_id, "leaf": "purchasable"}
        best = (GAP_COST, {"mol": mol_id, "leaf": "gap"})
        if depth >= max_depth:
            return best
        for h in self.producers(mol_id):
            step = self.grade(h.id)
            if step.grade == "blocked" or any(x in visiting for x in h.reactants):
                continue
            total = GRADE_COST[step.grade] + 0.6 * step.failures
            kids = []
            for x in h.reactants:
                c, sub = self._best(x, visiting | {mol_id}, depth + 1, max_depth)
                total += c
                kids.append(sub)
            if total < best[0]:
                best = (total, {"mol": mol_id, "rxn": h.id, "step": step, "children": kids})
        return best

    def routes(self, k: int = 3, max_depth: int = 6) -> list[Route]:
        if not self.target_id:
            return []
        cands = []
        for h in self.producers(self.target_id):
            step = self.grade(h.id)
            if step.grade == "blocked":
                continue
            total, kids = GRADE_COST[step.grade] + 0.6 * step.failures, []
            for x in h.reactants:
                c, sub = self._best(x, frozenset({self.target_id}), 1, max_depth)
                total += c
                kids.append(sub)
            cands.append((total, {"mol": self.target_id, "rxn": h.id, "step": step, "children": kids}))
        cands.sort(key=lambda c: c[0])
        out = []
        for cost, tree in cands[:k]:
            steps, leaves, gaps = [], [], []

            def visit(n):
                if "rxn" not in n:
                    (gaps if n["leaf"] == "gap" else leaves).append(n["mol"])
                    return
                for c in n["children"]:
                    visit(c)
                steps.append(n["step"])
            visit(tree)
            out.append(Route(route_id=f"route-{len(out) + 1}", rank=len(out) + 1, steps=steps,
                             cost=round(cost, 3), leaves=list(dict.fromkeys(leaves)),
                             gaps=list(dict.fromkeys(gaps)), metrics=self.metrics(steps)))
        return out

    def metrics(self, steps: list[RouteStep]) -> dict:
        ae = []
        for s in steps:
            h = self.reactions[s.hypothesis_id]
            mw_r = sum(Descriptors.MolWt(rd.parse(self.smiles(x))) for x in h.reactants)
            if mw_r:
                ae.append(min(1.0, Descriptors.MolWt(rd.parse(self.smiles(h.product))) / mw_r))
        return {"steps": len(steps),
                "grades": [s.grade for s in steps],
                "atom_economy_per_step": [round(a, 3) for a in ae],
                "overall_atom_economy": round(math.prod(ae), 3) if ae else None}
