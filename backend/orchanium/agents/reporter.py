"""Reporter: Muse Spark writes the final Markdown report from verified data.
It explains verdicts but receives them read-only."""
from __future__ import annotations

import json

from ..context import RunContext, prompt
from ..graph import RunGraph
from ..models import Route

AGENT_ID = "reporter"


def _step_data(g: RunGraph, rx_id: str) -> dict:
    rx = g.reactions[rx_id]
    evs = [g.evidence[e] for e in rx.evidence if e in g.evidence]
    return {
        "reactants": [g.molecules[x].name for x in rx.reactants],
        "product": g.molecules[rx.product].name,
        "reagents": rx.reagents,
        "conditions": sorted({e.conditions for e in evs if e.conditions}),
        "yields_pct": sorted({e.yield_pct for e in evs if e.yield_pct is not None}),
        "label": rx.label, "confidence": rx.confidence,
        "critic_verdict": rx.critic.verdict if rx.critic else None,
        "critic_checks": {c.name: f"{c.status}: {c.reason}" for c in (rx.critic.checks if rx.critic else [])},
        "reaction_classes": rx.critic.reaction_classes if rx.critic else [],
        "citations": [{"url": e.source_url, "title": e.source_title, "type": e.source_type,
                       "verified_on_page": g.citation_status.get(e.id), "snippet": e.snippet} for e in evs],
    }


def build_data(g: RunGraph, routes: list[Route], target_name: str) -> dict:
    rejected = [r for r in g.reactions.values() if r.label == "rejected"]
    return {
        "target": target_name,
        "routes": [{"rank": r.rank, "score": r.score, "complete": r.complete,
                    "starting_materials": [g.molecules[m].name for m in r.leaves],
                    "gaps": [g.molecules[m].name for m in r.gaps], "metrics": r.metrics,
                    "steps": [_step_data(g, s.reaction_id) for s in r.steps]} for r in routes],
        "rejected_steps": [{"reactants": [g.molecules[x].name for x in r.reactants],
                            "product": g.molecules[r.product].name,
                            "reason": r.critic.summary if r.critic else "not checked"} for r in rejected[:12]],
    }


async def run(ctx: RunContext, g: RunGraph, routes: list[Route]) -> str:
    data = build_data(g, routes, ctx.target.name)
    resp = await ctx.client.respond(
        prompt("reporter", target_name=ctx.target.name, data=json.dumps(data, indent=1, default=str)),
        effort="low",
    )
    md = resp.text.strip()
    ctx.bus.publish("report", {"markdown": md, "data": data})
    return md
