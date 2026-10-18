"""OKX public market data (keyless): order book, perpetual funding / mark / index, and the latest liquidation orders (LIQ is OKX only:
Binance has no REST liquidation history). An error answer has HTTP 200 and `code != "0"`: it is read, never mistaken for data."""

from __future__ import annotations

import asyncio
import time
from typing import Any, ClassVar

from ..world import cryptodepth as cd
from .base import Provider, ProviderError

DEPTH = "crypto_depth"
FUNDING = "crypto_funding"
FUNDING_DETAIL = "crypto_funding_detail"
LIQ = "crypto_liq"
API = "https://www.okx.com/api/v5"
INST_TTL_S = 24 * 3600.0


def _check(body: Any, what: str) -> Any:
    if isinstance(body, dict) and body.get("code") not in (None, "0"):
        kind = "not_found" if str(body.get("code")).startswith("51") else "unavailable"
        raise ProviderError(kind, f"OKX {what}: {body.get('msg') or body.get('code')}")
    return body


class OkxProvider(Provider):
    name = "okx"
    label = "OKX order book, funding, liquidations"
    capabilities = frozenset({DEPTH, FUNDING, FUNDING_DETAIL, LIQ})
    markets = "Spot order book, USDT-margined perpetual funding / mark / index, latest liquidation orders"
    terms = "Public market data, no key."
    rate = (5.0, 10)
    timeout = 8.0
    headers: ClassVar[dict[str, str]] = {"User-Agent": "OpenTerm", "Accept": "application/json"}

    def __init__(self, http, source: str | None = None):
        super().__init__(http, source)
        self._inst: dict[str, tuple[float, tuple[float, bool]]] = {}

    async def _json(self, path: str, params: dict[str, Any], what: str) -> Any:
        return _check(await self.get_json(f"{API}/{path}", params), what)

    async def crypto_depth(self, base: str, quote: str) -> dict[str, Any]:
        inst = f"{base}-{quote}"
        bids, asks, ts = cd.parse_okx_book(await self._json("market/books", {"instId": inst, "sz": 100}, "BOOK"))
        return {**cd.depth_summary(bids, asks, quote), "symbol": inst, "venue": "OKX SPOT", "ts_ms": ts}

    async def crypto_funding(self) -> list[dict[str, Any]]:
        fr, mk, ix = await asyncio.gather(self._json("public/funding-rate", {"instId": "ANY"}, "FUNDING"), self._json("public/mark-price", {"instType": "SWAP"}, "MARK"),
                                          self._json("market/index-tickers", {"quoteCcy": "USDT"}, "INDEX"))
        return cd.okx_board(fr, mk, ix)

    async def crypto_funding_detail(self, base: str) -> dict[str, Any]:
        inst = f"{base}-USDT-SWAP"
        fr, mk, ix, hist = await asyncio.gather(
            self._json("public/funding-rate", {"instId": inst}, "FUNDING"), self._json("public/mark-price", {"instType": "SWAP", "instId": inst}, "MARK"),
            self._json("market/index-tickers", {"instId": f"{base}-USDT"}, "INDEX"), self._json("public/funding-rate-history", {"instId": inst, "limit": 30}, "FUNDING HISTORY"))
        rows = cd.okx_board(fr, mk, ix) if base in cd.MAJORS else self._single(base, fr, mk, ix)
        if not rows:
            raise ProviderError("not_found", f"NO OKX PERPETUAL {inst}")
        row = rows[0]
        return {"row": row, "history": cd.funding_history(cd.parse_okx_history(hist), row["interval_h"] or 8.0)}

    @staticmethod
    def _single(base: str, fr: Any, mk: Any, ix: Any) -> list[dict[str, Any]]:
        f = (fr.get("data") or [None])[0]
        if not f:
            return []
        m = (mk.get("data") or [{}])[0]
        i = (ix.get("data") or [{}])[0]
        x = {"symbol": f"{base}-USDT-SWAP", "markPrice": m.get("markPx"), "indexPrice": i.get("idxPx"), "lastFundingRate": f.get("fundingRate"), "nextFundingTime": cd._int(f.get("fundingTime"))}
        return [cd._perp_row(base, x, cd._interval_okx(f), "okx")]

    async def _contract(self, base: str) -> tuple[float, bool]:
        hit = self._inst.get(base)
        if hit and time.time() - hit[0] < INST_TTL_S:
            return hit[1]
        body = await self._json("public/instruments", {"instType": "SWAP", "uly": f"{base}-USDT"}, "INSTRUMENTS")
        data = body.get("data") or []
        if not data:
            raise ProviderError("not_found", f"NO OKX PERPETUAL FOR {base}")
        val = (float(data[0]["ctVal"]), data[0].get("ctType") == "linear")
        self._inst[base] = (time.time(), val)
        return val

    async def crypto_liq(self, base: str) -> dict[str, Any]:
        ct, linear = await self._contract(base)
        body = await self._json("public/liquidation-orders", {"instType": "SWAP", "uly": f"{base}-USDT", "state": "filled"}, "LIQUIDATIONS")
        return {"base": base, "events": cd.parse_okx_liquidations(body, ct, linear), "ct_val": ct}

    async def probe(self) -> None:
        await self._json("market/books", {"instId": "BTC-USDT", "sz": 1}, "BOOK")
