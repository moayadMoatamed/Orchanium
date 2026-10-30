import asyncio
import socket

import pytest

from orchanium.chem import pubchem
from orchanium.chem import rdkit_utils as rd


def test_canonical_and_inchikey_agree_across_spellings():
    a = rd.canonical("OC(=O)c1ccccc1OC(C)=O")
    b = rd.canonical("CC(=O)OC1=CC=CC=C1C(=O)O")   # PubChem kekulé form
    assert a == b
    assert rd.inchikey(a) == "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"


def test_invalid_smiles_returns_none():
    assert rd.parse("C1CC") is None
    assert rd.canonical("not a smiles") is None
    assert rd.inchikey("C1CC") is None


def test_describe_reports_groups():
    d = rd.describe("CC(=O)Oc1ccccc1C(=O)O")
    assert d["formula"] == "C9H8O4"
    assert {"ester", "carboxylic_acid"} <= set(d["functional_groups"])
    assert d["aromatic_rings"] == 1


def test_depictions():
    svg = rd.depict_svg("c1ccccc1O")
    assert svg and svg.lstrip().startswith("<?xml")
    mb = rd.molblock_3d("c1ccccc1O")
    assert mb and "V2000" in mb


def test_name_variants_strip_quantities_and_qualifiers():
    assert pubchem.name_variants("2 equiv acetic anhydride")[0] == "acetic anhydride"
    v = pubchem.name_variants("sulfuric acid (cat.)")
    assert "sulfuric acid" in v
    assert "acetic acid" in pubchem.name_variants("glacial acetic acid")


def test_pick_smiles_handles_new_and_old_pubchem_keys():
    assert pubchem._pick_smiles({"SMILES": "C"}) == "C"
    assert pubchem._pick_smiles({"IsomericSMILES": "CC"}) == "CC"
    assert pubchem._pick_smiles({"CanonicalSMILES": "CCC"}) == "CCC"


def _online() -> bool:
    try:
        socket.create_connection(("pubchem.ncbi.nlm.nih.gov", 443), timeout=3).close()
        return True
    except OSError:
        return False


@pytest.mark.skipif(not _online(), reason="PubChem unreachable")
def test_pubchem_resolves_and_caches(tmp_path, monkeypatch):
    from orchanium import store
    monkeypatch.setattr(store, "_store", store.Store(tmp_path / "t.sqlite"))

    async def go():
        r1 = await pubchem.resolve("Aspirin")
        r2 = await pubchem.resolve("aspirin")
        miss = await pubchem.resolve("definitely-not-a-chemical-qqq")
        return r1, r2, miss

    r1, r2, miss = asyncio.run(go())
    assert r1.ok and r1.inchikey == "BSYNRYMUTXBXSQ-UHFFFAOYSA-N" and not r1.cached
    assert r2.cached and r2.smiles == r1.smiles
    assert not miss.ok


def test_purchasability():
    from orchanium.chem import purchasable
    sal = purchasable.check("YGSDEFSMJLZEOE-UHFFFAOYSA-N", "Oc1ccccc1C(=O)O")
    assert sal.purchasable and sal.basis == "catalog"
    small = purchasable.check(None, "CCCCC(=O)Cl")
    assert small.purchasable and small.basis == "heuristic"
    ibu = purchasable.check(rd.inchikey("CC(C)Cc1ccc(C(C)C(=O)O)cc1"), "CC(C)Cc1ccc(C(C)C(=O)O)cc1")
    assert not ibu.purchasable


@pytest.mark.parametrize("pubchem_down, opsin_down, unavailable", [
    (True, False, True),     # service outage: retryable, never "not found"
    (False, True, True),
    (False, False, False),   # both answered "no": a genuine miss
])
def test_outage_is_not_reported_as_not_found(monkeypatch, pubchem_down, opsin_down, unavailable):
    from orchanium.chem import resolver

    async def fake_pubchem(name):
        return pubchem.Resolution(query=name, ok=False, unavailable=pubchem_down,
                                  error="pubchem error" if pubchem_down else "not found in PubChem")

    async def fake_opsin(name):
        if opsin_down:
            raise resolver.Unavailable("OPSIN: timeout")
        return None

    monkeypatch.setattr(resolver.pubchem, "resolve", fake_pubchem)
    monkeypatch.setattr(resolver, "_opsin", fake_opsin)
    r = asyncio.run(resolver.from_name("palmitoyl tripeptide-1"))
    assert not r.ok and r.unavailable is unavailable
    assert ("did not respond" in r.error) is unavailable
