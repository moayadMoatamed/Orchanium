"""Citation checker (deterministic): verifies what each clue's source makes
verifiable. A quoted snippet is fuzzy-matched against the fetched page, along
with the species names. A structured database record (USPTO) is a provenance
record, not a quote, so it is marked `skip` with its link."""
from __future__ import annotations

import asyncio
import re

from rapidfuzz import fuzz

from ..context import RunContext
from ..events import ProvNode
from ..fetch import fetch_page
from ..graph import KnowledgeGraph
from ..models import Clue

AGENT_ID = "citation_checker"


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[‐-―−]", "-", s.lower())).strip()


def quote_score(snippet: str, text: str, window: int = 1500) -> float:
    s, t = _norm(snippet), _norm(text)
    if not s or not t:
        return 0.0
    if s in t:
        return 100.0
    best, step = 0.0, max(window - len(s), 200)
    for i in range(0, max(len(t) - 1, 1), step):
        best = max(best, fuzz.partial_ratio(s, t[i:i + window + len(s)]))
        if best >= 99:
            break
    return best


async def check_one(ctx: RunContext, g: KnowledgeGraph, clue: Clue) -> str:
    details = {"url": clue.source.url, "kind": clue.source.kind,
               "engine": "HTTP fetch + rapidfuzz partial match (deterministic, no LLM)"}
    if clue.source.kind == "database" or not clue.source.snippet:
        status, summary = "skip", f"structured record: {clue.source.citation or clue.source.title} (link provided)"
    else:
        page = await fetch_page(clue.source.url)
        text, code = page.get("text") or "", page.get("status")
        details.update({"http_status": code, "page_chars": len(text), "fetch_error": page.get("error")})
        if code is None or code in (404, 410):
            status, summary = "fail", f"URL does not resolve ({code or page.get('error', 'network error')})"
        elif code != 200 or len(text) < 200:
            status, summary = "warn", f"page not machine-readable (HTTP {code}): could not verify"
        else:
            q = await asyncio.to_thread(quote_score, clue.source.snippet, text)
            names = [r.name for r in clue.reactants + clue.products[:1] if r.name]
            found = [n for n in names if _norm(n) in _norm(text)]
            details.update({"quote_match": round(q, 1), "names_found": found, "names_checked": names})
            ok = q >= 85 or (q >= 65 and names and len(found) / len(names) >= 0.6)
            status = "pass" if ok else "warn"
            summary = (f"quote found on page ({q:.0f}% match), {len(found)}/{len(names)} species named" if ok
                       else f"claim weakly supported on page (quote {q:.0f}%, {len(found)}/{len(names)} species)")
    g.citation_status[clue.id] = status
    ctx.prov(ProvNode(id=f"cite:{clue.id}", node_type="citation", agent_id=AGENT_ID, step_id=clue.need_id,
                      parent_ids=[f"clue:{clue.id}"], status=status, summary=summary, details=details))
    return status


async def run(ctx: RunContext, g: KnowledgeGraph, clues: list[Clue]) -> None:
    todo = [c for c in clues if c.id in g.clues and c.id not in g.citation_status]
    if not todo:
        return
    results = await asyncio.gather(*(check_one(ctx, g, c) for c in todo), return_exceptions=True)
    for c, r in zip(todo, results):
        if isinstance(r, Exception):
            g.citation_status[c.id] = "warn"
    checked = [r for r in results if r in ("pass", "warn", "fail")]
    if checked:
        ctx.log(AGENT_ID, f"{checked.count('pass')}/{len(checked)} quoted citations verified on the source page")
