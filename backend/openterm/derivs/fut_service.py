"""CT, WIRP and COT on top of DataService (a mixin of Derivs, see derivs/service.py): provider fallback through the router, SWR cache,
one envelope. Pure payload builders are in fut_tables.py, parsers in fut_parse.py."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any, ClassVar

from ..router import AllFailed
from ..service import DataError, envelope
from . import fut_parse as fp
from . import fut_tables as ft

if TYPE_CHECKING:
    from ..service import DataService

FUT_TTL: dict[str, float] = {"contract": 120.0, "cot": 21600.0, "cot_markets": 86400.0, "fomc": 86400.0, "wirp": 120.0}


class FuturesMixin:
    svc: DataService
    FUT_TTL: ClassVar[dict[str, float]] = FUT_TTL

    def fttl(self, name: str) -> float:
        return self.svc.ttl.get(f"d_{name}", FUT_TTL[name])

    # --- one futures contract -------------------------------------------------------------------
    async def contract(self, symbol: str) -> dict | None:
        """The quote of one contract, or None when Yahoo has no such contract (it is skipped, never invented)."""
        async def fetch() -> dict:
            out, failed = await self.svc.router.call("futures_contract", lambda p: p.futures_contract(symbol), symbol)
            return {"data": out, "fallback_from": failed}

        try:
            return (await self.svc._swr(f"d:fut:{symbol}", self.fttl("contract"), fetch))["data"]
        except (DataError, AllFailed):
            return None

    async def contracts(self, root: str) -> tuple[list[dict], list[str], int]:
        today = self.today()  # type: ignore[attr-defined]
        plan = fp.contract_symbols(root, today.year, today.month)
        quotes = await asyncio.gather(*(self.contract(s) for s, _, _ in plan))
        got = [{"symbol": s, "year": y, "month": m, "quote": q} for (s, y, m), q in zip(plan, quotes, strict=True) if q is not None]
        skipped = [s for (s, _, _), q in zip(plan, quotes, strict=True) if q is None]
        return got, skipped, len(plan)

    # --- CT -------------------------------------------------------------------------------------
    async def fn_ct(self, root: str | None = None, symbol: str | None = None, **_: Any) -> dict:
        r = (root or symbol or "").strip().upper()
        if not r or r not in fp.ROOTS:
            raise DataError("bad_request", f"CT NEEDS A ROOT: {' '.join(fp.ROOTS)}" if not r else f"UNKNOWN ROOT {r}. ROOTS: {' '.join(fp.ROOTS)}")
        got, skipped, planned = await self.contracts(r)
        if not got:
            raise DataError("not_found", f"NO {r} CONTRACTS FROM YAHOO", "every contract was skipped")
        source = got[0]["quote"]["source"]
        return envelope({"data": ft.ct_payload(r, planned, got, skipped, source), "source": source}, time.time(), stale=False)

    # --- WIRP -----------------------------------------------------------------------------------
    async def fomc_dates(self) -> list[str]:
        async def fetch() -> dict:
            out, failed = await self.svc.router.call("fomc_dates", lambda p: p.fomc_dates())
            return {"data": out, "fallback_from": failed}

        return (await self.svc._swr("d:fomc", self.fttl("fomc"), fetch))["data"]

    async def _fred_last(self, sid: str) -> dict | None:
        try:
            d = (await self.svc.fred_series(sid, "1Y"))["data"]
        except (DataError, AllFailed):
            return None
        return {"value": float(d["last_value"]), "date": str(d["last_date"])}

    async def fn_wirp(self, **_: Any) -> dict:
        today = self.today()  # type: ignore[attr-defined]
        iso = today.isoformat()
        got, skipped, _planned = await self.contracts("ZQ")
        if not got:
            raise DataError("not_found", "NO FED FUNDS FUTURES FROM YAHOO", "every ZQ contract was skipped")
        effr, lo, hi, dates = await asyncio.gather(self._fred_last("DFF"), self._fred_last("DFEDTARL"), self._fred_last("DFEDTARU"),
                                                   self.fomc_dates())
        if effr is None:
            raise DataError("not_found", "NO EFFECTIVE FED FUNDS RATE (FRED DFF)")
        implied = {(c["year"], c["month"]): 100.0 - c["quote"]["price"] for c in got}
        meetings = [d for d in dates if d > iso]
        path = ft.wirp_path(effr["value"], meetings, implied)
        months = [{"contract": c["symbol"].split(".")[0], "month": fp.label(c["year"], c["month"]), "price": c["quote"]["price"],
                   "implied": 100.0 - c["quote"]["price"], "vs_effr": (100.0 - c["quote"]["price"] - effr["value"]) * 100.0}
                  for c in got]
        source = f"{got[0]['quote']['source']} + fred_csv + fomc"
        data = ft.wirp_payload(effr, (lo["value"] if lo else None, hi["value"] if hi else None), meetings, path, months,
                               [s.split(".")[0] for s in skipped], source)
        return envelope({"data": data, "source": source}, time.time(), stale=False)

    # --- COT ------------------------------------------------------------------------------------
    async def cot_markets(self) -> list[dict]:
        async def fetch() -> dict:
            out, failed = await self.svc.router.call("cot_markets", lambda p: p.cot_markets())
            return {"data": out, "fallback_from": failed}

        return (await self.svc._swr("d:cot_markets", self.fttl("cot_markets"), fetch))["data"]

    async def resolve_cot(self, market: str) -> tuple[str, list[str]]:
        """(CFTC contract market code, other matching market names). Curated aliases first, then a substring search of the names."""
        key = market.strip().upper()
        if key in fp.COT_ALIASES:
            return fp.COT_ALIASES[key], []
        try:
            names = await self.cot_markets()
        except (DataError, AllFailed) as e:
            raise DataError("unavailable", f"CANNOT SEARCH CFTC MARKET NAMES FOR {key}", str(e)) from e
        hits = sorted({(x["market_and_exchange_names"], x["cftc_contract_market_code"]) for x in names
                       if key in x["market_and_exchange_names"].upper()}, key=lambda h: (len(h[0]), h[0]))
        if not hits:
            raise DataError("not_found", f"NO COT MARKET MATCHING {key}")
        return hits[0][1], [h[0] for h in hits[1:6]]

    async def fn_cot(self, market: str | None = None, symbol: str | None = None, **_: Any) -> dict:
        m = (market or symbol or "").strip()
        if not m:
            raise DataError("bad_request", "MARKET REQUIRED: ES NQ CL GC SI ZN EUR JPY BTC OR PART OF A CFTC MARKET NAME")
        code, others = await self.resolve_cot(m)

        async def fetch() -> dict:
            src: list[str] = []

            async def one(p):
                src.append(p.source)
                return await p.cot_history(code)

            out, failed = await self.svc.router.call("cot_history", one, code)
            return {"data": out, "source": src[-1], "fallback_from": failed}

        env = await self.svc._swr(f"d:cot:{code}", self.fttl("cot"), fetch)
        rows = [fp.cot_row(r) for r in env["data"]]
        source = env.get("source") or "cftc"
        data = ft.cot_payload(rows, others, source)
        return {**env, "data": data, "source": source}
