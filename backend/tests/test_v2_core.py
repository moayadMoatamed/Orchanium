"""Offline tests for the v2 core: decomposition, precedent linking, routes,
route validation and the verdict rule. PubChem lookups are stubbed out."""
import asyncio

import pytest

from orchanium.agents import decomposer, verdict
from orchanium.agents.debate import DebateResult, Objection
from orchanium.chem import pubchem
from orchanium.chem import rdkit_utils as rd
from orchanium.chem.critic import Species, critique
from orchanium.chem.reactions import disconnect
from orchanium.chem.resolver import MolRef
from orchanium.context import RunContext
from orchanium.events import EventBus
from orchanium.graph import KnowledgeGraph, Reaction
from orchanium.models import Clue, SourceRef, TargetInfo

PARACETAMOL = "CC(=O)Nc1ccc(O)cc1"


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    from orchanium import store
    monkeypatch.setattr(store, "_store", store.Store(tmp_path / "t.sqlite"))

    async def no_lookup(key):
        return None
    monkeypatch.setattr(pubchem, "lookup_inchikey", no_lookup)


def _ctx(smiles: str) -> RunContext:
    ctx = RunContext(run_id="t", bus=EventBus("t"), client=None)
    ctx.target = TargetInfo(query=smiles, name="target", smiles=smiles, inchikey=rd.inchikey(smiles))
    return ctx


def _decomposed(smiles: str) -> tuple[RunContext, KnowledgeGraph]:
    ctx, g = _ctx(smiles), KnowledgeGraph()
    asyncio.run(decomposer.run(ctx, g))
    return ctx, g


def _observe(g: KnowledgeGraph, reactants: list[str], product: str, outcome="success") -> Reaction:
    ids = []
    for s in reactants + [product]:
        k = rd.inchikey(s)
        if k not in g.molecules:
            from orchanium.graph import Molecule
            g.molecules[k] = Molecule(id=k, smiles=rd.canonical(s), name=s, roles={"clue"})
        ids.append(k)
    cid = f"web:{len(g.clues)}"
    g.clues[cid] = Clue(id=cid, origin="web", reactants=[MolRef(smiles=s) for s in reactants],
                        products=[MolRef(smiles=product)], outcome=outcome,
                        source=SourceRef(kind="paper", title="t", url="https://x.org"))
    crit = critique([Species(name=s, smiles=s) for s in reactants], Species(name=product, smiles=product))
    rx = Reaction(id=f"obs:{len(g.reactions)}", kind="observed", reactants=ids[:-1], product=ids[-1],
                  classes=crit.reaction_classes, clue_ids=[cid], critic=crit)
    g.reactions[rx.id] = rx
    g.clue_reaction[cid] = rx.id
    return rx


def test_disconnect_finds_textbook_cuts():
    assert any(c.reaction_class.startswith("Amide") and "Nc1ccc(O)cc1" in c.precursors
               for c in disconnect(PARACETAMOL))
    assert any(c.reaction_class == "Sulfonamide formation" for c in disconnect("CN1CCN(S(=O)(=O)c2ccccc2)CC1"))


def test_decomposer_builds_hypotheses_down_to_purchasable():
    ctx, g = _decomposed(PARACETAMOL)
    assert g.target_id == rd.inchikey(PARACETAMOL)
    hyps = g.hypotheses()
    assert hyps and all(h.critic is not None for h in hyps)
    amide = next(h for h in hyps if any("Amide" in c for c in h.classes))
    assert all(g.molecules[x].purchasable for x in amide.reactants)      # acetic acid + 4-aminophenol


def test_analog_precedent_grades_the_step_and_makes_a_feasible_route():
    ctx, g = _decomposed(PARACETAMOL)
    _observe(g, ["CC(=O)OC(C)=O", "COc1ccc(N)cc1"], "COc1ccc(NC(C)=O)cc1")      # close analog
    _observe(g, ["c1ccccc1", "CC(=O)Cl"], "CC(=O)c1ccccc1")                       # unrelated
    g.link_precedents()
    amide = next(h for h in g.hypotheses() if any("Amide" in c for c in h.classes))
    step = g.grade(amide.id)
    assert step.grade == "analog" and step.precedent_score >= 0.55
    v = verdict.decide(ctx, g, DebateResult(route=[amide.id], builder_turns=[], skeptic_turns=[],
                                            sustained=[], struck_citations=[]))
    assert v.label == "Feasible" and v.route == [amide.id]


def test_failure_backed_fatal_objection_makes_it_unlikely():
    ctx, g = _decomposed(PARACETAMOL)
    _observe(g, ["CC(=O)OC(C)=O", "COc1ccc(N)cc1"], "COc1ccc(NC(C)=O)cc1")
    bad = _observe(g, ["CC(=O)O", "Nc1ccc(O)cc1"], "CC(=O)Nc1ccc(O)cc1", outcome="failure")
    g.link_precedents()
    amide = next(h for h in g.hypotheses() if any("Amide" in c for c in h.classes))
    obj = Objection(id="O1", hypothesis_id=amide.id, severity="fatal", claim="reported to fail",
                    cited_ids=[bad.clue_ids[0]])
    v = verdict.decide(ctx, g, DebateResult(route=[amide.id], builder_turns=[], skeptic_turns=[],
                                            sustained=[obj], struck_citations=[]))
    assert v.label == "Unlikely"


def test_invalid_route_falls_back_and_no_evidence_is_uncertain():
    ctx, g = _decomposed(PARACETAMOL)
    g.link_precedents()
    assert verdict.validate_route(g, ["hyp:nonexistent"])
    v = verdict.decide(ctx, g, DebateResult(route=["hyp:nonexistent"], builder_turns=[], skeptic_turns=[],
                                            sustained=[], struck_citations=[]))
    assert v.route_source == "fallback" and v.label == "Uncertain"
