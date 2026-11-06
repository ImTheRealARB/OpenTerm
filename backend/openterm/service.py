"""Data service: stale-while-revalidate over the cache, request coalescing, batch quotes.

Every response is an envelope: {data, source, as_of, age_s, stale, fallback_from}.
A stale envelope is served instantly and refreshed in the background; it is never dressed up as fresh.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar

from .bt.localdata import LocalData, LocalError
from .cache import Cache
from .news_tags import Filters, item_matches, validate
from .providers.base import ProviderError
from .providers.crypto import VS
from .providers.news import merge
from .providers.sec import US_ONLY, sec_ticker, store_from  # Phase 6
from .ranges import normalize
from .router import AllFailed, Router
from .symbols import resolve

log = logging.getLogger("openterm.service")

INTRADAY = {"1m", "2m", "5m", "15m", "30m", "60m", "90m"}


class DataError(Exception):
    """kind: bad_request | not_found | unavailable | key_required. `detail` names each provider's reason;
    `key` names the missing key (key_required only)."""

    def __init__(self, kind: str, message: str, detail: str | None = None, key: str | None = None):
        super().__init__(message)
        self.kind = kind
        self.detail = detail
        self.key = key


def envelope(value: dict, stored_at: float, stale: bool) -> dict:
    """value is the cached form: {"data": ..., "fallback_from": [...], optional "source"}."""
    data = value["data"]
    return {
        "data": data,
        "source": value.get("source") or (data.get("source") if isinstance(data, dict) else None),
        "as_of": stored_at,
        "age_s": round(time.time() - stored_at, 2),
        "stale": stale,
        "fallback_from": value.get("fallback_from", []),
        **({"fallback_notes": value["fallback_notes"]} if value.get("fallback_notes") else {}),
    }


class DataService:
    def __init__(self, router: Router, cache: Cache, ttl: dict[str, float] | None = None):
        self.router = router
        self.local: LocalData | None = None  # IMPORT: set by the lifespan (bars the user imported)
        self.research = None  # Phase 13 research functions: set by the lifespan (research/service.py)
        self.derivs = None  # Phase 14 options, rates and futures: set by the lifespan (derivs/service.py)
        self.rates_views = None  # Phase 14 RATES views (EUR, GBP, CAD, JPY, SPRD, AUCT, NS): set by the lifespan (rates/service.py)
        self.cache = cache
        self.ttl = {
            "quote": 5.0, "intraday": 60.0, "daily": 3600.0, "search": 86400.0, "profile": 86400.0,
            "news": 120.0, "movers": 60.0, "crypto": 60.0, **(ttl or {}),
        }
        self._inflight: dict[str, asyncio.Future] = {}
        self.rest_at: dict[str, float] = {}  # quote key -> when its REST snapshot was fetched (ticks refresh the price, not this)
        self._bg: set[asyncio.Task] = set()
        self.fresh_hits = 0
        self.stale_hits = 0
        self.misses = 0

    # --- coalescing -------------------------------------------------------------------------
    async def _once(self, key: str, fetch: Callable[[], Awaitable[dict]]) -> dict:
        """Concurrent callers for the same key share one upstream request.
        The fetch runs in its own task, so cancelling the first caller (a closed browser tab)
        cannot hand CancelledError to the callers waiting on the same key."""
        fut = self._inflight.get(key)
        if fut is None:
            fut = asyncio.get_running_loop().create_future()
            self._inflight[key] = fut

            async def work() -> None:
                try:
                    value = await fetch()
                    self.cache.put(key, value)
                    fut.set_result(value)
                except BaseException as e:  # noqa: BLE001 - forwarded to every waiter
                    fut.set_exception(e)
                    fut.exception()  # mark retrieved so a lone background refresh doesn't warn
                finally:
                    del self._inflight[key]

            self._background(work())  # keeps a reference so the task is not garbage collected
        return await asyncio.shield(fut)

    def _background(self, coro: Awaitable) -> None:
        task = asyncio.ensure_future(coro)
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)

    async def _refresh_quiet(self, key: str, fetch: Callable[[], Awaitable[dict]]) -> None:
        try:
            await self._once(key, fetch)
        except Exception as e:  # noqa: BLE001 - background refresh: stale data stays visible
            log.info("background refresh of %s failed: %s", key, e)

    async def _swr(self, key: str, ttl: float, fetch: Callable[[], Awaitable[dict]]) -> dict:
        entry = await self.cache.get(key)
        if entry is not None:
            value, stored_at = entry
            if time.time() - stored_at < ttl:
                self.fresh_hits += 1
                return envelope(value, stored_at, stale=False)
            self.stale_hits += 1
            if key not in self._inflight:
                self._background(self._refresh_quiet(key, fetch))
            return envelope(value, stored_at, stale=True)
        self.misses += 1
        try:
            value = await self._once(key, fetch)
        except AllFailed as e:
            detail = "; ".join(f"{name}: {err.kind} ({err})" for name, err in e.errors) or None
            raise DataError(e.kind if e.kind != "unsupported" else "not_found", str(e), detail, e.key) from e
        return envelope(value, self.cache.mem[key][1] if key in self.cache.mem else time.time(), stale=False)

    # --- public API ---------------------------------------------------------------------------
    async def history(self, raw_symbol: str, range_: str | None, interval: str | None) -> dict:
        symbol = resolve(raw_symbol)
        try:
            r, i = normalize(range_, interval)
        except ValueError as e:
            raise DataError("bad_request", str(e)) from e
        if self.local is not None and symbol in self.local.symbols:  # IMPORT: the user's own bars win, labelled LOCAL DATA
            try:
                data, imported_at = await self.local.history(symbol, r, i)
            except LocalError as e:
                raise DataError("bad_request", str(e)) from e
            return envelope({"data": data, "source": "local"}, imported_at, stale=False)
        ttl = self.ttl["intraday"] if i in INTRADAY else self.ttl["daily"]

        async def fetch() -> dict:
            bars, failed = await self.router.call("history", lambda p: p.history(symbol, r, i), symbol)
            return {"data": bars.model_dump(), "fallback_from": failed, "fallback_notes": self._notes(failed)}

        # A Kite login changes who answers Indian symbols, so the cache key names the key-gated sources that
        # are in the chain right now (otherwise Yahoo's cached bars would be served for an hour after adding a key).
        # Only a source that can really answer counts: an expired login must not share a cache key with a valid one (audit A-3).
        gated = "".join(f":{p.name[0]}" for p in self.router.candidates("history", symbol) if p.name in ("kite",) and p.why_down() is None)
        return await self._swr(f"h:{symbol}:{r}:{i}{gated}", ttl, fetch)

    async def profile(self, raw_symbol: str) -> dict:
        symbol = resolve(raw_symbol)

        async def fetch() -> dict:
            prof, failed = await self.router.call("profile", lambda p: p.profile(symbol), symbol)
            return {"data": prof.model_dump(), "fallback_from": failed}

        return await self._swr(f"p:{symbol}", self.ttl["profile"], fetch)

    async def news(self, symbol: str | None = None, query: str | None = None, filters: Filters | None = None, limit: int | None = None) -> dict:
        """Symbol headlines, a keyword search, or (neither) the market top stories.

        With `filters` (region / sector / commodity / section, optionally text) it is instead the pooled headlines of the
        curated feed table, filtered. `limit` trims the answer after caching, so every caller shares one cache entry.
        """
        if filters and filters.active:
            env = await self._news_pool(filters)
        else:
            env = await self._news_single(symbol, query)
        if limit and limit > 0:
            env = {**env, "data": {**env["data"], "items": env["data"]["items"][:limit]}}
        return env

    async def _news_pool(self, f: Filters) -> dict:
        """Pooled headlines from the feed table: fetch (per-feed cache inside the provider), filter, de-duplicate."""
        if problem := validate(f):
            raise DataError("bad_request", problem)

        async def fetch() -> dict:
            out, failed_sources = await self.router.call("news_pool", lambda p: p.news_pool(f.section), None)
            items = merge([i for feed, found in out["pool"] for i in found if item_matches(i.title, i.summary, feed, f)])
            return {
                "data": {
                    "kind": "pool", "query": f.q, "items": [i.model_dump() for i in items], "failed": out["failed"],
                    "feeds_ok": out["total"] - len(out["failed"]), "feeds_total": out["total"], "filters": f._asdict(),
                },
                "source": "rss", "fallback_from": failed_sources,
            }

        # Tech and crypto feeds move fastest, so their answers are kept 30 s; the rest 60 s.
        ttl = 30.0 if f.section in ("tech", "crypto") else 60.0
        return await self._swr("n:pool:" + "|".join(str(v) for v in f), ttl, fetch)

    async def _news_single(self, symbol: str | None, query: str | None) -> dict:
        if symbol and symbol.strip():
            kind, arg = "symbol", resolve(symbol)
            cap, call = "news_symbol", lambda p: p.news_symbol(arg)
        elif query and query.strip():
            kind, arg = "keyword", " ".join(query.split()).upper()
            if len(arg) < 2:
                raise DataError("bad_request", "SEARCH NEEDS 2+ CHARACTERS")
            cap, call = "news_keyword", lambda p: p.news_keyword(arg)
        else:
            kind, arg = "top", None
            cap, call = "news_top", lambda p: p.news_top()

        async def fetch() -> dict:
            # Phase 13: a keyed source (Finnhub, Alpaca) adds its headlines to the first keyless answer instead of
            # waiting to be a fallback. Without a key it does not support the capability and nothing changes.
            extras = [p for p in self.router.candidates(cap, arg) if getattr(p, "has_key", False)] if kind != "keyword" else []
            extra_results = await asyncio.gather(*(self._extra_news(p, call) for p in extras)) if extras else []
            try:
                out, failed = await self.router.call(cap, call, arg)
            except AllFailed:
                if not any(items for items, _ in extra_results):
                    raise
                out, failed = {"items": [], "failed": []}, []
            items = [*out["items"], *(i for found, _ in extra_results for i in found)]
            feeds = [*out["failed"], *(n.upper() for _, n in extra_results if n)]
            if extra_results:
                items = merge(items)
            return {
                "data": {"kind": kind, "query": arg, "items": [i.model_dump() for i in items], "failed": feeds},
                "source": "+".join(sorted({i.source.split(":")[0] for i in items})) if extra_results else (items[0].source if items else None),
                "fallback_from": failed,
            }

        try:
            return await self._swr(f"n:{kind}:{arg or ''}", self.ttl["news"], fetch)
        except DataError as e:
            if e.kind != "not_found":
                raise
            raise DataError("not_found", "NO HEADLINES FOUND", e.detail) from e

    async def _extra_news(self, provider, call) -> tuple[list, str | None]:
        """One keyed news source: (its items, None) or ([], its name when it failed)."""
        try:
            return (await self.router._attempt(provider, call))["items"], None
        except ProviderError:
            return [], provider.name

    async def movers(self) -> dict:
        async def fetch() -> dict:
            m, failed = await self.router.call("movers", lambda p: p.movers())
            return {"data": m.model_dump(), "fallback_from": failed}

        return await self._swr("mv:us", self.ttl["movers"], fetch)

    async def crypto(self, vs: str = "USD") -> dict:
        vs = vs.strip().upper()
        if vs not in VS:
            raise DataError("bad_request", f"QUOTE CURRENCY: {' '.join(sorted(VS))}")

        async def fetch() -> dict:
            coins, failed = await self.router.call("crypto", lambda p: p.crypto(vs), vs)
            return {
                "data": {"vs": vs, "coins": [c.model_dump() for c in coins]},
                "source": coins[0].source if coins else None,
                "fallback_from": failed,
            }

        return await self._swr(f"c:{vs}", self.ttl["crypto"], fetch)

    # Tick source code (see streaming/tick.py) -> the name shown as the quote's source. "p" is the REST poller: its tick
    # is built from a REST quote, so the quote already carries the right source.
    TICK_SOURCES: ClassVar[dict[str, str]] = {"y": "yahoo:stream", "a": "alpaca:iex", "k": "kite:ticker", "s": "synthetic"}
    # A streamed symbol keeps a fresh price, but a tick often has no volume or day range (Alpaca IEX never does), so the
    # full REST quote is re-fetched in the background at least this often to renew volume, high, low and previous close.
    REST_REFRESH_S = 60.0

    def apply_tick(self, tick) -> None:
        """Fold a streamed tick into the cached quote so REST snapshots match the stream."""
        key = f"q:{tick.symbol}"
        entry = self.cache.mem.get(key)
        if entry is None:
            return
        value, _ = entry
        q = value["data"]
        q["price"] = tick.price
        for k, v in (("change", tick.change), ("change_pct", tick.change_pct), ("volume", tick.volume),
                     ("high", tick.high), ("low", tick.low)):
            if v is not None:
                q[k] = v
        # A tick that brings no day range must still not leave the price outside the stored range.
        if tick.high is None and isinstance(q.get("high"), int | float) and tick.price > q["high"]:
            q["high"] = tick.price
        if tick.low is None and isinstance(q.get("low"), int | float) and tick.price < q["low"]:
            q["low"] = tick.price
        q["market_time"] = tick.time_ms // 1000
        q["as_of"] = time.time()
        name = self.TICK_SOURCES.get(tick.source)
        if name:
            q["source"] = name
        self.cache.mem[key] = (value, time.time())  # the price is fresh; `rest_at` remembers when the rest was fetched

    async def search(self, query: str) -> dict:
        q = query.strip().upper()
        if not q:
            raise DataError("bad_request", "EMPTY QUERY")

        async def fetch() -> dict:
            hits, failed = await self.router.call("search", lambda p: p.search(q))
            return {
                "data": [h.model_dump() for h in hits],
                "source": hits[0].source if hits else None,
                "fallback_from": failed,
            }

        return await self._swr(f"s:{q}", self.ttl["search"], fetch)

    def _notes(self, failed: list[str]) -> dict[str, str]:
        """{provider: reason} for the sources that were skipped for a reason worth saying ("KITE LOGIN EXPIRED: run KITE LOGIN")."""
        out = {}
        for n in failed:
            p = self.router.providers.get(n)
            why = p.why_down() if p is not None else None
            if why:
                out[n] = why
        return out

    async def quotes(self, raw_symbols: list[str]) -> dict[str, dict[str, Any]]:
        """Returns {requested symbol: envelope | {"error", "kind"}}. Missing/stale ones are batched upstream."""
        symbols = {raw: resolve(raw) for raw in raw_symbols}
        out: dict[str, dict] = {}
        need: list[str] = []
        stale: list[str] = []
        found = await self.cache.get_many([f"q:{s}" for s in symbols.values()])  # one SQLite query for every memory miss
        for raw, s in symbols.items():
            entry = found.get(f"q:{s}")
            if entry is None:
                self.misses += 1
                need.append(s)
                continue
            value, stored_at = entry
            now = time.time()
            is_stale = now - stored_at >= self.ttl["quote"]
            if is_stale:
                self.stale_hits += 1
                stale.append(s)
            else:
                self.fresh_hits += 1
                if now - self.rest_at.get(f"q:{s}", stored_at) >= self.REST_REFRESH_S:
                    stale.append(s)  # streamed price is fresh; renew volume / high / low / previous close in the background
            out[raw] = envelope(value, stored_at, is_stale)
        if stale:
            self._background(self._fetch_quotes(stale, quiet=True))
        if need:
            results = await self._fetch_quotes(list(dict.fromkeys(need)))
            for raw, s in symbols.items():
                if raw in out:
                    continue
                r = results.get(s)
                if isinstance(r, dict):
                    entry = self.cache.mem.get(f"q:{s}")
                    out[raw] = envelope(r, entry[1] if entry else time.time(), stale=False)
                else:
                    kind = getattr(r, "kind", "unavailable")
                    out[raw] = {"error": str(r) if r else "NO DATA FOR SYMBOL", "kind": kind, "symbol": s}
        return out

    async def _fetch_quotes(self, symbols: list[str], quiet: bool = False) -> dict[str, Any]:
        """Coalesced per symbol: symbols already in flight are awaited, the rest go out as one batch."""
        futures: dict[str, asyncio.Future] = {}
        mine: list[str] = []
        loop = asyncio.get_running_loop()
        for s in symbols:
            key = f"q:{s}"
            if key in self._inflight:
                futures[s] = self._inflight[key]
            else:
                fut = loop.create_future()
                self._inflight[key] = futures[s] = fut
                mine.append(s)
        if mine:
            try:
                found, errors = await self.router.quotes(mine)
                for s in mine:
                    fut = futures[s]
                    if s in found:
                        q, failed = found[s]
                        value = {"data": q.model_dump(), "fallback_from": failed, "fallback_notes": self._notes(failed)}
                        self.cache.put(f"q:{s}", value)
                        self.rest_at[f"q:{s}"] = time.time()
                        fut.set_result(value)
                    else:
                        fut.set_exception(errors[s])
                        fut.exception()
            except BaseException as e:
                for s in mine:
                    if not futures[s].done():
                        futures[s].set_exception(e)
                        futures[s].exception()
                if not quiet:
                    raise
            finally:
                for s in mine:
                    self._inflight.pop(f"q:{s}", None)
        results = await asyncio.gather(*(asyncio.shield(f) for f in futures.values()), return_exceptions=True)
        return dict(zip(futures.keys(), results))

    def stats(self) -> dict:
        total = self.fresh_hits + self.stale_hits + self.misses
        return {
            "fresh_hits": self.fresh_hits,
            "stale_hits": self.stale_hits,
            "misses": self.misses,
            "hit_pct": (self.fresh_hits + self.stale_hits) / total * 100 if total else None,
            "inflight": len(self._inflight),
            "mem_entries": len(self.cache.mem),
        }

    # --- Phase 6: SEC fundamentals, filings, insiders; Yahoo holders ---------------------------
    PHASE6_TTL: ClassVar[dict[str, float]] = {"facts": 21600.0, "filings": 900.0, "insiders": 3600.0, "holders": 21600.0}
    FILINGS_MAX = 300

    async def _sec(self, key: str, ttl: str, cap: str, symbol: str, call) -> dict:
        async def fetch() -> dict:
            out, failed = await self.router.call(cap, call, symbol)
            return {"data": out, "fallback_from": failed}

        try:
            return await self._swr(key, self.ttl.get(ttl, self.PHASE6_TTL[ttl]), fetch)
        except DataError as e:
            not_filer = sec_ticker(symbol) is None or "no SEC filer" in (e.detail or "")
            if e.kind == "not_found" and cap != "holders" and not_filer:
                raise DataError("not_found", US_ONLY, e.detail or f"{symbol}: not an SEC filer") from e
            raise

    async def fundamentals(self, raw_symbol: str, period: str = "A") -> dict:
        """FA. One upstream call (company facts) serves both views; the envelope carries only `period`."""
        period = (period or "A").strip().upper()
        if period not in ("A", "Q"):
            raise DataError("bad_request", "PERIOD: A (ANNUAL) OR Q (QUARTERLY)")
        symbol = resolve(raw_symbol)
        env = await self._sec(f"fa:{symbol}", "facts", "fundamentals", symbol, lambda p: p.fundamentals(symbol))
        d = env["data"]
        view = {k: v for k, v in d.items() if k not in ("A", "Q")}
        return {**env, "data": {**view, "period": period, **d[period]}}

    async def filings(self, raw_symbol: str, form: str | None = None) -> dict:
        """FIL. `form` filters exactly (10-K also matches 10-K/A)."""
        symbol = resolve(raw_symbol)
        env = await self._sec(f"fil:{symbol}", "filings", "filings", symbol, lambda p: p.filings(symbol))
        want = (form or "").strip().upper()
        rows = env["data"]["filings"]
        if want:
            rows = [f for f in rows if f["form"].upper() in (want, f"{want}/A")]
        total = len(rows)
        return {**env, "data": {**env["data"], "form": want or None, "total": total, "filings": rows[: self.FILINGS_MAX]}}

    async def insiders(self, raw_symbol: str) -> dict:
        """OWN. Form 4s parsed once per accession and kept in the cache table for good (filings are immutable)."""
        symbol = resolve(raw_symbol)
        store = store_from(self.cache.get, self.cache.put)
        return await self._sec(f"own:{symbol}", "insiders", "insiders", symbol, lambda p: p.insiders(symbol, store))

    async def holders(self, raw_symbol: str) -> dict:
        symbol = resolve(raw_symbol)
        return await self._sec(f"hds:{symbol}", "holders", "holders", symbol, lambda p: p.holders(symbol))

    # --- Phase 7: macro (FRED, MACRO list/search, RATES curve, ERN, ECO) ------------------------
    def _ttl7(self, name: str, default: float) -> float:
        if name in self.ttl:
            return self.ttl[name]
        return float((load_yaml().get("cache") or {}).get(f"{name}_ttl_s", default))

    def fred_key_set(self) -> bool:
        p = self.router.providers.get("fred")
        return bool(getattr(p, "has_key", False))

    async def fred_series(self, raw_id: str, range_: str | None = None) -> dict:
        sid = (raw_id or "").strip().upper()
        if not _macro.SERIES_ID.match(sid):
            raise DataError("bad_request", "SERIES ID: LETTERS, DIGITS, _ AND . (E.G. UNRATE)")
        r = (range_ or _macro.FRED_DEFAULT_RANGE).strip().upper()
        if r not in _macro.FRED_RANGES:
            raise DataError("bad_request", f"BAD RANGE: {r}. USE {' '.join(_macro.FRED_RANGES)}")
        start = _macro.range_start(r)

        async def fetch() -> dict:
            s, failed = await self.router.call("fred_series", lambda p: p.fred_series(sid, start), sid)
            return {"data": {**s.model_dump(), "range": r, "key_set": self.fred_key_set()}, "fallback_from": failed}

        try:
            return await self._swr(f"fred:{sid}:{r}", self._ttl7("fred", 3600), fetch)
        except DataError as e:
            if e.kind != "not_found":
                raise
            raise DataError("not_found", f"NO FRED SERIES {sid}", e.detail) from e

    async def macro(self, query: str | None = None) -> dict:
        """With FRED_API_KEY and a query: FRED search. Otherwise the curated list with latest values; a query then
        filters that list locally and the envelope carries needs_key so the panel can say search needs the key."""
        q = " ".join((query or "").split())
        if len(q) > 80:
            raise DataError("bad_request", "QUERY TOO LONG")
        key = self.fred_key_set()
        if q and key:
            async def fetch() -> dict:
                rows, failed = await self.router.call("fred_search", lambda p: p.fred_search(q), q)
                return {"data": {"mode": "search", "query": q, "needs_key": None, "rows": rows},
                        "source": self.router.providers["fred"].source, "fallback_from": failed}

            try:
                return await self._swr(f"macro:q:{q.upper()}", self._ttl7("fred_search", 86400), fetch)
            except DataError as e:
                if e.kind != "not_found":
                    raise
                raise DataError("not_found", f"NO FRED SERIES MATCH {q.upper()}", e.detail) from e

        wanted = [str(x).upper() for x in ((load_yaml().get("macro") or {}).get("curated") or [])] or [
            c[0] for c in _macro.CURATED]
        if q:
            ql = q.lower()
            wanted = [i for i in wanted if ql in " ".join(map(str, _macro.CURATED_META.get(i, (i,)))).lower()]
        results = await asyncio.gather(*(self.fred_series(i) for i in wanted), return_exceptions=True)
        rows, sources, ages, stale, fallback = [], [], [], False, set()
        for sid, env in zip(wanted, results):
            meta = _macro.CURATED_META.get(sid)
            row = {"id": sid, "label": meta[1] if meta else sid, "title": meta[2] if meta else None,
                   "units": meta[3] if meta else None, "frequency": meta[4] if meta else None}
            if isinstance(env, BaseException):
                row["error"] = str(env)
            else:
                d = env["data"]
                row.update(title=d.get("title") or row["title"], units=d.get("units") or row["units"],
                           frequency=d.get("frequency") or row["frequency"], last_value=d["last_value"],
                           last_date=d["last_date"], prev_value=d.get("prev_value"), change=d.get("change"),
                           source=env["source"], age_s=env["age_s"], stale=env["stale"])
                sources.append(env["source"])
                ages.append((env["as_of"], env["age_s"]))
                stale = stale or env["stale"]
                fallback.update(env["fallback_from"])
            rows.append(row)
        if wanted and not sources:
            first = next((r for r in results if isinstance(r, DataError)), None)
            raise DataError("unavailable", "PROVIDER DOWN", first.detail if first else None)
        oldest = min(ages) if ages else (time.time(), 0.0)
        return {
            "data": {"mode": "curated", "query": q or None, "needs_key": None if key else "FRED_API_KEY", "rows": rows},
            "source": sources[0] if sources else None, "as_of": oldest[0], "age_s": oldest[1], "stale": stale,
            "fallback_from": sorted(fallback),
        }

    async def rates(self) -> dict:
        async def fetch() -> dict:
            c, failed = await self.router.call("yield_curve", lambda p: p.yield_curve())
            return {"data": c.model_dump(), "fallback_from": failed}

        return await self._swr("rates:us", self._ttl7("rates", 1800), fetch)

    async def earnings(self, day: str | None = None) -> dict:
        today = _macro.ny_today()
        try:
            d = date.fromisoformat(day.strip()) if day and day.strip() else today
        except ValueError as e:
            raise DataError("bad_request", "DATE: YYYY-MM-DD") from e
        if abs((d - today).days) > 400:
            raise DataError("bad_request", "DATE MUST BE WITHIN 400 DAYS OF TODAY")

        async def fetch() -> dict:
            out, failed = await self.router.call("earnings", lambda p: p.earnings(d))
            return {"data": out, "fallback_from": failed}

        return await self._swr(f"ern:{d.isoformat()}", self._ttl7("earnings", 900), fetch)

    async def eco(self, start: str | None = None, days: int = 14) -> dict:
        try:
            s = date.fromisoformat(start.strip()) if start and start.strip() else _macro.ny_today()
        except ValueError as e:
            raise DataError("bad_request", "DATE: YYYY-MM-DD") from e
        if not 1 <= days <= 62:
            raise DataError("bad_request", "DAYS: 1-62")

        async def fetch() -> dict:
            since = _macro.ny_today() - timedelta(days=62)
            out, failed = await self.router.call("eco_calendar", lambda p: p.eco_calendar(since))
            events = [e.model_dump() for e in out["events"]]
            notes: list[str] = []
            try:  # Phase 19: the Fed's own FOMC decision dates (Phase 14 provider) join the calendar; the page being down is said, not hidden
                from .world.fomc_eco import fomc_events

                if getattr(self, "derivs", None) is None:
                    raise DataError("unavailable", "no futures service")
                have = {(e["date"], e["agency"]) for e in events}
                events += [e for e in fomc_events(await self.derivs.fomc_dates(), since.isoformat()) if (e["date"], e["agency"]) not in have]
            except (AllFailed, DataError):
                notes.append("FOMC: STALE (federalreserve.gov DID NOT ANSWER)")
            events.sort(key=lambda e: (e["ts"], e["agency"], e["name"]))
            return {"data": {"events": events, "failed": out["failed"], "notes": notes},
                    "source": events[0]["source"] if events else None, "fallback_from": failed}

        env = await self._swr("eco:us", self._ttl7("eco", 21600), fetch)
        lo, hi = s.isoformat(), (s + timedelta(days=days)).isoformat()
        events = env["data"]["events"]
        env["data"] = {
            "start": lo, "days": days, "events": [e for e in events if lo <= e["date"] < hi],
            "failed": env["data"]["failed"], "notes": env["data"].get("notes", []), "coverage_end": max((e["date"] for e in events), default=None),
            "key_set": self.fred_key_set(),
        }
        return env

    # --- Phase 9: screener (EQS) and peers (COMP) ---
    async def screener(self) -> dict:
        """The whole US universe as one columnar table (see providers/screener.py). Filtered in the browser."""

        async def fetch() -> dict:
            data, failed = await self.router.call("screener", lambda p: p.screener())
            return {"data": data, "fallback_from": failed}

        return await self._swr("scr:us", self.ttl.get("screener", 900.0), fetch)

    async def peers(self, raw_symbol: str, limit: int = 10) -> dict:
        """Yahoo recommended symbols; if none, the largest same-industry names from the screener (US only)."""
        symbol = resolve(raw_symbol)

        async def fetch() -> dict:
            peers: list[dict] = []
            failed: list[str] = []
            errors: list[str] = []
            basis, source = "yahoo", None
            try:
                found, failed = await self.router.call("peers", lambda p: p.peers(symbol), symbol)
                peers = [p for p in found["peers"] if p["symbol"] != symbol][:limit]
                source = found["source"]
            except AllFailed as e:
                failed = [n for n, _ in e.errors]
                errors = [f"{n}: {err.kind} ({err})" for n, err in e.errors]
            uni = None
            try:
                uni = (await self.screener())["data"]
            except DataError as e:
                errors.append(f"screener: {e.kind} ({e})")
            by_sym = {r[0]: r for r in uni["rows"]} if uni else {}

            def info(sym: str) -> dict:
                r = by_sym.get(sym)
                if r is None:
                    return {"name": None, "market_cap": None, "sector": None, "industry": None}
                return {"name": r[1], "market_cap": r[6], "sector": uni["sectors"][r[9]] or None,
                        "industry": uni["industries"][r[10]] or None}

            me = by_sym.get(symbol)
            if not peers:
                if me is None or not me[10]:
                    raise DataError("not_found", "NO PEERS FOUND", "; ".join(errors) or None)
                same = sorted((r for r in uni["rows"] if r[10] == me[10] and r[0] != symbol and r[6]),
                              key=lambda r: -r[6])
                peers = [{"symbol": r[0], "score": None} for r in same[:limit]]
                if not peers:
                    raise DataError("not_found", "NO PEERS FOUND", "; ".join(errors) or None)
                basis, source = "industry", f"{uni['source']}:industry"
                failed = [*failed, *(["yahoo_peers"] if "yahoo_peers" not in failed else [])]
            return {
                "data": {
                    "symbol": symbol, "basis": basis, "self": {"symbol": symbol, **info(symbol)},
                    "peers": [{**p, **info(p["symbol"])} for p in peers],
                },
                "source": source,
                "fallback_from": failed,
            }

        return await self._swr(f"peers:{symbol}", self.ttl.get("peers", 86400.0), fetch)


# --- Phase 7 imports (appended at the end so merges with other phases stay additive) ---
from datetime import date, timedelta

from .config import load_yaml
from .providers import macro as _macro
