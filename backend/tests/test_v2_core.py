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


def test_unreviewed_route_is_capped_at_plausible():
    ctx, g = _decomposed(PARACETAMOL)
    _observe(g, ["CC(=O)OC(C)=O", "COc1ccc(N)cc1"], "COc1ccc(NC(C)=O)cc1")
    g.link_precedents()
    v = verdict.decide(ctx, g, None)
    assert v.label == "Plausible" and any("not reviewed" in r for r in v.reasons)


def test_budget_reserve_blocks_early_phase_overspend():
    from orchanium.meta.client import Budget, BudgetExceeded
    b = Budget()
    b.cost.usd = 1.5
    b.check("llm")                       # 1.5 of 2.5 is fine with no reserve
    b.reserve = 0.5
    with pytest.raises(BudgetExceeded):
        b.check("llm")                   # research may only use half


def test_hidden_source_matches_patent_number_variants():
    from orchanium.clues import _hidden_hit
    ctx = _ctx(PARACETAMOL)
    ctx.blind, ctx.hidden = True, ["US08420823B2"]
    other = Clue(id="x", origin="web", reactants=[MolRef(smiles="CCO")], products=[MolRef(smiles="CC=O")],
                 source=SourceRef(kind="patent", title="Some patent", url="https://patents.google.com/patent/US8420823B2/en"))
    assert _hidden_hit(ctx, [], other) and "hidden source" in _hidden_hit(ctx, [], other)
    other.source.url = "https://patents.google.com/patent/US9999999B2/en"
    assert _hidden_hit(ctx, [], other) is None
    ctx.target.known = False                   # an unnamed target must not filter on the word "target"
    other.source.title = "Target engagement study"
    assert _hidden_hit(ctx, [], other) is None


def test_template_report_needs_no_llm():
    from orchanium.agents.reporter import template_report
    md = template_report({"verdict": {"label": "Plausible", "confidence": 0.67, "reasons": ["r1"]},
                          "starting_materials": ["a"], "debate": None,
                          "steps": [{"reaction": "a + b → c", "transformation": ["Amide"], "grade": "analog",
                                     "precedent_score": 0.7,
                                     "precedents": [{"url": "https://x", "reaction": "x → y", "score": 0.7,
                                                     "source": "US1"}]}],
                          "evidence": {"clues_by_source": {"uspto": 3}, "citation_checks": {"skip": 3}}})
    assert "**Plausible**" in md and "[1](https://x)" in md and "\n" in md


def test_evidence_policy_and_patent_ids():
    from orchanium.clues import classify_source, patent_id
    assert classify_source("https://www.benchchem.com/product/abc", "x", "web") == "vendor"
    assert classify_source("https://shop.example.cn/item/12", "Buy 2-fluorobenzamide", "web") == "vendor"
    assert classify_source("https://patents.justia.com/patent/9399619", "p", "web") == "patent"
    assert classify_source("https://example.org/blog", "Notes", "web") == "web"
    assert patent_id("https://patents.justia.com/patent/9399619") == "US9399619"
    assert patent_id("https://patents.google.com/patent/US08420823B2/en") == "US8420823"


def test_strict_mode_hides_near_identical_evidence():
    from orchanium.clues import _hidden_hit
    from orchanium.chem.resolver import Resolved
    ctx = _ctx(PARACETAMOL)
    ctx.blind, ctx.similarity_cap = True, 0.5
    near = "CC(=O)Nc1ccc(OC)cc1"                       # methacetin, very close to paracetamol
    far = "CC(=O)Nc1ccccc1Cl"
    r = lambda s: Resolved(ok=True, query=s, inchikey=rd.inchikey(s), smiles=s, name=s)  # noqa: E731
    clue = Clue(id="c", origin="web", reactants=[], products=[], source=SourceRef(kind="paper", title="t"))
    from orchanium.chem.similarity import tanimoto
    assert tanimoto(near, PARACETAMOL) > 0.5 > tanimoto(far, PARACETAMOL)
    assert "strict" in _hidden_hit(ctx, [r(near)], clue)
    assert _hidden_hit(ctx, [r(far)], clue) is None
