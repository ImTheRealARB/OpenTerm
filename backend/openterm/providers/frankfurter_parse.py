"""Pure helpers for the Frankfurter adapter (ECB reference FX rates). No network, no pandas.

Answer shape (v2 API, recorded 2026-11-05 from `GET https://api.frankfurter.dev/v2/rates?from=...&base=EUR&quotes=USD,INR&providers=ecb`):
a JSON ARRAY with one object per (date, quote): `{"date": "2026-10-28", "base": "EUR", "quote": "INR", "rate": 106.0095}`.
With `providers=ecb` only days the ECB published a fix appear (no weekends, no TARGET holidays).
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Any

from .base import ProviderError

# "EURUSD=X" (base then quote) or "INR=X" (Yahoo's short form: US dollars to INR). Letters only, so "BTC-USD" or "AAPL" never match.
_PAIR = re.compile(r"^([A-Z]{3})([A-Z]{3})=X$")
_SHORT = re.compile(r"^([A-Z]{3})=X$")

FIRST_DAY = date(1999, 1, 4)
"""The first ECB reference-rate day (the euro's launch). Used for MAX ranges."""


def pair_of(symbol: str) -> tuple[str, str] | None:
    """('EUR', 'USD') for EURUSD=X, ('USD', 'INR') for INR=X, None for anything that is not an FX pair symbol."""
    s = (symbol or "").upper()
    m = _PAIR.match(s)
    if m:
        base, quote = m.group(1), m.group(2)
    else:
        m = _SHORT.match(s)
        if not m:
            return None
        base, quote = "USD", m.group(1)
    return None if base == quote else (base, quote)


def day_ts(iso: str) -> int:
    """Epoch seconds for 00:00 UTC of an ISO date. A ValueError here means the answer is not the documented shape."""
    return int(datetime.fromisoformat(iso).replace(tzinfo=UTC).timestamp())


def series(rows: Any, base: str, quote: str) -> tuple[list[int], list[float]]:
    """(timestamps, rates) for one pair, oldest first, from a v2 `/rates` array. Rows for other pairs are skipped.

    Anything that is not an array of {date, base, quote, rate} objects is refused, not guessed at.
    """
    if not isinstance(rows, list):
        raise ProviderError("unavailable", "unexpected Frankfurter answer (not a list)")
    pairs: dict[str, float] = {}
    for r in rows:
        if not isinstance(r, dict) or r.get("base") != base or r.get("quote") != quote:
            continue
        rate = r.get("rate")
        day = r.get("date")
        if isinstance(rate, (int, float)) and isinstance(day, str):
            pairs[day] = float(rate)
    try:
        days = sorted(pairs)
        return [day_ts(d) for d in days], [pairs[d] for d in days]
    except ValueError as e:
        raise ProviderError("unavailable", "unexpected Frankfurter date format") from e


def latest_two(ts: list[int], rates: list[float]) -> tuple[int, float, float | None] | None:
    """(date ts, last rate, previous rate or None) from a series, or None when it is empty."""
    if not ts:
        return None
    return ts[-1], rates[-1], rates[-2] if len(rates) > 1 else None
