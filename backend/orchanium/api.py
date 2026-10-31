"""FastAPI surface: start runs, stream their events over SSE, replay stored
runs, take lab notes, and serve RDKit depictions. The UI is a pure function of the event
stream, so live and replay render identically."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from .chem import rdkit_utils as rd
from . import memory
from .config import settings
from .events import Event
from .lab import LabNote, NoteRejected, add_note
from .orchestrator import Orchestrator, live_bus
from .store import get_store

app = FastAPI(title="Orchanium", version="2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_tasks: dict[str, asyncio.Task] = {}


class RunRequest(BaseModel):
    target: str
    blind: bool = False
    web_budget: int = 4
    debate_rounds: int = 2
    hidden: list[str] = []
    similarity_cap: float | None = None


@app.get("/api/health")
async def health() -> dict:
    from .sources.uspto import available
    return {"ok": True, "meta_key": bool(settings.meta_api_key), "uspto_index": available(),
            "model": settings.meta_model}


@app.post("/api/runs")
async def start_run(req: RunRequest) -> dict:
    orch = Orchestrator(req.target, blind=req.blind or bool(req.hidden), hidden=req.hidden,
                        similarity_cap=req.similarity_cap, web_budget=req.web_budget,
                        debate_rounds=req.debate_rounds)
    _tasks[orch.run_id] = asyncio.create_task(orch.run())
    return {"run_id": orch.run_id, "target": req.target, "blind": orch.blind}


@app.get("/api/runs")
async def list_runs(limit: int = 30) -> list[dict]:
    return get_store().list_runs(limit)


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str) -> dict:
    events = get_store().events(run_id)
    if not events:
        raise HTTPException(404, "unknown run")
    return {"run_id": run_id, "events": [e.model_dump() for e in events],
            "live": live_bus(run_id) is not None and not live_bus(run_id).closed}


def _sse(event: Event) -> str:
    """Each frame carries its sequence number as the SSE id, so a dropped
    connection resumes exactly where it left off (the browser replays it back
    in the Last-Event-ID header)."""
    return (f"id: {event.seq}\nevent: {event.kind}\n"
            f"data: {json.dumps(event.model_dump(), default=str)}\n\n")


SSE_HEADERS = {"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}
HEARTBEAT_S = 15.0


@app.get("/api/runs/{run_id}/events")
async def stream(
    request: Request,
    run_id: str,
    replay_speed: float = Query(0, description="0 = as fast as possible"),
    since: int = Query(0, description="resume after this sequence number"),
):
    """Live runs stream from the bus (history first, then live). Finished runs
    replay from SQLite, optionally paced by their original timing. Both resume
    from `since` / Last-Event-ID, so a dropped connection loses nothing."""
    resume = max(since, int(request.headers.get("last-event-id") or 0))
    bus = live_bus(run_id)

    if bus is not None and not bus.closed:
        queue = bus.subscribe()

        async def live():
            while True:
                try:
                    evt = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_S)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"      # keeps proxies from closing an idle stream
                    continue
                if evt is None:
                    yield "event: end\ndata: {}\n\n"
                    return
                if evt.seq > resume:
                    yield _sse(evt)

        return StreamingResponse(live(), media_type="text/event-stream", headers=SSE_HEADERS)

    events = [e for e in get_store().events(run_id) if e.seq > resume]
    if not events and not resume:
        raise HTTPException(404, "unknown run")

    async def replay():
        prev: float | None = None
        for e in events:
            if replay_speed > 0 and prev is not None:
                await asyncio.sleep(min((e.ts - prev) / replay_speed, 2.0))
            prev = e.ts
            yield _sse(e)
        yield "event: end\ndata: {}\n\n"

    return StreamingResponse(replay(), media_type="text/event-stream", headers=SSE_HEADERS)


@app.post("/api/runs/{run_id}/notes")
async def add_lab_note(run_id: str, note: LabNote) -> dict:
    """A chemist's result on one route step. It revises this run's verdict by
    the same rule and joins the lasting knowledge graph for later runs."""
    try:
        events = await add_note(run_id, note)
    except NoteRejected as e:
        raise HTTPException(409, str(e)) from e
    return {"events": [e.model_dump() for e in events]}


@app.get("/api/knowledge")
async def knowledge() -> dict:
    """Size of the lasting knowledge graph."""
    return await asyncio.to_thread(memory.stats)


@app.get("/api/depict")
async def depict(smiles: str, width: int = 260, height: int = 200, theme: str = "light") -> Response:
    svg = await asyncio.to_thread(rd.depict_svg, smiles, width, height, theme)
    if not svg:
        raise HTTPException(400, "could not parse SMILES")
    return Response(svg, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/api/mol3d")
async def mol3d(smiles: str) -> Response:
    mb = await asyncio.to_thread(rd.molblock_3d, smiles)
    if not mb:
        raise HTTPException(400, "could not embed 3D conformer")
    return Response(mb, media_type="chemical/x-mdl-molfile",
                    headers={"Cache-Control": "public, max-age=86400"})


@app.get("/api/molecule")
async def molecule(smiles: str) -> dict[str, Any]:
    return await asyncio.to_thread(rd.describe, smiles)
