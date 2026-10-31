"""The lasting knowledge graph: evidence outlives the run that found it.

Each run still reasons over its own graph, but that graph no longer starts
empty. Every clue a run gathers (web research, lab notes) is remembered with
its resolved structures and citation status; later runs recall the remembered
clues that bear on their steps through MemorySource, the same ClueSource
interface the patent index and web research use. Recalled clues go through the
normal ingest path, so blind mode, precedent scoring and the critic treat them
exactly like fresh ones. Patent records are not copied: the local index
already holds them."""
from __future__ import annotations

import asyncio
from collections import Counter

from .chem import rdkit_utils as rd
from .chem.reactions import classify
from .chem.resolver import MolRef
from .chem.similarity import precedent_score, tanimoto
from .clues import ClueSource
from .context import RunContext
from .graph import KnowledgeGraph
from .models import Clue, ResearchNeed
from .store import get_store

NOT_REMEMBERED = {"uspto"}
MIN_PRODUCT_SIM = 0.3


def _structured(g: KnowledgeGraph, clue: Clue) -> tuple[Clue, str] | None:
    """The clue with its molecules as resolved in the graph (names and SMILES),
    so recalling it needs no lookups. None if it never made it into the graph."""
    rx = g.reactions.get(g.clue_reaction.get(clue.id, ""))
    if rx is None:
        return None
    ref = lambda x: MolRef(name=g.molecules[x].name, smiles=g.smiles(x))  # noqa: E731
    stored = clue.model_copy(update={"reactants": [ref(x) for x in rx.reactants],
                                     "products": [ref(x) for x in [rx.product, *rx.byproducts]],
                                     "need_id": None, "recalled_from": None})
    return stored, g.smiles(rx.product)


def remember(g: KnowledgeGraph, run_id: str, clue_ids: list[str] | None = None) -> int:
    rows = []
    for cid in clue_ids if clue_ids is not None else list(g.clues):
        clue = g.clues[cid]
        if clue.origin in NOT_REMEMBERED or not (s := _structured(g, clue)):
            continue
        stored, product = s
        rows.append((cid, clue.origin, product, stored.model_dump_json(), g.citation_status.get(cid),
                     clue.recalled_from or run_id))
    if rows:
        get_store().remember(rows)
    return len(rows)


def stats() -> dict:
    rows = get_store().evidence()
    clues = [r["clue"] for r in rows]
    molecules = {m["smiles"] for c in clues for m in c["reactants"] + c["products"] if m.get("smiles")}
    return {"clues": len(rows), "by_origin": dict(Counter(r["origin"] for r in rows)),
            "failures": sum(1 for c in clues if c["outcome"] == "failure"),
            "molecules": len(molecules), "runs": len({r["run_id"] for r in rows})}


def _recall(need: ResearchNeed, keep: int) -> list[Clue]:
    scored = []
    for row in get_store().evidence():
        if tanimoto(row["product_smiles"], need.product_smiles) < MIN_PRODUCT_SIM:
            continue
        clue = Clue.model_validate(row["clue"])
        rs = [m.smiles for m in clue.reactants if m.smiles]
        mols = [rd.parse(x) for x in rs]
        if not rs or any(m is None for m in mols):
            continue
        s = precedent_score(rs, row["product_smiles"], classify(mols, rd.parse(row["product_smiles"])),
                            need.reactant_smiles, need.product_smiles,
                            [need.reaction_class] if need.reaction_class else [])
        if s.grade != "none":
            scored.append((s.score, row, clue))
    scored.sort(key=lambda x: -x[0])
    return [clue.model_copy(update={"need_id": need.id, "recalled_from": row["run_id"]})
            for _, row, clue in scored[:keep]]


class MemorySource(ClueSource):
    name = "memory"
    label = "Knowledge graph (earlier runs and lab notes)"

    def __init__(self, keep: int = 8):
        self.keep = keep

    async def search(self, ctx: RunContext, g: KnowledgeGraph, need: ResearchNeed):
        clues = await asyncio.to_thread(_recall, need, self.keep)
        status = {r["id"]: r["citation_status"] for r in get_store().evidence()}
        for c in clues:
            if status.get(c.id):
                g.citation_status[c.id] = status[c.id]
        by = Counter(c.origin for c in clues)
        return (f"recalled {len(clues)} remembered clue(s)",
                {"by_origin": dict(by), "method": "product similarity, then the shared precedent score"}, clues)
