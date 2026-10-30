"""Command line entry point.

    python -m orchanium.cli run "aspirin" [--angles 3]
    python -m orchanium.cli runs
    python -m orchanium.cli events RUN_ID [--kind prov.node]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from .config import DATA
from .events import Event
from .store import get_store

_COLORS = {"warn": "\033[33m", "error": "\033[31m"} if sys.stdout.isatty() else {}
_RESET = "\033[0m" if sys.stdout.isatty() else ""


def _print_event(e: Event) -> None:
    d = e.data
    if e.kind == "agent.log":
        color = _COLORS.get(d["level"], "")
        print(f"{color}[{d['agent_id']:>18}] {d['text']}{_RESET if color else ''}", flush=True)
    elif e.kind == "agent.status" and d["status"] in ("done", "failed"):
        print(f"[{d['agent_id']:>18}] == {d['status'].upper()} {d['message']}", flush=True)


async def _run(query: str, angles: int | None) -> None:
    from .orchestrator import Orchestrator
    orch = Orchestrator(query, n_angles=angles, extra_sink=_print_event)
    res = await orch.run()
    g = res["graph"]
    print("\n" + "=" * 78)
    print(f"run {res['run_id']}: {res['status']}  cost=${res['summary']['cost']['usd']:.3f}  "
          f"llm_calls={res['summary']['cost']['llm_calls']} searches={res['summary']['cost']['searches']}")
    for r in res["routes"]:
        print(f"\nRoute {r.rank} (score {r.score}, {'complete' if r.complete else 'partial'}) "
              f"metrics={json.dumps(r.metrics)}")
        for i, s in enumerate(r.steps, 1):
            rx = g.reactions[s.reaction_id]
            print(f"  {i}. {' + '.join(g.molecules[x].name for x in rx.reactants)} → {g.molecules[rx.product].name}"
                  f"   [{rx.label}, conf {rx.confidence}, critic {rx.critic.verdict if rx.critic else '-'}, "
                  f"{len(rx.evidence)} evidence]")
        if r.gaps:
            print("  gaps:", ", ".join(g.molecules[m].name for m in r.gaps))
    out = DATA / "runs" / res["run_id"]
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.md").write_text(res["report"] or "", encoding="utf-8")
    print(f"\nreport: {out / 'report.md'}")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="orchanium")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("query")
    r.add_argument("--angles", type=int, default=None)
    sub.add_parser("runs")
    ev = sub.add_parser("events")
    ev.add_argument("run_id")
    ev.add_argument("--kind", default=None)
    a = p.parse_args(argv)
    if a.cmd == "run":
        asyncio.run(_run(a.query, a.angles))
    elif a.cmd == "runs":
        for run in get_store().list_runs():
            print(run["id"], run["status"], run["target"], json.dumps((run["summary"] or {}).get("cost", {})))
    elif a.cmd == "events":
        for e in get_store().events(a.run_id):
            if not a.kind or e.kind == a.kind:
                print(json.dumps(e.model_dump(), default=str))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
