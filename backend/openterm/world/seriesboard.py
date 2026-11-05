"""Shared pieces of the US macro and trade sources (BLS, BEA, Census, UN Comtrade). Pure code: no network, no pandas.

Every source is turned into the same "series" dict so one panel (USMAC) can show them all:
    {id, alias, label, unit, freq, last, last_period, prev, prev_period, chg, chg_pct, notes, points: [[period, value], ...]}
Nothing is estimated: a missing value stays None and a missing period is simply absent.
"""

from __future__ import annotations

import re
from typing import Any

MAX_POINTS = 60


class KeyRejected(ValueError):
    """The source answered HTTP 200 but its body says the key is wrong (BLS and BEA do this instead of a 401)."""


class NotUnderstood(ValueError):
    """The answer is not the shape the provider's documentation describes. Raised so the panel says so instead of guessing."""


class NoData(ValueError):
    """The source understood the question and has nothing for it (HTTP 404 NO DATA, not PROVIDER DOWN)."""


# Strings the sources print instead of a number. They mean "no value", never zero.
_NO_VALUE = {"", "-", "--", "NA", "N/A", "(NA)", "(D)", "(S)", "(NM)", "(X)", "...", "(*)"}


def num(text: Any) -> float | None:
    """'1,234.5' -> 1234.5; '-', '(NA)', '(D)', '' -> None. Anything else that is not a number raises NotUnderstood."""
    if text is None:
        return None
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return float(text)
    s = str(text).strip()
    if s.upper() in _NO_VALUE:
        return None
    try:
        return float(s.replace(",", ""))
    except ValueError:
        raise NotUnderstood(f"NOT A NUMBER: {s[:24]}") from None


_SAFE_ID = re.compile(r"^[A-Za-z0-9_#.\-]{1,40}$")


def safe_id(text: str) -> str:
    """Series ids go into request bodies and URLs: letters, digits and a few separators only."""
    if not _SAFE_ID.match(text):
        raise ValueError(f"BAD SERIES ID: {text[:24]}")
    return text


def build_series(sid: str, alias: str, label: str, unit: str, freq: str, points: list[tuple[str, float | None]],
                 notes: list[str] | None = None) -> dict[str, Any]:
    """`points` must be oldest first with sortable period strings ('2026-09', '2026Q2', '2025').

    last = the newest period that has a value; prev = the one before it that has a value. The change is last minus prev, and
    the percent change is None when prev is zero.
    """
    have = [(p, v) for p, v in points if v is not None]
    last_p, last_v = have[-1] if have else (None, None)
    prev_p, prev_v = have[-2] if len(have) > 1 else (None, None)
    chg = last_v - prev_v if last_v is not None and prev_v is not None else None
    pct = chg / abs(prev_v) * 100 if chg is not None and prev_v else None
    return {
        "id": sid, "alias": alias, "label": label, "unit": unit, "freq": freq,
        "last": last_v, "last_period": last_p, "prev": prev_v, "prev_period": prev_p,
        "chg": chg, "chg_pct": pct, "notes": list(dict.fromkeys(notes or []))[:3],
        "points": [[p, v] for p, v in points[-MAX_POINTS:]],
    }
