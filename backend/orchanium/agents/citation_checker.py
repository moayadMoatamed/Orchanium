"""Citation checker (deterministic): fetches every cited page and verifies that
the quoted snippet and the reaction's species actually appear on it."""
from __future__ import annotations

import asyncio
import re

from rapidfuzz import fuzz

from ..context import RunContext
from ..events import ProvNode
from ..fetch import fetch_page
from ..graph import RunGraph
from ..models import Evidence

AGENT_ID = "citation_checker"


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[‐-―−]", "-", s.lower())).strip()


def quote_score(snippet: str, text: str, window: int = 1500) -> float:
    """Best partial fuzzy match of the snippet against the page, chunked so it
    stays fast on long pages."""
    s, t = _norm(snippet), _norm(text)
    if not s or not t:
        return 0.0
    if s in t:
        return 100.0
    step = max(window - len(s), 200)
    best = 0.0
    for i in range(0, max(len(t) - 1, 1), step):
        best = max(best, fuzz.partial_ratio(s, t[i:i + window + len(s)]))
        if best >= 99:
            break
    return best


def names_found(names_per_species: list[set[str]], text: str) -> tuple[float, list[str], list[str]]:
    t = _norm(text)
    found, missing = [], []
    for variants in names_per_species:
        hit = next((v for v in variants if v and _norm(v) in t), None)
        (found if hit else missing).append(hit or sorted(variants)[0])
    frac = len(found) / len(names_per_species) if names_per_species else 0.0
    return frac, found, missing


async def check_one(ctx: RunContext, g: RunGraph, ev: Evidence) -> str:
    page = await fetch_page(ev.source_url)
    rx_id = next((r.id for r in g.reactions.values() if ev.id in r.evidence), None)
    species = []
    for n in ev.reactants + ev.products[:1]:
        variants = {n}
        m = next((m for m in g.molecules.values() if n in m.names), None)
        if m:
            variants |= m.names | {m.name}
        species.append(variants)
    details = {"url": ev.source_url, "http_status": page.get("status"), "fetch_error": page.get("error"),
               "content_type": page.get("content_type"), "page_chars": len(page.get("text") or ""),
               "snippet": ev.snippet, "cached_fetch": page.get("cached", False),
               "engine": "HTTP fetch + rapidfuzz partial match (deterministic, no LLM)"}
    status_code = page.get("status")
    text = page.get("text") or ""

    if status_code is None or status_code in (404, 410):
        status, summary = "fail", f"URL does not resolve ({status_code or page.get('error', 'network error')})"
    elif status_code != 200 or len(text) < 200:
        status, summary = "warn", (f"page not machine-readable (HTTP {status_code}, paywall/bot-block?): "
                                   "could not verify")
    else:
        q = await asyncio.to_thread(quote_score, ev.snippet, text)
        frac, found, missing = names_found(species, text)
        details.update({"quote_match": round(q, 1), "names_found": found, "names_missing": missing,
                        "names_fraction": round(frac, 2)})
        product_found = bool(species) and not any(n in missing for n in species[-1])
        if q >= 85 or (q >= 65 and frac >= 0.6) or (frac == 1.0 and product_found):
            status = "pass"
            summary = f"page resolves; quote match {q:.0f}%, {len(found)}/{len(species)} species named"
        else:
            status = "warn"
            summary = f"page resolves but claim weakly supported (quote {q:.0f}%, {len(found)}/{len(species)} species)"
    g.citation_status[ev.id] = status
    ctx.prov(ProvNode(id=f"cite:{ev.id}", node_type="citation", step_id=rx_id, agent_id=AGENT_ID,
                      parent_ids=[f"ext:{ev.id}"], status=status, summary=summary, details=details))
    return status


async def run(ctx: RunContext, g: RunGraph, evidence: list[Evidence]) -> None:
    ctx.log(AGENT_ID, f"Verifying {len(evidence)} citations against their pages")
    results = await asyncio.gather(*(check_one(ctx, g, e) for e in evidence), return_exceptions=True)
    ok = sum(1 for r in results if r == "pass")
    for e, r in zip(evidence, results):
        if isinstance(r, Exception):
            g.citation_status[e.id] = "warn"
            ctx.log(AGENT_ID, f"citation check crashed for {e.source_url}: {r}", "warn")
    ctx.log(AGENT_ID, f"{ok}/{len(evidence)} citations verified on the source page")
