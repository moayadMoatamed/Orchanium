"""The one path every clue takes into the graph, whatever its source:
  ClueSource.search(need) -> [Clue] -> resolve molecules -> blind filter
  -> observed reaction (deduped) -> critic -> provenance nodes
and the one place precedent links are scored and surfaced."""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from urllib.parse import urlsplit

from .chem import purchasable
from .chem import rdkit_utils as rd
from .chem.critic import Species, critique
from .chem.resolver import MolRef, Resolved, resolve_many
from .chem.similarity import tanimoto
from .context import RunContext, short_id
from .events import ProvNode
from .graph import KnowledgeGraph, Molecule, Reaction
from .models import Clue, ResearchNeed


class ClueSource(ABC):
    name: str
    label: str

    @abstractmethod
    async def search(self, ctx: RunContext, g: KnowledgeGraph, need: ResearchNeed) -> tuple[str, dict, list[Clue]]:
        """Returns (one-line description of the search, details, clues)."""


def need_for(g: KnowledgeGraph, hyp_id: str) -> ResearchNeed:
    h = g.reactions[hyp_id]
    p = g.molecules[h.product]
    return ResearchNeed(
        id=h.id, product_smiles=p.smiles, product_name=p.name,
        reactant_smiles=[g.smiles(x) for x in h.reactants],
        reactant_names=[g.molecules[x].name for x in h.reactants],
        reaction_class=h.classes[0] if h.classes else None,
        analog_names=[g.molecules[m].name for m, _ in g.similar_molecules(p.id) if g.molecules[m].known][:5])


async def gather(ctx: RunContext, g: KnowledgeGraph, source: ClueSource, need: ResearchNeed,
                 agent_id: str) -> list[Clue]:
    qid = short_id("q", source.name, need.id, agent_id)
    ctx.prov(ProvNode(id=qid, node_type="query", status="running", agent_id=agent_id, step_id=need.id,
                      parent_ids=[f"hyp:{need.id}"], summary=f"{source.label}: searching…",
                      details={"source": source.name, "need": need.model_dump()}))
    summary, details, clues = await source.search(ctx, g, need)
    ctx.prov(ProvNode(id=qid, node_type="query", status="pass" if clues else "warn", agent_id=agent_id,
                      summary=f"{source.label}: {summary} → {len(clues)} clue(s)", details=details))
    await ingest(ctx, g, clues, qid, agent_id)
    return clues


_PATENT = re.compile(r"(?<![A-Za-z])([A-Z]{2})0*(\d{5,})", re.I)

# ---------------------------------------------------------------- evidence policy
# Every source is classified once; supplier product pages are never evidence
# (a listing says a compound is sold, not that a reaction works).
_DOMAIN_KIND = [
    (("patents.google.", "patentimages.", "freepatentsonline.", "espacenet.", "patentscope.", "justia.",
      "uspto.gov", "lens.org"), "patent"),
    (("orgsyn.org",), "procedure"),
    (("pubs.acs.org", "rsc.org", "sciencedirect.", "wiley.com", "springer.", "nature.com", "mdpi.com",
      "ncbi.nlm.nih.gov", "europepmc.", "doi.org", "beilstein-journals.", "thieme-connect.", "chemrxiv.",
      "tandfonline.", "frontiersin.", "acs.org", "science.org"), "paper"),
    (("wikipedia.org",), "encyclopedia"),
    (("libretexts.org", ".edu", ".ac.uk"), "textbook"),
    (("benchchem.", "evitachem.", "smolecule.", "vulcanchem.", "chemicalbook.", "molport.", "sigmaaldrich.",
      "fishersci.", "tcichemicals.", "thermofisher.", "ambeed.", "bldpharm.", "chemscene.", "medchemexpress.",
      "selleckchem.", "combi-blocks.", "chemsrc.", "guidechem.", "lookchem.", "echemi.", "chemblink.",
      "aksci.", "apolloscientific.", "fluorochem.", "biosynth.", "cymitquimica.", "angenechemical."), "vendor"),
]
_SHOP_SIGNALS = re.compile(r"/(product|products|buy|catalog|shop|item)[/-]|\bbuy\b|price|in stock|add to cart", re.I)
NOT_EVIDENCE = {"vendor"}


def classify_source(url: str | None, title: str | None, claimed: str) -> str:
    host = urlsplit(url or "").netloc.lower()
    kind = next((k for needles, k in _DOMAIN_KIND if any(n in host for n in needles)), None)
    if kind:
        return kind
    if _SHOP_SIGNALS.search(urlsplit(url or "").path) or _SHOP_SIGNALS.search(title or ""):
        return "vendor"
    return claimed


