"""Kalshi public market data (PRED): `api.elections.kalshi.com/trade-api/v2` markets and candlesticks. Keyless, read only: no order, portfolio or balance call exists here.

`/markets` holds more than 12,000 open markets, nearest close first, with no volume ordering. PRED reads two 1000-market pages with multivariate
combos excluded: the nearest-closing page (sports props) and the page closing 30+ days out (elections, macro, long bets), merged by ticker.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, ClassVar

from .base import Provider, ProviderError

BASE = "https://api.elections.kalshi.com/trade-api/v2"
PAGE = 1000
FAR_DAYS = 30
CANDLE_DAYS = 7
CANDLE_MINUTES = 60


class KalshiMarketsProvider(Provider):
    name = "kalshi"
    label = "Kalshi (prediction markets)"
    capabilities = frozenset({"pred_kalshi", "pred_kalshi_market", "pred_kalshi_candles"})
    markets = "Kalshi event contracts: YES prices as implied probabilities (read only, first 2000 of the open markets)"
    terms = "Free public market-data API, no key for reads. Prices are market-implied probabilities, not forecasts."
    rate = (4.0, 8)
    timeout = 20.0
    max_wait = 1.0
    headers: ClassVar[dict[str, str]] = {"User-Agent": "OpenTerm", "Accept": "application/json"}

    async def _page(self, extra: dict[str, Any]) -> list[Any]:
        out = await self.get_json(f"{BASE}/markets", {"limit": PAGE, "status": "open", "mve_filter": "exclude", **extra})
        ms = out.get("markets") if isinstance(out, dict) else None
        if not isinstance(ms, list):
            raise ProviderError("unavailable", "Kalshi answered without a markets list")
        return ms

    async def pred_markets(self) -> dict[str, Any]:
        near, far = await asyncio.gather(self._page({}), self._page({"min_close_ts": int(time.time()) + FAR_DAYS * 86400}))
        merged = {m.get("ticker"): m for m in near + far if isinstance(m, dict) and m.get("ticker")}
        return {"markets": list(merged.values())}

    async def pred_market(self, ticker: str) -> dict[str, Any]:
        out = await self.get_json(f"{BASE}/markets/{ticker}")
        if not isinstance(out, dict) or not isinstance(out.get("market"), dict):
            raise ProviderError("unavailable", "Kalshi answered without a market")
        return out

    async def pred_history(self, series: str, ticker: str) -> dict[str, Any]:
        if not series:
            raise ProviderError("unsupported", "no series ticker for the candlesticks")
        now = int(time.time())
        return await self.get_json(f"{BASE}/series/{series}/markets/{ticker}/candlesticks",
                                   {"start_ts": now - CANDLE_DAYS * 86400, "end_ts": now, "period_interval": CANDLE_MINUTES})

    async def probe(self) -> None:
        out = await self.get_json(f"{BASE}/markets", {"limit": 1, "status": "open"})
        if not isinstance(out, dict) or "markets" not in out:
            raise ProviderError("unavailable", "no markets list")
