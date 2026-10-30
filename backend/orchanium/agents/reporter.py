"""Reporter: Muse Spark writes the final report from verified data. It
explains verdicts and grades but receives them read-only."""
from __future__ import annotations

import json
from collections import Counter

from ..context import RunContext, prompt
from ..graph import KnowledgeGraph
from .debate import DebateResult
from .verdict import Verdict


def build_data(g: KnowledgeGraph, verdict: Verdict, debate: DebateResult | None) -> dict:
    steps = []
    for s in verdict.steps:
        precs = []
        for p in g.precedents.get(s.hypothesis_id, [])[:3]:
            o = g.reactions[p.observed_id]
            for cid in o.clue_ids[:1]:
                c = g.clues[cid]
                precs.append({"score": p.score.score, "grade": p.score.grade, "outcome": p.outcome,
                              "product_similarity": p.score.product_similarity,
                              "transformation_similarity": p.score.transformation_similarity,
                              "reaction": f"{' + '.join(g.molecules[x].name for x in o.reactants)} → {g.molecules[o.product].name}",
                              "conditions": c.conditions.model_dump(exclude_none=True), "yield_pct": c.yield_pct,
                              "source": c.source.title, "url": c.source.url,
                              "citation_check": g.citation_status.get(cid)})
        h = g.reactions[s.hypothesis_id]
        steps.append({**s.model_dump(), "transformation": h.classes,
                      "critic": {c.name: f"{c.status}: {c.reason}" for c in h.critic.checks} if h.critic else {},
                      "precedents": precs})
    return {
        "target": g.molecules[g.target_id].name,
        "verdict": {"label": verdict.label, "confidence": verdict.confidence, "reasons": verdict.reasons,
                    "route_source": verdict.route_source,
                    "gaps": [g.molecules[x].name for x in verdict.gaps]},
        "starting_materials": sorted({g.molecules[x].name for hid in verdict.route
                                      for x in g.reactions[hid].reactants if g.molecules[x].purchasable}),
        "steps": steps,
        "debate": {"builder": [b.summary for b in debate.builder_turns],
                   "skeptic": [s.summary for s in debate.skeptic_turns],
                   "sustained_objections": [o.model_dump() for o in debate.sustained],
                   "struck_citations": debate.struck_citations} if debate else None,
        "evidence": {"clues_by_source": dict(Counter(c.origin for c in g.clues.values())),
                     "citation_checks": dict(Counter(g.citation_status.values()))},
    }


async def run(ctx: RunContext, g: KnowledgeGraph, verdict: Verdict, debate: DebateResult | None) -> str:
    data = build_data(g, verdict, debate)
    resp = await ctx.client.respond(
        prompt("reporter", target_name=data["target"], data=json.dumps(data, indent=1, default=str)), effort="low")
    md = resp.text.strip()
    ctx.bus.publish("report", {"markdown": md, "data": data})
    return md
