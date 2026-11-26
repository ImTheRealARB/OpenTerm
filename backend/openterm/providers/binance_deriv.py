"""Binance spot order book and USD-M futures funding / basis (keyless public REST). HTTP 451 means Binance blocks the caller's country:
that is `unavailable` with the reason named, and the router falls back to OKX."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any, ClassVar

from ..world import cryptodepth as cd
from ..world import orderflow as of
from .base import Provider, ProviderError

DEPTH = "crypto_depth"
FUNDING = "crypto_funding"
FUNDING_DETAIL = "crypto_funding_detail"
TRADES = "crypto_trades"  # Phase 23: spot aggregated trades (time and sales, big trades, footprint)
AGG_PAGE = 1000  # Binance returns at most 1000 aggregated trades per call
SPOT, FAPI = "https://api.binance.com", "https://fapi.binance.com"
INFO_TTL_S = 6 * 3600.0


class BinanceDerivProvider(Provider):
    name = "binance_deriv"
    label = "Binance order book + USD-M funding"
    capabilities = frozenset({DEPTH, FUNDING, FUNDING_DETAIL, TRADES})
    markets = "Spot order book (100 levels), spot aggregated trades and USD-M perpetual / quarterly futures funding, mark and index prices"
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

    async def crypto_trades(self, base: str, quote: str, window_ms: int | None = None, max_pages: int = 1) -> dict[str, Any]:
        """Latest spot aggregated trades, oldest first. One call = the newest 1000. With `window_ms`, older pages are fetched
        (`fromId` = the oldest id held minus 1000) until the trades span that long, or `max_pages` calls were made, or a page
        brings nothing new. The window is measured on the EXCHANGE's clock (newest trade), never the local one.
        `truncated` = the trades do not span the whole window (the caller must say so on screen)."""
        q = "USDT" if quote == "USD" else quote
        sym = f"{base}{q}"
        pages = [of.parse_agg_trades(await self._flow_json({"symbol": sym, "limit": AGG_PAGE}))]
        held = of.merge_pages(pages)
        while window_ms is not None and len(pages) < max_pages and held and held[-1].t - held[0].t < window_ms and held[0].id > 0:
            older = of.parse_agg_trades(await self._flow_json({"symbol": sym, "limit": AGG_PAGE, "fromId": max(0, held[0].id - AGG_PAGE)}))
            merged = of.merge_pages([*pages, older])
            if len(merged) == len(held):  # nothing new (start of the market, or a replay): stop instead of asking again
                break
            pages.append(older)
            held = merged
        if not held:
            raise ProviderError("not_found", f"NO RECENT TRADES FOR {sym}")
        truncated = window_ms is not None and held[-1].t - held[0].t < window_ms
        return {"symbol": sym, "venue": "BINANCE SPOT", "trades": held, "truncated": truncated, "pages": len(pages)}

    async def _flow_json(self, params: dict[str, Any]) -> Any:
        """aggTrades call. Binance answers 400 for a pair it does not list: that is `not_found` (a typo or a non-crypto symbol),
        not an outage, so it does not count as a circuit-breaker strike."""
        try:
            return await self._json(f"{SPOT}/api/v3/aggTrades", params)
        except ProviderError as e:
            if "HTTP 400" in str(e):
                raise ProviderError("not_found", "NOT A BINANCE SPOT PAIR") from e
            raise

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
