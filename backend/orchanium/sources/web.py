"""Web clue source: Muse Spark + built-in web_search, asked for published
reactions of the same kind on similar substrates (including failures)."""
from __future__ import annotations

from urllib.parse import urlsplit

from ..chem.resolver import MolRef
from ..clues import ClueSource
from ..context import RunContext, prompt, short_id
from ..graph import KnowledgeGraph
from ..meta.client import normalize_url
from ..models import Clue, ClueFindings, Conditions, ResearchNeed, SourceRef

_DOMAIN_KIND = [
    (("patents.google.", "patentimages.", "freepatentsonline.", "espacenet.", "patentscope.", "justia."), "patent"),
    (("orgsyn.org",), "procedure"),
    (("pubs.acs.org", "rsc.org", "sciencedirect.", "wiley.com", "springer.", "nature.com", "mdpi.com",
      "ncbi.nlm.nih.gov", "europepmc.", "doi.org", "beilstein-journals.", "thieme-connect.", "chemrxiv."), "paper"),
    (("wikipedia.org",), "encyclopedia"),
    (("libretexts.org", ".edu", ".ac.uk"), "textbook"),
]


def source_kind(url: str, claimed: str) -> str:
    host = urlsplit(url).netloc.lower()
    return next((kind for needles, kind in _DOMAIN_KIND if any(n in host for n in needles)), claimed)


class WebSource(ClueSource):
    name = "web"
    label = "Web research (Muse Spark + web_search)"

    async def search(self, ctx: RunContext, g: KnowledgeGraph, need: ResearchNeed):
        resp = await ctx.client.respond(
            prompt("clue_researcher", reaction_class=need.reaction_class or "unknown transformation",
                   reactants=", ".join(need.reactant_names), product=need.product_name,
                   analogs=", ".join(need.analog_names) or "none known yet",
                   focus=f"- **Specific question to investigate:** {need.focus}" if need.focus else ""),
            schema=ClueFindings, web_search=True, search_context="medium", effort="medium")
        found: ClueFindings = resp.parsed
        clues = []
        for c in found.clues:
            if not c.reactants or not c.products:
                continue
            url = (normalize_url(c.source_url) or "").split("#")[0]
            clues.append(Clue(
                id=short_id("web", url, c.reactants, c.products), origin=self.name, need_id=need.id,
                reactants=[MolRef(name=n) for n in c.reactants], products=[MolRef(name=n) for n in c.products],
                reagents=[MolRef(name=n) for n in c.reagents],
                conditions=Conditions(temperature_c=c.temperature_c, time=c.time, solvent=c.solvent,
                                      catalyst=c.catalyst, text=c.conditions_text),
                yield_pct=c.yield_pct, outcome=c.outcome,
                source=SourceRef(kind=source_kind(url, c.source_type), title=c.source_title, url=url,
                                 snippet=c.snippet)))
        queries = [s.query for s in resp.searches if s.query]
        return (f"{len(queries)} web searches", {"queries": queries, "notes": found.notes, "usd": resp.usd,
                                                 "pages_seen": sum(len(s.results) for s in resp.searches)}, clues)
