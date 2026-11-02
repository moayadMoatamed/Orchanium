"""The lasting knowledge graph, lab notes and the per-step conditions record.
Offline: PubChem is stubbed, the store and snapshots live in a temp dir."""
import asyncio

from orchanium import lab, memory
from orchanium.agents import conditions, verdict
from orchanium.agents.debate import DebateResult
from orchanium.chem.resolver import MolRef
from orchanium.clues import need_for
from orchanium.models import Conditions
from test_v2_core import PARACETAMOL, _decomposed, _observe, offline  # noqa: F401  (offline is an autouse fixture)


def _amide(g):
    return next(h for h in g.hypotheses() if any("Amide" in c for c in h.classes))


def _feasible_run(tmp_path, monkeypatch):
    monkeypatch.setattr(lab, "SNAPSHOTS", tmp_path / "snapshots")
    ctx, g = _decomposed(PARACETAMOL)
    _observe(g, ["CC(=O)OC(C)=O", "COc1ccc(N)cc1"], "COc1ccc(NC(C)=O)cc1")
    g.link_precedents()
    step = _amide(g)
    debate = DebateResult(route=[step.id], builder_turns=[], skeptic_turns=[], sustained=[], struck_citations=[])
    v = verdict.decide(ctx, g, debate)
    assert v.label == "Feasible"
    lab.save_snapshot("r1", lab.Snapshot(graph=g, debate=debate, verdict=v, report="# report", target=ctx.target))
    return step.id


def test_lab_failure_revises_the_verdict_and_says_why(tmp_path, monkeypatch):
    step = _feasible_run(tmp_path, monkeypatch)
    events = asyncio.run(lab.add_note("r1", lab.LabNote(step_id=step, outcome="failure", temperature_c=0,
                                                        observations="no product by TLC")))
    rev = next(e for e in events if e.kind == "revision").data
    assert rev["before"]["label"] == "Feasible" and rev["after"]["label"] == "Uncertain"
    assert any("failed in your lab" in c for c in rev["changes"])
    assert any(e.kind == "prov.node" and e.data["id"] == "verdict:route" for e in events)

    # a later success in the lab outranks both the literature and the earlier failure
    events = asyncio.run(lab.add_note("r1", lab.LabNote(step_id=step, outcome="success", yield_pct=71)))
    rev = next(e for e in events if e.kind == "revision").data
    assert rev["after"]["label"] == "Feasible"
    assert any("done in your lab" in c for c in rev["changes"])
    snap = lab.load_snapshot("r1")
    assert snap.verdict.steps[0].lab_successes == 1 and snap.verdict.steps[0].lab_failures == 1


def test_note_on_unknown_run_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(lab, "SNAPSHOTS", tmp_path / "none")
    try:
        asyncio.run(lab.add_note("missing", lab.LabNote(step_id="hyp:x", outcome="success")))
    except lab.NoteRejected:
        return
    raise AssertionError("expected NoteRejected")


def test_clues_outlive_the_run_and_are_recalled_by_similar_steps():
    _, g = _decomposed(PARACETAMOL)
    _observe(g, ["CC(=O)OC(C)=O", "COc1ccc(N)cc1"], "COc1ccc(NC(C)=O)cc1")
    patent = _observe(g, ["CC(=O)Cl", "Nc1ccccc1"], "CC(=O)Nc1ccccc1")
    g.clues[patent.clue_ids[0]].origin = "uspto"          # the patent index already keeps these
    assert memory.remember(g, "run-a") == 1
    assert memory.stats()["clues"] == 1

    _, fresh = _decomposed(PARACETAMOL)                   # a later run starts with an empty graph...
    recalled = memory._recall(need_for(fresh, _amide(fresh).id), keep=5)
    assert [c.recalled_from for c in recalled] == ["run-a"]  # ...but recalls what run-a found
    assert recalled[0].reactants[0].smiles                   # structures come back resolved


def test_conditions_record_says_where_each_value_came_from():
    _, g = _decomposed(PARACETAMOL)
    a = _observe(g, ["CC(=O)OC(C)=O", "COc1ccc(N)cc1"], "COc1ccc(NC(C)=O)cc1")
    b = _observe(g, ["CC(=O)OC(C)=O", "Cc1ccc(N)cc1"], "Cc1ccc(NC(C)=O)cc1")
    for rx, temp in ((a, 0), (b, 25)):
        c = g.clues[rx.clue_ids[0]]
        c.reagents = [MolRef(name="triethylamine", smiles="CCN(CC)CC"), MolRef(name="Oxolane", smiles="C1CCOC1")]
        c.conditions = Conditions(temperature_c=temp)
    g.link_precedents()
    rec = conditions.record(g, _amide(g).id, {"atmosphere": "nitrogen"})
    assert rec["solvent"]["value"] == "THF" and rec["solvent"]["basis"] == "analog"
    assert rec["reagents"]["value"] == "triethylamine"
    assert rec["temperature"]["range"] == "0 °C to 25 °C"
    assert rec["atmosphere"] == {"value": "nitrogen", "basis": "suggested"}
    assert rec["time"]["basis"] == "missing"
