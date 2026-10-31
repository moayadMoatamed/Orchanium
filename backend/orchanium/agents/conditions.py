"""One conditions record per route step, where every field says where its
value came from:
  lab        the user's own lab note on this exact step
  reported   a published record of exactly this step
  analog     a published record of a close analog
  suggested  the Builder's recommendation from the precedents
  missing    nobody reported it
Reported values all come from one anchor report (lab notes first, then
exact records, then the fullest report), so they describe a procedure
someone actually ran; gaps are filled by the Builder's suggestion. Numeric
fields also give the spread across every successful report."""
from __future__ import annotations

from ..chem import rdkit_utils as rd
from ..graph import KnowledgeGraph
from ..models import Clue

# common solvents, so patent records (which list solvents among the reagents)
# can say which is which; the common name also beats PubChem's systematic one
_SOLVENTS = {
    "ClCCl": "dichloromethane", "ClC(Cl)Cl": "chloroform", "ClCCCl": "1,2-dichloroethane",
    "CN(C)C=O": "DMF", "CC(=O)N(C)C": "DMA", "CN1CCCC1=O": "NMP", "CS(C)=O": "DMSO",
    "C1CCOC1": "THF", "CC1CCCO1": "2-methyl-THF", "C1COCCO1": "1,4-dioxane", "CCOCC": "diethyl ether",
    "COC(C)(C)C": "MTBE", "COCCOC": "DME", "CC#N": "acetonitrile", "CC(C)=O": "acetone",
    "CCOC(C)=O": "ethyl acetate", "CO": "methanol", "CCO": "ethanol", "CC(C)O": "isopropanol",
    "CC(C)(C)O": "tert-butanol", "O": "water", "Cc1ccccc1": "toluene", "c1ccccc1": "benzene",
    "CCCCCC": "hexane", "CCCCCCC": "heptane", "c1ccncc1": "pyridine", "CC(=O)O": "acetic acid",
}
SOLVENTS = {rd.canonical(k): v for k, v in _SOLVENTS.items()}
FIELDS = ("reagents", "solvent", "temperature", "time", "atmosphere", "yield")


def _solvent(smiles: str | None) -> str | None:
    return SOLVENTS.get(rd.canonical(smiles)) if smiles else None


def _from_clue(c: Clue) -> dict[str, object]:
    solvents = [s for r in c.reagents if (s := _solvent(r.smiles))]
    reagents = [r.label for r in c.reagents if not _solvent(r.smiles)]
    if c.conditions.catalyst and c.conditions.catalyst not in reagents:
        reagents.append(c.conditions.catalyst)
    return {"reagents": ", ".join(reagents) or None,
            "solvent": c.conditions.solvent or (", ".join(solvents) or None),
            "temperature": c.conditions.temperature_c, "time": c.conditions.time,
            "atmosphere": None, "yield": c.yield_pct}


def _fmt(field: str, v) -> str:
    if field == "temperature":
        return f"{v:g} °C"
    if field == "yield":
        return f"{v:g}%"
    return str(v)


def record(g: KnowledgeGraph, hyp_id: str, suggested: dict | None = None) -> dict[str, dict]:
    precs = [p for p in g.precedents.get(hyp_id, []) if p.outcome == "success"]
    reports = []                                     # (basis, clue) best first
    for p in precs:
        for cid in g.reactions[p.observed_id].clue_ids:
            c = g.clues[cid]
            if c.outcome != "success":
                continue
            basis = "lab" if c.origin == "lab" else "reported" if p.score.grade == "direct" else "analog"
            reports.append((basis, c))
    # lab notes first, then exact records, then the fullest report, so the
    # fields mostly describe one coherent procedure; ties keep score order
    rank = {"lab": 0, "reported": 1, "analog": 2}
    reports.sort(key=lambda r: (rank[r[0]], -sum(v not in (None, "") for v in _from_clue(r[1]).values())))

    # every value comes from one anchor report, so the record describes a
    # procedure someone actually ran; other reports only give numeric spread
    anchor = reports[0] if reports else None
    out: dict[str, dict] = {}
    for f in FIELDS:
        v = _from_clue(anchor[1])[f] if anchor else None
        if v not in (None, ""):
            basis, c = anchor
            entry = {"value": _fmt(f, v), "basis": basis, "source": c.source.title, "url": c.source.url}
            nums = [x for _, r in reports if isinstance(x := _from_clue(r)[f], (int, float))]
            if len(set(nums)) > 1:
                entry.update(n=len(nums), range=f"{_fmt(f, min(nums))} to {_fmt(f, max(nums))}")
            out[f] = entry
            continue
        s = _suggested(f, suggested or {})
        out[f] = {"value": s, "basis": "suggested"} if s else {"value": None, "basis": "missing"}
    return out


def _suggested(field: str, s: dict) -> str | None:
    v = {"reagents": ", ".join(s.get("reagents") or []) or None, "solvent": s.get("solvent"),
         "temperature": s.get("temperature_c"), "time": s.get("time"), "atmosphere": s.get("atmosphere"),
         "yield": s.get("expected_yield_pct")}[field]
    return _fmt(field, v) if v not in (None, "") else None
