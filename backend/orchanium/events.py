"""Typed event stream. The frontend rebuilds all UI state from these events alone,
so live runs and replays render identically."""
from __future__ import annotations

import asyncio
import time
from typing import Any, Literal

from pydantic import BaseModel, Field

NodeType = Literal[
    "query", "source", "extraction", "vision", "resolution",
    "check", "citation", "agreement", "verdict",
]
Status = Literal["pending", "running", "pass", "warn", "fail"]
Verdict = Literal["literature", "proposed", "rejected", "purchasable"]
AgentType = Literal[
    "planner", "researcher", "figure_reader", "graph_builder",
    "citation_checker", "critic", "reasoner", "reporter",
]
EventKind = Literal[
    "run.status", "agent.status", "agent.log", "prov.node",
    "graph.molecule", "graph.reaction", "route", "cost", "report",
]


class ProvNode(BaseModel):
    """One node in the Verification Chain. Re-emitting the same id is an upsert."""
    id: str
    parent_ids: list[str] = Field(default_factory=list)
    step_id: str | None = None          # reaction id this node supports
    node_type: NodeType
    status: Status = "pending"
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)
    agent_id: str | None = None
    verdict: Verdict | None = None      # only for node_type == "verdict"


class AgentStatus(BaseModel):
    agent_id: str
    agent_type: AgentType
    label: str
    status: Literal["idle", "running", "done", "failed"]
    message: str = ""


class AgentLog(BaseModel):
    agent_id: str
    text: str
    level: Literal["info", "warn", "error"] = "info"


class MoleculeEvt(BaseModel):
    id: str                              # InChIKey
    smiles: str
    name: str
    status: Literal["target", "intermediate", "purchasable", "unresolved"] = "intermediate"
    purchasable: bool = False
    depth: int | None = None


class ReactionEvt(BaseModel):
    id: str
    reactants: list[str]                 # molecule ids
    products: list[str]
    reagents: list[str] = Field(default_factory=list)   # names, free text
    evidence_ids: list[str] = Field(default_factory=list)
    label: Verdict | None = None
    critic: Literal["pass", "warn", "block"] | None = None


class RouteEvt(BaseModel):
    route_id: str
    rank: int
    steps: list[str]                     # reaction ids, starting materials -> target
    score: float
    label: str
    metrics: dict[str, Any] = Field(default_factory=dict)


class CostEvt(BaseModel):
    llm_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    searches: int = 0
    sam_images: int = 0
    usd: float = 0.0


class Event(BaseModel):
    seq: int
    run_id: str
    ts: float
    kind: EventKind
    data: dict[str, Any]


class EventBus:
    """Per-run fan-out: every published event goes to the persistence sink and
    to every live subscriber queue."""

    def __init__(self, run_id: str, sink=None):
        self.run_id = run_id
        self._seq = 0
        self._subs: list[asyncio.Queue[Event | None]] = []
        self._history: list[Event] = []
        self._sink = sink                # callable(Event) -> None, e.g. SQLite writer
        self.closed = False

    def publish(self, kind: EventKind, data: BaseModel | dict[str, Any]) -> Event:
        payload = data.model_dump() if isinstance(data, BaseModel) else data
        self._seq += 1
        evt = Event(seq=self._seq, run_id=self.run_id, ts=time.time(), kind=kind, data=payload)
        self._history.append(evt)
        if self._sink:
            self._sink(evt)
        for q in self._subs:
            q.put_nowait(evt)
        return evt

    # convenience wrappers
    def prov(self, node: ProvNode) -> Event:
        return self.publish("prov.node", node)

    def log(self, agent_id: str, text: str, level: str = "info") -> Event:
        return self.publish("agent.log", AgentLog(agent_id=agent_id, text=text, level=level))

    def subscribe(self) -> asyncio.Queue[Event | None]:
        """New subscribers first receive the full history, then live events."""
        q: asyncio.Queue[Event | None] = asyncio.Queue()
        for e in self._history:
            q.put_nowait(e)
        if self.closed:
            q.put_nowait(None)
        else:
            self._subs.append(q)
        return q

    def close(self) -> None:
        self.closed = True
        for q in self._subs:
            q.put_nowait(None)
        self._subs.clear()
