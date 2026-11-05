"""MF: Indian mutual fund NAV history from MFapi.in. Pure parsing and return maths (no network, no pandas: the server process must never import pandas).

MFapi.in (https://www.mfapi.in/) is a free community service that republishes the daily NAV (net asset value per unit) AMFI collects from the
fund houses. It is NOT an official AMFI API and can lag AMFI by a day. The provider (`providers/mfapi.py`) fetches; this file turns the answers
into the panel's payload. Shapes below were checked against the live service on 2026-11-05 (recordings: `tests/fixtures/mfapi_real_*.json`):

  GET /mf/search?q=<words>   -> [{"schemeCode": 122639, "schemeName": "..."}]          (every word must match, any order; [] = no match;
                                                                                         an empty q is an HTTP 400)
  GET /mf/<schemeCode>       -> {"meta": {"fund_house", "scheme_type", "scheme_category", "scheme_code", "scheme_name",
                                          "isin_growth", "isin_div_reinvestment"},
                                 "data": [{"date": "03-11-2026", "nav": "90.70430"}, ...], "status": "SUCCESS"}
                                 newest first, date is DD-MM-YYYY, nav is TEXT. An UNKNOWN scheme code is NOT an error: it answers
                                 HTTP 200 with scheme_code 0, empty strings in meta and "data": [].

NAV is an end-of-day value per unit, not a market price. For a plan that pays IDCW (the new name of "dividend") the NAV falls on every payout,
so a return worked out from the NAV alone leaves the payouts out; the payload says so.
"""

from __future__ import annotations

import calendar
import re
from bisect import bisect_right
from datetime import date, datetime, timedelta
from typing import Any

# Cap on search rows sent to the panel. "nifty" matches hundreds of schemes; the panel says how many there were in total.
SEARCH_LIMIT = 200
MIN_WORDS_CHARS = 3  # "sb" would match thousands of schemes; MFapi itself refuses an empty query
MAX_QUERY = 80
# A base NAV further than this many days before the target date is not "the nearest earlier NAV" any more, it is a hole in the history.
# (The widest real gap in 3,305 days of one fund's history was 6 days, a holiday week.)
MAX_GAP_DAYS = 10
YEAR_DAYS = 365.0  # the CAGR exponent: annualise with elapsed calendar days / 365

SOURCE = "MFAPI.IN"  # short on purpose: the panel prints it in its title line beside the age
SOURCE_NOTE = ("MFAPI.IN IS A FREE COMMUNITY SERVICE THAT REPUBLISHES AMFI'S DAILY NAV. IT IS NOT AN OFFICIAL AMFI API AND MAY LAG A DAY.")
NOTE = ("NAV IS AN END-OF-DAY VALUE PER UNIT, NOT A MARKET PRICE. RETURNS ARE WORKED OUT FROM THE NAV SERIES ALONE (NO EXIT LOAD, TAX OR "
        "SIP TIMING): HISTORICAL, NOT A FORECAST. UP TO 1Y = ABSOLUTE RETURN; OVER 1Y = CAGR (COMPOUND ANNUAL GROWTH RATE).")
PAYOUT_NOTE = ("THIS LOOKS LIKE AN IDCW/DIVIDEND PLAN: ITS NAV FALLS WHEN IT PAYS OUT, AND THE RETURNS BELOW LEAVE THE PAYOUTS OUT, "
               "SO THEY UNDERSTATE WHAT AN INVESTOR GOT. COMPARE GROWTH PLANS FOR A FAIR READING.")
SEARCH_NOTE = "ENTER OPENS THE FUND. EVERY WORD MUST APPEAR IN THE SCHEME NAME (ANY ORDER). DIRECT AND REGULAR PLANS ARE SEPARATE SCHEMES."

# (label, calendar offset). Months for 1M and up so "3Y" means the same calendar day three years back, not 1,095 days.
PERIODS: tuple[tuple[str, int, int], ...] = (  # label, days back, months back (exactly one of the two is non-zero)
    ("1D", 1, 0), ("1W", 7, 0), ("1M", 0, 1), ("3M", 0, 3), ("6M", 0, 6), ("1Y", 0, 12), ("3Y", 0, 36), ("5Y", 0, 60),
)
ABSOLUTE = "ABSOLUTE RETURN"
CAGR = "CAGR"

