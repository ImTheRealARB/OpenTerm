"""Which symbols a scan or MRR covers (pure parsing; the routes resolve the list).

Universe words:
    SPX NDX DJI RUT MID (SP500 = SPX)   index members, from the proxy ETF's SEC N-PORT filing (the MEMB function)
    MEMB:<ETF>                          the holdings of any ETF that files N-PORT
    WL:<NAME>                           a saved watchlist
    LIST:AAPL,MSFT,...                  an explicit list (the SCAN panel also sends an EQS screen result this way)
    NIFTY50 NIFTY500                    NSE index members, downloaded on this computer from NSE Indices (never shipped)
"""

from __future__ import annotations

import re

from ..research.fund_parse import INDEX_PROXY
from ..symbols import resolve

MAX_SYMBOLS = 600  # S&P 500 or NIFTY 500 plus room; a bigger list would take Yahoo many minutes cold
ALIASES = {"SP500": "SPX", "S&P500": "SPX", "NASDAQ100": "NDX", "DOW": "DJI", "RUSSELL2000": "RUT"}
NIFTY = {"NIFTY50": "ind_nifty50list.csv", "NIFTY500": "ind_nifty500list.csv"}
SYMBOL_RE = re.compile(r"^[A-Z0-9^][A-Z0-9.\-=^]{0,23}$")


class UniverseError(ValueError):
    """Shown to the user as is."""


USAGE = ("UNIVERSE: SPX NDX DJI RUT MID, MEMB:<ETF>, WL:<NAME>, LIST:SYM,SYM,..., NIFTY50 OR NIFTY500")


def parse(token: str) -> tuple[str, str]:
    """Universe word -> (kind, value): ("memb", "SPY"), ("wl", "TECH"), ("list", "AAPL,MSFT"), ("nifty", "NIFTY50")."""
    raw = (token or "").strip()
    u = ALIASES.get(raw.upper(), raw.upper())
    if u in INDEX_PROXY:
        return "memb", u
    if u in NIFTY:
        return "nifty", u
    head, _, rest = u.partition(":")
    if head == "MEMB" and rest.isalpha() and len(rest) <= 5:
        return "memb", rest
    if head == "WL" and rest:
        return "wl", rest
    if head == "LIST" and rest:
        return "list", rest
    raise UniverseError(f"UNKNOWN UNIVERSE {raw[:24]}: {USAGE}")


def clean(symbols: list[str]) -> list[str]:
    """Resolve aliases, drop blanks and duplicates (first seen wins), refuse junk and oversized lists."""
    out: list[str] = []
    for s in symbols:
        sym = resolve(str(s).strip().upper())
        if not sym:
            continue
        if not SYMBOL_RE.match(sym):
            raise UniverseError(f"BAD SYMBOL {str(s)[:24]}")
        if sym not in out:
            out.append(sym)
    if not out:
        raise UniverseError("THE UNIVERSE HAS NO SYMBOLS")
    if len(out) > MAX_SYMBOLS:
        raise UniverseError(f"{len(out)} SYMBOLS, AT MOST {MAX_SYMBOLS}")
    return out


def memb_members(payload: dict) -> list[tuple[str, float | None]]:
    """(symbol, weight) from a MEMB payload's constituents section; rows whose name matched no ticker are skipped."""
    rows = (payload.get("sections") or [{}])[0].get("rows") or []
    return [(r["symbol"], r.get("weight")) for r in rows if r.get("symbol")]


def nifty_rows(csv_text: str) -> list[dict]:
    """The same CSV -> [{symbol, name, industry}] for the IMAP NIFTY heat map (grouped by the list's own Industry column).
    A missing Company Name / Industry column leaves those fields empty rather than failing the map."""
    lines = [ln.strip() for ln in csv_text.splitlines() if ln.strip()]
    if not lines:
        raise UniverseError("NSE INDICES SENT AN EMPTY LIST")
    head = [h.strip().lower() for h in lines[0].split(",")]
    if "symbol" not in head:
        raise UniverseError("NSE INDICES' LIST HAS NO SYMBOL COLUMN (THE FILE FORMAT CHANGED)")
    k = head.index("symbol")
    ni = head.index("company name") if "company name" in head else None
    ii = head.index("industry") if "industry" in head else None
    out = []
    for ln in lines[1:]:
        cells = [c.strip() for c in ln.split(",")]
        if len(cells) <= k or not cells[k]:
            continue
        out.append({
            "symbol": cells[k].upper() + ".NS",
            "name": cells[ni] if ni is not None and len(cells) > ni else "",
            "industry": (cells[ii].upper() if ii is not None and len(cells) > ii and cells[ii] else "UNCLASSIFIED"),
        })
    return out


def nifty_members(csv_text: str) -> list[str]:
    """NSE Indices' constituent CSV (Company Name, Industry, Symbol, Series, ISIN Code) -> Yahoo symbols (`.NS`)."""
    lines = [ln.strip() for ln in csv_text.splitlines() if ln.strip()]
    if not lines:
        raise UniverseError("NSE INDICES SENT AN EMPTY LIST")
    head = [h.strip().lower() for h in lines[0].split(",")]
    if "symbol" not in head:
        raise UniverseError("NSE INDICES' LIST HAS NO SYMBOL COLUMN (THE FILE FORMAT CHANGED)")
    k = head.index("symbol")
    out = []
    for ln in lines[1:]:
        cells = ln.split(",")
        if len(cells) > k and cells[k].strip():
            out.append(cells[k].strip().upper() + ".NS")
    return out


def range_for(max_period: int) -> str:
    """Daily history long enough for the rule's slowest indicator to warm up (about 1.5x its period in trading days)."""
    if max_period <= 150:
        return "1Y"
    if max_period <= 320:
        return "2Y"
    return "5Y"
