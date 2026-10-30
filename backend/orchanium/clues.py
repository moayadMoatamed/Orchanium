"""The one path every clue takes into the graph, whatever its source:
  ClueSource.search(need) -> [Clue] -> resolve molecules -> blind filter
  -> observed reaction (deduped) -> critic -> provenance nodes
and the one place precedent links are scored and surfaced."""
from __future__ import annotations

from abc import ABC, abstractmethod
from urllib.parse import urlsplit

from .chem import purchasable
from .chem import rdkit_utils as rd
from .chem.critic import Species, critique
from .chem.resolver import Resolved, resolve_many
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


def _blind_hit(ctx: RunContext, resolved: list[Resolved], clue: Clue) -> bool:
    """Blind mode hides every clue that contains or names the target."""
    if not ctx.blind or not ctx.target:
        return False
    block = ctx.target.inchikey.split("-")[0]
    if any(r.ok and r.inchikey.split("-")[0] == block for r in resolved):
        return True
    text = " ".join(filter(None, [clue.source.snippet, clue.source.title])).lower()
    return ctx.target.name.lower() in text


async def _add_clue_molecule(ctx: RunContext, g: KnowledgeGraph, r: Resolved) -> Molecule:
    m = g.molecules.get(r.inchikey)
    if m is None:
        p = await purchasable.assess(r.inchikey, r.smiles, r.cid)
        m = Molecule(id=r.inchikey, smiles=r.smiles, name=r.name or r.query, known=r.known, cid=r.cid,
                     purchasable=p.purchasable and r.inchikey != g.target_id,
                     purchasable_basis=p.basis, purchasable_reason=p.reason)
        g.molecules[m.id] = m
    m.roles.add("clue")
    ctx.bus.publish("graph.molecule", m.to_event())
    return m


async def ingest(ctx: RunContext, g: KnowledgeGraph, clues: list[Clue], query_id: str, agent_id: str) -> int:
    added = 0
    for clue in clues:
        refs = clue.reactants + clue.products
        res = await resolve_many(refs + clue.reagents)
        main_res, reagent_res = res[:len(refs)], res[len(refs):]
        if _blind_hit(ctx, main_res, clue):
            ctx.log(agent_id, f"blind mode: dropped a clue mentioning the target ({clue.source.title[:60]})")
            continue
        url = clue.source.url or clue.source.citation or clue.id
        sid = short_id("src", url)
        ctx.prov(ProvNode(id=sid, node_type="source", agent_id=agent_id, parent_ids=[query_id], status="pass",
                          summary=f"{clue.source.title[:90]}" + (f" ({urlsplit(url).netloc})" if clue.source.url else ""),
                          details=clue.source.model_dump()))
        cid = f"clue:{clue.id}"
        names = [r.label for r in clue.reactants]
        ctx.prov(ProvNode(id=cid, node_type="extraction", agent_id=agent_id, parent_ids=[sid],
                          status="pass" if clue.outcome == "success" else "warn",
                          summary=f"{' + '.join(names)} → {clue.products[0].label}"
                                  + (" (reported FAILURE)" if clue.outcome == "failure" else ""),
                          details=clue.model_dump()))
        for ref, r in zip(refs, main_res):
            ctx.prov(ProvNode(id=f"res:{r.inchikey or 'x:' + ref.label}", node_type="resolution",
                              agent_id="resolver", parent_ids=[cid], status="pass" if r.ok else "fail",
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
