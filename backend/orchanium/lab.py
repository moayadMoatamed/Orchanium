"""Lab notes: a chemist's own result on a route step, as evidence.

A note becomes a clue (origin "lab") on the step's exact reaction, so it goes
through the same ingest, scoring and citation path as any published clue, and
it outranks literature because it is a direct record of this very step
(graph.grade, verdict.decide). Each finished run keeps a snapshot of its final
graph, so a note revises that run in place: the verdict is recomputed by the
same fixed rule, and a `revision` event says what changed and why, so the
answer never changes silently. The note also joins the lasting knowledge graph
(memory.py), so every later run sees it."""
from __future__ import annotations

import asyncio
import pickle
import time
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

from . import memory
from .agents import reporter, verdict
from .agents.debate import DebateResult
from .chem.resolver import MolRef
from .clues import ingest, link_and_emit
from .config import DATA
from .context import RunContext, short_id
from .events import Event, EventBus, ProvNode, RouteEvt
from .graph import KnowledgeGraph
from .models import Clue, Conditions, SourceRef
from .store import get_store

SNAPSHOTS = DATA / "snapshots"
_lock = asyncio.Lock()


@dataclass
class Snapshot:
    graph: KnowledgeGraph
    debate: DebateResult | None
    verdict: verdict.Verdict
    report: str
    target: Any


def save_snapshot(run_id: str, snap: Snapshot) -> None:
    SNAPSHOTS.mkdir(exist_ok=True)
    (SNAPSHOTS / f"{run_id}.pkl").write_bytes(pickle.dumps(snap))


def load_snapshot(run_id: str) -> Snapshot | None:
    path = SNAPSHOTS / f"{run_id}.pkl"
    return pickle.loads(path.read_bytes()) if path.exists() else None


class LabNote(BaseModel):
    step_id: str
    outcome: Literal["success", "failure"]
    yield_pct: float | None = None
    reagents: list[str] = Field(default_factory=list)
    solvent: str | None = None
    temperature_c: float | None = None
    time: str | None = None
    scale: str | None = None
    observations: str | None = None
    notes: str | None = None


class NoteRejected(Exception):
    pass


GRADE_WORDS = {"direct": "published for this exact reaction", "analog": "supported by similar published reactions",
               "weak": "backed only by loosely similar reactions", "none": "without published evidence",
               "blocked": "ruled out by the chemistry checks"}


def _state(s: verdict.StepVerdict) -> str:
    if s.lab_successes:
        return "done in your lab"
    if s.lab_failures:
        return "failed in your lab"
    return GRADE_WORDS.get(s.grade, s.grade)


def describe_changes(before: verdict.Verdict, after: verdict.Verdict, names: dict[str, str]) -> list[str]:
    """What a revision changed, in plain sentences, step by step and overall."""
    old = {s.hypothesis_id: s for s in before.steps}
    changes = []
    for i, s in enumerate(after.steps, 1):
        o = old.get(s.hypothesis_id)
        title = f"Step {i}" + (f" ({names[s.hypothesis_id]})" if names.get(s.hypothesis_id) else "")
        if o is None:
            changes.append(f"{title} is new in the route: {_state(s)}.")
        elif _state(o) != _state(s):
            changes.append(f"{title}: before, {_state(o)}; now, {_state(s)}.")
        elif (o.lab_successes, o.lab_failures) != (s.lab_successes, s.lab_failures):
            changes.append(f"{title} has another result from your lab ({_state(s)}).")
    if before.label != after.label:
        changes.append(f"The overall answer moved from {before.label} to {after.label}.")
    if round(before.confidence, 2) != round(after.confidence, 2):
        changes.append(f"Confidence went from {before.confidence:.0%} to {after.confidence:.0%}.")
    return changes or ["The answer did not change: the note agrees with the evidence it already had."]


def _clue(run_id: str, g: KnowledgeGraph, note: LabNote) -> Clue:
    h = g.reactions[note.step_id]
    ref = lambda x: MolRef(name=g.molecules[x].name, smiles=g.smiles(x))  # noqa: E731
    said = " ".join(filter(None, [note.observations, note.notes]))
    return Clue(
        id=short_id("lab", run_id, note.step_id, time.time()), origin="lab", need_id=note.step_id,
        reactants=[ref(x) for x in h.reactants], products=[ref(h.product)],
        reagents=[MolRef(name=n) for n in note.reagents if n.strip()],
        conditions=Conditions(temperature_c=note.temperature_c, time=note.time, solvent=note.solvent,
                              text=f"scale: {note.scale}" if note.scale else None),
        yield_pct=note.yield_pct, outcome=note.outcome,
        source=SourceRef(kind="lab", title=f"Your lab note, {time.strftime('%d %b %Y')}", snippet=said or None))


async def add_note(run_id: str, note: LabNote) -> list[Event]:
    async with _lock:
        snap = load_snapshot(run_id)
        if snap is None:
            raise NoteRejected("This run has no saved graph (it is still running, stopped early, or is older "
                               "than lab notes). Run the molecule again to add notes.")
        if note.step_id not in snap.verdict.route:
            raise NoteRejected("That step is not part of this run's route.")
        store, g, events = get_store(), snap.graph, []

        def sink(e: Event):
            store.append_event(e)
            events.append(e)
        bus = EventBus(run_id, sink=sink)
        bus._seq = store.last_seq(run_id)           # continue the run's own event log
        ctx = RunContext(run_id=run_id, bus=bus, client=None, target=snap.target)

        clue = _clue(run_id, g, note)
        qid = f"q:{clue.id}"
        ctx.prov(ProvNode(id=qid, node_type="query", status="pass", agent_id="lab", step_id=note.step_id,
                          parent_ids=[f"hyp:{note.step_id}"], summary="Lab note added by you",
                          details={"source": "lab"}))
        await ingest(ctx, g, [clue], qid, "lab")
        link_and_emit(ctx, g, [note.step_id])

        before = snap.verdict
        after = verdict.decide(ctx, g, snap.debate)
        bus.publish("route", RouteEvt(route_id="final", rank=1, steps=after.route, score=after.confidence,
                                      label=after.label, metrics={**g.metrics([g.grade(x) for x in after.route]),
                                                                  "gaps": after.gaps}))
        data = reporter.build_data(g, after, snap.debate)
        names = {s["hypothesis_id"]: s["name"] for s in data["steps"] if s.get("name")}
        changes = describe_changes(before, after, names)
        snap.report += (f"\n\n## Revision after a lab note ({time.strftime('%d %b %Y')})\n"
                        + "\n".join(f"- {c}" for c in changes))
        bus.publish("report", {"markdown": snap.report, "data": data})
        bus.publish("revision", {"note_id": clue.id, "step_id": note.step_id, "outcome": note.outcome,
                                 "changes": changes, "at": time.time(),
                                 "before": {"label": before.label, "confidence": before.confidence},
                                 "after": {"label": after.label, "confidence": after.confidence}})

        snap.verdict = after
        save_snapshot(run_id, snap)
        memory.remember(g, run_id, [clue.id])
        store.update_summary(run_id, {"verdict": after.label, "confidence": after.confidence})
        return events
