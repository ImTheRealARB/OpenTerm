"""Phase 13 research functions on top of DataService: provider fallback through the router, SWR cache, one envelope.

Every method returns the standard envelope whose `data` is a table payload (research/table.py). Providers answer
ready-made payloads (parsing is pure and unit-tested), so this layer only chooses the provider order, the cache key and
the TTL. Router capability names live next to the adapters (providers/research_yahoo.py and friends).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from ..service import DataError
from ..symbols import resolve

if TYPE_CHECKING:
    from ..service import DataService


class Research:
    TTL: ClassVar[dict[str, float]] = {
        "ee": 21600.0, "eeo": 21600.0, "anr": 21600.0, "mgmt": 86400.0,
    }
    SYMBOL_FUNCTIONS: ClassVar[set[str]] = {"ee", "eeo", "anr", "mgmt"}

    def __init__(self, svc: DataService):
        self.svc = svc

    def ttl(self, name: str) -> float:
        return self.svc.ttl.get(f"r_{name}", self.TTL.get(name, 3600.0))

    async def run(self, fn: str, **params: Any) -> dict:
        """Dispatch for GET /api/research/{fn}."""
        fn = fn.lower()
        method = getattr(self, f"fn_{fn}", None)
        if method is None:
            raise DataError("not_found", f"NO RESEARCH FUNCTION {fn.upper()}")
        if fn in self.SYMBOL_FUNCTIONS:
            if not params.get("symbol"):
                raise DataError("bad_request", "SYMBOL REQUIRED")
            return await method(params["symbol"])
        return await method(**{k: v for k, v in params.items() if k != "symbol"})

    async def _symbol_call(self, name: str, symbol: str, capability: str, call) -> dict:
        async def fetch() -> dict:
            out, failed = await self.svc.router.call(capability, call, symbol)
            return {"data": out, "fallback_from": failed}

        return await self.svc._swr(f"r:{name}:{symbol}", self.ttl(name), fetch)

    # --- EST: Yahoo quoteSummary --------------------------------------------------------------
    async def fn_ee(self, raw: str) -> dict:
        symbol = resolve(raw)
        return await self._symbol_call("ee", symbol, "estimates", lambda p: p.estimates(symbol))

    async def fn_eeo(self, raw: str) -> dict:
        symbol = resolve(raw)
        return await self._symbol_call("eeo", symbol, "estimates", lambda p: p.eeo(symbol))

    async def fn_anr(self, raw: str) -> dict:
        symbol = resolve(raw)
        return await self._symbol_call("anr", symbol, "ratings", lambda p: p.ratings(symbol))

    async def fn_mgmt(self, raw: str) -> dict:
        symbol = resolve(raw)
        proxies: list[dict] = []
        try:  # DEF 14A links come from the SEC filings feed; a non-US listing simply has none
            env = await self.svc.filings(symbol, "DEF 14A")
            proxies = env["data"]["filings"][:5]
        except DataError:
            pass
        return await self._symbol_call("mgmt", symbol, "officers", lambda p: p.officers(symbol, proxies))
