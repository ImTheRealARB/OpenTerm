"""Shared pieces of the US macro and trade sources (BLS, BEA, Census, UN Comtrade). Pure code: no network, no pandas.

Every source is turned into the same "series" dict so one panel (USMAC) can show them all:
    {id, alias, label, unit, kind, freq, last, last_period, prev, prev_period, chg, chg_pct, notes, points: [[period, value], ...]}
`kind` says what the numbers ARE, because that decides what a "change" means (see KINDS). Every series must declare it.
Nothing is estimated: a missing value stays None and a missing period is simply absent.
"""

from __future__ import annotations

import re
from typing import Any

MAX_POINTS = 60

# What a series' numbers are. This is declared per series (never guessed from the values), because it decides how a change reads:
#   level   = an amount or an index (GDP in dollars, CPI index, payrolls). The change is last - prev, and `chg_pct` is that change as a
#             percent of prev (CPI 300 -> 303 is +1.00%).
#   rate    = the value is ALREADY a percentage or a rate (unemployment 4.3%, GDP growth 2.0%, a yield). A "percent change of a
#             percentage" is misleading (2.2 -> 3.4 would read +54.55%), so the honest change is the difference in percentage POINTS
#             (+1.2 pp). `chg` holds that difference and `chg_pct` is None; the panel prints "pp".
#   unknown = we do not know (only a raw BLS series id typed by the user that is not in our catalogue). We do not guess either way:
#             `chg` is shown, `chg_pct` is None, and the panel says the kind is unknown.
KINDS = ("level", "rate", "unknown")


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
                 notes: list[str] | None = None, *, kind: str) -> dict[str, Any]:
    """`points` must be oldest first with sortable period strings ('2026-09', '2026Q2', '2025').

    last = the newest period that has a value; prev = the one before it that has a value. The change is last minus prev, and
    the percent change is None when prev is zero, and always None unless `kind` is "level" (see KINDS).

    `kind` is keyword-only with no default on purpose: forgetting it is a TypeError the first time the source is parsed, and a
    value outside KINDS is a ValueError, so a new series can never silently fall back to a percent change.
    """
    if kind not in KINDS:
        raise ValueError(f"SERIES {alias} HAS KIND {kind!r}, MUST BE ONE OF {KINDS}")
    have = [(p, v) for p, v in points if v is not None]
    last_p, last_v = have[-1] if have else (None, None)
    prev_p, prev_v = have[-2] if len(have) > 1 else (None, None)
    chg = last_v - prev_v if last_v is not None and prev_v is not None else None
    # Only an amount or index has a meaningful percent change. For a rate, `chg` already IS the change in percentage points.
    pct = chg / abs(prev_v) * 100 if kind == "level" and chg is not None and prev_v else None
    return {
        "id": sid, "alias": alias, "label": label, "unit": unit, "kind": kind, "freq": freq,
        "last": last_v, "last_period": last_p, "prev": prev_v, "prev_period": prev_p,
        "chg": chg, "chg_pct": pct, "notes": list(dict.fromkeys(notes or []))[:3],
        "points": [[p, v] for p, v in points[-MAX_POINTS:]],
    }
