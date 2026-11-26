"""Yahoo Finance screens: the US equity universe (EQS) and market movers (MOV), keyless.

Added 2026-11-26 because api.nasdaq.com blocks OpenTerm's client (docs/DATA_LIMITS.md "Nasdaq blocks OpenTerm"). Nasdaq stays
first in both orders (it has country and the $-volume / Nasdaq-100 tables); these answer when it is down.

Screener: Yahoo's screener (`v1/finance/screener`, POST, needs the session crumb the quote adapter already uses) answers at most
250 rows per call and its rows carry no sector or industry. So the adapter asks once per Yahoo industry (145 of them, listed by
the `fields` endpoint together with each one's sector) and pages through each: about 150 calls, ~7 s measured with 6 at a time.
Every row then knows its sector and industry from the query that returned it. Stocks Yahoo files under no industry are not in
any answer (about 600 of 7,400, mostly shells and new listings). Yahoo has no headquarters country: that column is blank.

The payload is the Nasdaq screener's own shape (`providers/screener.py` COLUMNS) so EQS, COMP, ALPHA, QRY and the plain-English
company list read it unchanged: symbols in screener spelling (`BRK/B`, preferreds `BAC^L`) and sectors in the Nasdaq names
(`quantjobs/sectors.py`).

Movers: Yahoo's predefined screens `day_gainers`, `day_losers`, `most_actives` (no crumb needed). They are Yahoo's own
definitions (US, larger companies only), not Nasdaq's tables; there is no $-volume or Nasdaq-100 table.
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from typing import Any

from ..models import Mover, Movers
from ..quantjobs.sectors import from_yahoo_name
from .base import MOVERS, ProviderError
from .http import SEARCH_BASE as YH
from .screener import COLUMNS, SCREENER
from .yahoo import YahooProvider

PAGE = 250  # Yahoo's largest page (size 1000 answers 400)
CONCURRENT = 6
# US listings the Nasdaq screener covered: Nasdaq Global Select / Global / Capital Market, NYSE, NYSE American, NYSE Arca, Cboe BZX.
EXCHANGES = ("NMS", "NGM", "NCM", "NAS", "NYQ", "ASE", "PCX", "BTS")
# Yahoo predefined screen -> MOV tab.
PREDEFINED = {"day_gainers": "GAINERS", "day_losers": "LOSERS", "most_actives": "ACTIVE"}

_PREFERRED = re.compile(r"^([A-Z]+)-P([A-Z]+)$")  # BAC-PL -> BAC^L (the screener spelling of a preferred series)
_CLASS = re.compile(r"^([A-Z]+)-([A-Z])$")  # BRK-B -> BRK/B


def screener_symbol(yahoo: str) -> str:
    """Yahoo spelling -> the Nasdaq screener spelling every reader of the payload expects (`nlIndex.toYahoo` turns it back)."""
    s = yahoo.strip().upper()
    if m := _PREFERRED.match(s):
        return f"{m[1]}^{m[2]}"
    if m := _CLASS.match(s):
        return f"{m[1]}/{m[2]}"
    return s


def industry_query(industry: str, offset: int) -> dict:
    """The screener request body for one industry page, largest companies first."""
    return {
        "size": PAGE, "offset": offset, "sortField": "intradaymarketcap", "sortType": "DESC", "quoteType": "EQUITY",
        "userId": "", "userIdType": "guid",
        "query": {"operator": "and", "operands": [
            {"operator": "eq", "operands": ["region", "us"]},
            {"operator": "or", "operands": [{"operator": "eq", "operands": ["exchange", e]} for e in EXCHANGES]},
            {"operator": "eq", "operands": ["industry", industry]},
        ]},
    }


def industries_from_fields(body: Any) -> list[tuple[str, str]]:
    """The `fields` answer -> [(industry, Yahoo sector)]. Each industry label names its sector (`dependentFilterLabel`)."""
    try:
        labels = body["finance"]["result"][0]["fields"]["industry"]["labels"]
    except (KeyError, IndexError, TypeError) as e:
        raise ProviderError("unavailable", "unexpected Yahoo screener fields answer") from e
    # The query value is the label's own criteria operand (Yahoo writes "Software—Infrastructure" with an em dash there).
    out = []
    for lab in labels:
        operands = (lab.get("criteria") or {}).get("operands") or []
        value = operands[1] if len(operands) == 2 else lab.get("displayName")
        if value:
            out.append((value, lab.get("dependentFilterLabel") or ""))
    if not out:
        raise ProviderError("unavailable", "Yahoo listed no industries")
    return out


def screen_result(body: Any) -> dict:
    """A screener answer's one result ({total, quotes}); Yahoo's own error object becomes an `unavailable` error."""
    fin = (body or {}).get("finance") if isinstance(body, dict) else None
    res = (fin or {}).get("result")
    if not res:
        raise ProviderError("unavailable", f"Yahoo screener error: {((fin or {}).get('error') or {}).get('code') or 'no result'}")
    return res[0]


def _year(ms: Any) -> int | None:
    return datetime.fromtimestamp(ms / 1000, UTC).year if isinstance(ms, int | float) and ms > 0 else None


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, int | float) else None


def build_screener(pages: list[tuple[str, str, list[dict]]], source: str, as_of: float) -> dict:
    """[(industry, Yahoo sector, quotes)] -> the columnar screener payload (same shape as `screener.screener_from_body`)."""
    sectors: list[str] = [""]
    industries: list[str] = [""]
    lk_s: dict[str, int] = {"": 0}
    lk_i: dict[str, int] = {"": 0}

    def index(table: list[str], lookup: dict[str, int], value: str) -> int:
        if value not in lookup:
            lookup[value] = len(table)
            table.append(value)
        return lookup[value]

    seen: set[str] = set()
    rows = []
    for industry, sector, quotes in pages:
        s_i = index(sectors, lk_s, from_yahoo_name(sector))
        i_i = index(industries, lk_i, industry)
        for q in quotes:
            sym = screener_symbol(str(q.get("symbol") or ""))
            if not sym or sym in seen:
                continue
            seen.add(sym)
            vol, cap = _num(q.get("regularMarketVolume")), _num(q.get("marketCap"))
            rows.append([
                sym,
                " ".join(str(q.get("longName") or q.get("shortName") or q.get("displayName") or "").split()),
                _num(q.get("regularMarketPrice")),
                _num(q.get("regularMarketChange")),
                _num(q.get("regularMarketChangePercent")),  # already in percent (1.5 = 1.5 %), like Nasdaq's pctchange
                int(vol) if vol is not None else None,
                cap or None,  # 0 means "none" (funds, units), as in the Nasdaq parser
                0,  # country: Yahoo has no headquarters country
                _year(q.get("firstTradeDateMilliseconds")),  # first trading day's year, Yahoo's nearest thing to an IPO year
                s_i,
                i_i,
            ])
    if not rows:
        raise ProviderError("not_found", "Yahoo screener returned no rows")
    rows.sort(key=lambda r: -(r[6] or 0))
    return {
        "columns": COLUMNS, "rows": rows, "sectors": sectors, "industries": industries, "countries": [""],
        "count": len(rows), "as_of_text": None, "market": "US", "source": source, "as_of": as_of,
    }


def movers_from_screens(bodies: dict[str, Any], source: str, as_of: float) -> Movers:
    """{predefined screen id: answer} -> Movers with the GAINERS / LOSERS / ACTIVE tabs Yahoo has."""
    tables: dict[str, list[Mover]] = {}
    newest = 0
    for scr, tab in PREDEFINED.items():
        rows = []
        for q in screen_result(bodies[scr]).get("quotes") or []:
            if not q.get("symbol"):
                continue
            rows.append(Mover(symbol=str(q["symbol"]).upper(), name=q.get("shortName") or q.get("longName"),
                              price=_num(q.get("regularMarketPrice")), change=_num(q.get("regularMarketChange")),
                              change_pct=_num(q.get("regularMarketChangePercent")), volume=_num(q.get("regularMarketVolume"))))
            t = q.get("regularMarketTime")
            if isinstance(t, int) and t > newest:
                newest = t
        tables[tab] = rows
    if not any(tables.values()):
        raise ProviderError("not_found", "no movers")
    return Movers(tables=tables, table_as_of={}, as_of_text=None, market_time=newest or None, source=source, as_of=as_of)


class YahooScreenerProvider(YahooProvider):
    name = "yahoo_screener"
    label = "Yahoo Finance screener (unofficial)"
    capabilities = frozenset({SCREENER})
    markets = "US-listed stocks (Nasdaq, NYSE, NYSE American, Arca, Cboe) with Yahoo's sector and industry; no country"
    terms = "Unofficial endpoint; personal use. About 150 requests per refresh (one per industry page). May break without notice."
    rate = (20.0, 20)  # one refresh is a burst of ~150 calls; the semaphore keeps 6 in flight
    max_wait = 10.0
    timeout = 15.0

    def supports(self, capability: str, symbol: str | None = None) -> bool:
        return capability in self.capabilities

    async def _post(self, body: dict) -> dict:
        """One screener call; a 401 (crumb expired) fetches a new crumb once, like `profile` does."""
        for attempt in range(2):
            crumb = await self._get_crumb(refresh=attempt > 0)
            try:
                return screen_result(await self.post_json(f"{YH}/v1/finance/screener", body,
                                                          params={"crumb": crumb, "formatted": "false", "lang": "en-US", "region": "US"}))
            except ProviderError as e:
                if attempt == 0 and "401" in str(e):
                    continue
                raise
        raise AssertionError("unreachable")

    async def _industry(self, industry: str, sector: str, gate: asyncio.Semaphore) -> tuple[str, str, list[dict]]:
        async with gate:
            first = await self._post(industry_query(industry, 0))
        quotes = list(first.get("quotes") or [])
        total = int(first.get("total") or 0)
        for offset in range(PAGE, total, PAGE):
            async with gate:
                quotes += (await self._post(industry_query(industry, offset))).get("quotes") or []
        return industry, sector, quotes

    async def screener(self) -> dict:
        crumb = await self._get_crumb()
        fields = await self.get_json(f"{YH}/v1/finance/screener/instrument/equity/fields",
                                     {"lang": "en-US", "region": "US", "category": "sector_industry", "crumb": crumb})
        gate = asyncio.Semaphore(CONCURRENT)
        # No return_exceptions: one failed industry fails the whole refresh (a silently missing industry would look like a
        # smaller market). The cache keeps serving the last full universe, labelled STALE.
        pages = await asyncio.gather(*(self._industry(i, s, gate) for i, s in industries_from_fields(fields)))
        return build_screener(list(pages), self.source, self.now())

    async def probe(self) -> None:
        await self._get_crumb()


class YahooMoversProvider(YahooProvider):
    name = "yahoo_movers"
    label = "Yahoo Finance predefined screens (unofficial)"
    capabilities = frozenset({MOVERS})
    markets = "US market movers: Yahoo's day gainers, day losers and most active (larger companies only)"
    terms = "Unofficial endpoint; personal use. Yahoo's own screen definitions, delayed. No $-volume or Nasdaq-100 table."

    def supports(self, capability: str, symbol: str | None = None) -> bool:
        return capability in self.capabilities

    async def _screen(self, scr: str) -> Any:
        return await self.get_json(f"{YH}/v1/finance/screener/predefined/saved", {"scrIds": scr, "count": 100, "formatted": "false"})

    async def movers(self) -> Movers:
        bodies = await asyncio.gather(*(self._screen(s) for s in PREDEFINED))
        return movers_from_screens(dict(zip(PREDEFINED, bodies, strict=True)), self.source, self.now())

    async def probe(self) -> None:
        await self._screen("day_gainers")