def patent_id(text: str | None, default_country: str = "US") -> str | None:
    """Patent number in a URL/string; a bare number on a patent page is assumed US."""
    m = _PATENT.search(text or "")
    if m:
        return f"{m.group(1).upper()}{m.group(2)}"
    bare = re.search(r"/(\d{7,11})(?:[/?#]|$)", text or "")
    return f"{default_country}{bare.group(1)}" if bare else None


def _source_keys(text: str) -> set[str]:
    """Comparable identifiers in a source string: patent cores (country + digits,
    so US08420823B2 == US8420823B2) plus the lower-cased text itself."""
    return {f"{c.upper()}{d}" for c, d in _PATENT.findall(text or "")} | {(text or "").lower()}


def _hidden_hit(ctx: RunContext, resolved: list[Resolved], clue: Clue,
                products: list[Resolved] | None = None) -> str | None:
    """Why a clue must be hidden in blind mode, or None.
    Blind mode hides clues that contain the target or a hidden molecule, name
    the target (if it has a real name), come from an explicitly hidden source
    (e.g. the held-out patent), or, in strict mode, MAKE a product more similar
    than `similarity_cap` to the target or a hidden molecule (ingredients are
    not judged: using the same buyable starting material is not leakage)."""
    if not ctx.blind or not ctx.target:
        return None
    protected = [ctx.target.smiles] + ctx.hidden_molecules
    blocks = {rd.inchikey(s).split("-")[0] for s in protected}
    for r in resolved:
        if r.ok and r.inchikey.split("-")[0] in blocks:
            return "contains the target" if r.inchikey == ctx.target.inchikey else f"contains hidden molecule {r.name}"
    if ctx.similarity_cap is not None:
        for r in (products if products is not None else resolved):
            if r.ok and (sim := max(tanimoto(r.smiles, s) for s in protected)) > ctx.similarity_cap:
                return f"makes {r.name}, {sim:.0%} similar to a hidden molecule (strict mode)"
    text = " ".join(filter(None, [clue.source.snippet, clue.source.title, clue.source.url, clue.source.citation]))
    if ctx.target.known and ctx.target.name.lower() in text.lower():
        return "names the target"
    keys = _source_keys(text)
    for h in ctx.hidden:
        hk = _source_keys(h)
        if hk & keys or any(h.lower() in k for k in keys):
            return f"from hidden source {h}"
    return None


async def _add_clue_molecule(ctx: RunContext, g: KnowledgeGraph, r: Resolved) -> Molecule:
    m = g.molecules.get(r.inchikey)
    if m is None:
        p = await purchasable.assess(r.inchikey, r.smiles, r.cid,
                                     (ctx.target.description or {}).get("heavy_atoms") if ctx.target else None)
        m = Molecule(id=r.inchikey, smiles=r.smiles, name=r.name or r.query, known=r.known, cid=r.cid,
                     purchasable=p.purchasable and r.inchikey != g.target_id,
                     purchasable_basis=p.basis, purchasable_reason=p.reason)
        g.molecules[m.id] = m
    m.roles.add("clue")
    ctx.bus.publish("graph.molecule", m.to_event())
    return m


def _doc_key(clue: Clue) -> str:
    """One key per source document, so blind mode can drop a whole paper or
    patent rather than one record out of it."""
    text = " ".join(filter(None, [clue.source.citation, clue.source.url]))
    if pats := _PATENT.findall(text):
        return f"{pats[0][0].upper()}{pats[0][1]}"
    if clue.source.url:
        s = urlsplit(clue.source.url)
        return f"{s.netloc}{s.path}"
    return clue.source.citation or clue.source.title or clue.id


