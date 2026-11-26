"""TradingView's public stock scanner: a keyless source for the US screener (EQS) and market movers (MOV).

Added 2026-11-26 because api.nasdaq.com blocks OpenTerm's client (docs/DATA_LIMITS.md "Nasdaq blocks OpenTerm"). It sits
after Nasdaq and before the Yahoo screens in both orders: one call returns the whole US universe (Yahoo needs ~150) with
headquarters country, and it fills all five MOV tabs (Yahoo has no $-volume or Nasdaq-100 table).

`scanner.tradingview.com/america/scan` is the endpoint TradingView's own screener page calls. It takes a JSON POST
(columns, filters, sort, row range) and answers the matching rows, so a movers table is the same call sorted by another
column. It is unofficial and undocumented: it can change without notice, the same risk Yahoo and Nasdaq carry. No crumb,
cookie or bot check. Prices are delayed 15 minutes (`update_mode` = delayed_streaming_900).

Both parsers return exactly the shapes Nasdaq's do (`screener.screener_from_body`, `nasdaq.movers_from_body`): symbols in
screener spelling (`BRK/B`, preferreds `BAC^L`) and sectors in the Nasdaq names (`quantjobs/sectors.py` `from_tradingview`),
so EQS, COMP, ALPHA, QRY and the plain-English company list read it unchanged. Industries stay TradingView's own names.
"""

import asyncio
import re
from typing import Any, ClassVar

from ..models import Mover, Movers
from ..quantjobs.sectors import from_tradingview
from .base import MOVERS, Provider, ProviderError
from .http import UA
from .nasdaq import num
from .screener import COLUMNS, SCREENER, _index

URL = "https://scanner.tradingview.com/america/scan"

# The same universe Nasdaq's screener covers: the three US listing exchanges. (TradingView files NYSE Arca ETFs
# such as SPY under AMEX.) OTC names are left out.
EXCHANGES = {"left": "exchange", "operation": "in_range", "right": ["AMEX", "NASDAQ", "NYSE"]}
# Nasdaq's screener lists stocks only (common, preferred, ADRs), not ETFs or funds: "dr" is TradingView's ADR type.
STOCKS = {"left": "type", "operation": "in_range", "right": ["stock", "dr"]}

# Column order matters: the parsers read rows by position (TradingView answers each row as a plain list `d`).
SCREENER_COLS = ["name", "description", "close", "change_abs", "change", "volume", "market_cap_basic",
                 "country", "sector", "industry", "subtype"]
MOVER_COLS = ["name", "description", "close", "change_abs", "change", "volume"]

MOVER_ROWS = 10  # Nasdaq's tables have 10 rows each; matching it keeps MOV the same whichever source answers.
NDX = {"symbolset": ["SYML:NASDAQ;NDX"]}  # TradingView's own list of the Nasdaq-100 members (about 101 symbols).


def _sorted(by: str, order: str) -> dict[str, Any]:
    return {"columns": MOVER_COLS, "filter": [EXCHANGES], "sort": {"sortBy": by, "sortOrder": order},
            "range": [0, MOVER_ROWS]}


# One request per MOV tab. Like Nasdaq's tables these include ETFs (SPY tops dollar volume) and penny stocks.
MOVER_SCANS: dict[str, dict[str, Any]] = {
    "GAINERS": _sorted("change", "desc"),
    "LOSERS": _sorted("change", "asc"),
    "ACTIVE": _sorted("volume", "desc"),
    "DOLLAR": _sorted("Value.Traded", "desc"),  # Value.Traded = price x share volume for the session
    # All members; the parser keeps the 10 that moved most either way (the scanner cannot sort by absolute change).
    "NDX100": {"columns": MOVER_COLS, "symbols": NDX, "range": [0, 200]},
}
SCREENER_SCAN: dict[str, Any] = {"columns": SCREENER_COLS, "filter": [EXCHANGES, STOCKS], "range": [0, 20000]}

_PREFERRED = re.compile(r"/P([A-Z]*)$")


def nasdaq_style(name: str) -> str:
    """TradingView ticker -> the spelling Nasdaq's screener uses, so EQS shows one convention whichever source answers.

    Class shares: BRK.B -> BRK/B. Preferred series: PCG/PB -> PCG^B (a bare /P becomes a bare ^, as in Nasdaq's PHXE^).
    """
    s = name.strip().upper()
    m = _PREFERRED.search(s)
    if m:
        return s[: m.start()] + "^" + m.group(1)
    return s.replace(".", "/")


