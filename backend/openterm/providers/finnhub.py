"""Finnhub (free tier): company news, market news, analyst recommendation trend, EPS surprises, and the earnings and IPO
calendars (added 2026-11-26 as fallbacks behind Nasdaq, which blocks OpenTerm's client; checked live on a free key that day).

A key unlocks more, never gates the basics: `supports()` is false without FINNHUB_API_KEY, so the router skips it and it
costs nothing. The key travels in the X-Finnhub-Token header, never in a URL. Answers are documented shapes; the fixtures
that replay the news / ratings / surprises are labelled doc-shaped (no key was available to record); the calendar fixtures are
real recordings (scripts/record_nasdaq_replacements.py).
"""

from __future__ import annotations

import calendar
from datetime import UTC, date, datetime, timedelta
from typing import Any, ClassVar

import httpx

from ..config import get_settings
from ..research import calendars_parse as cal
from ..research import keyed_parse as kp
from .base import NEWS_SYMBOL, NEWS_TOP, ProviderError
from .keyed import KeyedProvider
from .macro import EARNINGS
from .research_nasdaq import IPO

BASE = "https://finnhub.io/api/v1"
RATINGS = "ratings"
SURPRISES = "surprises"
NEWS_DAYS = 7


class FinnhubProvider(KeyedProvider):
    name = "finnhub"
    label = "Finnhub (free tier, key)"
    capabilities = frozenset({NEWS_SYMBOL, NEWS_TOP, RATINGS, SURPRISES, EARNINGS, IPO})
    markets = "US company news, general market news, analyst recommendation trend, EPS surprises, earnings and IPO calendars"
    terms = "Free key (FINNHUB_API_KEY), 60 calls/min. Headlines and links only; articles open on the publisher's site."
    rate = (1.0, 10)
    max_wait = 2.0
    timeout = 8.0
    key_name = "FINNHUB_API_KEY"
    headers: ClassVar[dict[str, str]] = {"User-Agent": "OpenTerm/0.1", "Accept": "application/json"}
    msg_rate_limited = "429 from Finnhub"
    msg_refused = "Finnhub refused the key ({code})"

    def __init__(self, http: httpx.AsyncClient, source: str | None = None, api_key: str | None = None, fixture: bool = False):
        super().__init__(http, source, fixture)
        # The first key comes from Settings (.env / environment); a key saved in APIKEYS later arrives through set_keys().
        self._key = get_settings().finnhub_api_key if api_key is None else api_key

    def auth_headers(self) -> dict[str, str]:
        return {"X-Finnhub-Token": self._key}  # a header, never the URL

    async def _api(self, path: str, params: dict[str, Any]) -> Any:
        return await self.get_json(f"{BASE}/{path}", params)

    async def news_symbol(self, symbol: str) -> dict:
        today = datetime.now(UTC).date()
        rows = await self._api("company-news", {"symbol": symbol, "from": (today - timedelta(days=NEWS_DAYS)).isoformat(),
                                                "to": today.isoformat()})
        items = kp.finnhub_news(rows, self.source)
        if not items:
            raise ProviderError("not_found", "no headlines")
        return {"items": items, "failed": []}

    async def news_top(self) -> dict:
        items = kp.finnhub_news(await self._api("news", {"category": "general"}), self.source)
        if not items:
            raise ProviderError("not_found", "no headlines")
        return {"items": items, "failed": []}

    async def ratings(self, symbol: str) -> dict:
        return kp.finnhub_ratings(symbol, await self._api("stock/recommendation", {"symbol": symbol}), self.source)

    async def surprises(self, symbol: str) -> dict:
        return kp.finnhub_surprises(symbol, await self._api("stock/earnings", {"symbol": symbol, "limit": 8}), self.source)

    async def earnings(self, day: date) -> dict:
        """One day of the earnings calendar. The free plan reaches about a month back (an older day answers no rows)."""
        d = day.isoformat()
        return cal.finnhub_earnings(await self._api("calendar/earnings", {"from": d, "to": d}), d, self.source, self.now())

    async def ipo(self, month: str) -> dict:
        """`month` is YYYY-MM (validated by the IPO function); Finnhub takes a from / to window."""
        y, m = (int(x) for x in month.split("-"))
        last = calendar.monthrange(y, m)[1]
        return cal.finnhub_ipo(await self._api("calendar/ipo", {"from": f"{month}-01", "to": f"{month}-{last:02d}"}), self.source)

    async def probe(self) -> None:
        await self._api("news", {"category": "general"})