async def ingest(ctx: RunContext, g: KnowledgeGraph, clues: list[Clue], query_id: str, agent_id: str) -> int:
    added = 0
    # first pass: resolve, and note every document that gives the answer away.
    # A document that knows the target is dropped whole, because its other
    # records would still hand over real conditions, amounts and solvents.
    kept: list[tuple[Clue, list]] = []
    for clue in clues:
        refs = clue.reactants + clue.products
        res = await resolve_many(refs + clue.reagents)
        main_res, reagent_res = res[:len(refs)], res[len(refs):]
        # reagents keep a readable name (patent records list them as bare SMILES)
        clue.reagents = [MolRef(name=r.name or ref.label, smiles=r.smiles) if r.ok else ref
                         for ref, r in zip(clue.reagents, reagent_res)]
        if clue.source.kind in NOT_EVIDENCE:
            ctx.log(agent_id, f"not evidence: supplier product page ({clue.source.title[:60]})")
            continue
        if why := _hidden_hit(ctx, main_res, clue, products=main_res[len(clue.reactants):]):
            ctx.blocked_sources.add(_doc_key(clue))
            ctx.log(agent_id, f"blind mode: dropped a clue that {why} ({clue.source.title[:60]})")
            continue
        kept.append((clue, main_res))

    for clue, main_res in kept:
        refs = clue.reactants + clue.products
        if (key := _doc_key(clue)) in ctx.blocked_sources:
            ctx.log(agent_id, f"blind mode: dropped a clue from {key}, a source that knows the target "
                              f"({clue.source.title[:60]})")
            continue
        url = clue.source.url or clue.source.citation or clue.id
        sid = short_id("src", url)
        # step_id ties every node to the hypothesis it was gathered for, so the
        # Verification chain for a step can be built from the event stream alone
        step = clue.need_id
        ctx.prov(ProvNode(id=sid, node_type="source", agent_id=agent_id, parent_ids=[query_id], status="pass",
                          step_id=step,
                          summary=f"{clue.source.title[:90]}" + (f" ({urlsplit(url).netloc})" if clue.source.url else ""),
                          details=clue.source.model_dump()))
        cid = f"clue:{clue.id}"
        names = [r.label for r in clue.reactants]
        ctx.prov(ProvNode(id=cid, node_type="extraction", agent_id=agent_id, parent_ids=[sid], step_id=step,
                          status="pass" if clue.outcome == "success" else "warn",
                          summary=f"{' + '.join(names)} → {clue.products[0].label}"
                                  + (" (reported FAILURE)" if clue.outcome == "failure" else ""),
                          details=clue.model_dump()))
        for ref, r in zip(refs, main_res):
            # a resolution is a fact about a molecule, not about one step, so it
            # carries no step_id; the chain looks it up by molecule id
            ctx.prov(ProvNode(id=f"res:{r.inchikey or 'x:' + ref.label}", node_type="resolution",
                              agent_id="resolver", parent_ids=[cid],
                              status="pass" if r.ok else "fail",
                              summary=(f"{ref.label} → {r.name} ({r.method}{', CID ' + str(r.cid) if r.cid else ''})"
                                       if r.ok else f"“{ref.label}” could not be resolved"),
                              details=r.model_dump()))
        if not all(r.ok for r in main_res):
            continue
        reactants = list(dict.fromkeys([(await _add_clue_molecule(ctx, g, r)).id for r in main_res[:len(clue.reactants)]]))
        prods = [await _add_clue_molecule(ctx, g, r) for r in main_res[len(clue.reactants):]]
        main = max(prods, key=lambda m: rd.parse(m.smiles).GetNumHeavyAtoms())
        rx_id = short_id("obs", sorted(reactants), main.id)
        rx = g.reactions.get(rx_id)
        if rx is None:
            reagent_species = [Species(name=r.name, smiles=r.smiles) for r in reagent_res if r.ok]
            critic = critique([Species(name=g.molecules[x].name, smiles=g.smiles(x), inchikey=x) for x in reactants],
                              Species(name=main.name, smiles=main.smiles, inchikey=main.id), reagent_species)
            rx = Reaction(id=rx_id, kind="observed", reactants=reactants, product=main.id,
                          byproducts=[p.id for p in prods if p.id != main.id],
                          classes=critic.reaction_classes, origin=clue.origin, critic=critic)
            g.reactions[rx_id] = rx
        if clue.id not in rx.clue_ids:
            rx.clue_ids.append(clue.id)
        g.clues[clue.id] = clue
        g.clue_reaction[clue.id] = rx_id
        ctx.bus.publish("graph.reaction", rx.to_event())
        added += 1
    return added


def link_and_emit(ctx: RunContext, g: KnowledgeGraph, hyp_ids: list[str] | None = None, top: int = 3) -> None:
    """Score precedents for hypotheses and surface the best ones as chain nodes."""
    g.link_precedents(hyp_ids)
    for h in ([g.reactions[i] for i in hyp_ids] if hyp_ids else g.hypotheses()):
        for p in g.precedents.get(h.id, [])[:top]:
            o = g.reactions[p.observed_id]
            s = p.score
            ctx.prov(ProvNode(
                id=f"prec:{h.id}:{o.id}", node_type="precedent", step_id=h.id, agent_id="graph",
                parent_ids=[f"clue:{c}" for c in o.clue_ids],
                status="fail" if p.outcome == "failure" else "pass" if s.grade in ("direct", "analog") else "warn",
                summary=f"{s.grade} precedent {s.score:.2f}: product {s.product_similarity:.0%} similar, "
                        f"transformation {s.transformation_similarity:.0%} similar"
                        + (", same class" if s.class_match else "") + (" — REPORTED FAILURE" if p.outcome == "failure" else ""),
                details={**s.model_dump(), "observed_reaction": o.id, "hypothesis": h.id, "outcome": p.outcome,
                         "method": "Morgan/difference-fingerprint similarity (RDKit, deterministic)"}))
