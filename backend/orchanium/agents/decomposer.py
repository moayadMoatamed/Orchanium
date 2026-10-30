"""Decomposer: cuts the target into precursors with the reaction-class registry
(retro direction), recursively, down to purchasable building blocks. Every cut
becomes a hypothesis reaction. All structures come from RDKit templates."""
from __future__ import annotations

import heapq

from ..chem import purchasable
from ..chem import rdkit_utils as rd
from ..chem.critic import Species, critique
from ..chem.reactions import Cut, disconnect, typical_reagents
from ..chem.resolver import from_smiles
from ..context import RunContext, short_id
from ..events import ProvNode
from ..graph import KnowledgeGraph, Molecule, Reaction

AGENT_ID = "decomposer"


async def add_molecule(ctx: RunContext, g: KnowledgeGraph, smiles: str, role: str,
                       name: str | None = None) -> Molecule:
    res = await from_smiles(smiles, query=name)
    m = g.molecules.get(res.inchikey)
    if m is None:
        p = await purchasable.assess(res.inchikey, res.smiles, res.cid)
        m = Molecule(id=res.inchikey, smiles=res.smiles, name=res.name, known=res.known, cid=res.cid,
                     purchasable=p.purchasable and role != "target", purchasable_basis=p.basis,
                     purchasable_reason=p.reason)
        g.molecules[m.id] = m
    m.roles.add(role)
    ctx.bus.publish("graph.molecule", m.to_event())
    return m


def _rank(cut: Cut, product_atoms: int) -> float:
    """Prefer cuts into purchasable pieces and into balanced halves."""
    mols = [rd.parse(s) for s in cut.precursors]
    sizes = [m.GetNumHeavyAtoms() for m in mols]
    buyable = sum(purchasable.check(rd.inchikey(m), s).purchasable for m, s in zip(mols, cut.precursors))
    balance = min(sizes) / max(sizes) if len(sizes) > 1 else 0.3
    simplification = 1 - max(sizes) / max(product_atoms, 1)
    return 2.0 * buyable / len(sizes) + balance + simplification


def add_hypothesis(ctx: RunContext, g: KnowledgeGraph, product: Molecule, reactants: list[Molecule],
                   classes: list[str], origin: str, depth: int, parent_prov: str | None) -> Reaction:
    rx_id = short_id("hyp", sorted(m.id for m in reactants), product.id)
    if rx_id in g.reactions:
        return g.reactions[rx_id]
    critic = critique([Species(name=m.name, smiles=m.smiles, inchikey=m.id) for m in reactants],
                      Species(name=product.name, smiles=product.smiles, inchikey=product.id),
                      [Species(name=r, smiles=r) for r in typical_reagents(classes)])
    h = Reaction(id=rx_id, kind="hypothesis", reactants=[m.id for m in reactants], product=product.id,
                 classes=list(dict.fromkeys(classes + critic.reaction_classes)), origin=origin,
                 depth=depth, critic=critic)
    g.reactions[rx_id] = h
    ctx.bus.publish("graph.reaction", h.to_event())
    ctx.prov(ProvNode(
        id=f"hyp:{rx_id}", node_type="hypothesis", step_id=rx_id, agent_id=AGENT_ID,
        parent_ids=[parent_prov] if parent_prov else [],
        status="fail" if critic.verdict == "block" else "pass",
        summary=f"{' + '.join(m.name for m in reactants)} → {product.name} ({', '.join(classes) or 'proposed'})",
        details={"reaction_class": classes, "origin": origin, "depth": depth,
                 "precursors": [{"id": m.id, "name": m.name, "smiles": m.smiles, "purchasable": m.purchasable,
                                 "known": m.known} for m in reactants],
                 "method": "RDKit retro-template from the reaction-class registry" if origin == "template"
                 else "agent-proposed precursors, resolved through PubChem/OPSIN"}))
    for c in critic.checks:
        ctx.prov(ProvNode(id=f"chk:{rx_id}:{c.name}", node_type="check", step_id=rx_id, agent_id="critic",
                          parent_ids=[f"hyp:{rx_id}"], status=c.status, summary=c.reason,
                          details={"check": c.name, **c.details, "engine": "RDKit (deterministic, no LLM)"}))
    return h


async def run(ctx: RunContext, g: KnowledgeGraph, max_depth: int = 3, width: int = 4,
              max_hypotheses: int = 30) -> None:
    target = ctx.target
    tmol = await add_molecule(ctx, g, target.smiles, "target", target.name)
    g.target_id = tmol.id
    # Best-first: a cut's priority is its parent's + 1 + 0.6 × its rank among siblings, so the
    # most promising line reaches building blocks first while alternatives are still explored.
    frontier: list[tuple[float, int, str, int]] = [(0.0, 0, tmol.id, 0)]
    expanded, tie = set(), 0
    while frontier and len(g.hypotheses()) < max_hypotheses:
        prio, _, mol_id, depth = heapq.heappop(frontier)
        mol = g.molecules[mol_id]
        if mol.id in expanded or depth >= max_depth or (mol.purchasable and mol.id != g.target_id):
            continue
        expanded.add(mol.id)
        n_atoms = rd.parse(mol.smiles).GetNumHeavyAtoms()
        cuts = sorted(disconnect(mol.smiles), key=lambda c: -_rank(c, n_atoms))[: width + (depth == 0)]
        for rank, cut in enumerate(cuts):
            reactants = [await add_molecule(ctx, g, s_, "precursor") for s_ in cut.precursors]
            h = add_hypothesis(ctx, g, mol, reactants, [cut.reaction_class], "template", depth,
                               parent_prov="target" if depth == 0 else None)
            if h.critic.verdict == "block":
                continue
            for m in reactants:
                if not m.purchasable:
                    tie += 1
                    heapq.heappush(frontier, (prio + 1 + 0.6 * rank, tie, m.id, depth + 1))
    hyps = g.hypotheses()
    ctx.log(AGENT_ID, f"Decomposed {target.name}: {len(hyps)} candidate steps over "
                      f"{len({h.product for h in hyps})} molecules; "
                      f"{sum(m.purchasable for m in g.molecules.values())} purchasable building blocks")
