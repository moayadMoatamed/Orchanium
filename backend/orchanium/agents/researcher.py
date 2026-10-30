"""Researcher: Muse Spark + built-in web_search, one research angle each.
Emits query -> source -> extraction provenance nodes for every evidence record."""
from __future__ import annotations

from urllib.parse import urlsplit

from ..context import RunContext, prompt, short_id
from ..events import ProvNode
from ..meta.client import normalize_url
from ..models import Evidence, ResearchAngle, ResearchFindings

_DOMAIN_TYPES = [
    (("patents.google.", "patentimages.", "freepatentsonline.", "espacenet.", "patentscope.", "wipo.int",
      "uspto.gov", "lens.org"), "patent"),
    (("orgsyn.org",), "procedure"),
    (("pubs.acs.org", "rsc.org", "sciencedirect.", "wiley.com", "springer.", "nature.com", "mdpi.com",
      "ncbi.nlm.nih.gov", "europepmc.", "doi.org", "beilstein-journals.", "thieme-connect.", "tandfonline.",
      "chemrxiv.", "researchgate.", "frontiersin.", "acs.org", "science.org", "cell.com"), "paper"),
    (("wikipedia.org", "britannica.com"), "encyclopedia"),
    (("libretexts.org", ".edu", ".ac.uk"), "textbook"),
]


def classify_source(url: str, claimed: str) -> str:
    host = urlsplit(url).netloc.lower() if url else ""
    for needles, kind in _DOMAIN_TYPES:
        if any(n in host for n in needles):
            return kind
    return claimed


def _canon(url: str | None) -> str:
    u = normalize_url(url or "") or ""
    return u.split("#")[0].rstrip("/")


async def run(ctx: RunContext, agent_id: str, angle: ResearchAngle, extra: str = "",
              parent_query_id: str | None = None) -> tuple[list[Evidence], list[str]]:
    t = ctx.target
    qid = f"q:{agent_id}"
    ctx.prov(ProvNode(id=qid, node_type="query", status="running", agent_id=agent_id,
                      parent_ids=[parent_query_id] if parent_query_id else [],
                      summary=f"{angle.title}: “{angle.query_hint}”",
                      details={"angle": angle.model_dump(), "researcher": agent_id}))
    ctx.log(agent_id, f"Searching: {angle.query_hint}")

    resp = await ctx.client.respond(
        prompt("researcher", target_name=t.name, target_smiles=t.smiles, angle_title=angle.title,
               angle_focus=angle.focus, query_hint=angle.query_hint, extra=extra),
        schema=ResearchFindings, web_search=True, search_context="medium", effort="medium",
    )
    findings: ResearchFindings = resp.parsed
    queries = [s.query for s in resp.searches if s.query]
    results = {_canon(r["url"]): r for s in resp.searches for r in s.results if r.get("url")}
    cited = {_canon(a["url"]): a for a in resp.annotations if a.get("url")}
    for q in queries:
        ctx.log(agent_id, f"web_search: {q}")
    ctx.prov(ProvNode(id=qid, node_type="query", status="pass", agent_id=agent_id,
                      summary=f"{angle.title}: {len(queries)} searches, {len(results)} pages seen",
                      details={"queries": queries, "pages_seen": len(results), "cited": len(cited),
                               "usd": resp.usd, "latency_s": resp.latency_s, "cached": resp.cached,
                               "notes": findings.notes}))

    evidence: list[Evidence] = []
    for step in findings.steps:
        if not step.reactants or not step.products:
            continue
        url = _canon(step.source_url)
        in_results = url in results or url in cited
        kind = classify_source(url, step.source_type)
        sid = short_id("src", url)
        host = urlsplit(url).netloc
        ctx.prov(ProvNode(
            id=sid, node_type="source", agent_id=agent_id, parent_ids=[qid],
            status="pass" if in_results else "warn",
            summary=f"{step.source_title[:90]} ({host})",
            details={"url": url, "title": step.source_title, "source_type": kind, "domain": host,
                     "in_search_results": in_results,
                     "check": "URL appeared in this agent's web_search results" if in_results
                     else "URL not found among web_search results — flagged for citation check"},
        ))
        eid = short_id("ev", agent_id, url, step.reactants, step.products)
        ev = Evidence(**step.model_dump(), id=eid, agent_id=agent_id, angle=angle.title,
                      query_node_id=qid, source_node_id=sid, url_in_search_results=in_results)
        ev.source_url, ev.source_type = url, kind
        evidence.append(ev)
        ctx.prov(ProvNode(
            id=f"ext:{eid}", node_type="extraction", status="pass", agent_id=agent_id, parent_ids=[sid],
            summary=f"{' + '.join(step.reactants)} → {step.products[0]}",
            details={"reactants": step.reactants, "products": step.products, "reagents": step.reagents,
                     "conditions": step.conditions, "yield_pct": step.yield_pct, "snippet": step.snippet,
                     "route_name": step.route_name, "step_number": step.step_number,
                     "figure_image_urls": step.figure_image_urls, "evidence_id": eid},
        ))
    ctx.log(agent_id, f"Extracted {len(evidence)} reaction steps from {len({e.source_url for e in evidence})} sources")
    return evidence, findings.intermediates_to_research
