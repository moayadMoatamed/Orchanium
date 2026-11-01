"""The confidence rule: what the evidence is allowed to say about a route."""
from types import SimpleNamespace

from orchanium.agents import confidence as C


class _Graph:
    """Only what step_evidence reads: a step's classes, its critic result and
    the precedents linked to it."""

    def __init__(self, classes, critic=None, precedents=0):
        self.reactions = {"h": SimpleNamespace(classes=classes, critic=critic)}
        self.precedents = {"h": [SimpleNamespace(outcome="success") for _ in range(precedents)]}


def _priors(monkeypatch, mapping):
    monkeypatch.setattr(C, "class_priors", lambda: mapping)


def test_a_routine_reaction_beats_the_floor_without_any_precedent(monkeypatch):
    """The point of the whole change: a molecule nobody has made has no close
    precedent for its last steps, and that must not look like bad chemistry."""
    _priors(monkeypatch, {"Amide formation (N-acylation)": 0.45})
    known = _Graph(["Amide formation (N-acylation)"])
    exotic = _Graph(["Kolbe-Schmitt carboxylation"])
    assert C.step_evidence(known, "h", None) > 0.4
    assert C.step_evidence(exotic, "h", None) == C.NO_PRECEDENT
    assert C.step_evidence(known, "h", None) > C.step_evidence(exotic, "h", None)


def test_a_real_precedent_still_wins_over_the_class(monkeypatch):
    _priors(monkeypatch, {"Amide formation (N-acylation)": 0.45})
    g = _Graph(["Amide formation (N-acylation)"])
    assert C.step_evidence(g, "h", 0.88) > 0.8       # the precedent is kept
    assert C.step_evidence(g, "h", 0.20) >= 0.45     # the class rescues a poor match


def test_corroboration_counts_but_only_a_little(monkeypatch):
    _priors(monkeypatch, {})
    one = _Graph([], precedents=1)
    many = _Graph([], precedents=6)
    assert C.step_evidence(many, "h", 0.6) > C.step_evidence(one, "h", 0.6)
    assert C.step_evidence(many, "h", 0.6) <= 0.6 * (1 + C.SUPPORT_STEP * C.SUPPORT_MAX) + 1e-9


def test_a_critic_warning_costs_the_step(monkeypatch):
    _priors(monkeypatch, {})
    clean = _Graph([], critic=SimpleNamespace(verdict="pass", checks=[]))
    warned = _Graph([], critic=SimpleNamespace(verdict="warn", checks=[]))
    assert C.step_evidence(warned, "h", 0.8) < C.step_evidence(clean, "h", 0.8)


def test_a_route_is_judged_by_its_weakest_link_too():
    """Four good steps must not hide one nobody can make."""
    even = C.route_confidence([0.6, 0.6, 0.6, 0.6], major=0, fatal_evidenced=0, gaps=0, lab_failed=0)
    lopsided = C.route_confidence([0.8, 0.8, 0.8, 0.1], major=0, fatal_evidenced=0, gaps=0, lab_failed=0)
    assert sum([0.8, 0.8, 0.8, 0.1]) / 4 > sum([0.6] * 4) / 4   # the average says lopsided is better
    assert lopsided < even                                       # the rule does not


def test_penalties_still_apply_and_the_floor_holds():
    base = C.route_confidence([0.7, 0.7], major=0, fatal_evidenced=0, gaps=0, lab_failed=0)
    objected = C.route_confidence([0.7, 0.7], major=2, fatal_evidenced=0, gaps=0, lab_failed=0)
    assert objected == round(base - 0.16, 2)
    assert C.route_confidence([0.3], major=0, fatal_evidenced=0, gaps=0, lab_failed=2) == 0.02
    assert C.route_confidence([], major=0, fatal_evidenced=0, gaps=0, lab_failed=0) == 0.02


def test_a_route_you_cannot_start_is_never_confident():
    """A gap means a precursor can be neither bought nor made here, so however
    well evidenced the steps are, nobody can run the route as written."""
    perfect = C.route_confidence([0.98], major=0, fatal_evidenced=0, gaps=0, lab_failed=0)
    stranded = C.route_confidence([0.98], major=0, fatal_evidenced=0, gaps=1, lab_failed=0)
    assert perfect > 0.9
    assert stranded <= C.INCOMPLETE_CAP
