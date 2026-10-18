"""Headline keyword score for CN (spec decision E). Not a model: positive minus negative word hits from the fixed lists
below, over whole words and a few stems. The label on screen says so (`KEYWORD SCORE, NOT A MODEL`). Pure, no I/O.
"""

from __future__ import annotations

import re

POSITIVE = frozenset({
    "beat", "beats", "surge", "surges", "surged", "soar", "soars", "soared", "jump", "jumps", "jumped", "gain", "gains",
    "gained", "rise", "rises", "rose", "rally", "rallies", "rallied", "record", "upgrade", "upgrades", "upgraded",
    "outperform", "bullish", "profit", "profits", "growth", "strong", "raises", "raised", "boost", "boosts", "boosted",
    "win", "wins", "approval", "approved", "buyback", "dividend", "expands", "expansion", "recovers", "rebound",
    "rebounds", "tops", "exceeds", "optimistic", "breakthrough",
})
NEGATIVE = frozenset({
    "miss", "misses", "missed", "plunge", "plunges", "plunged", "fall", "falls", "fell", "drop", "drops", "dropped",
    "slump", "slumps", "slumped", "tumble", "tumbles", "tumbled", "sink", "sinks", "sank", "cut", "cuts", "downgrade",
    "downgrades", "downgraded", "underperform", "bearish", "loss", "losses", "lawsuit", "sues", "sued", "probe",
    "investigation", "recall", "recalls", "fraud", "warning", "warns", "warned", "weak", "layoffs", "bankruptcy",
    "default", "defaults", "halt", "halted", "fine", "fined", "ban", "banned", "delay", "delays", "delayed", "crash",
    "concern", "concerns", "risk", "risks", "slowdown", "decline", "declines", "declined",
})
_WORD = re.compile(r"[a-z][a-z'-]*")
NOTE = "KEYWORD SCORE, NOT A MODEL: POSITIVE MINUS NEGATIVE WORD HITS IN THE HEADLINE FROM A FIXED LIST"


def score(text: str | None) -> int:
    """Positive hits minus negative hits over the words of `text`."""
    words = _WORD.findall((text or "").lower())
    return sum(w in POSITIVE for w in words) - sum(w in NEGATIVE for w in words)


def label(value: int) -> str:
    return "POS" if value > 0 else "NEG" if value < 0 else "NEU"
