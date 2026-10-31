"""The tools both debate agents use to traverse and extend the knowledge graph.
Every id in a tool result is a real graph id that can be cited."""
from __future__ import annotations

from typing import Awaitable, Callable, Literal

from pydantic import BaseModel, Field

from ..chem.resolver import from_name
from ..graph import KnowledgeGraph
from ..meta.client import Tool


def node_kind(g: KnowledgeGraph, node_id: str) -> str | None:
    if node_id in g.molecules:
        return "molecule"
    if node_id in g.reactions:
        return g.reactions[node_id].kind            # hypothesis | observed
    if node_id in g.clues:
        return "clue"
    return None


def _mol(g: KnowledgeGraph, mid: str) -> dict:
    m = g.molecules[mid]
    return {"id": m.id, "name": m.name, "purchasable": m.purchasable, "known": m.known}


def _clue_brief(g: KnowledgeGraph, cid: str) -> dict:
    c = g.clues[cid]
    cond = {k: v for k, v in c.conditions.model_dump().items() if v not in (None, "")}
    return {"id": cid, "origin": c.origin, "outcome": c.outcome, "conditions": cond, "yield_pct": c.yield_pct,
            "reagents": [r.label for r in c.reagents][:8],
            "source": {"kind": c.source.kind, "title": c.source.title, "url": c.source.url},
            "snippet": c.source.snippet, "citation_check": g.citation_status.get(cid, "pending")}


def _hyp_brief(g: KnowledgeGraph, hid: str) -> dict:
    h = g.reactions[hid]
    step = g.grade(hid)
    return {"id": hid, "product": _mol(g, h.product), "reactants": [_mol(g, x) for x in h.reactants],
            "reaction_class": h.classes, "critic": h.critic.verdict if h.critic else None,
            "evidence_grade": step.grade, "best_precedent_score": step.precedent_score,
            "failure_precedents": step.failures, "n_precedents": len(g.precedents.get(hid, [])),
            "lab_notes": {"successes": step.lab_successes, "failures": step.lab_failures}}


# ---------------------------------------------------------------- params

class NoParams(BaseModel):
    pass


class NodeId(BaseModel):
    id: str = Field(description="Any graph id: molecule (InChIKey), hyp:…, obs:…, or a clue id")


class PrecedentQuery(BaseModel):
    hypothesis_id: str
    limit: int = Field(description="Max precedents to return (1-12)")


class ClueQuery(BaseModel):
    text: str | None = Field(description="Words to look for in clue titles/snippets/conditions, or null")
    outcome: Literal["success", "failure", "any"]
    molecule_id: str | None = Field(description="Only clues involving this molecule id, or null")
    limit: int


class ResearchRequest(BaseModel):
    hypothesis_id: str
    focus: str = Field(description="What specifically to look for, e.g. 'does this work with a free phenol present?'")


class ProposeStep(BaseModel):
    product_id: str = Field(description="Molecule id (InChIKey) of the product this step makes")
    precursor_names: list[str] = Field(description="Chemical NAMES of the precursors (never SMILES)")
    reaction_class: str = Field(description="Name of the transformation")
    rationale: str


# ---------------------------------------------------------------- tools

