"""Reporter: Muse Spark writes the final report from verified data. It
explains verdicts and grades but receives them read-only."""
from __future__ import annotations

import json
from collections import Counter

from ..context import RunContext, prompt
from ..graph import KnowledgeGraph
from . import conditions
from .debate import DebateResult, StepArgument
from .graph_tools import node_kind
from .verdict import Verdict


def _arguments(debate: DebateResult | None) -> dict[str, StepArgument]:
    """The Builder's latest argument for each step."""
    out: dict[str, StepArgument] = {}
    for t in debate.builder_turns if debate else []:
        out.update({a.hypothesis_id: a for a in t.arguments})
    return out


def _lab_notes(g: KnowledgeGraph, hyp_id: str) -> list[dict]:
    ok, bad = g.lab_record(hyp_id)
    notes = [g.clues[c] for o in {**ok, **bad} for c in g.reactions[o].clue_ids if g.clues[c].origin == "lab"]
    return [{"id": c.id, "outcome": c.outcome, "yield_pct": c.yield_pct,
             "conditions": c.conditions.model_dump(exclude_none=True), "reagents": [r.label for r in c.reagents],
             "observations": c.source.snippet, "title": c.source.title} for c in notes]


def build_data(g: KnowledgeGraph, verdict: Verdict, debate: DebateResult | None) -> dict:
    args = _arguments(debate)
    objection_text = {o.id: o.plain or o.claim for t in (debate.skeptic_turns if debate else []) for o in t.objections}
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
                              "source": c.source.title, "url": c.source.url, "origin": c.origin,
                              "recalled_from": c.recalled_from, "citation_check": g.citation_status.get(cid)})
        h = g.reactions[s.hypothesis_id]
        a = args.get(s.hypothesis_id)
        procedure = [{**op.model_dump(exclude={"cited_ids"}), "backed": any(node_kind(g, i) for i in op.cited_ids),
                      "responds_to_text": objection_text.get(op.responds_to or "")}
                     for op in (a.procedure if a else [])]
        checks = {c.name: c for c in (h.critic.checks if h.critic else [])}
        conflict = checks.get("fg_conflicts")
        steps.append({**s.model_dump(), "transformation": h.classes,
                      "name": a.name if a else None, "plain": a.plain if a else None,
                      "procedure": procedure,
                      "conditions": conditions.record(g, s.hypothesis_id, a.conditions.model_dump() if a else None),
                      "competing_groups": conflict.reason if conflict and conflict.status == "warn" else None,
                      "lab_notes": _lab_notes(g, s.hypothesis_id),
                      "critic": {c.name: f"{c.status}: {c.reason}" for c in checks.values()},
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
                     "recalled": sum(1 for c in g.clues.values() if c.recalled_from),
                     "citation_checks": dict(Counter(g.citation_status.values()))},
    }


def template_report(data: dict) -> str:
    """Deterministic report from the verified data; used when the LLM is unavailable."""
    v = data["verdict"]
    lines = ["## Verdict", f"**{v['label']}** · confidence {v['confidence']:.0%}", ""]
    lines += [f"- {r}" for r in v["reasons"]] + ["", "## Proposed route", ""]
    if data["starting_materials"]:
        lines += [f"Starting materials: {', '.join(data['starting_materials'])}", ""]
    for i, s in enumerate(data["steps"], 1):
        lines.append(f"**Step {i}: {s.get('name') or s['reaction']}**  ")
        lines.append(f"{s['reaction']} · {', '.join(s['transformation']) or 'transformation'} · evidence grade "
                     f"**{s['grade']}**" + (f" (score {s['precedent_score']:.2f})" if s["precedent_score"] else ""))
        for j, op in enumerate(s.get("procedure") or [], 1):
            lines.append(f"  {j}. *{op['kind']}*: {op['action']}" + (f" ({', '.join(op['reagents'])})" if op["reagents"] else ""))
        cond = [f"{k}: {c['value']} ({c['basis']})" for k, c in (s.get("conditions") or {}).items() if c["value"]]
        if cond:
            lines.append("- conditions: " + "; ".join(cond))
        for j, p in enumerate(s["precedents"], 1):
            link = f"[{j}]({p['url']})" if p.get("url") else f"[{j}]"
            lines.append(f"- {link} {p['reaction']} — score {p['score']:.2f}, {p['source']}")
        lines.append("")
    if data.get("debate"):
        lines += ["## Standing objections", ""] + [f"- [{o['severity']}] {o['claim']}"
                                                   for o in data["debate"]["sustained_objections"]] + [""]
    ev = data["evidence"]
    lines += ["## Evidence summary", f"- clues by source: {ev['clues_by_source']}",
              f"- citation checks: {ev['citation_checks']}", "",
              "_This report was generated from the verified data without an LLM summary._"]
    return "\n".join(lines)


async def run(ctx: RunContext, g: KnowledgeGraph, verdict: Verdict, debate: DebateResult | None) -> str:
    data = build_data(g, verdict, debate)
    try:
        resp = await ctx.client.respond(
            prompt("reporter", target_name=data["target"], data=json.dumps(data, indent=1, default=str)),
            effort="low")
        md = resp.text.strip()
    except Exception as e:  # noqa: BLE001  (budget, outage, content filter: the report must still exist)
        ctx.log("reporter", f"LLM report unavailable ({type(e).__name__}); using the deterministic template", "warn")
        md = template_report(data)
    ctx.bus.publish("report", {"markdown": md, "data": data})
    return md
