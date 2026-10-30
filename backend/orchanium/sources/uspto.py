"""USPTO precedent source: 1.8M patent reactions (Lowe 1976-2016, CC0), searched
by product-fingerprint similarity, then ranked with the shared precedent score.
Built by scripts/build_uspto_index.py."""
from __future__ import annotations

import asyncio
import sqlite3
from functools import lru_cache

import numpy as np
from rdkit.Chem import rdFingerprintGenerator

from ..chem import rdkit_utils as rd
from ..chem.reactions import classify
from ..chem.resolver import MolRef
from ..chem.similarity import precedent_score
from ..clues import ClueSource
from ..config import DATA
from ..context import RunContext, short_id
from ..graph import KnowledgeGraph
from ..models import Clue, Conditions, ResearchNeed, SourceRef

INDEX = DATA / "uspto"
_GEN = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=1024)


@lru_cache(maxsize=1)
def _index():
    fps = np.load(INDEX / "product_fp.npy", mmap_mode="r")
    popcount = np.bitwise_count(fps).sum(axis=1, dtype=np.int32)
    db = sqlite3.connect(INDEX / "uspto.sqlite", check_same_thread=False)
    return fps, popcount, db


def available() -> bool:
    return (INDEX / "product_fp.npy").exists() and (INDEX / "uspto.sqlite").exists()


def similar_products(smiles: str, k: int = 150, min_sim: float = 0.3) -> list[tuple[int, float]]:
    m = rd.parse(smiles)
    if m is None:
        return []
    fps, pc, _ = _index()
    q = np.packbits(_GEN.GetFingerprintAsNumPy(m).astype(bool), bitorder="little").view(np.uint64)
    inter = np.bitwise_count(fps & q).sum(axis=1, dtype=np.int32)
    sim = inter / np.maximum(pc + int(np.bitwise_count(q).sum()) - inter, 1)
    top = np.argpartition(-sim, min(k, len(sim) - 1))[:k]
    return sorted(((int(i), float(sim[i])) for i in top if sim[i] >= min_sim), key=lambda x: -x[1])


def patent_url(patent: str) -> str:
    num = patent.replace("US0", "US") if patent.startswith("US0") else patent
    return f"https://patents.google.com/patent/{num}"


def _rows(ids: list[int]) -> list[tuple]:
    _, _, db = _index()
    q = f"SELECT id, reactants, agents, product, patent, year, yield_pct FROM rxn WHERE id IN ({','.join('?' * len(ids))})"
    return db.execute(q, ids).fetchall()


def _precedents(need: ResearchNeed, keep: int) -> tuple[list[dict], int]:
    hits = similar_products(need.product_smiles)
    if not hits:
        return [], 0
    sims = dict(hits)
    scored = []
    for rid, reactants, agents, product, patent, year, yld in _rows([i for i, _ in hits[:120]]):
        rs = [s for s in reactants.split(".") if (m := rd.parse(s)) is not None and m.GetNumHeavyAtoms() > 1]
        if not rs:
            continue
        classes = classify([rd.parse(s) for s in rs], rd.parse(product))
        s = precedent_score(rs, product, classes, need.reactant_smiles, need.product_smiles,
                            [need.reaction_class] if need.reaction_class else [])
        if s.grade != "none":
            scored.append({"id": rid, "reactants": rs, "agents": agents, "product": product, "patent": patent,
                           "year": year, "yield": yld, "score": s, "product_sim": sims[rid]})
    scored.sort(key=lambda x: -x["score"].score)
    # one record per distinct product keeps the evidence diverse
    out, seen = [], set()
    for x in scored:
        if x["product"] not in seen:
            seen.add(x["product"])
            out.append(x)
        if len(out) >= keep:
            break
    return out, len(hits)


class USPTOSource(ClueSource):
    name = "uspto"
    label = "USPTO reaction index"

    def __init__(self, keep: int = 5):
        self.keep = keep

    async def search(self, ctx: RunContext, g: KnowledgeGraph, need: ResearchNeed):
        if not available():
            return "index not built", {}, []
        found, n_candidates = await asyncio.to_thread(_precedents, need, self.keep)
        clues = []
        for x in found:
            agents = [MolRef(smiles=a) for a in (x["agents"] or "").split(".") if a][:6]
            clues.append(Clue(
                id=short_id("uspto", x["id"]), origin=self.name, need_id=need.id,
                reactants=[MolRef(smiles=s) for s in x["reactants"]], products=[MolRef(smiles=x["product"])],
                reagents=agents, yield_pct=x["yield"], conditions=Conditions(),
                source=SourceRef(kind="database", title=f"US patent {x['patent']} ({x['year']})",
                                 url=patent_url(x["patent"]), citation=f"USPTO reaction record #{x['id']}")))
        summary = f"products similar to {need.product_name} ({n_candidates} candidates ≥30% similar)"
        return summary, {"candidates": n_candidates, "kept": len(clues),
                         "method": "Morgan fingerprint Tanimoto over 1.8M USPTO products, then precedent score"}, clues
