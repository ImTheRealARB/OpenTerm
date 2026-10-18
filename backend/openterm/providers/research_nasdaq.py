"""Nasdaq.com public API for the Phase 13 corporate-data functions: dividends (DVD, CACS), IPO calendar (IPO), FINRA
short interest (SI). Same host, headers and rate as the quote adapter (`nasdaq`), under its own name so its health shows
separately. Plain US tickers only; the IPO calendar needs no symbol."""

from __future__ import annotations

from ..research import corp_parse as cp
from .base import ProviderError
from .nasdaq import BASE, NasdaqProvider

DIVIDENDS = "dividends"
IPO = "ipo"
SHORT_INTEREST = "short_interest"
EARNINGS_HISTORY = "earnings_history"


class NasdaqResearchProvider(NasdaqProvider):
    name = "nasdaq_research"
    label = "Nasdaq.com research data"
    capabilities = frozenset({DIVIDENDS, IPO, SHORT_INTEREST, EARNINGS_HISTORY})
    markets = "US dividends with declaration/record/pay dates, IPO calendar, FINRA short interest (plain US tickers)"
    terms = "Public website API; personal use. Undocumented: may change. Short interest is FINRA's, twice a month."

    async def dividends(self, symbol: str) -> dict:
        data = await self._get(symbol, "dividends", {})
        return cp.nasdaq_dividends({"data": data}, self.source)

    async def short_interest(self, symbol: str) -> dict:
        body = await self.get_json(f"{BASE}/{symbol}/short-interest", {"assetClass": "stocks"})
        return cp.nasdaq_short_interest(body, self.source)

    async def earnings_history(self, symbol: str) -> dict:
        body = await self.get_json(f"https://api.nasdaq.com/api/company/{symbol}/earnings-surprise")
        return cp.nasdaq_earnings_history(body, self.source)

    async def ipo(self, month: str) -> dict:
        body = await self.get_json("https://api.nasdaq.com/api/ipo/calendar", {"date": month})
        return cp.ipo_tables(body, self.source)

    async def probe(self) -> None:
        if not (await self.ipo("2026-01")):
            raise ProviderError("unavailable", "probe returned no data")
