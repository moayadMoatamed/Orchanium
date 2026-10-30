"""Run lifecycle (v2):

  planner      resolve the target (known or new)
  decomposer   cut it into hypothesis steps (RDKit templates)
  clue sources gather evidence per step: USPTO for every step, web research
               where the evidence is weakest on the most promising routes
  graph        precedent links scored; citations verified
  debate       Builder vs Skeptic over the graph (may request research / propose steps)
  verdict      deterministic feasibility label  →  reporter
"""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Callable

from .agents import citation_checker, debate, decomposer, planner, reporter, verdict
from .agents.graph_tools import _hyp_brief
from .clues import gather, link_and_emit, need_for
from .config import settings
from .context import RunContext
from .events import CostEvt, Event, EventBus, RouteEvt
from .graph import KnowledgeGraph
from .meta.client import Budget, MetaClient
from .sources.uspto import USPTOSource
from .sources.web import WebSource
from .store import get_store

_runs: dict[str, EventBus] = {}
GRADE_ORDER = {"none": 0, "weak": 1, "analog": 2, "direct": 3, "blocked": 4}


def live_bus(run_id: str) -> EventBus | None:
    return _runs.get(run_id)


class Orchestrator:
    def __init__(self, query: str, *, run_id: str | None = None, blind: bool = False,
                 hidden: list[str] | None = None, hidden_molecules: list[str] | None = None,
                 similarity_cap: float | None = None,
                 web_budget: int = 4,
                 debate_rounds: int = 2, debate_research_budget: int = 2, skeptic_model: str | None = None,
                 extra_sink: Callable[[Event], None] | None = None):
        self.query, self.blind, self.hidden = query, blind, hidden or []
        self.hidden_molecules = hidden_molecules or []
        self.similarity_cap = similarity_cap
        self.web_budget, self.debate_rounds = web_budget, debate_rounds
        self.debate_research_left = debate_research_budget
        self.skeptic_model = skeptic_model
        self.run_id = run_id or time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        store = get_store()

        def sink(e: Event):
            store.append_event(e)
            if extra_sink:
                extra_sink(e)

        self.bus = EventBus(self.run_id, sink=sink)
        _runs[self.run_id] = self.bus
        self.budget = Budget(on_change=lambda c: self.bus.publish("cost", CostEvt(**{
            k: v for k, v in c.snapshot().items() if k in CostEvt.model_fields})))
        self.g = KnowledgeGraph()
        self.ctx: RunContext | None = None
        self.uspto, self.web = USPTOSource(), WebSource()
        self._n_web = 0

    # ------------------------------------------------------------- research helpers
    async def _web_research(self, hyp_id: str, focus: str | None = None) -> list:
        ctx, g = self.ctx, self.g
        self._n_web += 1
        agent_id = f"researcher-{self._n_web}"
        need = need_for(g, hyp_id)
        need.focus = focus
        label = f"Researcher {self._n_web} · {need.reaction_class or 'step'} → {need.product_name[:40]}"
        clues: list = []
        async with ctx.agent(agent_id, "researcher", label) as h:
            clues = await asyncio.wait_for(gather(ctx, g, self.web, need, agent_id), settings.agent_timeout_s)
            h["message"] = f"{len(clues)} clues"
        await citation_checker.run(ctx, g, clues)
        link_and_emit(ctx, g, [hyp_id])
        return clues

    async def _uspto_all(self, hyp_ids: list[str]) -> None:
        sem = asyncio.Semaphore(4)

        async def one(hid):
            async with sem:
                await gather(self.ctx, self.g, self.uspto, need_for(self.g, hid), "uspto")
        async with self.ctx.agent("uspto", "researcher", "USPTO precedent search") as h:
            await asyncio.gather(*(one(h_) for h_ in hyp_ids))
            h["message"] = f"{sum(1 for c in self.g.clues.values() if c.origin == 'uspto')} patent precedents"
        link_and_emit(self.ctx, self.g, hyp_ids)

    def _web_targets(self) -> list[str]:
        """Spend web research where evidence is weakest on the most promising routes."""
        g = self.g
        on_routes = [s.hypothesis_id for r in g.routes(k=2) for s in r.steps]
        ranked = sorted(dict.fromkeys(on_routes + [h.id for h in g.hypotheses() if h.depth == 0]),
                        key=lambda hid: (GRADE_ORDER[g.grade(hid).grade], g.reactions[hid].depth or 0))
        return [h for h in ranked if g.grade(h).grade != "blocked"][: self.web_budget]

    # debate callbacks ---------------------------------------------------------
    async def _debate_research(self, hyp_id: str, focus: str) -> dict:
        if self.debate_research_left <= 0:
            return {"error": "research budget for this debate is used up; argue from existing evidence"}
        self.debate_research_left -= 1
        clues = await self._web_research(hyp_id, focus)
        return {"new_clues": [c.id for c in clues], "step_now": _hyp_brief(self.g, hyp_id)}

    async def _debate_propose(self, product_id: str, resolved: list, reaction_class: str, notes: list[str]) -> dict:
        ctx, g = self.ctx, self.g
        mols = [await decomposer.add_molecule(ctx, g, r.smiles, "precursor", r.name) for r in resolved]
        h = decomposer.add_hypothesis(ctx, g, g.molecules[product_id], mols, [reaction_class], "agent",
                                      depth=None, parent_prov=None)
        if h.critic.verdict != "block":
            await gather(ctx, g, self.uspto, need_for(g, h.id), "uspto")
            link_and_emit(ctx, g, [h.id])
        return {"added": _hyp_brief(g, h.id), "note": "critic: " + h.critic.summary}

    # ------------------------------------------------------------- run
    async def run(self) -> dict:
        store = get_store()
        store.create_run(self.run_id, self.query)
        bus = self.bus
        bus.publish("run.status", {"status": "running", "target": self.query, "blind": self.blind,
                                   "started_at": time.time()})
        client = MetaClient(self.budget)
        self.ctx = ctx = RunContext(run_id=self.run_id, bus=bus, client=client, blind=self.blind,
                                    hidden=self.hidden, hidden_molecules=self.hidden_molecules,
                                    similarity_cap=self.similarity_cap)
        g = self.g
        status, v, report, dbt = "failed", None, "", None
        try:
            async with ctx.agent("planner", "planner", "Planner") as h:
                await planner.run(ctx, self.query)
                h["message"] = ctx.target.name
            if not ctx.target:
                raise RuntimeError("target could not be resolved")
            bus.publish("run.status", {"status": "running", "target": self.query, "blind": self.blind,
                                       "target_info": ctx.target.model_dump()})

            async with ctx.agent("decomposer", "planner", "Decomposer (RDKit)") as h:
                await decomposer.run(ctx, g)
                h["message"] = f"{len(g.hypotheses())} candidate steps"
            live = [x.id for x in g.hypotheses() if x.critic.verdict != "block"]

            # each phase must leave a share of the budget for the phases after it
            self.budget.reserve = 0.5
            await self._uspto_all(live)
            await asyncio.gather(*(self._web_research(hid) for hid in self._web_targets()))

            self.budget.reserve = 0.1
            review_note = None if self.debate_rounds > 0 else "debate disabled"
            if self.debate_rounds > 0:
                async with ctx.agent("debate", "reasoner", "Debate") as h:
                    try:
                        dbt = await debate.run(ctx, g, self._debate_research, self._debate_propose,
                                               rounds=self.debate_rounds, skeptic_model=self.skeptic_model)
                    except Exception as e:
                        review_note = ("Meta's content filter declined the debate prompt"
                                       if "content_policy" in str(e) else f"debate failed: {type(e).__name__}")
                        raise
                    h["message"] = f"{len(dbt.sustained)} objection(s) stand"

            self.budget.reserve = 0.0
            async with ctx.agent("verdict", "critic", "Verdict (rule-based)") as h:
                v = verdict.decide(ctx, g, dbt, review_note)
                h["message"] = f"{v.label} ({v.confidence:.0%})"
            bus.publish("route", RouteEvt(route_id="final", rank=1, steps=v.route, score=v.confidence,
                                          label=v.label, metrics={**g.metrics(
                                              [g.grade(x) for x in v.route]), "gaps": v.gaps}))
            async with ctx.agent("reporter", "reporter", "Reporter") as h:
                report = await reporter.run(ctx, g, v, dbt)
            status = "done"
        except Exception as e:  # noqa: BLE001
            ctx.log("orchestrator", f"run failed: {type(e).__name__}: {e}", "error")
        finally:
            await client.aclose()
            summary = {"target": ctx.target.name if ctx.target else self.query, "blind": self.blind,
                       "verdict": v.label if v else None, "confidence": v.confidence if v else None,
                       "steps": len(v.route) if v else 0, "hypotheses": len(g.hypotheses()),
                       "clues": len(g.clues), "cost": self.budget.cost.snapshot()}
            bus.publish("run.status", {"status": status, "target": self.query, "summary": summary})
            store.finish_run(self.run_id, status, summary)
            bus.close()
        return {"run_id": self.run_id, "status": status, "verdict": v, "debate": dbt, "report": report,
                "graph": g, "summary": summary}
