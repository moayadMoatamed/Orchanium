"""Deterministic reaction critic. No LLM is involved in any verdict here; an
LLM may later *explain* a verdict in plain English but cannot change it."""
from __future__ import annotations

from collections import Counter
from typing import Literal

from pydantic import BaseModel, Field
from rdkit import Chem
from rdkit.Chem import rdFMCS

from . import rdkit_utils as rd
from .reactions import classify

CheckStatus = Literal["pass", "warn", "fail", "skip"]
Verdict = Literal["pass", "warn", "block"]

# Hydrogen is never counted. Oxygen often arrives unlisted (water, O2, workup),
# so an oxygen shortfall is a warning rather than a failure.
SOFT_ELEMENTS = {"O"}


class Species(BaseModel):
    name: str
    smiles: str | None = None        # None => unresolved
    inchikey: str | None = None


class CheckResult(BaseModel):
    name: str
    status: CheckStatus
    reason: str
    details: dict = Field(default_factory=dict)


class CriticResult(BaseModel):
    verdict: Verdict
    checks: list[CheckResult]
    reaction_classes: list[str] = Field(default_factory=list)
    core_conservation: float | None = None

    @property
    def summary(self) -> str:
        bad = [c for c in self.checks if c.status in ("fail", "warn")]
        return "; ".join(f"{c.name}: {c.reason}" for c in bad) or "all checks passed"


# ---------------------------------------------------------------- checks

def check_parse(reactants: list[Species], product: Species, reagents: list[Species]) -> CheckResult:
    missing = [s.name for s in reactants + [product] if not (s.smiles and rd.parse(s.smiles))]
    unresolved_reagents = [s.name for s in reagents if not s.smiles]
    if missing:
        return CheckResult(name="parse", status="fail",
                           reason=f"unresolved/unparseable: {', '.join(missing)}",
                           details={"missing": missing})
    if unresolved_reagents:
        return CheckResult(name="parse", status="pass",
                           reason="all reactants and product parse (some reagents unresolved, ignored)",
                           details={"unresolved_reagents": unresolved_reagents})
    return CheckResult(name="parse", status="pass", reason="all species parse and sanitize")


def check_product_differs(reactants: list[Species], product: Species) -> CheckResult:
    if product.inchikey and product.inchikey in {r.inchikey for r in reactants}:
        return CheckResult(name="product_differs", status="fail", reason="product is identical to a reactant")
    pk = (product.inchikey or "").split("-")[0]
    if pk and pk in {(r.inchikey or "").split("-")[0] for r in reactants}:
        return CheckResult(name="product_differs", status="warn",
                           reason="product differs from a reactant only in stereo/protonation")
    return CheckResult(name="product_differs", status="pass", reason="product is a new species")


def check_element_balance(reactants: list[Chem.Mol], reagents: list[Chem.Mol], product: Chem.Mol,
                          max_equiv: int = 2) -> CheckResult:
    """Every heavy element in the product must be supplied by reactants or
    reagents. Counts may use up to `max_equiv` equivalents of each input."""
    prod = rd.element_counts(product, include_h=False)
    react = sum((rd.element_counts(m, include_h=False) for m in reactants), Counter())
    supply = react + sum((rd.element_counts(m, include_h=False) for m in reagents), Counter())
    details = {"product": dict(prod), "reactants": dict(react), "reactants+reagents": dict(supply)}
    missing = sorted(e for e in prod if e not in supply and e not in SOFT_ELEMENTS)
    if missing:
        return CheckResult(name="element_balance", status="fail",
                           reason=f"product contains {', '.join(missing)} not present in any input",
                           details=details)
    short = {e: prod[e] - supply[e] for e in prod if prod[e] > supply[e]}
    hard_short = {e: n for e, n in short.items() if e not in SOFT_ELEMENTS}
    if any(prod[e] > supply[e] * max_equiv for e in hard_short):
        return CheckResult(name="element_balance", status="fail",
                           reason="product needs more atoms than inputs can supply: "
                                  + ", ".join(f"{e} short by {n}" for e, n in short.items()),
                           details=details)
    if short:
        soft = {e: n for e, n in short.items() if e in SOFT_ELEMENTS}
        parts = [f"{e}+{n} (needs >1 equivalent)" for e, n in hard_short.items()]
        parts += [f"O+{n} (unlisted oxidant/water)" for e, n in soft.items()]
        return CheckResult(name="element_balance", status="warn",
                           reason="balances only if: " + ", ".join(parts), details=details)
    lost = {e: supply[e] - prod.get(e, 0) for e in supply if supply[e] > prod.get(e, 0)}
    return CheckResult(name="element_balance", status="pass",
                       reason="heavy atoms balanced" + (f" (by-products carry {dict(lost)})" if lost else ""),
                       details=details)


def _mcs_atoms(a: Chem.Mol, b: Chem.Mol, timeout: int = 2) -> int:
    res = rdFMCS.FindMCS(
        [a, b], timeout=timeout,
        atomCompare=rdFMCS.AtomCompare.CompareElements,
        bondCompare=rdFMCS.BondCompare.CompareAny,
        ringMatchesRingOnly=False, completeRingsOnly=False,
    )
    return res.numAtoms


