"""The single entry point from 'a molecule mentioned somewhere' to a verified
structure. Every source (LLM extraction, USPTO, templates, user input) goes
through `resolve()`:
  SMILES  -> RDKit canonicalisation (name looked up in PubChem if known)
  name    -> PubChem, then OPSIN (systematic names, incl. never-made molecules)
LLMs never supply SMILES."""
from __future__ import annotations

import asyncio
from urllib.parse import quote

import httpx
from pydantic import BaseModel
from rdkit.Chem import rdMolDescriptors

from ..store import get_store
from . import pubchem
from . import rdkit_utils as rd

OPSIN = "https://www.ebi.ac.uk/opsin/ws/{}.json"


class MolRef(BaseModel):
    name: str | None = None
    smiles: str | None = None

    @property
    def label(self) -> str:
        return self.name or self.smiles or "?"


class Resolved(BaseModel):
    ok: bool
    query: str
    inchikey: str | None = None
    smiles: str | None = None
    name: str | None = None
    cid: int | None = None
    method: str | None = None        # smiles | pubchem | opsin
    known: bool = False              # has a PubChem record
    error: str | None = None
    tried: list[str] = []
    # a lookup service did not answer: the failure says nothing about the
    # molecule, so callers may retry, and must not report it as "not found"
    unavailable: bool = False


def formula_label(smiles: str) -> str:
    m = rd.parse(smiles)
    return rdMolDescriptors.CalcMolFormula(m) if m else smiles


class Unavailable(Exception):
    """A lookup service did not answer."""


async def _opsin(name: str) -> str | None:
    store = get_store()
    key = name.lower().strip()
    if (hit := store.cache_get("opsin.v1", key)) is not None:
        return hit or None
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(OPSIN.format(quote(name)))
    except httpx.HTTPError as e:
        raise Unavailable(f"OPSIN: {type(e).__name__}") from e
    if r.status_code not in (200, 404):
        raise Unavailable(f"OPSIN: HTTP {r.status_code}")
    smi = r.json().get("smiles") if r.status_code == 200 else None
    store.cache_set("opsin.v1", key, smi or "")
    return smi


async def from_smiles(smiles: str, query: str | None = None, want_name: bool = True) -> Resolved:
    m = rd.parse(smiles)
    if m is None:
        return Resolved(ok=False, query=query or smiles, error="invalid SMILES")
    canon, key = rd.Chem.MolToSmiles(m), rd.inchikey(m)
    hit = await pubchem.lookup_inchikey(key) if (want_name and key) else None
    return Resolved(ok=True, query=query or smiles, inchikey=key, smiles=canon,
                    name=(hit or {}).get("Title") or query or formula_label(canon),
                    cid=(hit or {}).get("CID"), method="smiles", known=bool(hit))


async def from_name(name: str) -> Resolved:
    res = await pubchem.resolve(name)
    if res.ok:
        return Resolved(ok=True, query=name, inchikey=res.inchikey, smiles=res.smiles, name=res.title or name,
                        cid=res.cid, method="pubchem", known=True, tried=res.tried)
    tried = res.tried + ["opsin"]
    try:
        smi = await _opsin(name)
    except Unavailable:
        smi, opsin_down = None, True
    else:
        opsin_down = False
    if smi and (r := await from_smiles(smi, query=name)).ok:
        r.method = "opsin"
        r.name = r.name if r.known else name
        r.tried = tried
        return r
    if res.unavailable or opsin_down:
        down = " and ".join(s for s, d in (("PubChem", res.unavailable), ("OPSIN", opsin_down)) if d)
        return Resolved(ok=False, query=name, tried=tried, unavailable=True,
                        error=f"{down} did not respond, so the name could not be looked up")
    return Resolved(ok=False, query=name, tried=tried,
                    error="no compound by this name in PubChem, and it is not a systematic name OPSIN can parse")


async def resolve(ref: MolRef, want_name: bool = True) -> Resolved:
    if ref.smiles:
        return await from_smiles(ref.smiles, query=ref.name, want_name=want_name)
    if ref.name:
        return await from_name(ref.name)
    return Resolved(ok=False, query="", error="empty reference")


async def resolve_many(refs: list[MolRef], want_name: bool = True) -> list[Resolved]:
    return list(await asyncio.gather(*(resolve(r, want_name) for r in refs)))
