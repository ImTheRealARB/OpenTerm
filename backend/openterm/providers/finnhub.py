"""Finnhub (free tier): company news, market news, analyst recommendation trend and EPS surprises.

A key unlocks more, never gates the basics: `supports()` is false without FINNHUB_API_KEY, so the router skips it and it
costs nothing. The key travels in the X-Finnhub-Token header, never in a URL. Answers are documented shapes; the fixtures
that replay them are labelled doc-shaped (no key was available to record).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import httpx

from ..config import get_settings
from ..research import keyed_parse as kp
from .base import NEWS_SYMBOL, NEWS_TOP, ProviderError
from .keyed import KeyedProvider

BASE = "https://finnhub.io/api/v1"
RATINGS = "ratings"
SURPRISES = "surprises"
NEWS_DAYS = 7


class FinnhubProvider(KeyedProvider):
    name = "finnhub"
    label = "Finnhub (free tier, key)"
    capabilities = frozenset({NEWS_SYMBOL, NEWS_TOP, RATINGS, SURPRISES})
    markets = "US company news, general market news, analyst recommendation trend, EPS surprises"
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

    async def probe(self) -> None:
        await self._api("news", {"category": "general"})
