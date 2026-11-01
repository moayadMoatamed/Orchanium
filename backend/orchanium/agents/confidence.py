"""How much the evidence backs a route, as a number.

The old rule gave every positive point to one thing: how closely a step
resembles a published reaction. Everything else could only subtract. That reads
fairly for a known compound and badly for a new one, because a molecule nobody
has made has no close precedent for its final steps by definition — so the
score punished novelty, which is the whole point of the tool.

What counts here is still only what code can establish. The Builder's argument
never adds; the Skeptic's objections still subtract, because they are anchored
to cited evidence. What is new is that two deterministic things now count for
something:

  the kind of reaction   knowing a step is an amide coupling is evidence it can
                         be made to work, even with no close precedent. The
                         prior comes from how routinely the class appears in the
                         patent index (scripts/build_class_priors.py) and is
                         capped well below a real precedent.
  the chemistry checks   a step whose atoms balance, whose skeleton is
                         conserved and whose groups do not clash is sounder than
                         one that scrapes through, and is no longer treated the
                         same.

A route is then judged on its average step AND its weakest one, because a chain
that is strong on average can still have a link nobody can make.
"""
from __future__ import annotations

import json
from functools import lru_cache

from ..config import DATA
from ..graph import KnowledgeGraph

NO_PRECEDENT = 0.1        # a step with nothing behind it and no class we know
SUPPORT_STEP = 0.05       # per corroborating precedent, up to SUPPORT_MAX of them
SUPPORT_MAX = 3
RISK_WARNED = 0.15        # the chemistry critic raised something
RISK_UNGUARDED = 0.15     # groups that could react in the wrong place, unprotected
WEAKEST_WEIGHT = 0.5      # how much the worst step counts against the average
INCOMPLETE_CAP = 0.35     # a route you cannot start is not a confident route


@lru_cache(maxsize=1)
def class_priors() -> dict[str, float]:
    """How routinely each reaction class is used, measured from the index.
    Empty when the index has not been profiled, which simply means class
    knowledge contributes nothing rather than that a step is bad."""
    path = DATA / "class_priors.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text()).get("priors", {})
    except (OSError, ValueError):
        return {}


def class_prior(classes: list[str]) -> float:
    priors = class_priors()
    return max((priors.get(c, 0.0) for c in classes), default=0.0)


def step_evidence(g: KnowledgeGraph, hyp_id: str, precedent_score: float | None) -> float:
    """What the evidence says about one step, in [0.02, 0.98]."""
    h = g.reactions.get(hyp_id)
    classes = h.classes if h else []
    base = max(precedent_score or 0.0, class_prior(classes), NO_PRECEDENT if not classes else 0.0)
    if base <= 0.0:
        base = NO_PRECEDENT

    # corroboration: several independent reports say more than the best one
    others = max(0, len([p for p in g.precedents.get(hyp_id, []) if p.outcome == "success"]) - 1)
    support = 1.0 + SUPPORT_STEP * min(others, SUPPORT_MAX)

    risk = 1.0
    critic = h.critic if h else None
    if critic and critic.verdict != "pass":
        risk -= RISK_WARNED
    if critic and any(c.status == "warn" and c.name == "fg_conflicts" for c in (critic.checks or [])):
        risk -= RISK_UNGUARDED

    return round(max(0.02, min(0.98, base * support * risk)), 3)


def route_confidence(evidence: list[float], *, major: int, fatal_evidenced: int,
                     gaps: int, lab_failed: int) -> float:
    """A chain is judged by its average link and its weakest one."""
    if not evidence:
        return 0.02
    average = sum(evidence) / len(evidence)
    blended = (1 - WEAKEST_WEIGHT) * average + WEAKEST_WEIGHT * min(evidence)
    conf = blended - 0.08 * major - 0.2 * fatal_evidenced - 0.1 * gaps - 0.25 * lab_failed
    if gaps:
        # A gap means a precursor can be neither bought nor made by this route,
        # so however well evidenced the steps are, nobody can run it as written.
        # That is a different kind of problem from thin evidence, and deducting
        # a little per gap let a one-step route with a perfect precedent come
        # out at 88% while its only starting material was unobtainable.
        conf = min(conf, INCOMPLETE_CAP)
    return round(max(0.02, min(0.97, conf)), 2)