def _rows(body: Any) -> list[list[Any]]:
    """The `d` lists of a scan answer; a scan error (an unknown column, say) fails loudly."""
    if not isinstance(body, dict):
        raise ProviderError("unavailable", "scanner answered no JSON object")
    if body.get("error"):
        raise ProviderError("unavailable", f"scanner error: {body['error']}")
    return [r["d"] for r in body.get("data") or [] if isinstance(r, dict) and isinstance(r.get("d"), list)]


def screener_from_scan(body: Any, source: str, as_of: float) -> dict:
    """Same payload as `screener.screener_from_body`. TradingView has no IPO year, so that column stays empty.

    TradingView gives every preferred series its issuer's market cap (each of Bank of America's ~20 series shows
    about $335B), which would flood a market-cap filter with copies of one company. That number is not the series'
    own, so preferreds get no market cap, like Nasdaq's.
    """
    sectors: list[str] = [""]
    industries: list[str] = [""]
    countries: list[str] = [""]
    lk_s, lk_i, lk_c = {"": 0}, {"": 0}, {"": 0}
    rows = []
    for sym, name, last, chg, pct, vol, cap, country, sector, industry, subtype in _rows(body):
        if not sym:
            continue
        v, c = num(vol), None if subtype == "preferred" else num(cap)
        rows.append([
            nasdaq_style(sym),
            " ".join((name or "").split()),
            num(last), num(chg), num(pct),
            int(v) if v is not None else None,
            c if c else None,  # same rule as Nasdaq's: no or zero market cap is "unknown", not 0
            _index(countries, lk_c, country),
            None,  # IPO year: not in the scanner
            _index(sectors, lk_s, from_tradingview(sector, industry)),  # Nasdaq's sector names; "" if unknown
            _index(industries, lk_i, industry),
        ])
    if not rows:
        raise ProviderError("not_found", "scanner returned no rows")
    return {
        "columns": COLUMNS, "rows": rows, "sectors": sectors, "industries": industries, "countries": countries,
        "count": len(rows), "as_of_text": None, "market": "US", "source": source, "as_of": as_of,
    }


def _mover(d: list[Any]) -> Mover:
    sym, name, last, chg, pct, vol = d
    return Mover(symbol=nasdaq_style(sym), name=" ".join((name or "").split()) or None, price=num(last),
                 change=num(chg), change_pct=num(pct), volume=num(vol))


def movers_from_scans(bodies: dict[str, Any], source: str, as_of: float) -> Movers:
    """One scan answer per tab (keys of MOVER_SCANS) -> the same Movers Nasdaq's parser builds.

    The scanner gives no "data as of" text, so `table_as_of` is empty: MOV shows the source with no time (STALE + age once the cache is old).
    """
    tables: dict[str, list[Mover]] = {}
    for tab in MOVER_SCANS:
        rows = [_mover(d) for d in _rows(bodies.get(tab)) if d and d[0]]
        if tab == "NDX100":
            rows.sort(key=lambda m: abs(m.change_pct or 0.0), reverse=True)
            rows = rows[:MOVER_ROWS]
        tables[tab] = rows
    if not any(tables.values()):
        raise ProviderError("not_found", "no movers")
    return Movers(tables=tables, table_as_of=dict.fromkeys(tables), as_of_text=None, market_time=None,
                  source=source, as_of=as_of)


class TradingViewProvider(Provider):
    name = "tradingview"
    label = "TradingView stock scanner"
    capabilities = frozenset({SCREENER, MOVERS})
    markets = "US-listed stocks (NASDAQ, NYSE, AMEX); screener universe and market movers"
    terms = "Unofficial endpoint of TradingView's public screener; personal use. Delayed 15 min. May change without notice."
    # MOV sends its five scans at once; the burst of 6 lets them all go without waiting.
    rate = (1.0, 6)
    max_wait = 1.0
    timeout = 20.0  # the whole universe is about 1 MB, about 1.5-2 s measured from India
    headers: ClassVar[dict[str, str]] = {"User-Agent": UA, "Accept": "application/json"}

    async def screener(self) -> dict:
        return screener_from_scan(await self.post_json(URL, SCREENER_SCAN), self.source, self.now())

    async def movers(self) -> Movers:
        tabs = list(MOVER_SCANS)
        # The five tabs are independent requests, so they run side by side (about 0.6 s each).
        answers = await asyncio.gather(*(self.post_json(URL, MOVER_SCANS[t]) for t in tabs))
        return movers_from_scans(dict(zip(tabs, answers, strict=True)), self.source, self.now())

    async def probe(self) -> None:
        # One row, not the 1 MB universe (the scheduler probes a tripped provider every 30 s).
        if not _rows(await self.post_json(URL, {"columns": ["name"], "filter": [EXCHANGES], "range": [0, 1]})):
            raise ProviderError("unavailable", "probe returned no rows")
