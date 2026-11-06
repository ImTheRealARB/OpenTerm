"""Binance spot order book and USD-M futures funding / basis (keyless public REST). HTTP 451 means Binance blocks the caller's country:
that is `unavailable` with the reason named, and the router falls back to OKX."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any, ClassVar

from ..world import cryptodepth as cd
from .base import Provider, ProviderError

DEPTH = "crypto_depth"
FUNDING = "crypto_funding"
FUNDING_DETAIL = "crypto_funding_detail"
SPOT, FAPI = "https://api.binance.com", "https://fapi.binance.com"
INFO_TTL_S = 6 * 3600.0


class BinanceDerivProvider(Provider):
    name = "binance_deriv"
    label = "Binance order book + USD-M funding"
    capabilities = frozenset({DEPTH, FUNDING, FUNDING_DETAIL})
    markets = "Spot order book (100 levels) and USD-M perpetual / quarterly futures funding, mark and index prices"
    terms = "Public market data, no key. Blocked in some countries (HTTP 451)."
    rate = (4.0, 10)
    timeout = 8.0
    headers: ClassVar[dict[str, str]] = {"User-Agent": "OpenTerm", "Accept": "application/json"}

    def __init__(self, http, source: str | None = None, fixture: bool = False):
        super().__init__(http, source, fixture)
        self._info: tuple[float, dict[str, float]] | None = None

    async def _json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        try:
            return await self.get_json(url, params)
        except ProviderError as e:
            if "451" in str(e):
                raise ProviderError("unavailable", "HTTP 451 (BINANCE BLOCKS THIS COUNTRY)") from e
            raise

    async def crypto_depth(self, base: str, quote: str) -> dict[str, Any]:
        q = "USDT" if quote == "USD" else quote
        bids, asks, _ = cd.parse_binance_book(await self._json(f"{SPOT}/api/v3/depth", {"symbol": f"{base}{q}", "limit": 100}))
        out = cd.depth_summary(bids, asks, q)
        return {**out, "symbol": f"{base}{q}", "venue": "BINANCE SPOT", "ts_ms": None}

    async def _intervals(self) -> dict[str, float]:
        if self._info and time.time() - self._info[0] < INFO_TTL_S:
            return self._info[1]
        iv = cd.binance_intervals(await self._json(f"{FAPI}/fapi/v1/fundingInfo"))
        self._info = (time.time(), iv)
        return iv

    async def crypto_funding(self) -> list[dict[str, Any]]:
        prem = await self._json(f"{FAPI}/fapi/v1/premiumIndex")
        return cd.binance_board(prem, await self._intervals(), datetime.now(UTC).date())

    async def crypto_funding_detail(self, base: str) -> dict[str, Any]:
        sym = f"{base}USDT"
        prem = await self._json(f"{FAPI}/fapi/v1/premiumIndex", {"symbol": sym})
        if not isinstance(prem, dict) or "markPrice" not in prem:
            raise ProviderError("not_found", f"NO BINANCE PERPETUAL {sym}")
        hours = (await self._intervals()).get(sym, 8.0)
        row = cd._perp_row(base, prem, hours, "binance")
        hist = cd.parse_binance_history(await self._json(f"{FAPI}/fapi/v1/fundingRate", {"symbol": sym, "limit": 30}))
        return {"row": row, "history": cd.funding_history(hist, hours)}

    async def probe(self) -> None:
        await self._json(f"{SPOT}/api/v3/depth", {"symbol": "BTCUSDT", "limit": 5})
