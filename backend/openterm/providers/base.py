import time
from typing import Any, ClassVar

import httpx
import orjson

from ..models import Bars, Coin, Movers, Profile, Quote, SearchHit
from ..ratelimit import RateLimited, TokenBucket

QUOTES = "quotes"
HISTORY = "history"
SEARCH = "search"
PROFILE = "profile"
NEWS_TOP = "news_top"
NEWS_SYMBOL = "news_symbol"
NEWS_KEYWORD = "news_keyword"
MOVERS = "movers"
CRYPTO = "crypto"


class ProviderError(Exception):
    """kind: not_found | unsupported | rate_limited | unavailable | key_required"""

    def __init__(self, kind: str, message: str = ""):
        super().__init__(message or kind)
        self.kind = kind


class Provider:
    """Base adapter. Subclasses set the class attributes and implement the capabilities they list."""

    name: str = ""
    label: str = ""
    capabilities: frozenset[str] = frozenset()
    markets: str = ""
    """Human-readable coverage, shown on the SOURCES screen."""
    terms: str = ""
    """Attribution / terms-of-use note, shown on the SOURCES screen."""
    rate: tuple[float, int] = (5.0, 10)
    """Token bucket (requests/second, burst)."""
    headers: ClassVar[dict[str, str]] = {}
    timeout: float = 6.0
    max_wait: float = 0.25
    """Longest wait for a rate-limit slot before failing over. Sources with one slot per few seconds raise it."""
    """Seconds per upstream request. Slow but useful sources (GDELT, Nasdaq movers) raise it."""

    def __init__(self, http: httpx.AsyncClient, source: str | None = None):
        self.http = http
        self.bucket = TokenBucket(*self.rate)
        self.source = source or self.name

    def supports(self, capability: str, symbol: str | None = None) -> bool:
        return capability in self.capabilities

    async def _request(self, url: str, params: dict[str, Any] | None, timeout: float | None) -> httpx.Response:
        try:
            await self.bucket.acquire(self.max_wait)
        except RateLimited as e:
            raise ProviderError("rate_limited", str(e)) from e
        try:
            r = await self.http.get(url, params=params, headers=self.headers, timeout=timeout or self.timeout)
        except httpx.TimeoutException as e:
            raise ProviderError("unavailable", "timeout") from e
        except httpx.HTTPError as e:
            raise ProviderError("unavailable", type(e).__name__) from e
        if r.status_code == 404:
            raise ProviderError("not_found", "404")
        if r.status_code == 429:
            raise ProviderError("rate_limited", "429 from upstream")
        if r.status_code in (401, 403):
            raise ProviderError("unavailable", f"{r.status_code} (blocked or needs auth)")
        if r.status_code >= 400:
            raise ProviderError("unavailable", f"HTTP {r.status_code}")
        return r

    async def get_json(self, url: str, params: dict[str, Any] | None = None, timeout: float | None = None) -> Any:
        r = await self._request(url, params, timeout)
        try:
            return orjson.loads(r.content)
        except orjson.JSONDecodeError as e:
            raise ProviderError("unavailable", "non-JSON response (bot check?)") from e

    async def get_bytes(self, url: str, params: dict[str, Any] | None = None, timeout: float | None = None) -> bytes:
        return (await self._request(url, params, timeout)).content

    @staticmethod
    def now() -> float:
        return time.time()

    async def quotes(self, symbols: list[str]) -> list[Quote]:
        raise ProviderError("unsupported")

    async def history(self, symbol: str, range_: str, interval: str) -> Bars:
        raise ProviderError("unsupported")

    async def search(self, query: str) -> list[SearchHit]:
        raise ProviderError("unsupported")

    async def profile(self, symbol: str) -> Profile:
        raise ProviderError("unsupported")

    async def news_top(self) -> dict:
        """{"items": [NewsItem], "failed": [feed names that did not answer]}"""
        raise ProviderError("unsupported")

    async def news_symbol(self, symbol: str) -> dict:
        raise ProviderError("unsupported")

    async def news_keyword(self, query: str) -> dict:
        raise ProviderError("unsupported")

    async def movers(self) -> Movers:
        raise ProviderError("unsupported")

    async def crypto(self, vs: str) -> list[Coin]:
        raise ProviderError("unsupported")

    async def probe(self) -> None:
        """Cheap liveness check; raises ProviderError when unhealthy."""
        raise NotImplementedError
