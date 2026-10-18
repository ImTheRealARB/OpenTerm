"""Grounding check: does every number in the answer appear in some tool result of this turn?

A check, not a proof: it catches invented figures, not a real figure used wrongly. Matching tolerates the usual rewrites: thousands separators,
K / M / B / T suffixes, rounding to the digits written, and percent versus fraction (0.0123 is 1.23%). Years, dates, citation markers like [T1],
list indexes and small whole counts (0-10) are ignored.
"""

from __future__ import annotations

import re

NUM = re.compile(r"(?<![\w.])(-?\$?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)(\s?%|[KMBT]\b)?", re.IGNORECASE)
STRIP = re.compile(r"\[T\d+\]|\b\d{4}-\d{2}-\d{2}\b|\b[A-Z]{1,3}\d{2,4}\b|^\s*\d+\.\s", re.MULTILINE)
MULT = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}
REL = 0.005


def _sig(raw: str) -> int:
    digits = raw.replace(",", "").replace("$", "").replace("-", "").lstrip("0").replace(".", "").lstrip("0")
    return max(len(digits), 1)


def _round_sig(x: float, sig: int) -> float:
    return float(f"{x:.{sig - 1}e}") if x else 0.0


def _tokens(text: str):
    """Yield (raw, value, is_percent, sig) for each number token."""
    for m in NUM.finditer(STRIP.sub(" ", text)):
        raw, suffix = m.group(1), (m.group(2) or "").strip().upper()
        clean = raw.replace(",", "").replace("$", "")
        try:
            value = float(clean)
        except ValueError:
            continue
        pct = suffix == "%"
        if suffix in MULT:
            value *= MULT[suffix]
        yield raw + (suffix if pct else (m.group(2) or "").strip() if suffix in MULT else ""), value, pct, _sig(raw)


def source_numbers(results: list[str]) -> list[float]:
    return [v for text in results for _, v, _, _ in _tokens(text)]


def _close(a: float, b: float, sig: int) -> bool:
    if a == b:
        return True
    if abs(a - b) <= REL * max(abs(a), abs(b)):
        return True
    return _round_sig(b, sig) == _round_sig(a, sig)


def check(answer: str, results: list[str]) -> list[str]:
    """Numbers in `answer` that no tool result contains, in order of first appearance (as written)."""
    src = source_numbers(results)
    out: list[str] = []
    for raw, value, pct, sig in _tokens(answer):
        plain = abs(value) == int(abs(value)) and "." not in raw and "," not in raw and not pct and not raw.startswith("$")
        if plain and (0 <= abs(value) <= 10 or 1900 <= abs(value) <= 2100):
            continue
        forms = [value, value / 100] if pct else [value]
        if any(_close(f, s, sig) for f in forms for s in src) or (pct and any(_close(value, s * 100, sig) for s in src)):
            continue
        if raw not in out:
            out.append(raw)
    return out
