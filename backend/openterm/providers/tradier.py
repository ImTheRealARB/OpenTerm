"""Tradier option chains with vendor Greeks (free sandbox token, 15-minute delayed). A keyed addition, never required: `supports()` is
false without TRADIER_TOKEN, so the router skips it and it costs nothing. It sits after Yahoo in the `option_chain` order, so it answers
when Yahoo does not; its Greeks and IV are shown as sent and labelled VENDOR. The token travels in the Authorization header only.
The fixtures that replay its answers are labelled doc-shaped (no token was available to record).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, ClassVar

import httpx

from ..config import get_settings
from ..options import chain as ch
from .base import ProviderError
from .keyed import KeyedProvider
from .options_yahoo import OPTION_CHAIN

BASE = "https://sandbox.tradier.com/v1"


class TradierProvider(KeyedProvider):
    name = "tradier"
    label = "Tradier sandbox (free token, key)"
    capabilities = frozenset({OPTION_CHAIN})
    markets = "US listed options with vendor Greeks and IV (sandbox: delayed 15 minutes)"
    terms = "Free sandbox token (TRADIER_TOKEN). Greeks come from the vendor; shown as sent and labelled VENDOR."
    rate = (1.0, 5)
    max_wait = 2.0
    timeout = 8.0
    key_name = "TRADIER_TOKEN"
    headers: ClassVar[dict[str, str]] = {"User-Agent": "OpenTerm/0.1", "Accept": "application/json"}
    msg_rate_limited = "429 from Tradier"
    msg_refused = "Tradier refused the token ({code})"
    msg_not_found = "404"

    def __init__(self, http: httpx.AsyncClient, source: str | None = None, token: str | None = None, fixture: bool = False):
        super().__init__(http, source, fixture)
        # The first token comes from Settings (.env / environment); one saved in APIKEYS later arrives through set_keys().
        self._key = get_settings().tradier_token if token is None else token

    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._key}"}

    async def _api(self, path: str, params: dict[str, Any]) -> Any:
        return await self.get_json(f"{BASE}/{path}", params)

    async def option_chain(self, symbol: str, expiry: int | None = None) -> dict:
        exp = await self._api("markets/options/expirations", {"symbol": symbol, "includeAllRoots": "true"})
        days = ch.listed(((exp or {}).get("expirations") or {}).get("date"))
        if not days:
            raise ProviderError("not_found", "no option chain")
        if expiry is None:
            day = days[0]
        else:
            day = datetime.fromtimestamp(expiry, UTC).strftime("%Y-%m-%d")
            if day not in days:
                raise ProviderError("not_found", "expiry not listed")
        chain, quote = await asyncio.gather(
            self._api("markets/options/chains", {"symbol": symbol, "expiration": day, "greeks": "true"}),
            self._api("markets/quotes", {"symbols": symbol}))
        return ch.parse_tradier_chain(symbol, exp, chain, quote, day, self.source)

    async def probe(self) -> None:
        await self._api("markets/quotes", {"symbols": "AAPL"})
