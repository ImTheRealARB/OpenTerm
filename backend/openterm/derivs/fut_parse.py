"""Pure parsers and tables for the futures and policy functions (CT, WIRP, COT), spec decisions L and M. No I/O."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

MONTH_CODES = {"F": 1, "G": 2, "H": 3, "J": 4, "K": 5, "M": 6, "N": 7, "Q": 8, "U": 9, "V": 10, "X": 11, "Z": 12}
MONTH_NAMES = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
CODE_OF_MONTH = {v: k for k, v in MONTH_CODES.items()}

#: root -> (Yahoo exchange suffix, month cycle as month numbers, contracts to list, first contract: "next" calendar month or "current")
ALL = tuple(range(1, 13))
QUARTERLY = (3, 6, 9, 12)
ROOTS: dict[str, tuple[str, tuple[int, ...], int, str, str]] = {
    "CL": ("NYM", ALL, 15, "next", "WTI CRUDE OIL"),
    "BZ": ("NYM", ALL, 12, "next", "BRENT CRUDE"),
    "NG": ("NYM", ALL, 15, "next", "NATURAL GAS"),
    "HO": ("NYM", ALL, 12, "next", "HEATING OIL"),
    "RB": ("NYM", ALL, 12, "next", "RBOB GASOLINE"),
    "GC": ("CMX", (2, 4, 6, 8, 10, 12), 8, "next", "GOLD"),
    "SI": ("CMX", (3, 5, 7, 9, 12), 6, "next", "SILVER"),
    "HG": ("CMX", (3, 5, 7, 9, 12), 6, "next", "COPPER"),
    "ES": ("CME", QUARTERLY, 4, "next", "E-MINI S&P 500"),
    "NQ": ("CME", QUARTERLY, 4, "next", "E-MINI NASDAQ-100"),
    "RTY": ("CME", QUARTERLY, 4, "next", "E-MINI RUSSELL 2000"),
    "6E": ("CME", QUARTERLY, 4, "next", "EURO FX"),
    "ZT": ("CBT", QUARTERLY, 3, "next", "2-YEAR NOTE"),
    "ZF": ("CBT", QUARTERLY, 3, "next", "5-YEAR NOTE"),
    "ZN": ("CBT", QUARTERLY, 3, "next", "10-YEAR NOTE"),
    "ZB": ("CBT", QUARTERLY, 3, "next", "30-YEAR BOND"),
    "ZQ": ("CBT", ALL, 13, "current", "30-DAY FED FUNDS"),
    "ZC": ("CBT", (3, 5, 7, 9, 12), 6, "next", "CORN"),
    "ZS": ("CBT", (1, 3, 5, 7, 8, 9, 11), 7, "next", "SOYBEANS"),
    "ZW": ("CBT", (3, 5, 7, 9, 12), 6, "next", "WHEAT"),
}


def contract_symbols(root: str, year: int, month: int) -> list[tuple[str, int, int]]:
    """[(Yahoo symbol, year, month)] for `root` from (year, month) (the month of 'today'), per the root table."""
    suffix, cycle, count, start, _ = ROOTS[root]
    y, m = year, month + (0 if start == "current" else 1)
    if m > 12:
        y, m = y + 1, 1
    out = []
    while len(out) < count:
        if m in cycle:
            out.append((f"{root}{CODE_OF_MONTH[m]}{y % 100:02d}.{suffix}", y, m))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def label(year: int, month: int) -> str:
    return f"{MONTH_NAMES[month - 1]} {year}"


def parse_contract(body: Any, symbol: str, source: str) -> dict | None:
    """One v8/chart answer -> the contract quote. None when Yahoo has no such contract (error object or no price)."""
    try:
        res = body["chart"]["result"][0]
        meta = res["meta"]
    except (KeyError, IndexError, TypeError):
        return None
    price = meta.get("regularMarketPrice")
    if price is None:
        return None
    closes: list[float] = []
    try:
        closes = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
    except (KeyError, IndexError, TypeError):
        pass
    change = meta.get("fulldayChange")
    pct = meta.get("fulldayChangePercent")
    if change is None and len(closes) >= 2:
        change = float(price) - closes[-2]
        pct = change / closes[-2] * 100.0 if closes[-2] else None
    return {"symbol": symbol, "price": float(price), "change": change, "change_pct": pct,
            "volume": meta.get("regularMarketVolume"), "name": meta.get("shortName") or meta.get("longName"),
            "time": meta.get("regularMarketTime"), "source": source}


# --- FOMC calendar ------------------------------------------------------------------------------------------------------
_YEAR = re.compile(r"(\d{4})\s*FOMC\s*Meetings")
_MEETING = re.compile(r"fomc-meeting__month[^>]*><strong>([\w/]+)</strong>.*?fomc-meeting__date[^>]*>\s*([\d]+)(?:-(\d+))?", re.DOTALL)


def parse_fomc(html: str) -> list[str]:
    """Decision dates (the last day of each two-day meeting), YYYY-MM-DD ascending. Month cells like 'Oct/Nov' use the last month."""
    marks = [(m.start(), m.group(1)) for m in _YEAR.finditer(html)]
    out: list[str] = []
    for i, (pos, year) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(html)
        for m in _MEETING.finditer(html[pos:end]):
            month = m.group(1).split("/")[-1]
            day = int(m.group(3) or m.group(2))
            try:
                out.append(f"{year}-{datetime.strptime(month, '%B').month:02d}-{day:02d}")
            except ValueError:
                continue
    return sorted(set(out))


# --- CFTC legacy futures-only report ------------------------------------------------------------------------------------
CFTC_FIELDS = ",".join([  # noqa: FLY002
    "report_date_as_yyyy_mm_dd", "market_and_exchange_names", "cftc_contract_market_code", "contract_units", "open_interest_all",
    "noncomm_positions_long_all", "noncomm_positions_short_all", "noncomm_postions_spread_all", "comm_positions_long_all",
    "comm_positions_short_all", "nonrept_positions_long_all", "nonrept_positions_short_all", "change_in_open_interest_all",
    "change_in_noncomm_long_all", "change_in_noncomm_short_all", "change_in_comm_long_all", "change_in_comm_short_all",
    "change_in_nonrept_long_all", "change_in_nonrept_short_all", "traders_tot_all"])

#: alias -> CFTC contract market code (curated; anything else is a substring search of the market names)
COT_ALIASES = {
    "ES": "13874A", "SPX": "13874A", "SP500": "13874A", "NQ": "209742", "NASDAQ": "209742", "CL": "067651", "WTI": "067651",
    "CRUDE": "067651", "OIL": "067651", "GC": "088691", "GOLD": "088691", "SI": "084691", "SILVER": "084691", "HG": "085692",
    "COPPER": "085692", "NG": "023651", "ZN": "043602", "TY": "043602", "ZB": "020601", "ZF": "044601", "ZT": "042601",
    "EUR": "099741", "EURUSD": "099741", "JPY": "097741", "USDJPY": "097741", "GBP": "096742", "ZC": "002602", "CORN": "002602",
    "ZS": "005602", "SOYBEANS": "005602", "ZW": "001602", "WHEAT": "001602", "BTC": "133741", "BITCOIN": "133741", "VIX": "1170E1",
}


def _i(row: dict, key: str) -> int:
    try:
        return int(float(row.get(key) or 0))
    except (TypeError, ValueError):
        return 0


def cot_row(row: dict) -> dict:
    """One weekly report as ints with derived nets."""
    out = {"date": str(row["report_date_as_yyyy_mm_dd"])[:10], "market": row.get("market_and_exchange_names"),
           "code": row.get("cftc_contract_market_code"), "units": row.get("contract_units"), "oi": _i(row, "open_interest_all"),
           "chg_oi": _i(row, "change_in_open_interest_all"), "traders": _i(row, "traders_tot_all")}
    for tag, long_k, short_k, cl_k, cs_k in (("nc", "noncomm_positions_long_all", "noncomm_positions_short_all",
                                               "change_in_noncomm_long_all", "change_in_noncomm_short_all"),
                                              ("c", "comm_positions_long_all", "comm_positions_short_all",
                                               "change_in_comm_long_all", "change_in_comm_short_all"),
                                              ("nr", "nonrept_positions_long_all", "nonrept_positions_short_all",
                                               "change_in_nonrept_long_all", "change_in_nonrept_short_all")):
        out[f"{tag}_long"], out[f"{tag}_short"] = _i(row, long_k), _i(row, short_k)
        out[f"{tag}_net"] = out[f"{tag}_long"] - out[f"{tag}_short"]
        out[f"{tag}_chg_long"], out[f"{tag}_chg_short"] = _i(row, cl_k), _i(row, cs_k)
        out[f"{tag}_chg_net"] = out[f"{tag}_chg_long"] - out[f"{tag}_chg_short"]
    return out