def check_conserved_core(reactants: list[Chem.Mol], product: Chem.Mol) -> tuple[CheckResult, float]:
    """Atom-mapping stand-in: the product should share a large common
    substructure with at least one reactant (its skeleton came from somewhere)."""
    n = product.GetNumHeavyAtoms() or 1
    per = [_mcs_atoms(r, product) for r in reactants]
    best = max(per) / n if per else 0.0
    coverage = min(1.0, sum(per) / n)
    details = {"mcs_atoms_per_reactant": per, "product_heavy_atoms": n,
               "best_fraction": round(best, 3), "coverage": round(coverage, 3)}
    if best >= 0.4 or coverage >= 0.75:
        return CheckResult(name="conserved_core", status="pass",
                           reason=f"{best:.0%} of product skeleton found in one reactant "
                                  f"({coverage:.0%} covered overall)", details=details), best
    if best >= 0.2 or coverage >= 0.5:
        return CheckResult(name="conserved_core", status="warn",
                           reason=f"weak skeleton overlap ({best:.0%} best, {coverage:.0%} overall)",
                           details=details), best
    return CheckResult(name="conserved_core", status="fail",
                       reason=f"product skeleton not traceable to reactants ({best:.0%} best overlap)",
                       details=details), best


# reagent-class SMARTS used for conflict rules
_REAGENT_CLASSES = {
    "strong_nucleophile_base": "[Mg,Li]",
    "hydride": "[AlH4-,BH4-,Al-,B-]",
    "acylating": "[CX3](=O)[Cl,Br,$(OC=O)]",
}
_RC = {k: Chem.MolFromSmarts(v) for k, v in _REAGENT_CLASSES.items()}


def check_fg_conflicts(reactants: list[Chem.Mol], reagents: list[Chem.Mol]) -> CheckResult:
    warnings: list[str] = []
    inputs = reactants + reagents
    fgs = Counter()
    for m in reactants:
        fgs.update(rd.functional_groups(m))
    has = lambda key: any(m.HasSubstructMatch(_RC[key]) for m in inputs)  # noqa: E731
    protic = [g for g in ("carboxylic_acid", "alcohol", "phenol", "primary_amine", "secondary_amine") if fgs[g]]
    if has("strong_nucleophile_base") and protic:
        warnings.append(f"organometallic reagent with protic groups ({', '.join(protic)}): quench risk")
    reducible = [g for g in ("ester", "ketone", "aldehyde", "nitro", "nitrile", "amide") if fgs[g]]
    if has("hydride") and len(reducible) > 1:
        warnings.append(f"hydride with several reducible groups ({', '.join(reducible)}): chemoselectivity")
    nucleophiles = [g for g in ("primary_amine", "secondary_amine", "alcohol", "phenol") if fgs[g]]
    if has("acylating") and len(nucleophiles) > 1:
        warnings.append(f"acylating agent with competing nucleophiles ({', '.join(nucleophiles)}): "
                        "chemoselectivity must be controlled")
    if warnings:
        return CheckResult(name="fg_conflicts", status="warn", reason="; ".join(warnings),
                           details={"functional_groups": dict(fgs)})
    return CheckResult(name="fg_conflicts", status="pass", reason="no functional-group conflicts detected",
                       details={"functional_groups": dict(fgs)})


def check_reaction_class(reactants: list[Chem.Mol], reagents: list[Chem.Mol], product: Chem.Mol) -> CheckResult:
    small = [m for m in reagents if m.GetNumHeavyAtoms() <= 12]
    hits = classify(reactants + small, product)
    if hits:
        return CheckResult(name="reaction_class", status="pass",
                           reason=f"reproduced by template: {hits[0]}", details={"templates": hits})
    return CheckResult(name="reaction_class", status="skip",
                       reason="no template in the library reproduces this step (not required)")


# ---------------------------------------------------------------- entry point

def critique(reactants: list[Species], product: Species, reagents: list[Species] | None = None) -> CriticResult:
    reagents = reagents or []
    checks = [check_parse(reactants, product, reagents)]
    if checks[0].status == "fail":
        return CriticResult(verdict="block", checks=checks)

    r_mols = [rd.parse(s.smiles) for s in reactants]
    g_mols = [m for m in (rd.parse(s.smiles) for s in reagents if s.smiles) if m is not None]
    p_mol = rd.parse(product.smiles)

    checks.append(check_product_differs(reactants, product))
    checks.append(check_element_balance(r_mols, g_mols, p_mol))
    core, frac = check_conserved_core(r_mols, p_mol)
    checks.append(core)
    checks.append(check_fg_conflicts(r_mols, g_mols))
    rc = check_reaction_class(r_mols, g_mols, p_mol)
    checks.append(rc)

    statuses = {c.status for c in checks}
    verdict: Verdict = "block" if "fail" in statuses else "warn" if "warn" in statuses else "pass"
    return CriticResult(verdict=verdict, checks=checks,
                        reaction_classes=rc.details.get("templates", []), core_conservation=round(frac, 3))


def check_no_cycle(step_products: list[str], step_reactants: list[list[str]]) -> CheckResult:
    """Route-level: no molecule may be produced by a step and also consumed
    by an earlier step in the same route (ordered starting materials -> target)."""
    seen_products: set[str] = set()
    for prods, reacts in zip(step_products, step_reactants):
        if prods in reacts:
            return CheckResult(name="no_cycle", status="fail", reason=f"{prods} consumes itself")
        seen_products.add(prods)
    if len(seen_products) != len(step_products):
        return CheckResult(name="no_cycle", status="fail", reason="a molecule is produced twice in the route")
    return CheckResult(name="no_cycle", status="pass", reason="route is acyclic")
