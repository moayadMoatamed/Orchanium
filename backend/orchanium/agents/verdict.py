"""Feasibility verdict: a deterministic rule over computed evidence grades and
the objections the Skeptic sustained. No LLM decides the label.

  Unlikely   any blocked step, or a fatal objection backed by a failure clue
  Uncertain  any step with no precedent, a route gap, or many weak points
  Feasible   every step has direct/analog precedent and no major objection stands
  Plausible  otherwise (at most one weak step / one major objection)
A route that was not adversarially reviewed (no debate) is capped at Plausible."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..context import RunContext
from ..events import ProvNode
from ..graph import KnowledgeGraph
from .debate import DebateResult, Objection
from .graph_tools import node_kind

Label = Literal["Feasible", "Plausible", "Uncertain", "Unlikely"]


class StepVerdict(BaseModel):
    hypothesis_id: str
    reaction: str
    grade: str
    precedent_score: float | None
    failure_precedents: int
    objections: list[Objection] = Field(default_factory=list)


class Verdict(BaseModel):
    label: Label
    confidence: float
    reasons: list[str]
    route: list[str]
    route_source: str                     # builder | fallback
    steps: list[StepVerdict]
    gaps: list[str]


def validate_route(g: KnowledgeGraph, route: list[str]) -> list[str]:
    """Problems with a route, empty if it is a valid synthesis of the target."""
    problems, made = [], set()
    for hid in route:
        if node_kind(g, hid) != "hypothesis":
            problems.append(f"{hid} is not a hypothesis step")
            continue
        h = g.reactions[hid]
        for x in h.reactants:
            if not g.molecules[x].purchasable and x not in made:
                problems.append(f"{g.molecules[x].name} is neither purchasable nor made by an earlier step")
        made.add(h.product)
    if not route or g.target_id not in made:
        problems.append("route does not end at the target")
    return problems


def _backed_by_failure(g: KnowledgeGraph, o: Objection) -> bool:
    for i in o.cited_ids:
        if node_kind(g, i) == "clue" and g.clues[i].outcome == "failure":
            return True
        if node_kind(g, i) == "observed" and any(g.clues[c].outcome == "failure" for c in g.reactions[i].clue_ids):
            return True
    return False


def decide(ctx: RunContext, g: KnowledgeGraph, debate: DebateResult | None) -> Verdict:
    route, source, reasons = (debate.route if debate else []), "builder", []
    problems = validate_route(g, route)
    if problems:
        best = g.routes(k=1)
        if debate:
            reasons.append("Builder's route was invalid (" + "; ".join(problems[:3]) + "); using the best computed route")
        route, source = ([s.hypothesis_id for s in best[0].steps] if best else []), "fallback"
    gaps = sorted({x for hid in route for x in g.reactions[hid].reactants
                   if not g.molecules[x].purchasable and x not in {g.reactions[h].product for h in route}})
    sustained = debate.sustained if debate else []
    steps = []
    for hid in route:
        h, st = g.reactions[hid], g.grade(hid)
        steps.append(StepVerdict(
            hypothesis_id=hid, grade=st.grade, precedent_score=st.precedent_score,
            failure_precedents=st.failures, objections=[o for o in sustained if o.hypothesis_id == hid],
            reaction=f"{' + '.join(g.molecules[x].name for x in h.reactants)} → {g.molecules[h.product].name}"))

    grades = [s.grade for s in steps]
    fatal = [o for o in sustained if o.severity == "fatal"]
    fatal_evidenced = [o for o in fatal if _backed_by_failure(g, o)]
    major = len([o for o in sustained if o.severity == "major"]) + len(fatal) - len(fatal_evidenced)
    weak = grades.count("weak")

    if not steps:
        label, reasons = "Uncertain", reasons + ["no route could be assembled from the graph"]
    elif "blocked" in grades or fatal_evidenced:
        label = "Unlikely"
        reasons += [f"step blocked by the chemistry critic" for g_ in grades if g_ == "blocked"]
        reasons += [f"fatal objection backed by a reported failure: {o.claim[:120]}" for o in fatal_evidenced]
    elif "none" in grades or gaps or weak + major >= 3:
        label = "Uncertain"
        if "none" in grades:
            reasons.append(f"{grades.count('none')} step(s) have no published precedent")
        if gaps:
            reasons.append(f"{len(gaps)} precursor(s) neither purchasable nor made in the route")
    elif weak == 0 and major == 0:
        label = "Feasible"
        reasons.append("every step has direct or close-analog published precedent; no major objection stands")
    else:
        label = "Plausible"
        reasons.append(f"{weak} weakly-supported step(s), {major} standing major objection(s)")
    if label == "Feasible" and debate is None:
        label = "Plausible"
        reasons.append("capped at Plausible: the route was not reviewed by the Skeptic")

    scores = [s.precedent_score or 0.1 for s in steps] or [0.0]
    conf = sum(scores) / len(scores) - 0.08 * major - 0.2 * len(fatal_evidenced) - 0.1 * len(gaps)
    conf = round(max(0.02, min(0.97, conf)), 2)
    v = Verdict(label=label, confidence=conf, reasons=reasons, route=route, route_source=source,
                steps=steps, gaps=gaps)

    for s in steps:
        lbl = {"direct": "literature", "blocked": "rejected"}.get(s.grade, "proposed")
        status = "fail" if s.grade == "blocked" else "pass" if s.grade in ("direct", "analog") and not s.objections \
            else "warn"
        ctx.prov(ProvNode(
            id=f"verdict:{s.hypothesis_id}", node_type="verdict", step_id=s.hypothesis_id, agent_id="verdict",
            verdict=lbl, status=status,
            parent_ids=[p for p in ([f"prec:{s.hypothesis_id}:{x.observed_id}" for x in g.precedents.get(s.hypothesis_id, [])[:3]]
                                    + [f"chk:{s.hypothesis_id}:{c.name}" for c in (g.reactions[s.hypothesis_id].critic.checks or [])]
                                    + [n for n in ctx.prov_nodes if n.startswith("debate:") and ctx.prov_nodes[n].step_id == s.hypothesis_id])
                        if p in ctx.prov_nodes],
            summary=f"{s.grade} precedent" + (f" ({s.precedent_score:.2f})" if s.precedent_score else "")
                    + (f" · {len(s.objections)} standing objection(s)" if s.objections else ""),
            details=s.model_dump()))
    ctx.prov(ProvNode(id="verdict:route", node_type="verdict", agent_id="verdict", status=
                      {"Feasible": "pass", "Plausible": "pass", "Uncertain": "warn", "Unlikely": "fail"}[label],
                      parent_ids=[f"verdict:{h}" for h in route],
                      summary=f"{label} · confidence {conf:.0%}", details=v.model_dump()))
    return v
