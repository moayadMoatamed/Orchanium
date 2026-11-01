"""Builder vs Skeptic debate over the knowledge graph.

The debate is a LangGraph cycle:

    builder → skeptic → another round? → builder … → stop

Each turn is a tool loop over the graph tools that ends in a structured
message. Code validates every cited id; unsupported claims are struck out.
The debate informs the verdict but can never override a computed grade."""
from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from ..context import RunContext, prompt
from ..events import ProvNode, current_agent
from ..graph import KnowledgeGraph
from .graph_tools import build_tools, node_kind

# ---------------------------------------------------------------- turn schemas (LLM)

PLAIN = "One or two sentences a non-chemist can follow: no ids, scores or abbreviations"


class SuggestedConditions(BaseModel):
    reagents: list[str] = Field(description="NAMES of reagents, catalysts and additives, e.g. 'HATU', 'DIPEA'")
    solvent: str | None
    temperature_c: float | None
    time: str | None = Field(description="e.g. '2 h', 'overnight'")
    atmosphere: str | None = Field(description="e.g. 'nitrogen', or null if air is fine")
    expected_yield_pct: float | None


class Operation(BaseModel):
    kind: Literal["protect", "activate", "react", "deprotect", "workup", "purify"]
    action: str = Field(description="Imperative, specific: 'Protect the lysine side-chain amine as its Boc carbamate'")
    reagents: list[str] = Field(description="NAMES of the reagents this operation uses")
    why: str = Field(description="Why it is needed, in plain words")
    responds_to: str | None = Field(description="Id of the Skeptic objection this operation answers, or null")
    cited_ids: list[str]


class StepArgument(BaseModel):
    hypothesis_id: str
    name: str = Field(description="Short title that tells this step apart from the others, naming what it "
                                  "joins or changes, e.g. 'Couple palmitoyl-glycine to histidine'")
    plain: str = Field(description=PLAIN)
    claim: str = Field(description="Why this step works, with the key evidence (scores, conditions, sources)")
    conditions: SuggestedConditions = Field(description="The conditions you recommend, taken from the best precedents")
    procedure: list[Operation] = Field(description="Every lab operation of this step in order, including any "
                                                   "protection before and deprotection after the main reaction")
    cited_ids: list[str]


class Rebuttal(BaseModel):
    objection_id: str
    concede: bool
    plain: str = Field(description=PLAIN)
    response: str
    cited_ids: list[str]


class BuilderTurn(BaseModel):
    route: list[str] = Field(description="Hypothesis ids in execution order (last one makes the target)")
    arguments: list[StepArgument]
    rebuttals: list[Rebuttal]
    summary: str


class Objection(BaseModel):
    id: str = Field(description="Short stable id, e.g. 'O1'; reuse ids when maintaining an objection")
    hypothesis_id: str
    severity: Literal["minor", "major", "fatal"]
    plain: str = Field(default="", description=PLAIN + ". Say what could go wrong and what would fix it")
    claim: str
    cited_ids: list[str]


class SkepticTurn(BaseModel):
    objections: list[Objection] = Field(description="All objections you still maintain (new or kept)")
    withdrawn: list[str] = Field(description="Ids of earlier objections you withdraw")
    supported_steps: list[str] = Field(description="Hypothesis ids you consider well supported")
    summary: str


# ---------------------------------------------------------------- helpers

def _valid(g: KnowledgeGraph, ids: list[str]) -> tuple[list[str], list[str]]:
    ok = [i for i in ids if node_kind(g, i)]
    return ok, [i for i in ids if not node_kind(g, i)]


def _prov_ref(g: KnowledgeGraph, node_id: str, step: str | None) -> str | None:
    """Map a graph id to the provenance node that shows it in the chain."""
    kind = node_kind(g, node_id)
    if kind == "molecule":
        return f"res:{node_id}"
    if kind == "hypothesis":
        return f"hyp:{node_id}"
    if kind == "clue":
        return f"clue:{node_id}"
    if kind == "observed":
        return f"prec:{step}:{node_id}" if step else next((f"clue:{c}" for c in g.reactions[node_id].clue_ids), None)
    return None


class DebateResult(BaseModel):
    route: list[str]
    builder_turns: list[BuilderTurn]
    skeptic_turns: list[SkepticTurn]
    sustained: list[Objection]
    struck_citations: list[str]


class DebateState(TypedDict, total=False):
    """One round of argument. The turns accumulate so each agent reads what has
    been said; everything else the debate needs sits on `_Deps`."""

    round: int
    transcript: list[dict]
    builders: list[BuilderTurn]
    skeptics: list[SkepticTurn]


@dataclass
class _Deps:
    """What both sides share for the length of one debate."""

    ctx: RunContext
    g: KnowledgeGraph
    rounds: int
    skeptic_model: str | None
    common: str
    b_tools: list
    s_tools: list
    target: Any
    struck: list[str] = field(default_factory=list)

    def logger(self, agent: str):
        def log(name: str, args: dict, result) -> None:
            self.ctx.log(agent, f"{name}({json.dumps(args)[:120]})")
        return log

    def emit(self, agent: str, turn_no: int,
             items: list[tuple[str, str | None, str, str, list[str], str, dict]]) -> None:
        """items: (key, hypothesis_id, plain, technical text, cited_ids, status, extra details)"""
        for key, hyp, plain, text, cited, status, extra in items:
            ok, bad = _valid(self.g, cited)
            self.struck.extend(bad)
            parents = [p for p in (_prov_ref(self.g, i, hyp) for i in ok) if p and p in self.ctx.prov_nodes]
            self.ctx.prov(ProvNode(id=f"debate:{agent}:{turn_no}:{key}", node_type="debate", step_id=hyp,
                                   agent_id=agent, parent_ids=parents, status=status,
                                   summary=(plain or text)[:220],
                                   details={"agent": agent, "turn": turn_no, "plain": plain, "text": text,
                                            "cited_ids": ok, "struck_citations": bad, **extra}))


