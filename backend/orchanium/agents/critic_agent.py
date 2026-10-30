"""Critic agent: runs the deterministic RDKit critic on each reaction and emits
one `check` provenance node per check. Then combines checks, citation
verification and cross-source agreement into the final verdict node."""
from __future__ import annotations

import asyncio
from collections import Counter
from urllib.parse import urlsplit

from ..chem.critic import Species, critique
from ..context import RunContext
from ..events import ProvNode
from ..graph import Reaction, RunGraph
from .graph_builder import res_node_id

AGENT_ID = "critic"

CHECK_LABELS = {
    "parse": "Structures parse",
    "product_differs": "Product ≠ reactants",
    "element_balance": "Element balance",
    "conserved_core": "Conserved skeleton (MCS)",
    "fg_conflicts": "Functional-group conflicts",
    "reaction_class": "Known reaction class",
}


def _species(g: RunGraph, mol_id: str) -> Species:
    m = g.molecules[mol_id]
    return Species(name=m.name, smiles=m.smiles, inchikey=m.id if m.resolved else None)


async def review(ctx: RunContext, g: RunGraph, rx_ids: list[str]) -> None:
    for rx_id in rx_ids:
        rx = g.reactions[rx_id]
        reactants = [_species(g, x) for x in rx.reactants]
        product = _species(g, rx.product)
        reagents = [Species(name=n, smiles=s) for n, s in rx.reagent_smiles.items()]
        result = await asyncio.to_thread(critique, reactants, product, reagents)
        rx.critic = result
        if result.verdict == "block":
            rx.label = "rejected"
        parents = [res_node_id(x) for x in rx.reactants + [rx.product]]
        for c in result.checks:
            ctx.prov(ProvNode(
                id=f"chk:{rx_id}:{c.name}", node_type="check", step_id=rx_id, agent_id=AGENT_ID,
                parent_ids=parents, status=c.status,
                summary=f"{CHECK_LABELS.get(c.name, c.name)}: {c.reason}",
                details={"check": c.name, "reason": c.reason, **c.details,
                         "engine": "RDKit (deterministic, no LLM)"},
            ))
        ctx.bus.publish("graph.reaction", rx.to_event())
        names = " + ".join(g.molecules[x].name for x in rx.reactants)
        ctx.log(AGENT_ID, f"{names} → {g.molecules[rx.product].name}: {result.verdict.upper()}"
                          + (f" ({result.summary})" if result.verdict != "pass" else ""),
                level="warn" if result.verdict == "block" else "info")


def finalize(ctx: RunContext, g: RunGraph, rx: Reaction) -> None:
    """Agreement + verdict nodes. Verdict is computed, never LLM-decided."""
    evs = [g.evidence[e] for e in rx.evidence if e in g.evidence]
    domains = sorted({urlsplit(e.source_url).netloc for e in evs})
    cites = Counter(g.citation_status.get(e.id, "pending") for e in evs)
    yields = sorted({e.yield_pct for e in evs if e.yield_pct is not None})
    conflicts = []
    if len(yields) > 1 and yields[-1] - yields[0] > 25:
        conflicts.append(f"reported yields differ: {', '.join(f'{y:g}%' for y in yields)}")
    n = len(domains)
    if rx.origin == "proposed":
        a_status, a_sum = "skip", "LLM-proposed step: no literature sources"
    elif cites["pass"] >= 1 and n >= 2:
        a_status, a_sum = "pass", f"{n} independent sources, {cites['pass']} citation(s) verified"
    elif cites["pass"] >= 1:
        a_status, a_sum = "pass", f"1 source, citation verified on the page"
    elif n >= 2:
        a_status, a_sum = "warn", f"{n} sources but no citation could be verified on its page"
    else:
        a_status, a_sum = "warn", "single source; citation not verified"
    if conflicts:
        a_status = "warn" if a_status == "pass" else a_status
        a_sum += "; " + "; ".join(conflicts)
    check_ids = [f"chk:{rx.id}:{c.name}" for c in (rx.critic.checks if rx.critic else [])]
    cite_ids = [f"cite:{e.id}" for e in evs]
    ctx.prov(ProvNode(id=f"agree:{rx.id}", node_type="agreement", step_id=rx.id, agent_id=AGENT_ID,
                      parent_ids=check_ids + cite_ids, status=a_status, summary=a_sum,
                      details={"sources": n, "domains": domains, "citations": dict(cites),
                               "conflicts": conflicts, "evidence_ids": rx.evidence}))

    critic = rx.critic.verdict if rx.critic else "block"
    if critic == "block":
        label, status = "rejected", "fail"
    elif rx.origin == "proposed":
        label, status = "proposed", "warn" if critic == "warn" else "pass"
    else:
        label, status = "literature", "pass" if (critic == "pass" and a_status == "pass") else "warn"
    conf = 0.0
    if label != "rejected":
        conf = 0.35 + 0.12 * min(n, 3) + 0.15 * min(cites["pass"], 2)
        conf += 0.1 if rx.critic and rx.critic.reaction_classes else 0
        conf -= 0.08 * sum(1 for c in rx.critic.checks if c.status == "warn")
        conf -= 0.25 if label == "proposed" else 0
        conf = round(max(0.05, min(0.99, conf)), 2)
    rx.label, rx.confidence = label, conf
    reason = rx.critic.summary if rx.critic else "not checked"
    ctx.prov(ProvNode(
        id=f"verdict:{rx.id}", node_type="verdict", step_id=rx.id, agent_id=AGENT_ID, verdict=label,
        parent_ids=[f"agree:{rx.id}"], status=status,
        summary={"literature": "Literature-backed", "proposed": "Proposed",
                 "rejected": "Rejected"}[label] + (f" · confidence {conf:.0%}" if label != "rejected" else f": {reason}"),
        details={"label": label, "confidence": conf, "critic": critic, "critic_summary": reason,
                 "reaction_classes": rx.critic.reaction_classes if rx.critic else []},
    ))
    ctx.bus.publish("graph.reaction", rx.to_event())
