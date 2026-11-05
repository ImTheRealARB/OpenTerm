"""Marketaux (free key): financial news with a sentiment score per company, as one more source for N / CN headlines.

A key unlocks more, never gates the basics: `supports()` is false without MARKETAUX_KEY, so the router skips it and it costs
nothing. With a key it is merged into the symbol and top-story headlines the way Finnhub and Alpaca are (`DataService.news`
asks every provider with `has_key` in parallel), and each headline carries the source's own sentiment score (-1 to +1) in
`NewsItem.sentiment`. That number is Marketaux's, not OpenTerm's: the N panel labels it that way.

Quota care. The free plan is about 100 requests a day (an unverified figure from one comparison page: confirm it on
marketaux.com/pricing). N refreshes every two minutes, so this adapter protects the quota twice:
  - it keeps each answer for 15 minutes (in memory), so repeated refreshes cost nothing;
  - it stops at DAILY_BUDGET (90) requests per UTC day and answers `rate_limited` ("DAILY BUDGET USED") until midnight.
Marketaux's own HTTP 402 `usage_limit_reached` is mapped the same way.

The key travels as the `api_token` query parameter: that is the only method the docs describe. It is registered with
redact.py, and no error text here ever includes a URL. Checked live on 2026-11-05 with a real key (fixture `marketaux_real_news_aapl`): field names match, `published_at` is UTC text ending in Z,
`source` is a domain, entities carry `sentiment_score`. The free plan returns at most 3 articles per request, 100 requests a day
(`x-usagelimit-limit`) and 30 a minute (`x-ratelimit-limit`). Keyword search (`news_keyword`, the N panel's `q=`) does NOT use this
source: only GDELT serves it, so a GDELT 429 shows as 503 PROVIDER DOWN there even though Marketaux is fine.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any, ClassVar

import httpx
import orjson

from ..ratelimit import RateLimited
from ..redact import redact
from . import marketaux_parse as mp
from .base import NEWS_SYMBOL, NEWS_TOP, Provider, ProviderError

URL = "https://api.marketaux.com/v1/news/all"
DAILY_BUDGET = 90
CACHE_S = 900.0


class MarketauxProvider(Provider):
    name = "marketaux"
    label = "Marketaux (free tier, key)"
    capabilities = frozenset({NEWS_SYMBOL, NEWS_TOP})
    markets = "Global company and market news in English, each article scored for sentiment per company"
    terms = "Free key (MARKETAUX_KEY), about 100 requests a day. Headlines, teasers, links and sentiment scores only."
    rate = (0.5, 3)
    max_wait = 2.0
    timeout = 10.0
    key_name = "MARKETAUX_KEY"
    headers: ClassVar[dict[str, str]] = {"User-Agent": "OpenTerm", "Accept": "application/json"}

    def __init__(self, http: httpx.AsyncClient, source: str | None = None):
        super().__init__(http, source)
        self.fixtures = (source or "").endswith(":fixture")
        self.source = "marketaux (doc-shaped fixture, NOT A RECORDING)" if self.fixtures else "marketaux"
        self._key = ""
        self._cache: dict[str, tuple[float, list]] = {}
        self._day = ""  # the UTC date the request counter belongs to
        self.requests_today = 0

    @property
    def has_key(self) -> bool:
        return bool(self._key)

    def set_keys(self, values: dict[str, str] | None) -> None:
        self._key = (values or {}).get("MARKETAUX_KEY", "")

    def supports(self, capability: str, symbol: str | None = None) -> bool:
        return self.has_key and capability in self.capabilities

    def _spend(self) -> None:
        """Counts one request against today's budget, or refuses when the budget is used up."""
        today = datetime.now(UTC).date().isoformat()
        if today != self._day:
            self._day, self.requests_today = today, 0
        if self.requests_today >= DAILY_BUDGET:
            raise ProviderError("rate_limited", f"MARKETAUX DAILY BUDGET USED ({DAILY_BUDGET} REQUESTS, RESETS AT 00:00 UTC)")
        self.requests_today += 1

    async def _api(self, params: dict[str, Any]) -> Any:
        if not self._key:
            raise ProviderError("key_required", "MARKETAUX_KEY is not set")
        self._spend()
        try:
            await self.bucket.acquire(self.max_wait)
        except RateLimited as e:
            raise ProviderError("rate_limited", str(e)) from e
        try:
            r = await self.http.get(URL, params={**params, "api_token": self._key}, headers=self.headers, timeout=self.timeout)
        except httpx.TimeoutException as e:
            raise ProviderError("unavailable", "timeout") from e
        except httpx.HTTPError as e:
            raise ProviderError("unavailable", type(e).__name__) from e  # never str(e): it can carry the URL with the token
        try:
            body = orjson.loads(r.content)
        except orjson.JSONDecodeError:
            body = None
        err = mp.error_of(r.status_code, body)
        if err is not None:
            raise ProviderError(err.kind, redact(str(err), [self._key]))
        return body

    async def _news(self, cache_key: str, params: dict[str, Any], symbol: str | None) -> dict:
        hit = self._cache.get(cache_key)
        if hit and time.time() - hit[0] < CACHE_S:
            return {"items": hit[1], "failed": []}
        items = mp.parse_news(await self._api(params), self.source, symbol)
        if not items:
            raise ProviderError("not_found", "no headlines")
        self._cache[cache_key] = (time.time(), items)
        return {"items": items, "failed": []}

    async def news_symbol(self, symbol: str) -> dict:
        # filter_entities=true keeps only the requested company's entity on each article, so its sentiment score is the right one.
        return await self._news(f"s:{symbol}", {"symbols": symbol, "language": "en", "filter_entities": "true"}, symbol)

    async def news_top(self) -> dict:
        return await self._news("top", {"language": "en"}, None)

    # No probe(): the scheduler would call it every 30 s while the provider is tripped, and every call spends one of ~100 daily requests.
    # Without a probe the circuit-breaker cool-down just runs out by itself (see scheduler.probe_down_providers).
