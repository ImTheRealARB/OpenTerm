"""Pure parsers for the sources that replace Nasdaq's calendars while api.nasdaq.com blocks OpenTerm (2026-11-26).

- Finnhub `calendar/earnings` -> the ERN payload (`providers/macro.parse_earnings` shape).
- Finnhub `calendar/ipo` -> the normalised IPO rows `corp_parse.ipo_payload` draws.
- FMP `earnings` -> GP's earnings markers (`corp_parse.nasdaq_earnings_history` shape).

No network, no clock: callers pass `as_of` / `today`.
"""

from __future__ import annotations

import re
from typing import Any

from ..models import Earning
from ..providers.base import ProviderError

# Finnhub `hour`: bmo = before market open, amc = after market close, dmh = during market hours, "" = not given.
FINNHUB_HOUR = {"bmo": "PRE", "amc": "POST"}
# Finnhub IPO `status` -> the IPO panel's section.
FINNHUB_IPO_SECTION = {"expected": "upcoming", "priced": "priced", "filed": "filed", "withdrawn": "withdrawn"}
IPO_SECTIONS = ("upcoming", "priced", "filed", "withdrawn")


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def surprise_pct(actual: float | None, estimate: float | None) -> float | None:
    """(actual - estimate) / |estimate| in percent, the formula Nasdaq's surprise column uses; None without both or with a 0 estimate."""
    if actual is None or estimate is None or estimate == 0:
        return None
    return round((actual - estimate) / abs(estimate) * 100, 2)


def finnhub_earnings(body: Any, day: str, source: str, as_of: float) -> dict:
    """One day of Finnhub's earnings calendar. Finnhub gives no company name, analyst count or market cap: those stay None
    (the service fills names and market caps from the screener when it can)."""
    rows_in = body.get("earningsCalendar") if isinstance(body, dict) else None
    if not isinstance(rows_in, list):
        raise ProviderError("unavailable", "unexpected Finnhub earnings answer")
    rows = []
    for r in rows_in:
        sym = str(r.get("symbol") or "").strip().upper()
        if not sym or r.get("date") != day:
            continue
        q, y = r.get("quarter"), r.get("year")
        eps, est = _num(r.get("epsActual")), _num(r.get("epsEstimate"))
        rows.append(Earning(symbol=sym, time=FINNHUB_HOUR.get(r.get("hour") or ""),
                            fiscal_quarter=f"Q{q} {y}" if q and y else None, eps_forecast=est, eps=eps,
                            surprise_pct=surprise_pct(eps, est)).model_dump())
    return {"date": day, "as_of_text": None, "rows": rows, "source": source, "as_of": as_of}


_RANGE = re.compile(r"^\s*([\d.]+)\s*-\s*([\d.]+)\s*$")


def finnhub_ipo(body: Any, source: str) -> dict:
    """Finnhub's IPO calendar for a window -> {"rows": {section: [row]}, "note", "source"}. `price` is a number or a range
    ("4.00-5.00"); a range has no single price, so `price` is None and the range text is kept."""
    rows_in = body.get("ipoCalendar") if isinstance(body, dict) else None
    if not isinstance(rows_in, list):
        raise ProviderError("unavailable", "unexpected Finnhub IPO answer")
    out: dict[str, list[dict]] = {s: [] for s in IPO_SECTIONS}
    for r in rows_in:
        section = FINNHUB_IPO_SECTION.get(str(r.get("status") or "").lower())
        if not section:
            continue
        price_text = str(r["price"]).strip() if r.get("price") not in (None, "") else None
        price = None
        if price_text and not _RANGE.match(price_text):
            try:
                price = float(price_text)
            except ValueError:
                price = None
        out[section].append({
            "symbol": r.get("symbol") or None, "company": r.get("name"), "exchange": r.get("exchange"),
            "price": price, "range": price_text, "shares": _num(r.get("numberOfShares")), "date": r.get("date"),
            # Finnhub gives one date per deal (its status date); a withdrawn deal's filing date is not in the answer.
            "filed": r.get("date") if section == "filed" else None, "amount": _num(r.get("totalSharesValue")),
        })
    for rows in out.values():
        rows.sort(key=lambda x: x["date"] or "", reverse=True)
    return {"rows": out, "note": "FINNHUB IPO CALENDAR (US); ONE DATE PER DEAL; A FILED DEAL HAS NO SYMBOL UNTIL IT PRICES",
            "source": source}


def fmp_earnings_history(body: Any, today: str, source: str) -> dict:
    """FMP `earnings`: announcement dates with EPS. Only reported quarters (a date up to today with an actual EPS) become markers;
    the next scheduled date has no EPS yet and is left out, as the Nasdaq history leaves it out."""
    if not isinstance(body, list):
        raise ProviderError("unavailable", "unexpected FMP earnings answer")
    out = []
    for r in body:
        day, eps = r.get("date"), _num(r.get("epsActual"))
        if not isinstance(day, str) or day > today or eps is None:
            continue
        est = _num(r.get("epsEstimated"))
        out.append({"date": day, "fiscal": None, "eps": eps, "estimate": est, "surprise_pct": surprise_pct(eps, est)})
    if not out:
        raise ProviderError("not_found", "no earnings history")
    out.sort(key=lambda x: x["date"], reverse=True)
    return {"rows": out, "source": source}
