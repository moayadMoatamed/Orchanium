"""Colour and section headings for the terminal log.

The run log is read by people who are not chemists — during a demo, over a
shoulder, in a screen recording. So each phase announces itself in plain
language before its model calls scroll past, and colour is used to separate
kinds of line, never to carry meaning on its own.

Honest by construction: every heading says what the phase *does*. None of them
praise a model or claim a result, because a log that editorialises is a log
nobody should trust.
"""
from __future__ import annotations

import logging
import os
import sys


def _supports_colour() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if not hasattr(sys.stdout, "isatty") or not sys.stdout.isatty():
        return False
    if sys.platform == "win32":
        # Windows Terminal handles ANSI; older conhost needs it switched on.
        try:
            import ctypes

            k = ctypes.windll.kernel32
            k.SetConsoleMode(k.GetStdHandle(-11), 7)   # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        except Exception:  # noqa: BLE001
            return False
    return True


COLOUR = _supports_colour()


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if COLOUR else text


def dim(t: str) -> str:
    return _c("2", t)


def bold(t: str) -> str:
    return _c("1", t)


def blue(t: str) -> str:
    return _c("38;5;75", t)


def green(t: str) -> str:
    return _c("38;5;71", t)


def amber(t: str) -> str:
    return _c("38;5;179", t)


def rule(width: int = 78) -> str:
    return dim("─" * width)


def _log() -> logging.Logger:
    # imported lazily: client.py uses this module's colours, so a module-level
    # import here would be a cycle
    from .meta.client import log

    return log


def phase(title: str, blurb: str) -> None:
    """Announce a phase before its work starts."""
    log = _log()
    log.info("")
    log.info("%s  %s", bold(blue(f"▸ {title.upper()}")), dim(blurb))
    log.info(rule())


def note(text: str) -> None:
    _log().info("  %s", dim(text))


# What each phase is for, in words a non-chemist can follow. Kept here rather
# than inline so the whole narration can be read — and corrected — in one place.
PHASES: dict[str, tuple[str, str]] = {
    "plan": ("Plan", "what molecule is this? — resolved against PubChem, never drawn by a model"),
    "decompose": ("Decompose", "what steps could make it? — RDKit applies reaction templates in reverse"),
    "evidence": ("Evidence", "has anyone published a reaction like each step? — researchers search in parallel"),
    "debate": ("Debate", "two agents argue over the evidence — one proposes a route, one attacks it"),
    "verdict": ("Verdict", "computed by a fixed rule over the evidence — the argument informs it, never overrides it"),
    "report": ("Report", "writing the route up with its conditions and sources"),
}
