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


def formula_label(smiles: str) -> str:
    m = rd.parse(smiles)
    return rdMolDescriptors.CalcMolFormula(m) if m else smiles


async def _opsin(name: str) -> str | None:
    store = get_store()
    key = name.lower().strip()
    if (hit := store.cache_get("opsin.v1", key)) is not None:
        return hit or None
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(OPSIN.format(quote(name)))
    except httpx.HTTPError:
        return None
    smi = r.json().get("smiles") if r.status_code == 200 else None
    if r.status_code in (200, 404):
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
    smi = await _opsin(name)
    if smi and (r := await from_smiles(smi, query=name)).ok:
        r.method = "opsin"
        r.name = r.name if r.known else name
        r.tried = res.tried + ["opsin"]
        return r
    return Resolved(ok=False, query=name, error="not found in PubChem; OPSIN could not parse the name",
                    tried=res.tried + ["opsin"])


async def resolve(ref: MolRef, want_name: bool = True) -> Resolved:
    if ref.smiles:
        return await from_smiles(ref.smiles, query=ref.name, want_name=want_name)
    if ref.name:
        return await from_name(ref.name)
    return Resolved(ok=False, query="", error="empty reference")


async def resolve_many(refs: list[MolRef], want_name: bool = True) -> list[Resolved]:
    return list(await asyncio.gather(*(resolve(r, want_name) for r in refs)))
