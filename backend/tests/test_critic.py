from orchanium.chem import rdkit_utils as rd
from orchanium.chem.critic import Species, check_no_cycle, critique


def sp(name: str, smiles: str | None) -> Species:
    return Species(name=name, smiles=rd.canonical(smiles) if smiles else None,
                   inchikey=rd.inchikey(smiles) if smiles else None)


SALICYLIC = sp("salicylic acid", "Oc1ccccc1C(=O)O")
AC2O = sp("acetic anhydride", "CC(=O)OC(C)=O")
ASPIRIN = sp("aspirin", "CC(=O)Oc1ccccc1C(=O)O")
AMINOPHENOL = sp("4-aminophenol", "Nc1ccc(O)cc1")
PARACETAMOL = sp("paracetamol", "CC(=O)Nc1ccc(O)cc1")
IBB = sp("isobutylbenzene", "CC(C)Cc1ccccc1")
IBAP = sp("4'-isobutylacetophenone", "CC(C)Cc1ccc(C(C)=O)cc1")
IBPE = sp("1-(4-isobutylphenyl)ethanol", "CC(C)Cc1ccc(C(C)O)cc1")
IBUPROFEN = sp("ibuprofen", "CC(C)Cc1ccc(C(C)C(=O)O)cc1")
H2 = sp("hydrogen", "[H][H]")
CO = sp("carbon monoxide", "[C-]#[O+]")
HF = sp("hydrogen fluoride", "F")


def checks(res):
    return {c.name: c.status for c in res.checks}


def test_aspirin_acetylation_passes_with_template():
    r = critique([SALICYLIC, AC2O], ASPIRIN, [sp("sulfuric acid", "OS(=O)(=O)O")])
    assert r.verdict == "pass", r.summary
    assert any("O-acylation" in t for t in r.reaction_classes)


def test_paracetamol_warns_about_chemoselectivity():
    r = critique([AMINOPHENOL, AC2O], PARACETAMOL)
    assert checks(r)["fg_conflicts"] == "warn"
    assert r.verdict == "warn"
    assert any("N-acylation" in t for t in r.reaction_classes)


def test_bhc_route_steps():
    s1 = critique([IBB, AC2O], IBAP, [HF])
    assert s1.verdict == "pass" and any("Friedel-Crafts" in t for t in s1.reaction_classes), s1.summary
    s2 = critique([IBAP], IBPE, [H2])
    assert s2.verdict == "pass" and any("reduction" in t for t in s2.reaction_classes), s2.summary
    s3 = critique([IBPE, CO], IBUPROFEN)
    assert s3.verdict == "pass" and any("Carbonylation" in t for t in s3.reaction_classes), s3.summary


def test_identical_product_blocks():
    r = critique([ASPIRIN], ASPIRIN)
    assert checks(r)["product_differs"] == "fail" and r.verdict == "block"


def test_unresolved_species_blocks():
    r = critique([sp("mystery reagent", None)], ASPIRIN)
    assert r.verdict == "block" and checks(r) == {"parse": "fail"}


def test_missing_element_blocks():
    chlorobenzene = sp("chlorobenzene", "Clc1ccccc1")
    r = critique([sp("benzene", "c1ccccc1")], chlorobenzene)
    assert checks(r)["element_balance"] == "fail"
    # supplying chlorine as a reagent fixes the balance
    r2 = critique([sp("benzene", "c1ccccc1")], chlorobenzene, [sp("chlorine", "ClCl")])
    assert checks(r2)["element_balance"] == "pass"


def test_unrelated_skeleton_blocks():
    r = critique([sp("methanol", "CO"), sp("ammonia", "N")], sp("caffeine", "Cn1cnc2c1c(=O)n(C)c(=O)n2C"))
    assert r.verdict == "block"
    assert checks(r)["conserved_core"] == "fail" or checks(r)["element_balance"] == "fail"


def test_oxygen_shortfall_is_only_a_warning():
    r = critique([sp("toluene", "Cc1ccccc1")], sp("benzoic acid", "OC(=O)c1ccccc1"))
    assert checks(r)["element_balance"] == "warn"


def test_no_cycle():
    assert check_no_cycle(["B", "C"], [["A"], ["B"]]).status == "pass"
    assert check_no_cycle(["B", "B"], [["A"], ["B"]]).status == "fail"
