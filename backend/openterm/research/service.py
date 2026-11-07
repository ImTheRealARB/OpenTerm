"""Phase 13 research functions on top of DataService: provider fallback through the router, SWR cache, one envelope.

Every method returns the standard envelope whose `data` is a table payload (research/table.py). Providers answer
ready-made payloads (parsing is pure and unit-tested), so this layer only chooses the provider order, the cache key and
the TTL. Router capability names live next to the adapters (providers/research_yahoo.py and friends).
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any, ClassVar

from ..errors import DataError
from ..providers.base import ProviderError
from ..redact import redact
from ..router import AllFailed
from ..service import envelope
from ..symbols import resolve
from . import cn
from . import corp_parse as cp
from . import fund_parse as fp
from . import valuation as vp

if TYPE_CHECKING:
    from ..service import DataService


class Research:
    TTL: ClassVar[dict[str, float]] = {
        "ee": 21600.0, "eeo": 21600.0, "anr": 21600.0, "mgmt": 86400.0, "dvd": 21600.0, "splt": 21600.0, "si": 21600.0,
        "ipo": 3600.0, "cn": 120.0,
        "etf": 21600.0, "memb": 21600.0, "mgr": 86400.0,
    }
    SYMBOL_FUNCTIONS: ClassVar[set[str]] = {"ee", "eeo", "anr", "mgmt", "dvd", "splt", "cacs", "si", "evts", "etf", "cn"}

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

        return await self.svc.swr(f"r:{name}:{symbol}", self.ttl(name), fetch)

    # --- EST: Yahoo quoteSummary --------------------------------------------------------------
    async def fn_ee(self, raw: str) -> dict:
        symbol = resolve(raw)
        return await self._symbol_call("ee", symbol, "estimates", lambda p: p.estimates(symbol))

    async def fn_eeo(self, raw: str) -> dict:
        symbol = resolve(raw)
        return await self._symbol_call("eeo", symbol, "surprises", lambda p: p.surprises(symbol))

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

    # --- CN: company news from every source that answers, scored by keyword ---------------------
    async def fn_cn(self, raw: str) -> dict:
        symbol = resolve(raw)
        router = self.svc.router

        async def one(p):
            try:
                return p, (await router.attempt(p, lambda prov: prov.news_symbol(symbol)))["items"], None
            except ProviderError as e:
                return p, [], e

        async def fetch() -> dict:
            # GDELT is left out: one call per 5 s and 8-12 s answers would hold the panel for every other source.
            live = [p for p in router.candidates("news_symbol", symbol) if p.name != "gdelt"]
            results = await asyncio.gather(*(one(p) for p in live))
            items = [i for _, found, _ in results for i in found]
            errors = [(p.name, e) for p, _, e in results if e is not None]
            answered = [p.name for p, found, e in results if e is None and found]
            if not answered:
                raise AllFailed(errors or [("news", ProviderError("not_found"))])
            failed = [n for n, e in errors if e.kind not in ("not_found", "unsupported")]
            missing = [
                {"key": p.key_name, "what": f"{p.name.upper()} COMPANY HEADLINES"}
                for n in ("finnhub", "alpaca") if (p := router.providers.get(n)) is not None and not p.has_key
            ]
            return {"data": cn.cn_payload(symbol, items, failed, missing, answered), "fallback_from": []}

        return await self.svc.swr(f"r:cn:{symbol}", self.ttl("cn"), fetch)

    # --- CORP: Nasdaq, Yahoo chart events, FINRA, SEC filings ---------------------------------
    async def _raw_call(self, symbol: str | None, capability: str, call):
        """One provider call outside the cache: (raw, failed provider names)."""
        return await self.svc.router.call(capability, call, symbol)

    async def fn_dvd(self, raw: str) -> dict:
        symbol = resolve(raw)

        async def fetch() -> dict:
            out, failed = await self._raw_call(symbol, "dividends", lambda p: p.dividends(symbol))
            return {"data": cp.dvd_payload(symbol, out), "fallback_from": failed}

        return await self.svc.swr(f"r:dvd:{symbol}", self.ttl("dvd"), fetch)

    async def fn_splt(self, raw: str) -> dict:
        symbol = resolve(raw)

        async def fetch() -> dict:
            out, failed = await self._raw_call(symbol, "splits", lambda p: p.splits(symbol))
            return {"data": cp.splt_payload(symbol, out), "fallback_from": failed}

        return await self.svc.swr(f"r:splt:{symbol}", self.ttl("splt"), fetch)

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

        return await self.svc.swr(f"r:cacs:{symbol}", self.ttl("dvd"), fetch)

    async def chart_events(self, raw: str) -> dict:
        """GP `EVT` markers: dividends, splits and the last four earnings dates, each part optional (a missing part is named)."""
        symbol = resolve(raw)

        async def fetch() -> dict:
            async def part(capability: str, call):
                try:
                    return (await self._raw_call(symbol, capability, call))[0], None
                except AllFailed as e:
                    return None, e

            (dvd, dvd_err), (splt, splt_err), (earn, earn_err) = await asyncio.gather(
                part("dividends", lambda p: p.dividends(symbol)), part("splits", lambda p: p.splits(symbol)),
                part("earnings_history", lambda p: p.earnings_history(symbol)))
            if dvd is None and splt is None and earn is None:
                raise dvd_err
            missing = [n for n, e in (("DIVIDENDS", dvd_err), ("SPLITS", splt_err), ("EARNINGS", earn_err))
                       if e is not None and e.kind != "not_found"]
            return {"data": cp.chart_events(symbol, dvd, splt, earn, missing), "fallback_from": []}

        return await self.svc.swr(f"r:events:{symbol}", self.ttl("dvd"), fetch)

    async def fn_ipo(self, month: str | None = None) -> dict:
        try:
            m = cp.valid_month(month)
        except ValueError as e:
            raise DataError("bad_request", str(e)) from e

        async def fetch() -> dict:
            out, failed = await self._raw_call(None, "ipo", lambda p: p.ipo(m))
            return {"data": cp.ipo_payload(m, out), "fallback_from": failed}

        return await self.svc.swr(f"r:ipo:{m}", self.ttl("ipo"), fetch)

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
                reasons = "; ".join(f"{n}: {redact(str(e))}" for n, e in vol.errors) or "NO PROVIDER"
                vol, note = None, f"FINRA DAILY SHORT VOLUME UNAVAILABLE ({reasons})"
            elif isinstance(vol, BaseException):
                raise vol
            if isinstance(ks, AllFailed):
                ks = None
            elif isinstance(ks, BaseException):
                raise ks
            return {"data": cp.si_payload(symbol, interest, vol, note, ks), "fallback_from": failed}

        return await self.svc.swr(f"r:si:{symbol}", self.ttl("si"), fetch)

    async def fn_evts(self, raw: str) -> dict:
        symbol = resolve(raw)
        env = await self.svc.filings(symbol, "8-K")
        d = env["data"]
        data = cp.evts_payload(symbol, d["filings"], d["total"], env.get("source") or "sec")
        return {**env, "data": data}


    # --- FUND: ETF, MEMB, MGR (Yahoo fund data, SEC N-PORT, SEC 13F-HR) --------------------------
    async def _fund(self, name: str, symbol: str, **kw) -> dict:
        async def fetch() -> dict:
            summary, failed = await self._raw_call(symbol, "fund_info", lambda p: p.fund(symbol))
            nport = None
            try:
                nport, _ = await self._raw_call(symbol, "etf_holdings", lambda p: p.holdings(symbol))
            except AllFailed as e:
                failed = [*failed, *(n for n, _ in e.errors)]
            source = nport["source"] if nport else "yahoo_research"
            return {"data": fp.etf_payload(symbol, summary, nport, source, **kw), "fallback_from": failed}

        return await self.svc.swr(f"r:{name}:{symbol}", self.ttl(name), fetch)

    async def fn_etf(self, raw: str) -> dict:
        return await self._fund("etf", resolve(raw))

    async def fn_memb(self, index: str | None = None) -> dict:
        key = (index or "").strip().upper()
        proxy = fp.INDEX_PROXY.get(key, key)
        usage = f"INDEX: {' '.join(fp.INDEX_PROXY)} OR AN ETF TICKER"
        if not key or not proxy.isalpha() or len(proxy) > 5:
            raise DataError("bad_request", usage)
        try:
            return await self._fund("memb", proxy, title_prefix="MEMB", proxy=proxy, index_label=key)
        except DataError as e:
            if e.kind == "not_found":
                raise DataError("bad_request", usage, e.detail) from e
            raise

    async def fn_mgr(self, manager: str | None = None) -> dict:
        key = (manager or "").strip()
        if not key:
            raise DataError("bad_request", "MANAGER: A NAME (" + " ".join(sorted(fp.MANAGERS)) + ") OR A CIK NUMBER")

        async def fetch() -> dict:
            out, failed = await self._raw_call(None, "manager_13f", lambda p: p.manager(key))
            now, before = out["now"], out["before"]
            rows = fp.diff_13f(now["table"], before["table"] if before else None)
            return {"data": fp.mgr_payload(key.upper(), out["name"], now, before, rows, out["source"]), "fallback_from": failed}

        return await self.svc.swr(f"r:mgr:{key.upper()}", self.ttl("mgr"), fetch)

    # --- VAL: DCF, WACC, RV ---------------------------------------------------------------------
    VALUATION: ClassVar[set[str]] = {"dcf", "wacc", "rv"}

    async def run_valuation(self, fn: str, symbol: str | None, query: dict[str, str]) -> dict:
        fn = fn.lower()
        if fn not in self.VALUATION:
            raise DataError("not_found", f"NO VALUATION FUNCTION {fn.upper()}")
        if not symbol:
            raise DataError("bad_request", "SYMBOL REQUIRED")
        try:
            params = vp.parse_params(query)
        except vp.ParamError as e:
            raise DataError("bad_request", str(e)) from e
        sym = resolve(symbol)
        data = await getattr(self, f"val_{fn}")(sym, params)
        return envelope({"data": data, "source": data["source"]}, time.time(), stale=False)

    async def _safe(self, awaitable):
        try:
            return await awaitable
        except (DataError, AllFailed) as e:
            return e

    async def _fin(self, symbol: str, period: str = "A"):
        r = await self._safe(self.svc.fundamentals(symbol, period))
        if isinstance(r, Exception):
            return None, str(getattr(r, "detail", None) or r)
        return vp.Fin(r["data"]), None

    async def _prices(self, symbols: list[str]) -> dict[str, float | None]:
        """One batched quote call for several symbols (separate concurrent calls raced on the quote cache)."""
        r = await self._safe(self.svc.quotes(symbols))
        if isinstance(r, Exception):
            return dict.fromkeys(symbols)
        return {s: (((r.get(s) or {}).get("data") or {}).get("price")) for s in symbols}

    async def _price(self, symbol: str) -> float | None:
        return (await self._prices([symbol]))[symbol]

    async def _market(self, symbol: str):
        """beta, risk-free rate, market cap, each as (value, source text)."""
        async def beta():
            out, _ = await self._raw_call(symbol, "keystats", lambda p: p.keystats(symbol))
            return cp.keystats_values(out)["beta"]

        async def rate():
            env = await self.svc.rates()
            d = env["data"]
            y = d["yields"][d["tenors"].index("10Y")]
            return (y / 100.0 if y is not None else None), d["date"]

        async def profile():
            return (await self.svc.profile(symbol))["data"].get("market_cap")

        b, r, m = await asyncio.gather(beta(), rate(), profile(), return_exceptions=True)
        b_out = (None, "Yahoo key statistics unavailable") if isinstance(b, BaseException) else (b, "Yahoo key statistics (beta)")
        r_out = (None, "US Treasury curve unavailable") if isinstance(r, BaseException) else (r[0], f"US Treasury 10Y par yield, {r[1]}")
        m_out = (None, "profile unavailable") if isinstance(m, BaseException) else (m, "profile market cap (Yahoo/Nasdaq)")
        return b_out, r_out, m_out

    async def val_wacc(self, symbol: str, p: dict) -> dict:
        (fin, err), (beta, rf, cap) = await asyncio.gather(self._fin(symbol), self._market(symbol))
        g = vp.gather(fin, err, beta, rf, cap, p)
        return vp.build_wacc(symbol, g, p, "sec + yahoo_research + treasury")

    async def val_dcf(self, symbol: str, p: dict) -> dict:
        (fin, err), (beta, rf, cap), price = await asyncio.gather(self._fin(symbol), self._market(symbol), self._price(symbol))
        g = vp.gather(fin, err, beta, rf, cap, p)
        return vp.build_dcf(symbol, g, p, price, "sec + yahoo_research + treasury")

    async def val_rv(self, symbol: str, p: dict) -> dict:
        peer_basis = "typed on the command line (PEERS=)"
        names = p.get("peers")
        if not names:
            env = await self._safe(self.svc.peers(symbol))
            names = [] if isinstance(env, Exception) else [x["symbol"] for x in env["data"]["peers"]][:6]
            peer_basis = "Yahoo recommended symbols, first six (PEERS= overrides)" if names else "none found"

        others = [n for n in names if n != symbol]
        prices = await self._prices([symbol, *others])

        async def one(sym: str, target: bool):
            price = prices.get(sym)
            (fa, err), (fq, _), cap_env = await asyncio.gather(
                self._fin(sym, "A"), self._fin(sym, "Q"), self._safe(self.svc.profile(sym)))
            if fa is None or fq is None:
                return sym, None, err or "no SEC quarterly data"
            cap = None if isinstance(cap_env, Exception) else cap_env["data"].get("market_cap")
            c, why = vp.company_inputs(sym, fa, fq, cap, price, target)
            return sym, c, why

        results = await asyncio.gather(one(symbol, True), *(one(n, False) for n in others))
        _, target, target_why = results[0]
        peers = [c for _, c, _ in results[1:] if c]
        skipped = {s: why for s, c, why in results[1:] if not c}
        return vp.build_rv(symbol, target, target_why, peers, skipped, prices.get(symbol), "sec + yahoo", peer_basis)