def build_tools(g: KnowledgeGraph,
                research: Callable[[str, str], Awaitable[dict]],
                propose: Callable[[str, list, str, list[str]], Awaitable[dict]],
                allow: set[str]) -> list[Tool]:
    """`allow` selects which tools a role gets; `research` and `propose` are
    supplied by the orchestrator (they spend budget and add to the graph)."""

    async def overview(_: NoParams) -> dict:
        t = g.molecules[g.target_id]
        routes = g.routes(k=3)
        return {
            "target": {"id": t.id, "name": t.name, "smiles": t.smiles, "known_compound": t.known},
            "counts": {"molecules": len(g.molecules), "hypotheses": len(g.hypotheses()),
                       "observed_reactions": len(g.observed()), "clues": len(g.clues)},
            "hypotheses": [_hyp_brief(g, h.id) for h in g.hypotheses()],
            "suggested_routes": [{"route_id": r.route_id, "cost": r.cost,
                                  "steps": [s.hypothesis_id for s in r.steps],
                                  "grades": [s.grade for s in r.steps],
                                  "unsolved_molecules": [_mol(g, m) for m in r.gaps]} for r in routes],
        }

    async def get_node(p: NodeId) -> dict:
        kind = node_kind(g, p.id)
        if kind == "molecule":
            m = g.molecules[p.id]
            return {"kind": kind, **_mol(g, m.id), "smiles": m.smiles, "roles": sorted(m.roles),
                    "purchasable_reason": m.purchasable_reason,
                    "made_by_hypotheses": [h.id for h in g.producers(m.id)],
                    "used_in": [r.id for r in g.reactions.values() if m.id in r.reactants],
                    "similar_molecules": [{**_mol(g, x), "similarity": round(s, 2)} for x, s in g.similar_molecules(m.id)]}
        if kind == "hypothesis":
            h = g.reactions[p.id]
            return {"kind": kind, **_hyp_brief(g, p.id),
                    "critic_checks": [{"check": c.name, "status": c.status, "reason": c.reason}
                                      for c in (h.critic.checks if h.critic else [])],
                    "top_precedents": [{"observed_id": x.observed_id, "score": x.score.score, "grade": x.score.grade,
                                        "outcome": x.outcome} for x in g.precedents.get(p.id, [])[:5]]}
        if kind == "observed":
            o = g.reactions[p.id]
            return {"kind": kind, "id": o.id, "reactants": [_mol(g, x) for x in o.reactants],
                    "product": _mol(g, o.product), "reaction_class": o.classes,
                    "critic": o.critic.verdict if o.critic else None,
                    "clues": [_clue_brief(g, c) for c in o.clue_ids]}
        if kind == "clue":
            return {"kind": kind, **_clue_brief(g, p.id), "observed_reaction": g.clue_reaction.get(p.id)}
        return {"error": f"no node with id {p.id}"}

    async def precedents(p: PrecedentQuery) -> dict:
        if node_kind(g, p.hypothesis_id) != "hypothesis":
            return {"error": "not a hypothesis id"}
        out = []
        for x in g.precedents.get(p.hypothesis_id, [])[: max(1, min(p.limit, 12))]:
            o = g.reactions[x.observed_id]
            out.append({"observed_id": o.id, "outcome": x.outcome, **x.score.model_dump(),
                        "reaction": f"{' + '.join(g.molecules[r].name for r in o.reactants)} → {g.molecules[o.product].name}",
                        "clues": [_clue_brief(g, c) for c in o.clue_ids]})
        return {"hypothesis": _hyp_brief(g, p.hypothesis_id), "precedents": out}

    async def find_clues(p: ClueQuery) -> dict:
        words = [w for w in (p.text or "").lower().split() if len(w) > 2]
        out = []
        for cid, c in g.clues.items():
            if p.outcome != "any" and c.outcome != p.outcome:
                continue
            rx = g.reactions.get(g.clue_reaction.get(cid, ""))
            if p.molecule_id and (not rx or p.molecule_id not in rx.reactants + [rx.product]):
                continue
            hay = " ".join(filter(None, [c.source.title, c.source.snippet, c.conditions.text, c.conditions.solvent,
                                         c.conditions.catalyst])).lower()
            if words and not any(w in hay for w in words):
                continue
            out.append({**_clue_brief(g, cid), "observed_reaction": rx.id if rx else None})
            if len(out) >= max(1, min(p.limit, 20)):
                break
        return {"clues": out, "total_clues_in_graph": len(g.clues)}

    async def request_research(p: ResearchRequest) -> dict:
        if node_kind(g, p.hypothesis_id) != "hypothesis":
            return {"error": "not a hypothesis id"}
        return await research(p.hypothesis_id, p.focus)

    async def propose_step(p: ProposeStep) -> dict:
        if p.product_id not in g.molecules:
            return {"error": "product_id must be an existing molecule id"}
        resolved = [await from_name(n) for n in p.precursor_names]
        bad = [r.query for r in resolved if not r.ok]
        if bad:
            return {"error": f"could not resolve: {bad}. Use names PubChem or OPSIN can resolve."}
        return await propose(p.product_id, resolved, p.reaction_class, [p.rationale])

    all_tools = [
        Tool(name="overview", description="Map of the graph: target, every hypothesis step with its evidence "
             "grade, and the cheapest suggested routes. Call this first.", params=NoParams, fn=overview),
        Tool(name="get_node", description="Details and neighbours of any node (molecule, hypothesis, observed "
             "reaction, clue).", params=NodeId, fn=get_node),
        Tool(name="precedents", description="Ranked published precedents for a hypothesis step, with similarity "
             "breakdown, conditions, yields, sources and citation-check status.", params=PrecedentQuery, fn=precedents),
        Tool(name="find_clues", description="Search all clues by text, outcome (use 'failure' to find negative "
             "evidence) or molecule.", params=ClueQuery, fn=find_clues),
        Tool(name="request_research", description="Send a researcher to the web for more evidence on one "
             "hypothesis step (costs budget; use when evidence is weak or contested).", params=ResearchRequest,
             fn=request_research),
        Tool(name="propose_step", description="Add a new candidate step for a molecule using precursor NAMES; it "
             "is resolved, checked by the RDKit critic and searched for precedents.", params=ProposeStep,
             fn=propose_step),
    ]
    return [t for t in all_tools if t.name in allow]
