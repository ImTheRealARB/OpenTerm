"""Yahoo quoteSummary modules for the Phase 13 research functions (EE, EEO, ANR, MGMT, SI fallback, ETF info) and the
chart `events` feed for dividends and splits. A subclass of the ownership adapter so it reuses the cookie + crumb flow,
under its own name (`yahoo_research`) so its health shows separately on SOURCES.
"""

from __future__ import annotations

from typing import Any

from ..research import corp_parse as cp
from ..research import yahoo_parse as yp
from .base import ProviderError
from .http import BASE
from .ownership import YahooOwnProvider

ESTIMATES = "estimates"
RATINGS = "ratings"
OFFICERS = "officers"
KEYSTATS = "keystats"
FUND_INFO = "fund_info"
CORP_EVENTS = "corp_events"
DIVIDENDS = "dividends"
SPLITS = "splits"
SHORT_INTEREST = "short_interest"
SURPRISES = "surprises"


class YahooResearchProvider(YahooOwnProvider):
    name = "yahoo_research"
    label = "Yahoo Finance research (unofficial)"
    capabilities = frozenset({ESTIMATES, RATINGS, OFFICERS, KEYSTATS, FUND_INFO, CORP_EVENTS, DIVIDENDS, SPLITS, SHORT_INTEREST,
                              SURPRISES})
    markets = "Analyst estimates and ratings, officers, key statistics, fund profile, dividend and split events; mostly US"
    terms = "Unofficial quoteSummary and chart endpoints; personal use. Consensus data is Yahoo's aggregation."

    async def estimates(self, symbol: str) -> dict:
        return yp.estimates(symbol, await self._summary(symbol, "earningsTrend,earningsHistory"), self.source)

    async def eeo(self, symbol: str) -> dict:
        return yp.revisions_and_surprises(symbol, await self._summary(symbol, "earningsTrend,earningsHistory"), self.source)

    async def surprises(self, symbol: str) -> dict:
        return await self.eeo(symbol)

    async def ratings(self, symbol: str) -> dict:
        r = await self._summary(symbol, "recommendationTrend,upgradeDowngradeHistory,financialData")
        return yp.ratings(symbol, r, self.source)

    async def officers(self, symbol: str, proxies: list[dict] | None = None) -> dict:
        return yp.management(symbol, await self._summary(symbol, "assetProfile"), self.source, proxies)

    async def keystats(self, symbol: str) -> dict:
        """Raw defaultKeyStatistics + summaryDetail (short interest, beta, shares); parsed by the caller."""
        return await self._summary(symbol, "defaultKeyStatistics,summaryDetail")

    async def fund(self, symbol: str) -> dict:
        return await self._summary(symbol, "topHoldings,fundProfile,quoteType")

    async def events(self, symbol: str) -> dict[str, Any]:
        """Dividend and split events over the full history (monthly bars; the events do not depend on the interval)."""
        body = await self.get_json(f"{BASE}/v8/finance/chart/{symbol}",
                                   {"range": "max", "interval": "1mo", "events": "div,splits"})
        chart = body.get("chart") or {}
        if chart.get("error") or not chart.get("result"):
            raise ProviderError("not_found", (chart.get("error") or {}).get("description", "no data"))
        res = chart["result"][0]
        return {"events": res.get("events") or {}, "currency": (res.get("meta") or {}).get("currency")}

    async def dividends(self, symbol: str) -> dict:
        return cp.yahoo_dividends(await self.events(symbol), self.source)

    async def splits(self, symbol: str) -> dict:
        return cp.yahoo_splits(await self.events(symbol), self.source)

    async def short_interest(self, symbol: str) -> dict:
        return cp.yahoo_short_interest(await self.keystats(symbol), self.source)
