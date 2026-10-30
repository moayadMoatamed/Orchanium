"""Reaction-class templates. A template "reproduces" a step when running it on
the step's reactants (and small reagents) yields the stated product. This is
a deterministic confidence signal, never a requirement: unmatched steps are
reported as `skip`, not as failures."""
from __future__ import annotations

from itertools import permutations

from rdkit import Chem
from rdkit.Chem import AllChem

# name -> mapped reaction SMARTS
TEMPLATES: dict[str, str] = {
    "O-acylation (anhydride)":
        "[OX2H1:1][#6:2].[CX3:3](=[O:4])O[CX3](=O)>>[CX3:3](=[O:4])[O:1][#6:2]",
    "O-acylation (acyl chloride)":
        "[OX2H1:1][#6:2].[CX3:3](=[O:4])[Cl,Br]>>[CX3:3](=[O:4])[O:1][#6:2]",
    "N-acylation (anhydride)":
        "[NX3;H2,H1;!$(NC=O):1].[CX3:3](=[O:4])O[CX3](=O)>>[CX3:3](=[O:4])[N:1]",
    "N-acylation (acyl chloride)":
        "[NX3;H2,H1;!$(NC=O):1].[CX3:3](=[O:4])[Cl,Br]>>[CX3:3](=[O:4])[N:1]",
    "Amide coupling (acid + amine)":
        "[NX3;H2,H1;!$(NC=O):1].[CX3:3](=[O:4])[OX2H1]>>[CX3:3](=[O:4])[N:1]",
    "Fischer esterification":
        "[CX3:1](=[O:2])[OX2H1].[OX2H1:3][CX4:4]>>[CX3:1](=[O:2])[O:3][C:4]",
    "Friedel-Crafts acylation (acyl chloride)":
        "[cH1:1].[CX3:2](=[O:3])[Cl,Br]>>[c:1][C:2]=[O:3]",
    "Friedel-Crafts acylation (anhydride)":
        "[cH1:1].[CX3:2](=[O:3])O[CX3](=O)>>[c:1][C:2]=[O:3]",
    "Carbonyl reduction to alcohol":
        "[#6:1][CX3:2](=[OX1:3])[#6:4]>>[#6:1][C:2]([O:3])[#6:4]",
    "Aldehyde reduction to alcohol":
        "[#6:1][CX3H1:2]=[OX1:3]>>[#6:1][C:2][O:3]",
    "Carbonylation of alcohol (Pd/CO)":
        "[CX4:1][OX2H1]>>[C:1]C(=O)O",
    "Nitro reduction":
        "[c,C:1][N+](=O)[O-]>>[*:1]N",
    "Nitro reduction (neutral form)":
        "[c,C:1]N(=O)=O>>[*:1]N",
    "Aromatic nitration":
        "[cH1:1]>>[c:1][N+](=O)[O-]",
    "Kolbe-Schmitt carboxylation":
        "[OX2H1:1][c:2][cH1:3]>>[O:1][c:2][c:3]C(=O)O",
    "Chlorosulfonation":
        "[cH1:1]>>[c:1]S(=O)(=O)Cl",
    "Sulfonamide formation":
        "[SX4:1](=[O:2])(=[O:3])Cl.[NX3;H2,H1;!$(NC=O);!$(NS=O):4]>>[S:1](=[O:2])(=[O:3])[N:4]",
    "Williamson ether / O-alkylation":
        "[OX2H1:1][#6:2].[CX4:3][Cl,Br,I]>>[#6:2][O:1][C:3]",
    "N-alkylation":
        "[NX3;H2,H1;!$(NC=O):1].[CX4:3][Cl,Br,I]>>[N:1][C:3]",
    "Ester hydrolysis":
        "[CX3:1](=[O:2])[OX2:3][CX4,c]>>[C:1](=[O:2])[O:3]",
    "Nitrile hydrolysis to acid":
        "[CX2:1]#[NX1]>>[C:1](=O)O",
    "Oxime formation":
        "[CX3:1]=[OX1]>>[C:1]=NO",
    "Oxime dehydration to nitrile":
        "[CX3H1:1]=N[OH]>>[C:1]#N",
    "Darzens glycidic ester condensation":
        "[CX3:1]=[OX1:2].[CH2:3]([Cl,Br])[C:4](=[O:5])[O:6]>>[C:1]1[O:2][C:3]1[C:4](=[O:5])[O:6]",
    "Acid to acyl chloride":
        "[CX3:1](=[O:2])[OX2H1]>>[C:1](=[O:2])Cl",
}
_RXNS = {k: AllChem.ReactionFromSmarts(v) for k, v in TEMPLATES.items()}


def _key14(m: Chem.Mol) -> str | None:
    try:
        Chem.SanitizeMol(m)
        k = Chem.MolToInchiKey(m)
        return k.split("-")[0] if k else None
    except Exception:  # noqa: BLE001
        return None


def match_templates(reactants: list[Chem.Mol], product: Chem.Mol, max_products: int = 400) -> list[str]:
    """Names of templates that turn (some of) `reactants` into `product`.
    Compares InChIKey connectivity blocks, so stereo differences are tolerated."""
    target = _key14(Chem.Mol(product))
    if not target:
        return []
    hits: list[str] = []
    for name, rxn in _RXNS.items():
        n = rxn.GetNumReactantTemplates()
        if n > len(reactants):
            continue
        for combo in permutations(reactants, n):
            try:
                outs = rxn.RunReactants(tuple(combo), max_products)
            except Exception:  # noqa: BLE001
                continue
            if any(_key14(Chem.Mol(ps[0])) == target for ps in outs):
                hits.append(name)
                break
    return hits
