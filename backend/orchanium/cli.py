"""Command line entry point.

    python -m orchanium.cli run "paracetamol" [--blind] [--web 4] [--rounds 2]
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


async def _run(query: str, blind: bool, hide: list[str], web: int, rounds: int) -> None:
    from .orchestrator import Orchestrator
    orch = Orchestrator(query, blind=blind or bool(hide), hidden=hide, web_budget=web, debate_rounds=rounds,
                        extra_sink=_print_event)
    res = await orch.run()
    g, v, s = res["graph"], res["verdict"], res["summary"]
    print("\n" + "=" * 78)
    print(f"run {res['run_id']}: {res['status']}  blind={blind}  cost=${s['cost']['usd']:.3f}  "
          f"llm_calls={s['cost']['llm_calls']} searches={s['cost']['searches']}  clues={s['clues']}")
    if v:
        print(f"\nVERDICT: {v.label}  (confidence {v.confidence:.0%}, route from {v.route_source})")
        for r in v.reasons:
            print(f"  - {r}")
        for i, st in enumerate(v.steps, 1):
            print(f"  {i}. {st.reaction}\n     grade={st.grade} score={st.precedent_score} "
                  f"failures={st.failure_precedents} objections={[o.severity for o in st.objections]}")
    out = DATA / "runs" / res["run_id"]
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.md").write_text(res["report"] or "", encoding="utf-8")
    print(f"\nreport: {out / 'report.md'}")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="orchanium")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("query")
    r.add_argument("--blind", action="store_true", help="hide clues that contain or name the target")
    r.add_argument("--hide", action="append", default=[], help="blind mode: also hide this source (patent id or URL)")
    r.add_argument("--web", type=int, default=4, help="web research budget (researchers)")
    r.add_argument("--rounds", type=int, default=2, help="debate rounds (0 = no debate)")
    sub.add_parser("runs")
    ev = sub.add_parser("events")
    ev.add_argument("run_id")
    ev.add_argument("--kind", default=None)
    a = p.parse_args(argv)
    if a.cmd == "run":
        asyncio.run(_run(a.query, a.blind, a.hide, a.web, a.rounds))
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
