"""Reaction-class registry: each class is defined once, with
  - `retro`:   product pattern >> precursors   (used to cut a target into precursors)
  - `forward`: reactants >> product variants    (used to recognise a reported step)
Forward variants cover common reagent equivalents (acid / acyl chloride / anhydride).
All structures are produced by RDKit from these templates, never by an LLM."""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import permutations

from rdkit import Chem
from rdkit.Chem import AllChem


@dataclass(frozen=True)
class ReactionClass:
    name: str
    retro: str | None
    forward: tuple[str, ...] = field(default_factory=tuple)
    reagents: tuple[str, ...] = ()       # typical reagents (SMILES) that supply atoms not in the precursors


_ACYL_DONORS = ("[CX3:3](=[O:4])O[CX3](=O)", "[CX3:3](=[O:4])[Cl,Br]", "[CX3:3](=[O:4])[OX2H1]")

REGISTRY: tuple[ReactionClass, ...] = (
    ReactionClass(
        "Ester formation (O-acylation)",
        "[CX3:1](=[O:2])-!@[OX2:3]-!@[#6;!$(C=O):4]>>[C:1](=[O:2])O.[O:3][*:4]",
        tuple(f"[OX2H1:1][#6;!$(C=O):2].{d}>>[C:3](=[O:4])[O:1][*:2]" for d in _ACYL_DONORS)),
    ReactionClass(
        "Amide formation (N-acylation)",
        "[CX3;!R:1](=[O:2])-!@[NX3;!$(N(C=O)C=O);!$(NS(=O)=O):3]>>[C:1](=[O:2])O.[N:3]",
        tuple(f"[NX3;H2,H1;!$(NC=O);!$(NS=O):1].{d}>>[C:3](=[O:4])[N:1]" for d in _ACYL_DONORS)),
    ReactionClass(
        "Sulfonamide formation",
        "[SX4:1](=[O:2])(=[O:3])-!@[NX3:4]>>[S:1](=[O:2])(=[O:3])Cl.[N:4]",
        ("[SX4:1](=[O:2])(=[O:3])Cl.[NX3;H2,H1;!$(NC=O);!$(NS=O):4]>>[S:1](=[O:2])(=[O:3])[N:4]",)),
    ReactionClass(
        "Chlorosulfonation",
        "[c:1]-[SX4](=O)(=O)Cl>>[cH:1]",
        ("[cH1:1]>>[c:1]S(=O)(=O)Cl",), ("O=S(=O)(O)Cl",)),
    ReactionClass(
        "Friedel-Crafts acylation",
        "[c:1]-!@[CX3:2](=[O:3])-[#6;!c:4]>>[cH:1].[C:2](=[O:3])([*:4])Cl",
        ("[cH1:1].[CX3:2](=[O:3])[Cl,Br]>>[c:1][C:2]=[O:3]",
         "[cH1:1].[CX3:2](=[O:3])O[CX3](=O)>>[c:1][C:2]=[O:3]")),
    ReactionClass(
        "Carbonyl reduction",
        "[#6:1][CX4H1:2]([OX2H1:3])[#6:4]>>[*:1][C:2](=[O:3])[*:4]",
        ("[#6:1][CX3:2](=[OX1:3])[#6:4]>>[*:1][C:2]([O:3])[*:4]",
         "[#6:1][CX3H1:2]=[OX1:3]>>[*:1][C:2][O:3]"), ("[H][H]",)),
    ReactionClass(
        "Alcohol carbonylation (Pd/CO)",
        "[CX4;H1,H2:1]-!@[CX3](=O)[OX2H1]>>[C:1]O",
        ("[CX4:1][OX2H1]>>[C:1]C(=O)O",), ("[C-]#[O+]",)),
    ReactionClass(
        "Nitrile hydrolysis",
        "[#6:1]-!@[CX3](=O)[OX2H1]>>[*:1]C#N",
        ("[#6:1][CX2]#[NX1]>>[*:1]C(=O)O",), ("O",)),
    ReactionClass(
        "Nitro reduction",
        "[c:1]-[NX3H2]>>[c:1][N+](=O)[O-]",
        ("[c,C:1][N+](=O)[O-]>>[*:1]N", "[c,C:1]N(=O)=O>>[*:1]N"), ("[H][H]",)),
    ReactionClass(
        "Aromatic nitration",
        "[c:1]-[N+](=O)[O-]>>[cH:1]",
        ("[cH1:1]>>[c:1][N+](=O)[O-]",), ("O=[N+]([O-])O",)),
    ReactionClass(
        "Kolbe-Schmitt carboxylation",
        "[OX2H1:1][c:2][c:3]-[CX3](=O)[OX2H1]>>[O:1][c:2][cH:3]",
        ("[OX2H1:1][c:2][cH1:3]>>[O:1][c:2][c:3]C(=O)O",), ("O=C=O",)),
    ReactionClass(
        "Ether formation (O-alkylation)",
        "[#6;!$(C=O):1]-!@[OX2:2]-!@[CX4;!$(C(O)O):3]>>[*:1][O:2].[C:3]Br",
        ("[OX2H1:1][#6:2].[CX4:3][Cl,Br,I]>>[*:2][O:1][C:3]",)),
    ReactionClass(
        "N-alkylation",
        "[NX3;!$(N-[C,S]=O);!$(N-a):1]-!@[CX4;!$(C(N)[N,O]):2]>>[N:1].[C:2]Br",
        ("[NX3;H2,H1;!$(NC=O):1].[CX4:2][Cl,Br,I]>>[N:1][C:2]",)),
    ReactionClass(
        "Reductive amination",
        "[NX3;!$(N-[C,S]=O);!$(N-a):1]-!@[CX4;H1,H2;!$(C(N)[N,O]):2]>>[N:1].[C:2]=O",
        ("[NX3;H2,H1;!$(NC=O):1].[CX3:2]=[OX1]>>[N:1][C:2]",)),
    ReactionClass(
        "Suzuki coupling",
        "[c:1]-!@[c:2]>>[c:1]Br.[c:2]B(O)O",
        ("[c:1][Br,I,Cl].[c:2][BX3]([OX2H1])[OX2H1]>>[c:1][c:2]",)),
    ReactionClass(
        "Acyl chloride formation",
        "[CX3:1](=[O:2])Cl>>[C:1](=[O:2])O",
        ("[CX3:1](=[O:2])[OX2H1]>>[C:1](=[O:2])Cl",), ("O=S(Cl)Cl",)),
    # recognised in reports but not used as retro cuts (they add protecting-group detours)
    ReactionClass("Ester hydrolysis", None, ("[CX3:1](=[O:2])[OX2:3][CX4,c]>>[C:1](=[O:2])[O:3]",)),
    ReactionClass("Oxime formation", None, ("[CX3:1]=[OX1]>>[C:1]=NO",)),
    ReactionClass("Oxime dehydration to nitrile", None, ("[CX3H1:1]=N[OH]>>[C:1]#N",)),
    ReactionClass("Darzens glycidic ester condensation", None,
                  ("[CX3:1]=[OX1:2].[CH2:3]([Cl,Br])[C:4](=[O:5])[O:6]>>[C:1]1[O:2][C:3]1[C:4](=[O:5])[O:6]",)),
)

