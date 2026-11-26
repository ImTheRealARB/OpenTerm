"""Service functions behind TAS / BIGT / FOOT (`/api/world/flow/trades|bigtrades|footprint`): Binance spot aggregated trades.

Thin on purpose: the maths lives in `orderflow.py` (pure), the HTTP in `providers/binance_deriv.py`. This file only validates the
arguments, asks the router for trades, shapes the answer and caches it for a few seconds (`DataService.swr`).
Crypto only: any symbol Binance does not list answers `ORDER FLOW: CRYPTO ONLY (BINANCE SPOT PAIRS)` (HTTP 400).
"""

from __future__ import annotations

from typing import Any

from ..errors import DataError
from . import cryptodepth as cd
from . import orderflow as of

TRADES_TTL_S = 2.0
BIG_TTL_S = 4.0
FOOT_TTL_S = 5.0
BIG_WINDOW_MS = 3_600_000  # BIGT looks back at most one hour of trades...
BIG_PAGES = 5  # ...and at most 5 calls (5,000 trades): the span actually covered is returned, never assumed
FOOT_MAX_PAGES = 8  # footprint: up to 8,000 trades; a busy pair may then cover fewer bars than asked (marked `truncated`)
DEFAULT_BIG_USD = 100_000.0
CRYPTO_ONLY = "ORDER FLOW: CRYPTO ONLY (BINANCE SPOT PAIRS)"


def _pair(sym: str) -> tuple[str, str]:
    """`BTCUSDT` / `BTC-USDT` / `BTC-USD` / `BTC` -> (base, quote). Anything that is not a pair shape is the crypto-only error."""
    try:
        return cd.parse_pair(sym)
    except ValueError as e:
        raise DataError("bad_request", CRYPTO_ONLY) from e


async def _swr(svc: Any, key: str, ttl: float, fetch: Any) -> dict[str, Any]:
    """`svc.swr`, but a pair Binance does not list (`not_found` from every source) becomes the crypto-only 400."""
    try:
        return await svc.swr(key, ttl, fetch)
    except DataError as e:
        if e.kind == "not_found":
            raise DataError("bad_request", CRYPTO_ONLY) from e
        raise


async def _trades(svc: Any, base: str, quote: str, window_ms: int | None, max_pages: int) -> tuple[dict[str, Any], list[str]]:
    return await svc.router.call("crypto_trades", lambda p: p.crypto_trades(base, quote, window_ms, max_pages), f"{base}{quote}")


def _head(out: dict[str, Any], base: str, quote: str) -> dict[str, Any]:
    trades = out["trades"]
    return {"symbol": out["symbol"], "pair": f"{base}/{quote}", "base": base, "quote": quote, "quote_is_usd": quote in cd.USD_QUOTES,
            "venue": out["venue"], "basis": of.LABEL_EXACT, "n": len(trades), "span_s": (trades[-1].t - trades[0].t) / 1000.0,
            "newest_t": trades[-1].t}


async def trades(svc: Any, sym: str, limit: int) -> dict[str, Any]:
    """TAS: the newest `limit` trades, newest first."""
    base, quote = _pair(sym)

    async def fetch() -> dict:
        out, failed = await _trades(svc, base, quote, None, 1)
        head = _head(out, base, quote)
        return {"data": {**head, "rows": of.recent(out["trades"], limit)}, "fallback_from": failed, "source": "binance_deriv"}

    return await _swr(svc, f"w:flow:tas:{base}{quote}:{limit}", TRADES_TTL_S, fetch)


async def bigtrades(svc: Any, sym: str, min_qty: float | None, usd: float | None) -> dict[str, Any]:
    """BIGT: trades of at least `min_qty` coins or at least `usd` (USD-quoted pairs only), over the newest <= 5,000 trades, newest first."""
    base, quote = _pair(sym)
    if usd is not None and quote not in cd.USD_QUOTES:
        raise DataError("bad_request", f"USD= NEEDS A USD-QUOTED PAIR ({base}{quote} IS QUOTED IN {quote}): USE MIN=<COINS>")
    if min_qty is None and usd is None:
        if quote not in cd.USD_QUOTES:
            raise DataError("bad_request", f"BIGT {base}{quote}: SET MIN=<COINS>")
        usd = DEFAULT_BIG_USD

    async def fetch() -> dict:
        out, failed = await _trades(svc, base, quote, BIG_WINDOW_MS, BIG_PAGES)
        big = of.big_trades(out["trades"], min_qty, usd)
        head = _head(out, base, quote)
        return {"data": {**head, "rows": [of.trade_row(t) for t in big[:500]], "found": len(big), "scanned": len(out["trades"]),
                         "filter": {"min_qty": min_qty, "usd": usd}},
                "fallback_from": failed, "source": "binance_deriv"}

    return await _swr(svc, f"w:flow:big:{base}{quote}:{min_qty}:{usd}", BIG_TTL_S, fetch)


async def footprint(svc: Any, sym: str, interval: str, bars: int, step: float | None) -> dict[str, Any]:
    """FOOT: the newest `bars` bars of `interval` as a footprint (bid x ask volume per price level, delta, cumulative delta)."""
    base, quote = _pair(sym)
    iv = of.INTERVAL_MS.get(interval)
    if iv is None:
        raise DataError("bad_request", f"INTERVAL: {', '.join(of.INTERVAL_MS)}")

    async def fetch() -> dict:
        out, failed = await _trades(svc, base, quote, bars * iv, FOOT_MAX_PAGES)
        try:
            fp = of.footprint(out["trades"], iv, bars, step, out["truncated"])
        except ValueError as e:  # a bad `step` from the URL
            raise DataError("bad_request", str(e)) from e
        head = _head(out, base, quote)
        return {"data": {**head, "interval": interval, "bars_asked": bars, "truncated": out["truncated"], **fp},
                "fallback_from": failed, "source": "binance_deriv"}

    return await _swr(svc, f"w:flow:foot:{base}{quote}:{interval}:{bars}:{step}", FOOT_TTL_S, fetch)
