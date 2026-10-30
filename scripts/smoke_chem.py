"""Smoke-test RDKit and PubChem PUG REST (no API key needed)."""
from __future__ import annotations

import time
from urllib.parse import quote

import httpx
from rdkit import Chem
from rdkit.Chem import AllChem, Descriptors, rdFMCS
from rdkit.Chem.Draw import rdMolDraw2D

PUG = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"


def pubchem(name: str) -> dict:
    url = f"{PUG}/compound/name/{quote(name)}/property/IsomericSMILES,CanonicalSMILES,InChIKey,IUPACName,MolecularFormula/JSON"
    t0 = time.time()
    r = httpx.get(url, timeout=20)
    r.raise_for_status()
    props = r.json()["PropertyTable"]["Properties"][0]
    print(f"  {name:<22} {time.time() - t0:.2f}s  {props}")
    return props


def main():
    print("=== RDKit")
    m = Chem.MolFromSmiles("CC(=O)Oc1ccccc1C(=O)O")
    print("  canonical:", Chem.MolToSmiles(m), "inchikey:", Chem.MolToInchiKey(m), "MW:", round(Descriptors.MolWt(m), 2))
    mh = Chem.AddHs(m)
    assert AllChem.EmbedMolecule(mh, AllChem.ETKDGv3()) == 0
    AllChem.MMFFOptimizeMolecule(mh)
    print("  3D molblock lines:", len(Chem.MolToMolBlock(mh).splitlines()))
    d = rdMolDraw2D.MolDraw2DSVG(300, 220)
    d.DrawMolecule(m)
    d.FinishDrawing()
    print("  SVG bytes:", len(d.GetDrawingText()))
    mcs = rdFMCS.FindMCS([m, Chem.MolFromSmiles("Oc1ccccc1C(=O)O")], timeout=2)
    print("  MCS atoms (aspirin vs salicylic acid):", mcs.numAtoms)

    print("=== PubChem")
    for n in ["aspirin", "salicylic acid", "acetic anhydride", "ibuprofen", "isobutylbenzene", "sildenafil", "not-a-real-chemical-xyz"]:
        try:
            p = pubchem(n)
            smi = p.get("IsomericSMILES") or p.get("SMILES") or p.get("CanonicalSMILES")
            assert Chem.MolFromSmiles(smi) is not None
        except httpx.HTTPStatusError as e:
            print(f"  {n:<22} HTTP {e.response.status_code} (expected for fake name)")
        time.sleep(0.25)  # PubChem asks for <= 5 req/s


if __name__ == "__main__":
    main()
