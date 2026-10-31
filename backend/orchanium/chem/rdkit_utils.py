"""RDKit helpers: parsing, identity, structure inspection, depiction, 3D."""
from __future__ import annotations

from collections import Counter
from functools import lru_cache

from rdkit import Chem, RDLogger
from rdkit.Chem import AllChem, Descriptors, rdMolDescriptors
from rdkit.Chem.Draw import rdMolDraw2D
from rdkit.Chem.Scaffolds import MurckoScaffold

RDLogger.DisableLog("rdApp.*")

# Functional groups the planner reports and the critic uses for conflict warnings.
FG_SMARTS: dict[str, str] = {
    "carboxylic_acid": "[CX3](=O)[OX2H1]",
    "ester": "[#6][CX3](=O)[OX2H0][#6]",
    "amide": "[NX3][CX3](=[OX1])",
    "acyl_halide": "[CX3](=[OX1])[Cl,Br,I]",
    "anhydride": "[CX3](=O)[OX2][CX3](=O)",
    "aldehyde": "[CX3H1](=O)[#6]",
    "ketone": "[#6][CX3](=O)[#6]",
    "primary_amine": "[NX3;H2][CX4,c]",
    "secondary_amine": "[NX3;H1]([CX4,c])[CX4,c]",
    "alcohol": "[OX2H][CX4]",
    "phenol": "[OX2H]c",
    "ether": "[OD2]([#6;!$(C=O)])[#6;!$(C=O)]",
    "nitro": "[$([NX3](=O)=O),$([NX3+](=O)[O-])]",
    "nitrile": "[NX1]#[CX2]",
    "alkyl_halide": "[CX4][Cl,Br,I]",
    "aryl_halide": "c[F,Cl,Br,I]",
    "sulfonamide": "[SX4](=[OX1])(=[OX1])[NX3]",
    "sulfonyl_chloride": "[SX4](=O)(=O)Cl",
    "alkene": "[CX3]=[CX3]",
    "alkyne": "[CX2]#[CX2]",
    "epoxide": "C1OC1",
    "boronic_acid": "[BX3]([OX2H])[OX2H]",
    "organometallic": "[Mg,Li,Zn]",
}
_FG_PATTERNS = {k: Chem.MolFromSmarts(v) for k, v in FG_SMARTS.items()}


def parse(smiles: str | None) -> Chem.Mol | None:
    if not smiles:
        return None
    try:
        return Chem.MolFromSmiles(smiles)
    except Exception:  # noqa: BLE001
        return None


def canonical(smiles: str) -> str | None:
    m = parse(smiles)
    return Chem.MolToSmiles(m) if m else None


def inchikey(mol_or_smiles: Chem.Mol | str) -> str | None:
    m = parse(mol_or_smiles) if isinstance(mol_or_smiles, str) else mol_or_smiles
    if m is None:
        return None
    try:
        return Chem.MolToInchiKey(m) or None
    except Exception:  # noqa: BLE001
        return None


def element_counts(m: Chem.Mol, include_h: bool = True) -> Counter:
    c: Counter = Counter()
    for a in m.GetAtoms():
        c[a.GetSymbol()] += 1
        if include_h:
            c["H"] += a.GetTotalNumHs()
    return c


def functional_groups(m: Chem.Mol) -> dict[str, int]:
    out = {}
    for name, patt in _FG_PATTERNS.items():
        n = len(m.GetSubstructMatches(patt))
        if n:
            out[name] = n
    return out


def describe(smiles: str) -> dict:
    """Structural summary used by the planner and shown in the UI."""
    m = parse(smiles)
    if m is None:
        return {"valid": False}
    ri = m.GetRingInfo()
    stereo = Chem.FindMolChiralCenters(m, includeUnassigned=True, useLegacyImplementation=False)
    return {
        "valid": True,
        "canonical_smiles": Chem.MolToSmiles(m),
        "inchikey": inchikey(m),
        "formula": rdMolDescriptors.CalcMolFormula(m),
        "mw": round(Descriptors.MolWt(m), 2),
        "heavy_atoms": m.GetNumHeavyAtoms(),
        "rings": ri.NumRings(),
        "aromatic_rings": rdMolDescriptors.CalcNumAromaticRings(m),
        "stereocenters": len(stereo),
        "rotatable_bonds": rdMolDescriptors.CalcNumRotatableBonds(m),
        "functional_groups": functional_groups(m),
    }


# ---- depiction --------------------------------------------------------------

_DARK_PALETTE = {
    6: (0.86, 0.89, 0.94), 7: (0.45, 0.65, 1.0), 8: (1.0, 0.42, 0.42), 16: (0.98, 0.82, 0.3),
    9: (0.5, 0.9, 0.6), 17: (0.5, 0.9, 0.6), 35: (0.85, 0.5, 0.35), 53: (0.75, 0.45, 0.95),
    15: (1.0, 0.6, 0.2), 1: (0.75, 0.78, 0.85),
}


@lru_cache(maxsize=2048)
def depict_svg(smiles: str, width: int = 260, height: int = 200, theme: str = "dark") -> str | None:
    m = parse(smiles)
    if m is None:
        return None
    AllChem.Compute2DCoords(m)
    d = rdMolDraw2D.MolDraw2DSVG(width, height)
    o = d.drawOptions()
    o.clearBackground = False
    o.bondLineWidth = 2
    o.padding = 0.08
    o.additionalAtomLabelPadding = 0.1
    if theme == "dark":
        o.setAtomPalette(_DARK_PALETTE)
        o.setSymbolColour((0.86, 0.89, 0.94))
    d.DrawMolecule(m)
    d.FinishDrawing()
    return d.GetDrawingText()


@lru_cache(maxsize=512)
def molblock_3d(smiles: str, seed: int = 0xC0FFEE) -> str | None:
    m = parse(smiles)
    if m is None:
        return None
    mh = Chem.AddHs(m)
    params = AllChem.ETKDGv3()
    params.randomSeed = seed
    if AllChem.EmbedMolecule(mh, params) != 0:
        params.useRandomCoords = True
        if AllChem.EmbedMolecule(mh, params) != 0:
            return None
    try:
        AllChem.MMFFOptimizeMolecule(mh, maxIters=500)
    except Exception:  # noqa: BLE001
        pass
    return Chem.MolToMolBlock(mh)


def png_bytes(smiles: str, size: int = 300) -> bytes | None:
    from rdkit.Chem import Draw
    m = parse(smiles)
    if m is None:
        return None
    d = rdMolDraw2D.MolDraw2DCairo(size, size)
    d.DrawMolecule(m)
    d.FinishDrawing()
    return d.GetDrawingText()

@lru_cache(maxsize=4096)
def scaffold(smiles: str | None, min_rings: int = 2, min_atoms: int = 10) -> str | None:
    """The molecule's ring skeleton (Murcko scaffold), or None when it is too
    plain to identify a chemical series. A one-ring scaffold like benzene says
    nothing about who a molecule is related to, so it is not returned."""
    m = parse(smiles)
    if m is None:
        return None
    core = MurckoScaffold.GetScaffoldForMol(m)
    if core is None or core.GetNumHeavyAtoms() < min_atoms:
        return None
    if rdMolDescriptors.CalcNumRings(core) < min_rings:
        return None
    return Chem.MolToSmiles(core)
