"""Run lifecycle. Each researcher's findings flow through graph building,
critic and citation checks as soon as that researcher finishes, so the graph
(and the Verification Chain) grows live instead of in one batch at the end."""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Callable

from .agents import citation_checker, critic_agent, graph_builder, planner, reasoner, reporter, researcher
from .config import settings
from .context import RunContext
from .events import CostEvt, Event, EventBus
from .graph import RunGraph
from .meta.client import Budget, MetaClient
from .models import ResearchAngle
from .store import get_store

_runs: dict[str, EventBus] = {}          # live buses, for SSE subscribers


def live_bus(run_id: str) -> EventBus | None:
    return _runs.get(run_id)


class Orchestrator:
    def __init__(self, query: str, run_id: str | None = None, n_angles: int | None = None,
                 extra_sink: Callable[[Event], None] | None = None):
        self.query = query
        self.run_id = run_id or time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        self.n_angles = n_angles or settings.max_researchers
        store = get_store()

        def sink(e: Event):
            store.append_event(e)
            if extra_sink:
                extra_sink(e)

        self.bus = EventBus(self.run_id, sink=sink)
        _runs[self.run_id] = self.bus
        self.budget = Budget(on_change=lambda c: self.bus.publish("cost", CostEvt(**{
            k: v for k, v in c.snapshot().items() if k in CostEvt.model_fields})))
        self.graph = RunGraph()
        self.ctx: RunContext | None = None
        self._ingest_lock = asyncio.Lock()
        self._researched: set[str] = set()
        self._n_research = 0

    # ------------------------------------------------------------------ pipeline
    async def _research_pipeline(self, angle: ResearchAngle, extra: str = "",
                                 parent: str | None = None) -> list[str]:
        ctx, g = self.ctx, self.graph
        self._n_research += 1
        agent_id = f"researcher-{self._n_research}"
        label = f"Researcher {self._n_research} · {angle.title}"
        found: dict = {}
        async with ctx.agent(agent_id, "researcher", label) as h:
            ev, inter = await asyncio.wait_for(researcher.run(ctx, agent_id, angle, extra, parent),
                                               settings.agent_timeout_s)
            found.update(ev=ev, inter=inter)
            h["message"] = f"{len(ev)} steps from {len({e.source_url for e in ev})} sources"
        if not found.get("ev"):
            return []
        ev = found["ev"]
        async with self._ingest_lock:
            new_rx = await graph_builder.ingest(ctx, g, ev)
        await critic_agent.review(ctx, g, new_rx)
        await citation_checker.run(ctx, g, ev)
        for rx_id in {r.id for r in g.reactions.values() if set(r.evidence) & {e.id for e in ev}}:
            critic_agent.finalize(ctx, g, g.reactions[rx_id])
        return found.get("inter", [])

    async def _follow_up(self, depth: int) -> None:
        """Send researchers after intermediates that block the best routes."""
        ctx, g = self.ctx, self.graph
        routes = reasoner.search(ctx, g, emit=False)
        todo = [m for m in reasoner.gaps(g, routes) if m not in self._researched and m != ctx.target.inchikey][:3]
        if not todo:
            return
        ctx.log("reasoner", f"Follow-up research (depth {depth}) on: "
                            + ", ".join(g.molecules[m].name for m in todo))
        tasks = []
        for m in todo:
            self._researched.add(m)
            mol = g.molecules[m]
            angle = ResearchAngle(title=f"Intermediate: {mol.name}",
                                  focus=f"Published syntheses of the intermediate {mol.name}",
                                  query_hint=f"synthesis of {mol.name} preparation")
            extra = (f"\nFocus: this researcher looks specifically for how to make the intermediate "
                     f"**{mol.name}** (SMILES `{mol.smiles}`), which is needed on a route to the target.")
            tasks.append(self._research_pipeline(angle, extra))
        await asyncio.gather(*tasks)

    # ------------------------------------------------------------------ run
    async def run(self) -> dict:
        store = get_store()
        store.create_run(self.run_id, self.query)
        bus = self.bus
        bus.publish("run.status", {"status": "running", "target": self.query, "started_at": time.time(),
                                   "caps": {"llm_calls": settings.max_llm_calls, "searches": settings.max_searches}})
        client = MetaClient(self.budget)
        self.ctx = ctx = RunContext(run_id=self.run_id, bus=bus, client=client)
        status, routes, report = "failed", [], ""
        try:
            plan = None
            async with ctx.agent("planner", "planner", "Planner") as h:
                _, plan = await planner.run(ctx, self.query, self.n_angles)
                h["message"] = f"{len(plan.angles)} research angles"
            if plan is None:
                raise RuntimeError("planner failed: cannot continue without a resolved target")
            bus.publish("run.status", {"status": "running", "target": self.query, "target_info": ctx.target.model_dump(),
                                       "plan": plan.model_dump()})
            for a, t in (("graph_builder", "Graph builder"), ("critic", "Critic (RDKit)"),
                         ("citation_checker", "Citation checker")):
                ctx.agent_status(a, a if a != "critic" else "critic", t, "running")
            self._researched.add(ctx.target.inchikey)

            await asyncio.gather(*(self._research_pipeline(a) for a in plan.angles))
            for depth in range(1, settings.max_followup_depth + 1):
                await self._follow_up(depth)

            # final consistent pass over every reaction
            for rx in self.graph.reactions.values():
                critic_agent.finalize(ctx, self.graph, rx)
            for a, t in (("graph_builder", "Graph builder"), ("critic", "Critic (RDKit)"),
                         ("citation_checker", "Citation checker")):
                ctx.agent_status(a, a, t, "done")

            async with ctx.agent("reasoner", "reasoner", "Reasoner") as h:
                routes = reasoner.search(ctx, self.graph)
                h["message"] = f"{len(routes)} route(s); best is {'complete' if routes and routes[0].complete else 'partial'}"
            async with ctx.agent("reporter", "reporter", "Reporter") as h:
                report = await reporter.run(ctx, self.graph, routes)
            status = "done"
        except Exception as e:  # noqa: BLE001
            ctx.log("orchestrator", f"run failed: {type(e).__name__}: {e}", "error")
        finally:
            await client.aclose()
            summary = {"routes": len(routes), "complete": bool(routes and routes[0].complete),
                       "molecules": len(self.graph.molecules), "reactions": len(self.graph.reactions),
                       "evidence": len(self.graph.evidence), "cost": self.budget.cost.snapshot(),
                       "target": ctx.target.name if ctx.target else self.query}
            bus.publish("run.status", {"status": status, "target": self.query, "summary": summary})
            store.finish_run(self.run_id, status, summary)
            bus.close()
        return {"run_id": self.run_id, "status": status, "routes": routes, "report": report,
                "graph": self.graph, "summary": summary}
