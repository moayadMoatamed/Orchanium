"""One run: what it owns, and what it hands to the pipeline.

The Orchestrator holds everything a run shares — the knowledge graph, the run
context, the budget, the clue sources — and exposes the work each phase does
(gathering evidence, researching the web, the debate's two callbacks). The
order those phases run in belongs to pipeline.py, which wires them into a
LangGraph state machine.

Every clue found is kept for later runs (memory.py), and the final graph is
snapshotted so a lab note can revise this run's verdict afterwards (lab.py).
"""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Callable

from . import memory, pipeline
from .agents import citation_checker
from .agents.graph_tools import _hyp_brief
from .chem.pubchem import synonyms
from .clues import gather, link_and_emit, need_for
from .config import settings
from .events import CostEvt, Event, EventBus
from .context import RunContext
from .graph import KnowledgeGraph
from .memory import MemorySource
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
                 memory: bool = True, extra_sink: Callable[[Event], None] | None = None):
        self.query, self.blind, self.hidden = query, blind, hidden or []
        self.hidden_molecules = hidden_molecules or []
        # blind mode is strict by default: a source that makes something nearly
        # identical to the target is as good as a source that makes the target
        self.similarity_cap = similarity_cap if similarity_cap is not None else (0.85 if blind else None)
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
        self.memory = MemorySource() if memory else None
        self._n_web = 0

    # ------------------------------------------------------------- research helpers
    async def research_web(self, hyp_id: str, focus: str | None = None) -> list:
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

    async def apply_blind_mode(self) -> None:
        """Blind mode holds back the answer, not just the paper that holds it:
        every name the target is known by is scrubbed from each request, so an
        agent cannot recall a published route instead of working one out."""
        ctx = self.ctx
        names = [ctx.target.name, ctx.target.query]
        if ctx.target.cid:
            names += await synonyms(ctx.target.cid)
        # longest first, so "paxlovid tablet" goes before "paxlovid"
        ctx.redact_terms = sorted({n.strip() for n in names if n and len(n.strip()) >= 4},
                                  key=len, reverse=True)
        ctx.client.redact = ctx.redact
        ctx.log("planner", f"blind mode: {len(ctx.redact_terms)} names of the target are hidden from every agent, "
                           "and any source that names it is dropped whole", level="warn")

    async def gather_local_evidence(self, hyp_ids: list[str]) -> None:
        """Evidence that costs nothing to look up: the patent index and the
        lasting knowledge graph (clues earlier runs and lab notes left behind)."""
        sources = [(self.uspto, "uspto", "USPTO precedent search")]
        if self.memory and memory.stats()["clues"]:
            sources.append((self.memory, "memory", "Knowledge graph recall"))
        sem = asyncio.Semaphore(4)

        async def one(source, agent_id, hid):
            async with sem:
                await gather(self.ctx, self.g, source, need_for(self.g, hid), agent_id)

        async def search(source, agent_id, label):
            async with self.ctx.agent(agent_id, "researcher", label) as h:
                await asyncio.gather(*(one(source, agent_id, x) for x in hyp_ids))
                n = sum(1 for c in self.g.clues.values()
                        if (c.recalled_from if source is self.memory else c.origin == "uspto"))
                h["message"] = f"{n} {'remembered clues' if source is self.memory else 'patent precedents'}"
        await asyncio.gather(*(search(*x) for x in sources))
        link_and_emit(self.ctx, self.g, hyp_ids)

    def web_research_targets(self) -> list[str]:
        """Spend web research where evidence is weakest on the most promising routes."""
        g = self.g
        on_routes = [s.hypothesis_id for r in g.routes(k=2) for s in r.steps]
        ranked = sorted(dict.fromkeys(on_routes + [h.id for h in g.hypotheses() if h.depth == 0]),
                        key=lambda hid: (GRADE_ORDER[g.grade(hid).grade], g.reactions[hid].depth or 0))
        return [h for h in ranked if g.grade(h).grade != "blocked"][: self.web_budget]

    # debate callbacks ---------------------------------------------------------
    async def debate_research(self, hyp_id: str, focus: str) -> dict:
        if self.debate_research_left <= 0:
            return {"error": "research budget for this debate is used up; argue from existing evidence"}
        self.debate_research_left -= 1
        clues = await self.research_web(hyp_id, focus)
        return {"new_clues": [c.id for c in clues], "step_now": _hyp_brief(self.g, hyp_id)}

    async def debate_propose(self, product_id: str, resolved: list, reaction_class: str, notes: list[str]) -> dict:
        ctx, g = self.ctx, self.g
        mols = [await decomposer.add_molecule(ctx, g, r.smiles, "precursor", r.name) for r in resolved]
        h = decomposer.add_hypothesis(ctx, g, g.molecules[product_id], mols, [reaction_class], "agent",
                                      depth=None, parent_prov=None)
        if h.critic.verdict != "block":
            for source, agent_id in [(self.uspto, "uspto"), (self.memory, "memory")]:
                if source:
                    await gather(ctx, g, source, need_for(g, h.id), agent_id)
            link_and_emit(ctx, g, [h.id])
        return {"added": _hyp_brief(g, h.id), "note": "critic: " + h.critic.summary}

    # ------------------------------------------------------------- run
    async def run(self) -> dict:
        """Set the run up, let the pipeline drive it, then close it down.
        The phases themselves live in pipeline.py."""
        store = get_store()
        store.create_run(self.run_id, self.query)
        self.bus.publish("run.status", {"status": "running", "target": self.query, "blind": self.blind,
                                        "started_at": time.time()})
        client = MetaClient(self.budget)
        self.ctx = ctx = RunContext(run_id=self.run_id, bus=self.bus, client=client, blind=self.blind,
                                    hidden=self.hidden, hidden_molecules=self.hidden_molecules,
                                    similarity_cap=self.similarity_cap)
        state: dict = {}
        status, failure = "failed", None
        try:
            state = await pipeline.build(self).ainvoke({})
            status = "done"
        except Exception as e:  # noqa: BLE001
            ctx.log("orchestrator", f"run failed: {type(e).__name__}: {e}", "error")
            # a failed run says why, so the UI never mistakes it for "no route exists"
            failure = {"message": str(e) or type(e).__name__, "retryable": getattr(e, "retryable", False)}
        finally:
            await client.aclose()
            v, dbt = state.get("verdict"), state.get("debate")
            summary = self._summarise(v, failure)
            self._keep_clues()
            self.bus.publish("run.status", {"status": status, "target": self.query, "summary": summary})
            store.finish_run(self.run_id, status, summary)
            self.bus.close()
        return {"run_id": self.run_id, "status": status, "verdict": v, "debate": dbt,
                "report": state.get("report", ""), "graph": self.g, "summary": summary}

    def _keep_clues(self) -> None:
        """Everything learned here is kept for later runs. Losing that write
        must never lose the run itself."""
        try:
            kept = memory.remember(self.g, self.run_id)
            self.ctx.log("orchestrator", f"{kept} clue(s) kept in the lasting knowledge graph")
        except Exception as e:  # noqa: BLE001
            self.ctx.log("orchestrator", f"could not save clues to the lasting graph: {e}", "warn")

    def _summarise(self, v, failure: dict | None) -> dict:
        g, ctx = self.g, self.ctx
        return {"target": ctx.target.name if ctx.target else self.query, "blind": self.blind,
                "verdict": v.label if v else None, "confidence": v.confidence if v else None,
                "steps": len(v.route) if v else 0, "hypotheses": len(g.hypotheses()),
                "clues": len(g.clues), "recalled": sum(1 for c in g.clues.values() if c.recalled_from),
                "cost": self.budget.cost.snapshot(), "failure": failure}
