"""Builder vs Skeptic debate over the knowledge graph.

Each turn is a Muse Spark tool loop (graph tools) that ends in a structured
message. Code validates every cited id; unsupported claims are struck out.
The debate informs the verdict but cannot override computed grades."""
from __future__ import annotations

import json
from typing import Awaitable, Callable, Literal

from pydantic import BaseModel, Field

from ..context import RunContext, prompt
from ..events import ProvNode
from ..graph import KnowledgeGraph
from .graph_tools import build_tools, node_kind


# ---------------------------------------------------------------- turn schemas (LLM)

class StepArgument(BaseModel):
    hypothesis_id: str
    claim: str = Field(description="Why this step works, with the key evidence (scores, conditions, sources)")
    recommended_conditions: str | None
    cited_ids: list[str]


class Rebuttal(BaseModel):
    objection_id: str
    concede: bool
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


async def run(ctx: RunContext, g: KnowledgeGraph,
              research: Callable[[str, str], Awaitable[dict]],
              propose: Callable[..., Awaitable[dict]], rounds: int = 2,
              skeptic_model: str | None = None) -> DebateResult:
    common = prompt("debate_common")
    b_tools = build_tools(g, research, propose,
                          {"overview", "get_node", "precedents", "find_clues", "request_research", "propose_step"})
    s_tools = build_tools(g, research, propose,
                          {"overview", "get_node", "precedents", "find_clues", "request_research"})
    target = g.molecules[g.target_id]
    transcript: list[dict] = []
    builders: list[BuilderTurn] = []
    skeptics: list[SkepticTurn] = []
    struck: list[str] = []

    def tool_logger(agent: str):
        def log(name: str, args: dict, result) -> None:
            brief = json.dumps(args)[:120]
            ctx.log(agent, f"🔧 {name}({brief})")
        return log

    def emit(agent: str, turn_no: int, items: list[tuple[str, str | None, str, list[str], str]]):
        """items: (key, hypothesis_id, text, cited_ids, status)"""
        for key, hyp, text, cited, status in items:
            ok, bad = _valid(g, cited)
            struck.extend(bad)
            parents = [p for p in (_prov_ref(g, i, hyp) for i in ok) if p and p in ctx.prov_nodes]
            ctx.prov(ProvNode(id=f"debate:{agent}:{turn_no}:{key}", node_type="debate", step_id=hyp,
                              agent_id=agent, parent_ids=parents, status=status,
                              summary=f"{'🔨' if agent == 'builder' else '🔍'} {text[:220]}",
                              details={"agent": agent, "turn": turn_no, "text": text, "cited_ids": ok,
                                       "struck_citations": bad}))

    for rnd in range(1, rounds + 1):
        # ---- Builder
        ctx.agent_status("builder", "reasoner", "🔨 Builder", "running", f"round {rnd}")
        b_input = (f"Target: {target.name} (id {target.id}). Round {rnd} of {rounds}.\n"
                   + ("Debate so far:\n" + json.dumps(transcript, indent=1) if transcript else
                      "Start by exploring the graph, then propose your route."))
        bt = (await ctx.client.run_tools([{"role": "user", "content": b_input}], b_tools,
                                         instructions=common + "\n\n" + prompt("builder"), schema=BuilderTurn,
                                         effort="medium", on_call=tool_logger("builder"))).parsed
        builders.append(bt)
        emit("builder", rnd, [(a.hypothesis_id, a.hypothesis_id, a.claim, a.cited_ids, "pass") for a in bt.arguments]
             + [(f"re-{r.objection_id}", None, ("Concedes: " if r.concede else "Rebuts: ") + r.response,
                 r.cited_ids, "warn" if r.concede else "pass") for r in bt.rebuttals])
        transcript.append({"builder": bt.model_dump()})
        ctx.agent_status("builder", "reasoner", "🔨 Builder", "done", bt.summary[:160])
        ctx.log("builder", bt.summary)

        # ---- Skeptic
        ctx.agent_status("skeptic", "reasoner", "🔍 Skeptic", "running", f"round {rnd}")
        s_input = (f"Target: {target.name} (id {target.id}). Round {rnd} of {rounds}. "
                   + ("This is the final round: keep only objections the evidence sustains.\n" if rnd == rounds else "\n")
                   + "Debate so far:\n" + json.dumps(transcript, indent=1))
        st = (await ctx.client.run_tools([{"role": "user", "content": s_input}], s_tools,
                                         instructions=common + "\n\n" + prompt("skeptic"), schema=SkepticTurn,
                                         effort="medium", model=skeptic_model, on_call=tool_logger("skeptic"))).parsed
        skeptics.append(st)
        emit("skeptic", rnd, [(o.id, o.hypothesis_id, f"[{o.severity}] {o.claim}", o.cited_ids,
                               "fail" if o.severity == "fatal" else "warn" if o.severity == "major" else "skip")
                              for o in st.objections])
        transcript.append({"skeptic": st.model_dump()})
        ctx.agent_status("skeptic", "reasoner", "🔍 Skeptic", "done", st.summary[:160])
        ctx.log("skeptic", st.summary)

    final_route = builders[-1].route
    withdrawn = {w for s in skeptics for w in s.withdrawn}
    sustained = [o for o in skeptics[-1].objections if o.id not in withdrawn]
    return DebateResult(route=final_route, builder_turns=builders, skeptic_turns=skeptics,
                        sustained=sustained, struck_citations=sorted(set(struck)))
