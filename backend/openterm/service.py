"""Data service: stale-while-revalidate over the cache, request coalescing, batch quotes.

Every response is an envelope: {data, source, as_of, age_s, stale, fallback_from}.
A stale envelope is served instantly and refreshed in the background; it is never dressed up as fresh.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from .cache import Cache
from .providers.crypto import VS
from .ranges import normalize
from .router import AllFailed, Router
from .symbols import resolve

log = logging.getLogger("openterm.service")

INTRADAY = {"1m", "2m", "5m", "15m", "30m", "60m", "90m"}


class DataError(Exception):
    """kind: bad_request | not_found | unavailable. `detail` names each provider's reason."""

    def __init__(self, kind: str, message: str, detail: str | None = None):
        super().__init__(message)
        self.kind = kind
        self.detail = detail


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
    }


class DataService:
    def __init__(self, router: Router, cache: Cache, ttl: dict[str, float] | None = None):
        self.router = router
        self.cache = cache
        self.ttl = {
            "quote": 5.0, "intraday": 60.0, "daily": 3600.0, "search": 86400.0, "profile": 86400.0,
            "news": 120.0, "movers": 60.0, "crypto": 60.0, **(ttl or {}),
        }
        self._inflight: dict[str, asyncio.Future] = {}
        self._bg: set[asyncio.Task] = set()
        self.fresh_hits = 0
        self.stale_hits = 0
        self.misses = 0

    # --- coalescing -------------------------------------------------------------------------
    async def _once(self, key: str, fetch: Callable[[], Awaitable[dict]]) -> dict:
        """Concurrent callers for the same key share one upstream request."""
        fut = self._inflight.get(key)
        if fut is None:
            fut = asyncio.get_running_loop().create_future()
            self._inflight[key] = fut
            try:
                value = await fetch()
                self.cache.put(key, value)
                fut.set_result(value)
            except BaseException as e:  # noqa: BLE001 - forwarded to every waiter
                fut.set_exception(e)
                fut.exception()  # mark retrieved so a lone background refresh doesn't warn
            finally:
                del self._inflight[key]
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
            raise DataError(e.kind if e.kind != "unsupported" else "not_found", str(e), detail) from e
        return envelope(value, self.cache.mem[key][1] if key in self.cache.mem else time.time(), stale=False)

    # --- public API ---------------------------------------------------------------------------
    async def history(self, raw_symbol: str, range_: str | None, interval: str | None) -> dict:
        symbol = resolve(raw_symbol)
        try:
            r, i = normalize(range_, interval)
        except ValueError as e:
            raise DataError("bad_request", str(e)) from e
        ttl = self.ttl["intraday"] if i in INTRADAY else self.ttl["daily"]

        async def fetch() -> dict:
            bars, failed = await self.router.call("history", lambda p: p.history(symbol, r, i), symbol)
            return {"data": bars.model_dump(), "fallback_from": failed}

        return await self._swr(f"h:{symbol}:{r}:{i}", ttl, fetch)

    async def profile(self, raw_symbol: str) -> dict:
        symbol = resolve(raw_symbol)

        async def fetch() -> dict:
            prof, failed = await self.router.call("profile", lambda p: p.profile(symbol), symbol)
            return {"data": prof.model_dump(), "fallback_from": failed}

        return await self._swr(f"p:{symbol}", self.ttl["profile"], fetch)

    async def news(self, symbol: str | None = None, query: str | None = None) -> dict:
        """Symbol headlines, a keyword search, or (neither) the market top stories."""
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
            out, failed = await self.router.call(cap, call, arg)
            items = out["items"]
            return {
                "data": {"kind": kind, "query": arg, "items": [i.model_dump() for i in items], "failed": out["failed"]},
                "source": items[0].source if items else None,
                "fallback_from": failed,
            }

        try:
            return await self._swr(f"n:{kind}:{arg or ''}", self.ttl["news"], fetch)
        except DataError as e:
            if e.kind != "not_found":
                raise
            raise DataError("not_found", "NO HEADLINES FOUND", e.detail) from e

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
        q["market_time"] = tick.time_ms // 1000
        q["as_of"] = time.time()
        if tick.source == "y":
            q["source"] = "yahoo:stream"
        self.cache.mem[key] = (value, time.time())

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

    async def quotes(self, raw_symbols: list[str]) -> dict[str, dict[str, Any]]:
        """Returns {requested symbol: envelope | {"error", "kind"}}. Missing/stale ones are batched upstream."""
        symbols = {raw: resolve(raw) for raw in raw_symbols}
        out: dict[str, dict] = {}
        need: list[str] = []
        stale: list[str] = []
        for raw, s in symbols.items():
            entry = await self.cache.get(f"q:{s}")
            if entry is None:
                self.misses += 1
                need.append(s)
                continue
            value, stored_at = entry
            is_stale = time.time() - stored_at >= self.ttl["quote"]
            if is_stale:
                self.stale_hits += 1
                stale.append(s)
            else:
                self.fresh_hits += 1
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
                        value = {"data": q.model_dump(), "fallback_from": failed}
                        self.cache.put(f"q:{s}", value)
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
