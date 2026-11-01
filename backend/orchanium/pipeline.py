"""The run as a LangGraph state machine.

    plan → decompose → evidence → debate? → verdict → report

LangGraph owns the control flow and nothing else. Each node is a plain async
function that calls the same planner, decomposer, clue sources, debate, verdict
and reporter as before, because that is where the chemistry lives. The Meta
client in particular stays outside: blind-mode scrubbing, strict structured
output, the response cache and the per-phase budget guards all hook into it, and
a generic model wrapper would drop them silently.

Every node may fail. `ctx.agent` reports the failure and the run carries on with
whatever the earlier phases produced, so a dead debate costs the argument, not
the answer. Only an unresolved target ends the run, because nothing downstream
means anything without it.
"""
from __future__ import annotations

import asyncio
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from . import lab
from .agents import debate as debate_agent
from .agents import decomposer, planner, reporter
from .agents import verdict as verdict_agent
from .events import RouteEvt


class RunState(TypedDict, total=False):
    """What one phase hands the next. The knowledge graph, run context and
    budget are not in here: every phase adds to the one graph rather than
    passing a new copy along, so they live on the Orchestrator."""

    live: list[str]            # hypotheses the chemistry critic did not block
    debate: Any                # DebateResult, or None if it was skipped or failed
    review_note: str | None    # why the debate is missing, shown in the verdict
    verdict: Any               # Verdict
    report: str                # markdown


def build(orch: Any):
    """Compile the pipeline for one run. `orch` carries the graph, context and
    budget that every phase shares."""

    async def plan(state: RunState) -> RunState:
        ctx = orch.ctx
        async with ctx.agent("planner", "planner", "Planner") as h:
            await planner.run(ctx, orch.query)
            h["message"] = ctx.target.name
        if not ctx.target:
            raise RuntimeError("target could not be resolved")
        if orch.blind:
            await orch.apply_blind_mode()
        orch.bus.publish("run.status", {"status": "running", "target": orch.query, "blind": orch.blind,
                                        "target_info": ctx.target.model_dump()})
        return {}

    async def decompose(state: RunState) -> RunState:
        ctx, g = orch.ctx, orch.g
        async with ctx.agent("decomposer", "planner", "Decomposer (RDKit)") as h:
            await decomposer.run(ctx, g)
            h["message"] = f"{len(g.hypotheses())} candidate steps"
        return {"live": [x.id for x in g.hypotheses() if x.critic.verdict != "block"]}

    async def evidence(state: RunState) -> RunState:
        # research may not spend what the debate and the report still need
        orch.budget.reserve = 0.5
        live = state.get("live") or []
        await orch.gather_local_evidence(live)
        await asyncio.gather(*(orch.research_web(hid) for hid in orch.web_research_targets()))
        return {}

    async def debate(state: RunState) -> RunState:
        ctx, note = orch.ctx, None
        orch.budget.reserve = 0.1
        result = None
        async with ctx.agent("debate", "reasoner", "Debate") as h:
            try:
                result = await debate_agent.run(ctx, orch.g, orch.debate_research, orch.debate_propose,
                                                rounds=orch.debate_rounds, skeptic_model=orch.skeptic_model)
            except Exception as e:  # noqa: BLE001
                note = ("Meta's content filter declined the debate prompt" if "content_policy" in str(e)
                        else f"debate failed: {type(e).__name__}")
                raise
            h["message"] = f"{len(result.sustained)} objection(s) stand"
        return {"debate": result, "review_note": note}

    async def decide(state: RunState) -> RunState:
        ctx, g = orch.ctx, orch.g
        orch.budget.reserve = 0.0
        note = state.get("review_note") or (None if orch.debate_rounds > 0 else "debate disabled")
        async with ctx.agent("verdict", "critic", "Verdict (rule-based)") as h:
            v = verdict_agent.decide(ctx, g, state.get("debate"), note)
            h["message"] = f"{v.label} ({v.confidence:.0%})"
        orch.bus.publish("route", RouteEvt(route_id="final", rank=1, steps=v.route, score=v.confidence,
                                           label=v.label,
                                           metrics={**g.metrics([g.grade(x) for x in v.route]), "gaps": v.gaps}))
        return {"verdict": v}

    async def report(state: RunState) -> RunState:
        ctx, g, v = orch.ctx, orch.g, state.get("verdict")
        text = ""
        async with ctx.agent("reporter", "reporter", "Reporter") as h:
            text = await reporter.run(ctx, g, v, state.get("debate"))
            h["message"] = f"{len(v.route) if v else 0} step(s) written up"
        # the snapshot is what lets a lab note revise this run's answer later
        lab.save_snapshot(orch.run_id, lab.Snapshot(graph=g, debate=state.get("debate"), verdict=v,
                                                    report=text, target=ctx.target))
        return {"report": text}

    def after_evidence(state: RunState) -> str:
        return "debate" if orch.debate_rounds > 0 else "verdict"

    flow = StateGraph(RunState)
    for name, node in [("plan", plan), ("decompose", decompose), ("evidence", evidence),
                       ("debate", debate), ("verdict", decide), ("report", report)]:
        flow.add_node(name, node)
    flow.add_edge(START, "plan")
    flow.add_edge("plan", "decompose")
    flow.add_edge("decompose", "evidence")
    flow.add_conditional_edges("evidence", after_evidence, {"debate": "debate", "verdict": "verdict"})
    flow.add_edge("debate", "verdict")
    flow.add_edge("verdict", "report")
    flow.add_edge("report", END)
    return flow.compile()
