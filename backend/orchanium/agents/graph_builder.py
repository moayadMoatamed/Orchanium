"""Graph builder: normalises every name through PubChem, dedupes molecules by
InChIKey and reactions by (reactants, product), and merges evidence."""
from __future__ import annotations

from ..chem import pubchem, purchasable
from ..chem import rdkit_utils as rd
from ..context import RunContext, short_id
from ..events import ProvNode
from ..graph import Molecule, Reaction, RunGraph
from ..models import Evidence

AGENT_ID = "graph_builder"


def _norm(name: str) -> str:
    return " ".join(name.lower().split())


def res_node_id(mol_id: str) -> str:
    return f"res:{mol_id}"


def _upsert_molecule(ctx: RunContext, g: RunGraph, name: str, res: pubchem.Resolution) -> Molecule:
    mol_id = res.inchikey if res.ok else f"unresolved:{_norm(name)}"
    m = g.molecules.get(mol_id)
    if m is None:
        m = Molecule(id=mol_id, name=res.title or name if res.ok else name, smiles=res.smiles, cid=res.cid,
                     is_target=bool(ctx.target and mol_id == ctx.target.inchikey))
        if m.is_target:
            m.name = ctx.target.name
        if res.ok:
            p = purchasable.check(res.inchikey, res.smiles)
            m.purchasable, m.purchasable_basis, m.purchasable_reason = p.purchasable, p.basis, p.reason
            if m.is_target:
                m.purchasable = False      # never "buy" the target
        g.molecules[mol_id] = m
    m.names.add(name)
    ctx.bus.publish("graph.molecule", m.to_event())
    return m


async def ingest(ctx: RunContext, g: RunGraph, evidence: list[Evidence]) -> list[str]:
    """Adds evidence to the graph. Returns ids of reactions that are new."""
    names = [n for e in evidence for n in e.reactants + e.products + e.reagents]
    resolved = await pubchem.resolve_many(names)
    ctx.log(AGENT_ID, f"Resolved {sum(r.ok for r in resolved.values())}/{len(resolved)} names via PubChem")
    new_rx: list[str] = []

    for ev in evidence:
        g.evidence[ev.id] = ev
        ext_id = f"ext:{ev.id}"
        species: dict[str, Molecule] = {}
        for name in ev.reactants + ev.products:
            res = resolved[name] if name in resolved else await pubchem.resolve(name)
            m = _upsert_molecule(ctx, g, name, res)
            species[name] = m
            ctx.prov(ProvNode(
                id=res_node_id(m.id), node_type="resolution", agent_id=AGENT_ID, parent_ids=[ext_id],
                status="pass" if res.ok else "fail",
                summary=(f"“{name}” → {m.name} (CID {res.cid})" if res.ok
                         else f"“{name}” could not be resolved in PubChem"),
                details={"name": name, "smiles": res.smiles, "inchikey": res.inchikey, "cid": res.cid,
                         "iupac": res.iupac, "formula": res.formula, "tried": res.tried, "error": res.error,
                         "purchasable": m.purchasable, "purchasable_basis": m.purchasable_basis,
                         "purchasable_reason": m.purchasable_reason,
                         "method": "PubChem PUG REST name lookup → RDKit canonical SMILES / InChIKey"},
            ))
        reactants = list(dict.fromkeys(species[n].id for n in ev.reactants))
        prods = [species[n] for n in ev.products]
        resolved_prods = [p for p in prods if p.resolved]
        # main product: the target if present, else the largest resolved product, else the first listed
        main = next((p for p in prods if p.is_target), None) or (
            max(resolved_prods, key=lambda p: rd.parse(p.smiles).GetNumHeavyAtoms()) if resolved_prods else prods[0])
        byproducts = [p.id for p in prods if p.id != main.id]
        rx_id = short_id("rx", sorted(reactants), main.id)
        rx = g.reactions.get(rx_id)
        if rx is None:
            rx = Reaction(id=rx_id, reactants=reactants, product=main.id, byproducts=byproducts)
            g.reactions[rx_id] = rx
            new_rx.append(rx_id)
        for r in ev.reagents:
            if r not in rx.reagents:
                rx.reagents.append(r)
                if (rr := resolved.get(r)) and rr.ok:
                    rx.reagent_smiles[r] = rr.smiles
        if ev.id not in rx.evidence:
            rx.evidence.append(ev.id)
        ctx.prov(ProvNode(id=ext_id, node_type="extraction", step_id=rx_id, status="pass",
                          summary=ctx.prov_nodes[ext_id].summary if ext_id in ctx.prov_nodes else rx_id,
                          details={"reaction_id": rx_id}))
        ctx.bus.publish("graph.reaction", rx.to_event())
    ctx.log(AGENT_ID, f"Graph: {len(g.molecules)} molecules, {len(g.reactions)} reactions "
                      f"({len(new_rx)} new)")
    return new_rx
