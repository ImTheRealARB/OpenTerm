"""Phase 13 research functions on top of DataService: provider fallback through the router, SWR cache, one envelope.

Every method returns the standard envelope whose `data` is a table payload (research/table.py). Providers answer
ready-made payloads (parsing is pure and unit-tested), so this layer only chooses the provider order, the cache key and
the TTL. Router capability names live next to the adapters (providers/research_yahoo.py and friends).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, ClassVar

from ..router import AllFailed
from ..service import DataError
from ..symbols import resolve
from . import corp_parse as cp

if TYPE_CHECKING:
    from ..service import DataService


class Research:
    TTL: ClassVar[dict[str, float]] = {
        "ee": 21600.0, "eeo": 21600.0, "anr": 21600.0, "mgmt": 86400.0, "dvd": 21600.0, "splt": 21600.0, "si": 21600.0,
        "ipo": 3600.0,
    }
    SYMBOL_FUNCTIONS: ClassVar[set[str]] = {"ee", "eeo", "anr", "mgmt", "dvd", "splt", "cacs", "si", "evts"}

    EXTRA_PARAMS: ClassVar[dict[str, tuple[str, ...]]] = {"ipo": ("month",), "memb": ("index",), "mgr": ("manager",)}

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
        wanted = self.EXTRA_PARAMS.get(fn, ())
        return await method(**{k: v for k, v in params.items() if k in wanted and v is not None})

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

    # --- CORP: Nasdaq, Yahoo chart events, FINRA, SEC filings ---------------------------------
    async def _raw_call(self, symbol: str | None, capability: str, call):
        """One provider call outside the cache: (raw, failed provider names)."""
        return await self.svc.router.call(capability, call, symbol)

    async def fn_dvd(self, raw: str) -> dict:
        symbol = resolve(raw)

        async def fetch() -> dict:
            out, failed = await self._raw_call(symbol, "dividends", lambda p: p.dividends(symbol))
            return {"data": cp.dvd_payload(symbol, out), "fallback_from": failed}

        return await self.svc._swr(f"r:dvd:{symbol}", self.ttl("dvd"), fetch)

    async def fn_splt(self, raw: str) -> dict:
        symbol = resolve(raw)

        async def fetch() -> dict:
            out, failed = await self._raw_call(symbol, "splits", lambda p: p.splits(symbol))
            return {"data": cp.splt_payload(symbol, out), "fallback_from": failed}

        return await self.svc._swr(f"r:splt:{symbol}", self.ttl("splt"), fetch)

    async def fn_cacs(self, raw: str) -> dict:
        symbol = resolve(raw)

        async def fetch() -> dict:
            async def part(capability: str, call):
                try:
                    return (await self._raw_call(symbol, capability, call))[0], None
                except AllFailed as e:
                    return None, e

            (dvd, dvd_err), (splt, splt_err) = await asyncio.gather(
                part("dividends", lambda p: p.dividends(symbol)), part("splits", lambda p: p.splits(symbol)))
            if dvd is None and splt is None:
                raise dvd_err
            missing = [n for n, e in (("DIVIDENDS", dvd_err), ("SPLITS", splt_err)) if e is not None and e.kind != "not_found"]
            sources = [x["source"] for x in (dvd, splt) if x]
            return {"data": cp.cacs_payload(symbol, dvd, splt, missing, " + ".join(sources)), "fallback_from": []}

        return await self.svc._swr(f"r:cacs:{symbol}", self.ttl("dvd"), fetch)

    async def fn_ipo(self, month: str | None = None) -> dict:
        try:
            m = cp.valid_month(month)
        except ValueError as e:
            raise DataError("bad_request", str(e)) from e

        async def fetch() -> dict:
            out, failed = await self._raw_call(None, "ipo", lambda p: p.ipo(m))
            return {"data": cp.ipo_payload(m, out), "fallback_from": failed}

        return await self.svc._swr(f"r:ipo:{m}", self.ttl("ipo"), fetch)

    async def fn_si(self, raw: str) -> dict:
        symbol = resolve(raw)

        async def fetch() -> dict:
            interest, failed = await self._raw_call(symbol, "short_interest", lambda p: p.short_interest(symbol))

            async def keystats():
                out, _ = await self._raw_call(symbol, "keystats", lambda p: p.keystats(symbol))
                return cp.keystats_values(out)

            async def volume():
                return (await self._raw_call(symbol, "short_volume", lambda p: p.short_volume(symbol)))[0]

            ks, vol = await asyncio.gather(keystats(), volume(), return_exceptions=True)
            note = None
            if isinstance(vol, AllFailed):
                reasons = "; ".join(f"{n}: {e}" for n, e in vol.errors) or "NO PROVIDER"
                vol, note = None, f"FINRA DAILY SHORT VOLUME UNAVAILABLE ({reasons})"
            elif isinstance(vol, BaseException):
                raise vol
            if isinstance(ks, AllFailed):
                ks = None
            elif isinstance(ks, BaseException):
                raise ks
            return {"data": cp.si_payload(symbol, interest, vol, note, ks), "fallback_from": failed}

        return await self.svc._swr(f"r:si:{symbol}", self.ttl("si"), fetch)

    async def fn_evts(self, raw: str) -> dict:
        symbol = resolve(raw)
        env = await self.svc.filings(symbol, "8-K")
        d = env["data"]
        data = cp.evts_payload(symbol, d["filings"], d["total"], env.get("source") or "sec")
        return {**env, "data": data}
