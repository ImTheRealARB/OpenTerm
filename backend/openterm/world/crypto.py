"""Service functions behind CDEP, FUND, LIQ, STBL and DEFI (`/api/world/cdep|fund|liq|stbl|defi`). Binance first, OKX as the fallback
(HTTP 451 = Binance blocks the country); the answer names the venue that served it and the one(s) it fell back from."""

from __future__ import annotations

from typing import Any

from ..service import DataError
from . import cryptodepth as cd

DEPTH_TTL_S = 4.0
FUND_TTL_S = 30.0
LIQ_TTL_S = 20.0
LLAMA_TTL_S = 600.0


def _bad(e: ValueError) -> DataError:
    return DataError("bad_request", str(e))


async def cdep(svc: Any, pair: str) -> dict[str, Any]:
    try:
        base, quote = cd.parse_pair(pair)
    except ValueError as e:
        raise _bad(e) from e

    async def fetch() -> dict:
        out, failed = await svc.router.call("crypto_depth", lambda p: p.crypto_depth(base, quote), f"{base}{quote}")
        return {"data": {**out, "base": base}, "fallback_from": failed, "source": out["venue"].lower()}

    return await svc._swr(f"w:cdep:{base}{quote}", DEPTH_TTL_S, fetch)


async def fund(svc: Any, sym: str) -> dict[str, Any]:
    try:
        base = cd.parse_base(sym)
    except ValueError as e:
        raise _bad(e) from e
    if not base:
        async def board() -> dict:
            rows, failed = await svc.router.call("crypto_funding", lambda p: p.crypto_funding())
            return {"data": {"mode": "BOARD", "rows": rows, "detail": None, "venue": rows[0]["source"].upper() if rows else None, "majors": list(cd.MAJORS)},
                    "fallback_from": failed, "source": rows[0]["source"] if rows else "binance_deriv"}

        return await svc._swr("w:fund:board", FUND_TTL_S, board)

    async def one() -> dict:
        out, failed = await svc.router.call("crypto_funding_detail", lambda p: p.crypto_funding_detail(base), base)
        return {"data": {"mode": "DETAIL", "rows": [out["row"]], "detail": out["history"], "venue": out["row"]["source"].upper(), "majors": list(cd.MAJORS)},
                "fallback_from": failed, "source": out["row"]["source"]}

    return await svc._swr(f"w:fund:{base}", FUND_TTL_S, one)


async def liq(svc: Any, sym: str) -> dict[str, Any]:
    try:
        base = cd.parse_base(sym) or "BTC"
    except ValueError as e:
        raise _bad(e) from e

    async def fetch() -> dict:
        out, failed = await svc.router.call("crypto_liq", lambda p: p.crypto_liq(base), base)
        agg = cd.aggregate_liquidations(out["events"])
        return {"data": {"base": base, "venue": "OKX", **agg, "ct_val": out["ct_val"],
                         "note": "OKX RETURNS ONLY THE LATEST FILLED LIQUIDATION ORDERS (ABOUT 100), NOT A FIXED WINDOW. BINANCE PUBLISHES NO LIQUIDATION HISTORY OVER REST."},
                "fallback_from": failed, "source": "okx"}

    return await svc._swr(f"w:liq:{base}", LIQ_TTL_S, fetch)


async def stbl(svc: Any, chain: str) -> dict[str, Any]:
    key = chain.strip()
    if len(key) > 24:
        raise DataError("bad_request", "CHAIN NAME TOO LONG")

    async def fetch() -> dict:
        out, failed = await svc.router.call("stablecoins", lambda p: p.stablecoins(key))
        return {"data": out, "fallback_from": failed, "source": "defillama"}

    return await svc._swr(f"w:stbl:{key.lower()}", LLAMA_TTL_S, fetch)


async def defi(svc: Any, q: str) -> dict[str, Any]:
    key = q.strip()
    if len(key) > 40:
        raise DataError("bad_request", "QUERY TOO LONG")

    async def pools() -> dict:
        out, failed = await svc.router.call("yields", lambda p: p.yields())
        return {"data": out, "fallback_from": failed, "source": "defillama"}

    env = await svc._swr("w:defi:pools", LLAMA_TTL_S, pools)  # the filtered list is cached once; the raw 11 MB answer is gone by now
    try:
        sel = cd.select_pools(env["data"], key)
    except Exception as e:  # ProviderError(not_found) from the selection
        kind = getattr(e, "kind", "")
        if kind == "not_found":
            raise DataError("not_found", str(e)) from e
        raise
    return {**env, "data": sel}