_DIGITS = re.compile(r"^\d+$")
_PAYOUT = re.compile(r"idcw|dividend", re.IGNORECASE)


class MfundError(Exception):
    """The upstream answer is not the shape documented above (or the user's words are unusable). `kind`: bad_request | unavailable."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


# --- what the user typed -------------------------------------------------------------------------------------------------
def norm_query(text: str | None) -> tuple[str, str]:
    """`("code", "122639")` for a scheme code, `("search", "parag parikh")` for words. Raises MfundError("bad_request") for unusable input."""
    q = re.sub(r"\s+", " ", text or "").strip()
    if _DIGITS.match(q):
        if not 4 <= len(q) <= 7:
            raise MfundError("bad_request", "A SCHEME CODE HAS 5 OR 6 DIGITS (E.G. MF 122639); TO SEARCH BY NAME USE WORDS (E.G. MF PARAG PARIKH)")
        return "code", str(int(q))
    if len(q) < MIN_WORDS_CHARS:
        raise MfundError("bad_request", "GIVE A FUND NAME OR SCHEME CODE, E.G. MF PARAG PARIKH OR MF 122639")
    if len(q) > MAX_QUERY:
        raise MfundError("bad_request", f"SEARCH IS LIMITED TO {MAX_QUERY} CHARACTERS")
    return "search", q


# --- search ------------------------------------------------------------------------------------------------------------
def parse_search(body: Any) -> list[dict[str, Any]]:
    """The `[{schemeCode, schemeName}]` answer as `[{code, name}]`. A malformed row raises (nothing is dropped silently)."""
    if not isinstance(body, list):
        raise MfundError("unavailable", "MFAPI SEARCH DID NOT ANSWER A LIST (CHANGED FORMAT?)")
    out = []
    for i, row in enumerate(body):
        try:
            code, name = int(row["schemeCode"]), str(row["schemeName"]).strip()
        except (KeyError, TypeError, ValueError) as e:
            raise MfundError("unavailable", f"MFAPI SEARCH ROW {i} HAS NO schemeCode/schemeName (CHANGED FORMAT?)") from e
        out.append({"code": code, "name": name})
    return out


def search_payload(query: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    """The panel's SEARCH payload: at most SEARCH_LIMIT rows plus the real total."""
    shown = items[:SEARCH_LIMIT]
    return {"mode": "SEARCH", "query": query, "items": shown, "total": len(items), "shown": len(shown), "note": SEARCH_NOTE, "source_note": SOURCE_NOTE}


# --- one fund ----------------------------------------------------------------------------------------------------------
def parse_fund(body: Any) -> dict[str, Any] | None:
    """The `/mf/<code>` answer as a dict with `dates` (ascending `date`s) and `navs` (floats). None = no such scheme (code 0, no rows).

    Raises MfundError("unavailable") when the answer is not the documented shape, a date or NAV cannot be read, a NAV is zero or negative, or two rows
    share a date: bad data is shown as an error, never smoothed over.
    """
    if not isinstance(body, dict) or not isinstance(body.get("meta"), dict) or not isinstance(body.get("data"), list):
        raise MfundError("unavailable", "MFAPI FUND ANSWER HAS NO meta/data (CHANGED FORMAT?)")
    meta, rows = body["meta"], body["data"]
    if not rows and not meta.get("scheme_code"):
        return None  # the documented "unknown scheme" answer
    if not rows:
        raise MfundError("unavailable", "MFAPI SENT A FUND WITH NO NAV ROWS")
    pairs: list[tuple[date, float]] = []
    for i, row in enumerate(rows):
        try:
            d = datetime.strptime(row["date"], "%d-%m-%Y").date()
            nav = float(row["nav"])
        except (KeyError, TypeError, ValueError) as e:
            raise MfundError("unavailable", f"MFAPI NAV ROW {i} IS UNREADABLE: {str(row)[:60]}") from e
        if not nav > 0:  # also catches NaN
            raise MfundError("unavailable", f"MFAPI NAV ROW {i} ({row['date']}) IS NOT A POSITIVE NUMBER: {row['nav']}")
        pairs.append((d, nav))
    pairs.sort()  # the service sends newest first; every calculation below wants oldest first
    dates = [p[0] for p in pairs]
    if len(set(dates)) != len(dates):
        raise MfundError("unavailable", "MFAPI SENT TWO NAVS FOR THE SAME DAY")
    try:
        code = int(meta["scheme_code"])
        name = str(meta["scheme_name"]).strip()
    except (KeyError, TypeError, ValueError) as e:
        raise MfundError("unavailable", "MFAPI FUND meta HAS NO scheme_code/scheme_name (CHANGED FORMAT?)") from e
    return {
        "code": code, "name": name,
        "fund_house": str(meta.get("fund_house") or "").strip(), "scheme_type": str(meta.get("scheme_type") or "").strip(),
        "category": str(meta.get("scheme_category") or "").strip(),
        "isin_growth": meta.get("isin_growth") or None, "isin_div": meta.get("isin_div_reinvestment") or None,
        "dates": dates, "navs": [p[1] for p in pairs],
    }