def _build_flow(d: _Deps):
    """builder → skeptic → another round, or stop. The cycle is the debate."""

    async def builder(state: DebateState) -> DebateState:
        rnd, transcript = state["round"], state["transcript"]
        d.ctx.agent_status("builder", "reasoner", "Builder", "running", f"round {rnd}")
        tok = current_agent.set(f"builder r{rnd}")      # so its model calls are named in the log
        said = (f"Target: {d.target.name} (id {d.target.id}). Round {rnd} of {d.rounds}.\n"
                + ("Debate so far:\n" + json.dumps(transcript, indent=1) if transcript else
                   "Start by exploring the graph, then propose your route."))
        bt = (await d.ctx.client.run_tools([{"role": "user", "content": said}], d.b_tools,
                                           instructions=d.common + "\n\n" + prompt("builder"), schema=BuilderTurn,
                                           effort="medium", on_call=d.logger("builder"))).parsed
        hyp_of = {o.id: o.hypothesis_id for t in state["skeptics"] for o in t.objections}
        d.emit("builder", rnd, [(a.hypothesis_id, a.hypothesis_id, a.plain, a.claim,
                                 a.cited_ids + [i for op in a.procedure for i in op.cited_ids], "pass",
                                 {"name": a.name, "procedure": [op.model_dump() for op in a.procedure]})
                                for a in bt.arguments]
               + [(f"re-{r.objection_id}", hyp_of.get(r.objection_id), r.plain, r.response, r.cited_ids,
                   "warn" if r.concede else "pass", {"objection_id": r.objection_id, "concede": r.concede})
                  for r in bt.rebuttals])
        current_agent.reset(tok)
        d.ctx.agent_status("builder", "reasoner", "Builder", "done", bt.summary[:160])
        d.ctx.log("builder", bt.summary)
        return {"builders": state["builders"] + [bt], "transcript": transcript + [{"builder": bt.model_dump()}]}

    async def skeptic(state: DebateState) -> DebateState:
        rnd, transcript = state["round"], state["transcript"]
        d.ctx.agent_status("skeptic", "reasoner", "Skeptic", "running", f"round {rnd}")
        tok = current_agent.set(f"skeptic r{rnd}")      # so its model calls are named in the log
        said = (f"Target: {d.target.name} (id {d.target.id}). Round {rnd} of {d.rounds}. "
                + ("This is the final round: keep only objections the evidence sustains.\n"
                   if rnd == d.rounds else "\n")
                + "Debate so far:\n" + json.dumps(transcript, indent=1))
        st = (await d.ctx.client.run_tools([{"role": "user", "content": said}], d.s_tools,
                                           instructions=d.common + "\n\n" + prompt("skeptic"), schema=SkepticTurn,
                                           effort="medium", model=d.skeptic_model,
                                           on_call=d.logger("skeptic"))).parsed
        d.emit("skeptic", rnd, [(o.id, o.hypothesis_id, o.plain, o.claim, o.cited_ids,
                                 "fail" if o.severity == "fatal" else "warn" if o.severity == "major" else "skip",
                                 {"objection_id": o.id, "severity": o.severity})
                                for o in st.objections])
        current_agent.reset(tok)
        d.ctx.agent_status("skeptic", "reasoner", "Skeptic", "done", st.summary[:160])
        d.ctx.log("skeptic", st.summary)
        return {"skeptics": state["skeptics"] + [st], "round": rnd + 1,
                "transcript": transcript + [{"skeptic": st.model_dump()}]}

    def another_round(state: DebateState) -> str:
        return "builder" if state["round"] <= d.rounds else END

    flow = StateGraph(DebateState)
    flow.add_node("builder", builder)
    flow.add_node("skeptic", skeptic)
    flow.add_edge(START, "builder")
    flow.add_edge("builder", "skeptic")
    flow.add_conditional_edges("skeptic", another_round, {"builder": "builder", END: END})
    return flow.compile()


async def run(ctx: RunContext, g: KnowledgeGraph,
              research: Callable[[str, str], Awaitable[dict]],
              propose: Callable[..., Awaitable[dict]], rounds: int = 2,
              skeptic_model: str | None = None) -> DebateResult:
    """Builder and Skeptic argue over the graph for `rounds` rounds, then what
    the Skeptic still objects to after the Builder's last answer stands."""
    d = _Deps(
        ctx=ctx, g=g, rounds=rounds, skeptic_model=skeptic_model,
        common=prompt("debate_common"),
        b_tools=build_tools(g, research, propose,
                            {"overview", "get_node", "precedents", "find_clues",
                             "request_research", "propose_step"}),
        s_tools=build_tools(g, research, propose,
                            {"overview", "get_node", "precedents", "find_clues", "request_research"}),
        target=g.molecules[g.target_id],
    )
    final: DebateState = await _build_flow(d).ainvoke(
        {"round": 1, "transcript": [], "builders": [], "skeptics": []},
        {"recursion_limit": 4 * rounds + 6})
    builders, skeptics = final["builders"], final["skeptics"]
    withdrawn = {w for s in skeptics for w in s.withdrawn}
    return DebateResult(route=builders[-1].route, builder_turns=builders, skeptic_turns=skeptics,
                        sustained=[o for o in skeptics[-1].objections if o.id not in withdrawn],
                        struck_citations=sorted(set(d.struck)))
