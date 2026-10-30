"""Purchasability approximation, in order of evidence:
  1. curated, PubChem-resolved building-block list
  2. PubChem lists >= MIN_VENDORS chemical vendors for it, and it is
     building-block sized (vendors also sell complex drugs; those still count
     as synthesis targets)
  3. conservative size/simplicity heuristic
Clearly labelled as an approximation everywhere it surfaces."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel
from rdkit import Chem

from . import rdkit_utils as rd
from .pubchem import vendor_count

_DATA = Path(__file__).parent / "data" / "building_blocks.yaml"
_ALLOWED_HEURISTIC = {"C", "H", "N", "O", "S", "F", "Cl", "Br", "I", "B", "P", "Na", "K", "Li", "Mg"}


MIN_VENDORS = 5
MAX_BUILDING_BLOCK_ATOMS = 18


class Purchasability(BaseModel):
    purchasable: bool
    basis: Literal["catalog", "vendors", "heuristic", "none"]
    reason: str
    catalog_name: str | None = None


@lru_cache(maxsize=1)
def catalog() -> dict[str, dict]:
    return yaml.safe_load(_DATA.read_text(encoding="utf-8")) or {}


def check(inchikey: str | None, smiles: str | None, vendors: int = 0) -> Purchasability:
    cat = catalog()
    if inchikey and inchikey in cat:
        e = cat[inchikey]
        return Purchasability(purchasable=True, basis="catalog", catalog_name=e["name"],
                              reason=f"in curated building-block list as '{e['name']}'")
    # same connectivity, different stereo/charge form
    if inchikey:
        block = inchikey.split("-")[0]
        for k, e in cat.items():
            if k.startswith(block):
                return Purchasability(purchasable=True, basis="catalog", catalog_name=e["name"],
                                      reason=f"matches catalog entry '{e['name']}' (ignoring stereo/charge)")
    m = rd.parse(smiles)
    if m is None:
        return Purchasability(purchasable=False, basis="none", reason="structure unknown")
    heavy = m.GetNumHeavyAtoms()
    if vendors >= MIN_VENDORS and heavy <= MAX_BUILDING_BLOCK_ATOMS:
        return Purchasability(purchasable=True, basis="vendors",
                              reason=f"listed by {vendors} chemical vendors in PubChem (building-block sized)")
    stereo = Chem.FindMolChiralCenters(m, includeUnassigned=True, useLegacyImplementation=False)
    elements = {a.GetSymbol() for a in m.GetAtoms()}
    rings = m.GetRingInfo().NumRings()
    if heavy <= 8 and not stereo and rings <= 1 and elements <= _ALLOWED_HEURISTIC:
        return Purchasability(purchasable=True, basis="heuristic",
                              reason=f"small simple molecule ({heavy} heavy atoms, no stereocentres): "
                                     "likely commodity chemical (heuristic)")
    return Purchasability(purchasable=False, basis="none",
                          reason=f"not in catalog; too complex for heuristic ({heavy} heavy atoms, "
                                 f"{len(stereo)} stereocentres, {rings} rings)")


async def assess(inchikey: str | None, smiles: str | None, cid: int | None) -> Purchasability:
    """`check` plus the PubChem vendor signal when the compound has a CID."""
    quick = check(inchikey, smiles)
    if quick.basis == "catalog" or not cid:
        return quick
    return check(inchikey, smiles, await vendor_count(cid))