def minus_months(d: date, months: int) -> date:
    """`d` moved back `months` calendar months, the day clamped to the month's length (31 May minus 3 months = 29 Feb in a leap year)."""
    y, m = divmod(d.year * 12 + (d.month - 1) - months, 12)
    return date(y, m + 1, min(d.day, calendar.monthrange(y, m + 1)[1]))


def returns(dates: list[date], navs: list[float]) -> list[dict[str, Any]]:
    """1D 1W 1M 3M 6M 1Y 3Y 5Y returns from an ASCENDING NAV series.

    For each period the target date is the latest NAV date moved back by the period; the base is the nearest NAV ON OR BEFORE that date (the target
    may be a weekend or holiday). Up to 1Y the figure is the ABSOLUTE RETURN `latest / base - 1`; over 1Y it is the CAGR
    `(latest / base) ** (365 / elapsed days) - 1`, with the elapsed days counted between the base date actually used and the latest date, so a
    base a few days early is not flattered. When the history starts after the target date, or the nearest earlier NAV is more than MAX_GAP_DAYS
    before it, `pct` is None and `why` says why: the panel shows "-", never a made-up number.
    """
    last_d, last_nav = dates[-1], navs[-1]
    out = []
    for label, days, months in PERIODS:
        target = last_d - timedelta(days=days) if days else minus_months(last_d, months)
        kind = ABSOLUTE if label in ("1D", "1W", "1M", "3M", "6M", "1Y") else CAGR
        row: dict[str, Any] = {"period": label, "kind": kind, "target": target.isoformat(), "base_date": None, "base_nav": None, "pct": None, "why": None}
        i = bisect_right(dates, target) - 1  # index of the last date <= target; -1 = the history starts later
        if i < 0:
            row["why"] = f"HISTORY STARTS {dates[0].isoformat()}"
        elif (target - dates[i]).days > MAX_GAP_DAYS:
            row["why"] = f"NO NAV WITHIN {MAX_GAP_DAYS} DAYS BEFORE {target.isoformat()}"
        else:
            base_d, base_nav = dates[i], navs[i]
            ratio = last_nav / base_nav
            elapsed = (last_d - base_d).days
            row["base_date"], row["base_nav"] = base_d.isoformat(), base_nav
            row["pct"] = (ratio - 1.0) * 100.0 if kind == ABSOLUTE else (ratio ** (YEAR_DAYS / elapsed) - 1.0) * 100.0
        out.append(row)
    return out


def fund_payload(fund: dict[str, Any]) -> dict[str, Any]:
    """The panel's FUND payload from `parse_fund`'s dict: header facts, the return table and the NAV series (epoch seconds at 00:00 UTC, NAV)."""
    dates, navs = fund["dates"], fund["navs"]
    payout = bool(_PAYOUT.search(fund["name"]))
    return {
        "mode": "FUND", "code": fund["code"], "name": fund["name"], "fund_house": fund["fund_house"], "scheme_type": fund["scheme_type"],
        "category": fund["category"], "isin_growth": fund["isin_growth"], "isin_div": fund["isin_div"],
        "latest": {"date": dates[-1].isoformat(), "nav": navs[-1]}, "first_date": dates[0].isoformat(), "points": len(dates),
        "returns": returns(dates, navs), "t": [calendar.timegm(d.timetuple()) for d in dates], "v": navs,
        "payout_plan": payout, "note": NOTE + (" " + PAYOUT_NOTE if payout else ""), "source_note": SOURCE_NOTE,
    }
