"""Alpaca market data (free keys): news, and the latest IEX trades behind real-time quotes (streaming/iex.py).

`supports()` is false without both keys (ALPACA_KEY_ID, ALPACA_SECRET_KEY), so the router skips it. Keys travel in the
APCA-API-* headers only. Answers are documented shapes; the fixtures that replay them are labelled doc-shaped.
"""

from __future__ import annotations

from typing import Any, ClassVar

import httpx

from ..ratelimit import RateLimited
from ..redact import redact
from ..research import keyed_parse as kp
from .base import NEWS_SYMBOL, NEWS_TOP, Provider, ProviderError

DATA = "https://data.alpaca.markets"


class AlpacaProvider(Provider):
    name = "alpaca"
    label = "Alpaca market data (free keys)"
    capabilities = frozenset({NEWS_SYMBOL, NEWS_TOP})
    markets = "US news (Benzinga) for a symbol or the whole market"
    terms = "Free account keys (ALPACA_KEY_ID, ALPACA_SECRET_KEY), 200 calls/min. Headlines and links only."
    rate = (2.0, 10)
    max_wait = 2.0
    timeout = 8.0
    key_name = "ALPACA_KEY_ID"
    headers: ClassVar[dict[str, str]] = {"User-Agent": "OpenTerm/0.1", "Accept": "application/json"}

    def __init__(self, http: httpx.AsyncClient, source: str | None = None, key_id: str = "", secret: str = ""):
        super().__init__(http, source)
        self._id, self._secret = key_id, secret

    @property
    def has_key(self) -> bool:
        return bool(self._id and self._secret)

    def set_keys(self, values: dict[str, str] | None) -> None:
        v = values or {}
        self._id, self._secret = v.get("ALPACA_KEY_ID", ""), v.get("ALPACA_SECRET_KEY", "")

    def supports(self, capability: str, symbol: str | None = None) -> bool:
        return self.has_key and capability in self.capabilities

    async def _api(self, path: str, params: dict[str, Any]) -> Any:
        if not self.has_key:
            raise ProviderError("key_required", "ALPACA_KEY_ID and ALPACA_SECRET_KEY are not set")
        try:
            await self.bucket.acquire(self.max_wait)
        except RateLimited as e:
            raise ProviderError("rate_limited", str(e)) from e
        auth = {"APCA-API-KEY-ID": self._id, "APCA-API-SECRET-KEY": self._secret}
        try:
            r = await self.http.get(f"{DATA}/{path}", params=params, headers={**self.headers, **auth}, timeout=self.timeout)
        except httpx.TimeoutException as e:
            raise ProviderError("unavailable", "timeout") from e
        except httpx.HTTPError as e:
            raise ProviderError("unavailable", type(e).__name__) from e
        if r.status_code == 429:
            raise ProviderError("rate_limited", "429 from Alpaca")
        if r.status_code in (401, 403):
            raise ProviderError("key_required", redact(f"Alpaca refused the keys ({r.status_code})", [self._id, self._secret]))
        if r.status_code >= 400:
            raise ProviderError("unavailable", f"HTTP {r.status_code}")
        try:
            return r.json()
        except ValueError as e:
            raise ProviderError("unavailable", "non-JSON response") from e

    async def _news(self, params: dict[str, Any]) -> dict:
        items = kp.alpaca_news(await self._api("v1beta1/news", {**params, "limit": 50, "sort": "desc",
                                                                "include_content": "false"}), self.source)
        if not items:
            raise ProviderError("not_found", "no headlines")
        return {"items": items, "failed": []}

    async def news_symbol(self, symbol: str) -> dict:
        return await self._news({"symbols": symbol})

    async def news_top(self) -> dict:
        return await self._news({})

    async def latest_trades(self, symbols: list[str]) -> dict[str, tuple[float, int | None, int]]:
        """Last IEX trade per symbol (IEX volume only, not the consolidated tape): {symbol: (price, size, epoch ms)}."""
        return kp.alpaca_trades(await self._api("v2/stocks/trades/latest", {"symbols": ",".join(symbols), "feed": "iex"}))

    async def probe(self) -> None:
        await self._api("v1beta1/news", {"limit": 1})
