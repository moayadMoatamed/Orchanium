"""PubChem PUG REST: the only name -> structure source. LLMs never write SMILES
for names; they emit names and this module resolves them. Every lookup
(including misses) is cached in SQLite."""
from __future__ import annotations

import asyncio
import re
import time

import httpx
from pydantic import BaseModel

from ..store import get_store
from . import rdkit_utils as rd

PUG = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
PROPS = "SMILES,IsomericSMILES,CanonicalSMILES,InChIKey,IUPACName,MolecularFormula,Title"
CACHE_NS = "pubchem.v1"


class Resolution(BaseModel):
    query: str
    ok: bool
    cid: int | None = None
    smiles: str | None = None            # RDKit canonical (isomeric) SMILES
    inchikey: str | None = None          # RDKit InChIKey (graph node id)
    pubchem_inchikey: str | None = None
    iupac: str | None = None
    title: str | None = None
    formula: str | None = None
    tried: list[str] = []
    cached: bool = False
    error: str | None = None

    @property
    def display_name(self) -> str:
        return self.title or self.query


# PubChem asks for <= 5 requests/second.
class _RateLimiter:
    def __init__(self, per_sec: float):
        self._gap = 1.0 / per_sec
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def wait(self):
        async with self._lock:
            delta = time.monotonic() - self._last
            if delta < self._gap:
                await asyncio.sleep(self._gap - delta)
            self._last = time.monotonic()


_limiter = _RateLimiter(4.0)
_inflight: dict[str, asyncio.Future] = {}

_QTY = re.compile(r"^\s*(\d+(\.\d+)?\s*(equiv|eq|mol%|mmol|mol|g|mg|ml|mL)\.?\s+(of\s+)?)", re.I)
_TRAIL_PAREN = re.compile(r"\s*\((cat(alyst|\.)?|excess|aq\.?|aqueous|conc\.?|anhydrous|\d+(\.\d+)?\s*equiv\.?)\)\s*$", re.I)


def name_variants(name: str) -> list[str]:
    """Candidate spellings to try, most specific first."""
    n = " ".join(name.strip().split())
    n = _QTY.sub("", n)
    out = [n]
    stripped = _TRAIL_PAREN.sub("", n)
    if stripped != n:
        out.append(stripped)
    for prefix in ("anhydrous ", "glacial ", "aqueous ", "concentrated ", "dry ", "conc. "):
        if stripped.lower().startswith(prefix):
            out.append(stripped[len(prefix):])
    if stripped.lower().endswith(" solution"):
        out.append(stripped[: -len(" solution")])
    seen, uniq = set(), []
    for v in out:
        if v and v.lower() not in seen:
            seen.add(v.lower())
            uniq.append(v)
    return uniq


def _pick_smiles(props: dict) -> str | None:
    return props.get("SMILES") or props.get("IsomericSMILES") or props.get("CanonicalSMILES") \
        or props.get("ConnectivitySMILES")


_concurrency: asyncio.Semaphore | None = None   # PubChem also limits requests in flight


def _sem() -> asyncio.Semaphore:
    global _concurrency
    if _concurrency is None:
        _concurrency = asyncio.Semaphore(4)
    return _concurrency


async def _fetch_props(client: httpx.AsyncClient, name: str, attempts: int = 4) -> dict | None:
    # POST avoids URL-escaping problems with commas, slashes, brackets in names.
    for attempt in range(attempts):
        async with _sem():
            await _limiter.wait()
            try:
                r = await client.post(f"{PUG}/compound/name/property/{PROPS}/JSON", data={"name": name}, timeout=30)
            except httpx.TransportError:
                r = None
        if r is not None and r.status_code == 404:
            return None
        if r is not None and r.status_code == 200:
            rows = r.json().get("PropertyTable", {}).get("Properties", [])
            return rows[0] if rows else None
        if r is not None and r.status_code not in (429, 500, 502, 503, 504):
            r.raise_for_status()
        await asyncio.sleep(1.0 * 2 ** attempt)   # busy / throttled / network blip
    raise httpx.HTTPError(f"PubChem unavailable after {attempts} attempts")


async def _resolve_uncached(name: str) -> Resolution:
    tried: list[str] = []
    async with httpx.AsyncClient(headers={"User-Agent": "Orchanium/0.1 (hackathon research tool)"}) as client:
        for variant in name_variants(name):
            tried.append(variant)
            try:
                props = await _fetch_props(client, variant)
            except httpx.HTTPError as e:
                return Resolution(query=name, ok=False, tried=tried, error=f"pubchem error: {e}")
            if not props:
                continue
            smi = _pick_smiles(props)
            m = rd.parse(smi)
            if m is None:
                continue
            return Resolution(
                query=name, ok=True, cid=props.get("CID"),
                smiles=rd.Chem.MolToSmiles(m), inchikey=rd.inchikey(m),
                pubchem_inchikey=props.get("InChIKey"), iupac=props.get("IUPACName"),
                title=props.get("Title"), formula=props.get("MolecularFormula"), tried=tried,
            )
    return Resolution(query=name, ok=False, tried=tried, error="not found in PubChem")


async def resolve(name: str) -> Resolution:
    key = " ".join(name.lower().split())
    store = get_store()
    hit = store.cache_get(CACHE_NS, key)
    if hit is not None:
        return Resolution(**{**hit, "cached": True})
    # coalesce concurrent lookups of the same name
    if key in _inflight:
        return await _inflight[key]
    fut: asyncio.Future = asyncio.get_running_loop().create_future()
    _inflight[key] = fut
    try:
        res = await _resolve_uncached(name)
        if res.ok or res.error == "not found in PubChem":   # don't cache transient errors
            store.cache_set(CACHE_NS, key, res.model_dump(exclude={"cached"}))
        fut.set_result(res)
        return res
    except Exception as e:  # noqa: BLE001
        fut.set_exception(e)
        raise
    finally:
        _inflight.pop(key, None)


async def resolve_many(names: list[str]) -> dict[str, Resolution]:
    uniq = list(dict.fromkeys(n for n in names if n and n.strip()))
    results = await asyncio.gather(*(resolve(n) for n in uniq))
    return dict(zip(uniq, results))


async def lookup_inchikey(key: str) -> dict | None:
    """Cross-check a structure (e.g. from a figure read) against PubChem."""
    store = get_store()
    hit = store.cache_get(CACHE_NS + ".ik", key)
    if hit is not None:
        return hit or None
    await _limiter.wait()
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{PUG}/compound/inchikey/{key}/property/Title,IUPACName,CID/JSON", timeout=20)
    rows = r.json().get("PropertyTable", {}).get("Properties", []) if r.status_code == 200 else []
    val = rows[0] if rows else {}
    if r.status_code in (200, 404):
        store.cache_set(CACHE_NS + ".ik", key, val)
    return val or None
