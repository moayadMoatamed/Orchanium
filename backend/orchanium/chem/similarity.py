"""Similarity and the single precedent-scoring function used for every clue,
whatever its source.

precedent_score(observed, hypothesis) blends three general signals:
  - product similarity     (are the products alike?)
  - reactant similarity    (are the starting materials alike?)
  - transformation similarity (is the same change happening? RDKit reaction
                               difference fingerprints, class-independent)
plus a small bonus when both are recognised as the same reaction class."""
from __future__ import annotations

from functools import lru_cache

from pydantic import BaseModel
from rdkit import DataStructs
from rdkit.Chem import AllChem, rdChemReactions, rdFingerprintGenerator

from . import rdkit_utils as rd

_MORGAN = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)
DIRECT, ANALOG, WEAK = 0.999, 0.55, 0.35


@lru_cache(maxsize=20000)
def fingerprint(smiles: str):
    m = rd.parse(smiles)
    return _MORGAN.GetFingerprint(m) if m is not None else None


def tanimoto(a: str, b: str) -> float:
    fa, fb = fingerprint(a), fingerprint(b)
    return DataStructs.TanimotoSimilarity(fa, fb) if fa is not None and fb is not None else 0.0


@lru_cache(maxsize=20000)
def _diff_fp(reaction_smiles: str):
    try:
        rxn = AllChem.ReactionFromSmarts(reaction_smiles, useSmiles=True)
        return rdChemReactions.CreateDifferenceFingerprintForReaction(rxn)
    except Exception:  # noqa: BLE001
        return None


def transformation_similarity(r1: str, r2: str) -> float:
    a, b = _diff_fp(r1), _diff_fp(r2)
    if a is None or b is None:
        return 0.0
    return max(0.0, DataStructs.TanimotoSimilarity(a, b))


class PrecedentScore(BaseModel):
    score: float
    grade: str                       # direct | analog | weak | none
    product_similarity: float
    reactant_similarity: float
    transformation_similarity: float
    class_match: bool


def reaction_smiles(reactants: list[str], product: str) -> str:
    return ".".join(reactants) + ">>" + product


def grade(score: float) -> str:
    return "direct" if score >= DIRECT else "analog" if score >= ANALOG else "weak" if score >= WEAK else "none"


def precedent_score(obs_reactants: list[str], obs_product: str, obs_classes: list[str],
                    hyp_reactants: list[str], hyp_product: str, hyp_classes: list[str]) -> PrecedentScore:
    p = tanimoto(obs_product, hyp_product)
    # each hypothesis reactant matched to its most similar observed reactant
    r = (sum(max((tanimoto(h, o) for o in obs_reactants), default=0.0) for h in hyp_reactants)
         / len(hyp_reactants)) if hyp_reactants else 0.0
    t = transformation_similarity(reaction_smiles(obs_reactants, obs_product),
                                  reaction_smiles(hyp_reactants, hyp_product))
    cls = bool(set(obs_classes) & set(hyp_classes))
    # same product by the same transformation counts as direct, even with an
    # equivalent reagent (acid vs anhydride vs acyl chloride)
    if p >= 0.999 and (r >= 0.999 or cls):
        score = 1.0
    else:
        score = min(0.98, 0.35 * p + 0.25 * r + 0.4 * t + (0.1 if cls else 0.0))
    return PrecedentScore(score=round(score, 3), grade=grade(score), product_similarity=round(p, 3),
                          reactant_similarity=round(r, 3), transformation_similarity=round(t, 3),
                          class_match=cls)
