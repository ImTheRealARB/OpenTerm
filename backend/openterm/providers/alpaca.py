"""Alpaca market data (free keys): news, and the latest IEX trades behind real-time quotes (streaming/iex.py).

`supports()` is false without both keys (ALPACA_KEY_ID, ALPACA_SECRET_KEY), so the router skips it. Keys travel in the
APCA-API-* headers only. Answers are documented shapes; the fixtures that replay them are labelled doc-shaped.
"""

from __future__ import annotations

from typing import Any, ClassVar

import httpx

from ..research import keyed_parse as kp
from .base import NEWS_SYMBOL, NEWS_TOP, ProviderError
from .keyed import KeyedProvider

DATA = "https://data.alpaca.markets"


class AlpacaProvider(KeyedProvider):
    name = "alpaca"
    label = "Alpaca market data (free keys)"
    capabilities = frozenset({NEWS_SYMBOL, NEWS_TOP})
    markets = "US news (Benzinga) for a symbol or the whole market"
    terms = "Free account keys (ALPACA_KEY_ID, ALPACA_SECRET_KEY), 200 calls/min. Headlines and links only."
    rate = (2.0, 10)
    max_wait = 2.0
    timeout = 8.0
    key_name = "ALPACA_KEY_ID"
    key_fields = ("ALPACA_KEY_ID", "ALPACA_SECRET_KEY")  # two values: the adapter has a key only when both are set
    headers: ClassVar[dict[str, str]] = {"User-Agent": "OpenTerm/0.1", "Accept": "application/json"}
    msg_rate_limited = "429 from Alpaca"
    msg_refused = "Alpaca refused the keys ({code})"

    def __init__(self, http: httpx.AsyncClient, source: str | None = None, key_id: str = "", secret: str = "", fixture: bool = False):
        super().__init__(http, source, fixture)
        self._values = {"ALPACA_KEY_ID": key_id, "ALPACA_SECRET_KEY": secret}

    def auth_headers(self) -> dict[str, str]:
        return {"APCA-API-KEY-ID": self._values["ALPACA_KEY_ID"], "APCA-API-SECRET-KEY": self._values["ALPACA_SECRET_KEY"]}

    async def _api(self, path: str, params: dict[str, Any]) -> Any:
        return await self.get_json(f"{DATA}/{path}", params)

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
