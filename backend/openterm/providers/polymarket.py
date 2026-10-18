"""Polymarket public market data (PRED): the gamma list/detail API and the CLOB price history. Keyless, read only: no order, wallet or trading call exists here.

`gamma-api.polymarket.com/markets` answers a bare JSON list; `outcomes`, `outcomePrices` and `clobTokenIds` are JSON-encoded strings (parsed in `world/pred.py`).
Resolved markets still say `active: true`, so the request asks for `closed=false` and the parser filters `closed` again.
"""

from __future__ import annotations

from typing import Any, ClassVar

from .base import Provider, ProviderError

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
LIST_LIMIT = 200
HISTORY_FIDELITY_MIN = 240  # one point per four hours over the last month


class PolymarketProvider(Provider):
    name = "polymarket"
    label = "Polymarket (prediction markets)"
    capabilities = frozenset({"pred_poly", "pred_poly_market", "pred_poly_history"})
    markets = "Polymarket event markets: YES/NO and multi-outcome prices as implied probabilities (read only)"
    terms = "Free public gamma and CLOB read APIs, no key. Prices are market-implied probabilities, not forecasts."
    rate = (4.0, 8)
    timeout = 12.0
    headers: ClassVar[dict[str, str]] = {"User-Agent": "OpenTerm", "Accept": "application/json"}

    async def pred_markets(self) -> list[Any]:
        out = await self.get_json(f"{GAMMA}/markets", {"limit": LIST_LIMIT, "active": "true", "closed": "false", "order": "volumeNum", "ascending": "false"})
        if not isinstance(out, list):
            raise ProviderError("unavailable", "Polymarket answered with something other than a list")
        return out

    async def pred_market(self, market_id: str) -> dict[str, Any]:
        out = await self.get_json(f"{GAMMA}/markets/{market_id}")
        if not isinstance(out, dict):
            raise ProviderError("unavailable", "Polymarket answered with something other than a market")
        return out

    async def pred_history(self, token: str) -> dict[str, Any]:
        out = await self.get_json(f"{CLOB}/prices-history", {"market": token, "interval": "1m", "fidelity": HISTORY_FIDELITY_MIN})
        if not isinstance(out, dict):
            raise ProviderError("unavailable", "Polymarket price history is not an object")
        return out

    async def probe(self) -> None:
        out = await self.get_json(f"{GAMMA}/markets", {"limit": 1, "active": "true", "closed": "false"})
        if not isinstance(out, list):
            raise ProviderError("unavailable", "not a list")
