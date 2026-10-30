"""Held-out evaluation: run Orchanium on a patent target while hiding that
patent and every molecule on its route (except starting materials), then
score the proposed route against the patent's real route.

    python scripts/eval_holdout.py US20160024004A1 [--web 4] [--rounds 2]

A ground-truth step counts as recovered when the proposed route makes the same
product AND (uses the same reaction class OR shares a non-reagent starting
material). Stereo/salt forms are ignored (InChIKey connectivity block)."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from orchanium.chem import rdkit_utils as rd  # noqa: E402
from orchanium.orchestrator import Orchestrator  # noqa: E402


def block(smiles: str) -> str | None:
    k = rd.inchikey(smiles)
    return k.split("-")[0] if k else None


def ground_truth(c: dict) -> list[dict]:
    steps = []
    for key in ("step_A", "step_B"):
        s = c[key]
        partners = [r for r in s["reactants"] if rd.parse(r) and rd.parse(r).GetNumHeavyAtoms() > 4]
        steps.append({"product": s["product"], "classes": s["classes"], "partners": partners, "yield": s["yield"]})
    return steps


def score(g, verdict, truth: list[dict]) -> dict:
    route = [g.reactions[h] for h in verdict.route]
    rows = []
    for t in truth:
        tb = block(t["product"])
        partner_blocks = {block(p) for p in t["partners"]}
        hit = None
        for h in route:
            if g.molecules[h.product].id.split("-")[0] != tb:
                continue
            shares = partner_blocks & {x.split("-")[0] for x in h.reactants}
            same_class = bool(set(h.classes) & set(t["classes"]))
            if shares or same_class:
                hit = {"hypothesis": h.id, "same_class": same_class, "shared_partners": len(shares),
                       "grade": g.grade(h.id).grade}
                break
        # was the ground-truth step at least among the candidates the system considered?
        considered = any(g.molecules[h.product].id.split("-")[0] == tb and (
            partner_blocks & {x.split("-")[0] for x in h.reactants} or set(h.classes) & set(t["classes"]))
            for h in g.hypotheses())
        rows.append({"truth_classes": t["classes"], "recovered": bool(hit), "considered": considered, **(hit or {})})
    return {"steps": rows, "all_recovered": all(r["recovered"] for r in rows),
            "last_step_recovered": rows[-1]["recovered"], "route_length": len(route),
            "verdict": verdict.label, "confidence": verdict.confidence}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("patent")
    ap.add_argument("--web", type=int, default=4)
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--strict", type=float, default=None,
                    help="also hide evidence with molecules more similar than this to the target/intermediates")
    a = ap.parse_args()
    cands = {c["patent"]: c for c in json.loads((ROOT / "data" / "holdout_candidates.json").read_text())}
    c = cands[a.patent]
    truth = ground_truth(c)
    hidden_mols = [t["product"] for t in truth[:-1]]                       # intermediates (SMILES)
    orch = Orchestrator(c["target"], blind=True, hidden=[a.patent], hidden_molecules=hidden_mols,
                        similarity_cap=a.strict,
                        web_budget=a.web, debate_rounds=a.rounds,
                        extra_sink=lambda e: print(f"[{e.data['agent_id']:>16}] {e.data['text'][:200]}", flush=True)
                        if e.kind == "agent.log" and "🔧" not in e.data["text"] else None)
    res = await orch.run()
    v = res["verdict"]
    result = {"patent": a.patent, "target": c["target"], "run_id": res["run_id"], "strict": a.strict,
              "cost_usd": res["summary"]["cost"]["usd"], **score(res["graph"], v, truth)}
    g = res["graph"]
    result["proposed_route"] = [f"{' + '.join(g.molecules[x].name for x in g.reactions[h].reactants)} → "
                                f"{g.molecules[g.reactions[h].product].name}  [{', '.join(g.reactions[h].classes)}]"
                                for h in v.route]
    out = ROOT / "data" / "eval" / f"holdout_{a.patent}{'_strict' if a.strict else ''}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, default=str))
    print("\n" + json.dumps(result, indent=1, default=str))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
