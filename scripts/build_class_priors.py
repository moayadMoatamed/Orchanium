"""How routinely each reaction class is used in real patent chemistry.

    python scripts/build_class_priors.py [--sample 40000]

Knowing that a step is an amide coupling is evidence that it can be made to
work, even when no published reaction resembles it closely. That matters most
for the compounds Orchanium exists for: a molecule nobody has made has no close
precedent for its final steps by definition, so without this the score punishes
novelty itself.

This takes a systematic sample of the USPTO index, classifies each reaction
with the same templates the decomposer uses, and writes each class's share to
data/class_priors.json.

The number is a proxy: it measures how commonly chemists reach for a class, not
how often it succeeds. It is capped well below a real precedent so it can never
stand in for one.
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from orchanium.chem import rdkit_utils as rd  # noqa: E402
from orchanium.chem.reactions import REGISTRY, classify  # noqa: E402

CAP = 0.45          # a class prior can never reach "analog", let alone "direct"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=40000)
    ap.add_argument("--db", default=str(ROOT / "data" / "uspto" / "uspto.sqlite"))
    a = ap.parse_args()

    db = sqlite3.connect(a.db)
    total = db.execute("select count(*) from rxn").fetchone()[0]
    step = max(1, total // a.sample)
    rows = db.execute("select reactants, product from rxn where rowid % ? = 0 limit ?", (step, a.sample))

    counts: Counter[str] = Counter()
    seen = 0
    for reactants, product in rows:
        pm = rd.parse(product)
        rms = [m for s in reactants.split(".") if (m := rd.parse(s))]
        if pm is None or not rms:
            continue
        seen += 1
        for name in classify(rms, pm):
            counts[name] += 1
        if seen % 5000 == 0:
            print(f"  {seen} reactions, {sum(counts.values())} classified", flush=True)

    top = max(counts.values(), default=1)
    # log scale: the commonest class earns the cap, rarer ones fall away gently
    priors = {name: round(CAP * math.log1p(counts[name]) / math.log1p(top), 3)
              for name in (rc.name for rc in REGISTRY) if counts[name]}
    out = {"sampled": seen, "classified": sum(counts.values()), "cap": CAP,
           "counts": dict(counts.most_common()), "priors": priors}
    path = ROOT / "data" / "class_priors.json"
    path.write_text(json.dumps(out, indent=1))
    print(f"\n{seen} reactions sampled of {total}; wrote {path}")
    for name, p in sorted(priors.items(), key=lambda x: -x[1]):
        print(f"  {p:>6.3f}  {name}  ({counts[name]})")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
