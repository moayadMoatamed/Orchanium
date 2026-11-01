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


def rejected(t: str) -> str:
    return _c("38;5;131", t)


def rule(width: int = 62) -> str:
    return dim("─" * width)


def _log() -> logging.Logger:
    # imported lazily: client.py uses this module's colours, so a module-level
    # import here would be a cycle
    from .meta.client import log

    return log


# What each phase is for, in words a non-chemist can follow. Kept here rather
# than inline so the whole narration can be read — and corrected — in one place.
PHASES: dict[str, tuple[str, str]] = {
    "plan": ("Plan", "what molecule is this?"),
    "decompose": ("Decompose", "what steps could make it?"),
    "evidence": ("Evidence", "has anyone published a reaction like each step?"),
    "debate": ("Debate", "two agents argue over the evidence"),
    "verdict": ("Verdict", "computed by a rule, not asked of a model"),
    "report": ("Report", "write it up with conditions and sources"),
}

# The second line of a heading: the detail that will not fit beside the title.
# Kept short so nothing wraps in a terminal sharing the screen with the app.
PHASE_NOTES: dict[str, str] = {
    "plan": "resolved against PubChem — never drawn by a model",
    "decompose": "RDKit applies reaction templates in reverse",
    "evidence": "researchers search the literature in parallel",
    "debate": "one proposes a route, the other attacks it",
    "verdict": "the argument informs it, it cannot override it",
    "report": "",
}


def phase(key: str) -> None:
    """Announce a phase before its work starts."""
    title, blurb = PHASES[key]
    log = _log()
    log.info("")
    log.info("%s  %s", bold(blue(f"▸ {title.upper()}")), dim(blurb))
    if PHASE_NOTES.get(key):
        log.info("%s", dim(f"  {PHASE_NOTES[key]}"))
    log.info(rule())


def note(text: str) -> None:
    _log().info("  %s", dim(text))


WIDTH = 72


def _wrap(text: str, first: str, cont: str) -> list[str]:
    """Hard-wrap so a narrow terminal beside the app never breaks a column."""
    words, lines, cur = text.split(), [], first
    pad = " " * len(cont)
    for w in words:
        if len(cur) + len(w) + 1 > WIDTH and cur.strip() not in (first.strip(), ""):
            lines.append(cur)
            cur = cont if not lines[1:] else pad
        cur += ("" if cur.endswith(" ") or not cur.strip() else " ") + w
    if cur.strip():
        lines.append(cur)
    return lines


def agent_line(agent: str, text: str, level: str = "info") -> None:
    """What an agent actually did — the part a judge can learn something from."""
    log = _log()
    paint = rejected if level == "error" else amber if level == "warn" else (lambda t: t)
    blind = text.startswith("blind mode:")
    if blind:
        text = text.split("blind mode:", 1)[1].strip()
        head = f"  {_c('38;5;131', '\u2717')} {dim('blind')}  "
        plain = "  x blind  "
    else:
        head = f"  {dim(agent)}  "
        plain = f"  {agent}  "
    for i, line in enumerate(_wrap(text, " " * len(plain), " " * len(plain))):
        body = paint(line.strip()) if i == 0 else paint(line.rstrip())
        log.info("%s%s", head if i == 0 else " " * len(plain), body if i == 0 else line.strip())


def search_line(agent: str, query: str, results: int) -> None:
    """The query the model actually sent, and how much came back.

    Named with its agent: several researchers run at once, so an unlabelled
    query cannot be attributed to the call it belongs to.
    """
    q = query if len(query) <= 40 else query[:39] + "\u2026"
    _log().info("    %s %s %s %s", dim("web"), dim(agent.ljust(12)),
                _c("38;5;180", f'"{q}"'), dim(f"\u00b7 {results}"))