_FWD = [(rc.name, AllChem.ReactionFromSmarts(s)) for rc in REGISTRY for s in rc.forward]
_BY_NAME = {rc.name: rc for rc in REGISTRY}


def typical_reagents(class_names: list[str]) -> list[str]:
    """SMILES of the reagents the given classes normally use (for the critic's atom balance)."""
    return [r for n in class_names if n in _BY_NAME for r in _BY_NAME[n].reagents]
_RETRO = [(rc.name, AllChem.ReactionFromSmarts(rc.retro)) for rc in REGISTRY if rc.retro]


def _sanitized(m: Chem.Mol) -> Chem.Mol | None:
    try:
        m = Chem.Mol(m)
        Chem.SanitizeMol(m)
        return Chem.MolFromSmiles(Chem.MolToSmiles(m))      # round-trip fixes Hs / aromaticity
    except Exception:  # noqa: BLE001
        return None


def _key14(m: Chem.Mol) -> str | None:
    try:
        k = Chem.MolToInchiKey(m)
        return k.split("-")[0] if k else None
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------- forward

def classify(reactants: list[Chem.Mol], product: Chem.Mol, max_products: int = 400) -> list[str]:
    """Classes whose forward template turns (some of) `reactants` into `product`
    (compared by InChIKey connectivity, so stereo differences are tolerated)."""
    target = _key14(product)
    if not target:
        return []
    hits: list[str] = []
    for name, rxn in _FWD:
        if name in hits:
            continue
        n = rxn.GetNumReactantTemplates()
        for combo in permutations(reactants, n) if n <= len(reactants) else ():
            try:
                outs = rxn.RunReactants(tuple(combo), max_products)
            except Exception:  # noqa: BLE001
                continue
            if any((p := _sanitized(ps[0])) is not None and _key14(p) == target for ps in outs):
                hits.append(name)
                break
    return hits


# ---------------------------------------------------------------- retro

@dataclass
class Cut:
    reaction_class: str
    precursors: list[str]          # canonical SMILES


def disconnect(smiles: str) -> list[Cut]:
    """All single-step disconnections of a molecule allowed by the registry."""
    product = Chem.MolFromSmiles(smiles)
    if product is None:
        return []
    n_prod = product.GetNumHeavyAtoms()
    seen: set[tuple] = set()
    cuts: list[Cut] = []
    for name, rxn in _RETRO:
        try:
            outs = rxn.RunReactants((product,), 200)
        except Exception:  # noqa: BLE001
            continue
        for ps in outs:
            mols = [_sanitized(p) for p in ps]
            if any(m is None for m in mols):
                continue
            smis = sorted(Chem.MolToSmiles(m) for m in mols)
            if smiles in smis or any(m.GetNumHeavyAtoms() > n_prod for m in mols):
                continue
            key = (name, tuple(smis))
            if key not in seen:
                seen.add(key)
                cuts.append(Cut(name, smis))
    return cuts
