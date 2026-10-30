"""Reasoner: AND/OR best-first search over the knowledge graph from the target
back to purchasable leaves. Reports gaps (molecules with no known synthesis)
so the orchestrator can send follow-up research or ask for proposals."""
from __future__ import annotations

from ..config import settings
from ..context import RunContext
from ..events import RouteEvt
from ..graph import RunGraph
from ..models import Route

AGENT_ID = "reasoner"


def search(ctx: RunContext, g: RunGraph, k: int = 3, emit: bool = True) -> list[Route]:
    routes = g.find_routes(ctx.target.inchikey, max_depth=settings.max_route_depth, k=k)
    for r in routes:
        if emit:
            names = " → ".join(g.molecules[s.product].name for s in r.steps) or "(no steps)"
            gap_txt = f"{len(r.gaps)} gap(s)"
            ctx.log(AGENT_ID, f"Route {r.rank}: {len(r.steps)} steps, score {r.score:.2f}, "
                              f"{'complete' if r.complete else gap_txt}: {names}")
            ctx.bus.publish("route", RouteEvt(
                route_id=r.route_id, rank=r.rank, steps=[s.reaction_id for s in r.steps], score=r.score,
                label="complete" if r.complete else "partial",
                metrics={**r.metrics, "leaves": r.leaves, "gaps": r.gaps}))
    return routes


def gaps(g: RunGraph, routes: list[Route]) -> list[str]:
    """Unsolved molecules in the best routes, best route first."""
    out: list[str] = []
    for r in routes:
        for m in r.gaps:
            if m not in out and not m.startswith("unresolved:"):
                out.append(m)
    return out
