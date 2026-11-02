"""Mine the USPTO index for held-out evaluation targets: obscure drug-sized
molecules that one patent makes in a 2-step chain (step A's product is a
reactant of step B), where both steps are reaction classes Orchanium can
express. The patent's own route is the ground truth; the run hides it."""
from __future__ import annotations

import json
import random
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from orchanium.chem import purchasable  # noqa: E402
from orchanium.chem.reactions import classify  # noqa: E402
from rdkit import Chem, RDLogger  # noqa: E402

RDLogger.DisableLog("rdApp.*")
DB = Path(__file__).resolve().parents[1] / "data" / "uspto" / "uspto.sqlite"


def canon(s: str) -> str | None:
    m = Chem.MolFromSmiles(s)
    return Chem.MolToSmiles(m) if m else None


def main(n_patents: int = 4000, seed: int = 7):
    db = sqlite3.connect(DB)
    patents = [r[0] for r in db.execute("SELECT DISTINCT patent FROM rxn WHERE year >= 2010")]
    random.Random(seed).shuffle(patents)
    found = []
    for pat in patents[:n_patents]:
        rows = db.execute("SELECT id, reactants, product, yield_pct FROM rxn WHERE patent = ?", (pat,)).fetchall()
        if len(rows) < 2:
            continue
        by_product = {r[2]: r for r in rows}
        for _rid, reactants, product, yld in rows:
            tm = Chem.MolFromSmiles(product)
            if tm is None or not 20 <= tm.GetNumHeavyAtoms() <= 32:
                continue
            if Chem.FindMolChiralCenters(tm, includeUnassigned=True, useLegacyImplementation=False):
                continue
            frags = [c for c in (canon(s) for s in reactants.split(".")) if c]
            inter = [f for f in frags if f in by_product and f != product]
            if not inter:
                continue
            a = by_product[inter[0]]
            a_frags = [c for c in (canon(s) for s in a[1].split(".")) if c]
            mols_b = [Chem.MolFromSmiles(f) for f in frags if Chem.MolFromSmiles(f).GetNumHeavyAtoms() > 1]
            mols_a = [Chem.MolFromSmiles(f) for f in a_frags if Chem.MolFromSmiles(f).GetNumHeavyAtoms() > 1]
            cls_b, cls_a = classify(mols_b, tm), classify(mols_a, Chem.MolFromSmiles(inter[0]))
            if not cls_b or not cls_a:
                continue
            others_b = [f for f in frags if f != inter[0] and Chem.MolFromSmiles(f).GetNumHeavyAtoms() > 3]
            # the starting materials of step A should be plausible building blocks
            if any(Chem.MolFromSmiles(f).GetNumHeavyAtoms() > 18 for f in a_frags):
                continue
            found.append({"patent": pat, "target": product, "target_atoms": tm.GetNumHeavyAtoms(),
                          "step_A": {"reactants": a_frags, "product": inter[0], "classes": cls_a, "yield": a[3]},
                          "step_B": {"reactants": frags, "key_partner": others_b, "product": product,
                                     "classes": cls_b, "yield": yld},
                          "intermediate_purchasable": purchasable.check(None, inter[0]).purchasable})
            break
        if len(found) >= 40:
            break
    out = Path(__file__).resolve().parents[1] / "data" / "holdout_candidates.json"
    out.write_text(json.dumps(found, indent=1))
    print(f"{len(found)} candidates -> {out}")
    for f in found[:40]:
        print(f"{f['patent']:<16} {f['target_atoms']:>2} atoms  A: {f['step_A']['classes'][0]:<30} "
              f"B: {f['step_B']['classes'][0]:<30} {f['target']}")


if __name__ == "__main__":
    main()
