import asyncio
import time

import pytest

from openterm.cache import Cache
from openterm.db import MIGRATIONS, open_db
from openterm.errors import DataError
from openterm.models import Bars, Quote
from openterm.providers.base import Provider, ProviderError
from openterm.ranges import normalize
from openterm.ratelimit import RateLimited, TokenBucket
from openterm.router import AllFailed, Router
from openterm.service import DataService
from openterm.symbols import kind, resolve


class Fake(Provider):
    """Scriptable provider: `behaviour` is a value to return or an exception to raise."""

    capabilities = frozenset({"quotes", "history", "search"})
    rate = (1000.0, 1000)

    def __init__(self, name, behaviour=None, delay=0.0):
        self.name = name
        super().__init__(http=None)  # type: ignore[arg-type]
        self.behaviour = behaviour
        self.delay = delay
        self.calls = 0

    async def _act(self, make):
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if isinstance(self.behaviour, Exception):
            raise self.behaviour
        return make()

    async def history(self, symbol, range_, interval):
        return await self._act(lambda: Bars(
            symbol=symbol, range=range_, interval=interval, t=[1], o=[1.0], h=[1.0], l=[1.0], c=[1.0],
            v=[1], source=self.name, as_of=time.time(),
        ))

    async def quotes(self, symbols):
        return await self._act(lambda: [Quote(symbol=s, price=1.0, source=self.name, as_of=time.time()) for s in symbols])

    async def probe(self):
        await self._act(lambda: None)


def make(*providers, ttl=None):
    order = {"quotes": [p.name for p in providers], "history": [p.name for p in providers]}
    router = Router({p.name: p for p in providers}, order)
    return DataService(router, Cache(None), ttl), router


# --- symbols / ranges ------------------------------------------------------------------------
def test_resolve():
    assert resolve("eurusd") == "EURUSD=X"
    assert resolve("BTCUSD") == "BTC-USD"
    assert resolve("BTC-USD") == "BTC-USD"
    assert resolve("spx") == "^GSPC"
    assert resolve("NIFTY") == "^NSEI"
    assert resolve("RELIANCE.NS") == "RELIANCE.NS"
    assert kind("^GSPC") == "index" and kind("EURUSD=X") == "fx" and kind("BTC-USD") == "crypto"


def test_ranges():
    assert normalize("1Y", None) == ("1y", "1d")
    assert normalize("1d", None) == ("1d", "5m")
    assert normalize("1M", None) == ("1mo", "60m")  # 1M is a month range, never a minute
    assert normalize("5D", "1m") == ("5d", "1m")
    assert normalize("1Y", "W") == ("1y", "1wk")
    # How far back a minute candle reaches depends on which source answers, so normalize() no longer rejects it:
    # each provider declares its own depth (Yahoo: see test_yahoo_declares_and_enforces_its_intraday_depth).
    assert normalize("1Y", "1m") == ("1y", "1m")
    with pytest.raises(ValueError):
        normalize("7Q", None)


# --- rate limiter ----------------------------------------------------------------------------
async def test_token_bucket_never_stalls():
    b = TokenBucket(rate=1.0, burst=2)
    await b.acquire()
    await b.acquire()
    t0 = time.monotonic()
    with pytest.raises(RateLimited):
        await b.acquire(max_wait=0.1)  # next slot is ~1s away: refuse instead of waiting
    assert time.monotonic() - t0 < 0.05


async def test_token_bucket_short_wait():
    b = TokenBucket(rate=50.0, burst=1)
    await b.acquire()
    t0 = time.monotonic()
    await b.acquire(max_wait=0.1)
    assert 0.01 < time.monotonic() - t0 < 0.1


# --- router ----------------------------------------------------------------------------------
async def test_router_falls_back_and_reports():
    bad = Fake("a", ProviderError("unavailable", "boom"))
    good = Fake("b")
    _, router = make(bad, good)
    bars, failed = await router.call("history", lambda p: p.history("X", "1y", "1d"))
    assert bars.source == "b" and failed == ["a"]


async def test_circuit_breaker_trips_and_skips():
    bad = Fake("a", ProviderError("unavailable"))
    good = Fake("b")
    _, router = make(bad, good)
    for _ in range(3):
        await router.call("history", lambda p: p.history("X", "1y", "1d"))
    assert router.health["a"].down
    calls = bad.calls
    await router.call("history", lambda p: p.history("X", "1y", "1d"))
    assert bad.calls == calls  # tripped provider is skipped


async def test_not_found_does_not_trip():
    nf = Fake("a", ProviderError("not_found"))
    _, router = make(nf)
    for _ in range(5):
        with pytest.raises(AllFailed) as e:
            await router.call("history", lambda p: p.history("X", "1y", "1d"))
    assert e.value.kind == "not_found" and str(e.value) == "NO DATA FOR SYMBOL"
    assert not router.health["a"].down


async def test_rate_limited_trips_immediately():
    rl = Fake("a", ProviderError("rate_limited"))
    _, router = make(rl, Fake("b"))
    await router.call("history", lambda p: p.history("X", "1y", "1d"))
    assert router.health["a"].down


async def test_all_down_is_provider_down():
    _, router = make(Fake("a", ProviderError("unavailable")), Fake("b", ProviderError("unavailable")))
    with pytest.raises(AllFailed) as e:
        await router.call("history", lambda p: p.history("X", "1y", "1d"))
    assert str(e.value) == "PROVIDER DOWN"


# --- service: SWR + coalescing ----------------------------------------------------------------
async def test_coalescing_one_upstream_call():
    slow = Fake("a", delay=0.05)
    svc, _ = make(slow)
    results = await asyncio.gather(*(svc.history("AAPL", "1Y", None) for _ in range(10)))
    assert slow.calls == 1
    assert all(r["data"]["source"] == "a" and r["stale"] is False for r in results)


async def test_stale_while_revalidate():
    p = Fake("a")
    svc, _ = make(p, ttl={"daily": 0.5})  # wide TTL: a 50 ms one flaked on a loaded machine
    await svc.history("AAPL", "1Y", None)
    await asyncio.sleep(0.55)
    r = await svc.history("AAPL", "1Y", None)
    assert r["stale"] is True and r["age_s"] >= 0.5  # served instantly, marked stale
    await asyncio.sleep(0.05)
    assert p.calls == 2  # background refresh happened
    assert (await svc.history("AAPL", "1Y", None))["stale"] is False


async def test_stale_survives_provider_outage():
    p = Fake("a")
    svc, _ = make(p, ttl={"daily": 0.01})
    await svc.history("AAPL", "1Y", None)
    p.behaviour = ProviderError("unavailable")
    await asyncio.sleep(0.02)
    r = await svc.history("AAPL", "1Y", None)
    assert r["stale"] is True and r["data"]["c"] == [1.0]  # last known data, labelled stale, never invented


async def test_bad_range_is_bad_request():
    svc, _ = make(Fake("a"))
    with pytest.raises(DataError) as e:
        await svc.history("AAPL", "9Z", None)
    assert e.value.kind == "bad_request"


async def test_batch_quotes_dedupe_and_errors():
    p = Fake("a", delay=0.02)
    svc, _ = make(p)
    a, b = await asyncio.gather(svc.quotes(["AAPL", "MSFT"]), svc.quotes(["AAPL"]))
    assert p.calls == 1  # the second request joined the in-flight batch
    assert a["AAPL"]["data"]["price"] == 1.0 and b["AAPL"]["data"]["price"] == 1.0
    p.behaviour = ProviderError("unavailable")
    c = await svc.quotes(["NEW"])
    assert c["NEW"]["error"] == "PROVIDER DOWN"


async def test_quote_fallback_for_unsupported_symbols():
    class UsOnly(Fake):
        def supports(self, capability, symbol=None):
            return symbol is None or "." not in symbol

    us = UsOnly("us")
    glob = Fake("glob")
    svc, _ = make(us, glob)
    r = await svc.quotes(["AAPL", "RELIANCE.NS"])
    assert r["AAPL"]["source"] == "us" and r["RELIANCE.NS"]["source"] == "glob"


# --- cache + db ------------------------------------------------------------------------------
async def test_cache_persists_and_evicts(tmp_path):
    db = await open_db(tmp_path / "t.db")
    c = Cache(db, max_entries=2, flush_s=0.0)
    c.put("a", {"x": 1})
    c.put("b", {"x": 2})
    c.put("c", {"x": 3})
    assert "a" not in c.mem  # LRU bound
    await c.flush()
    c2 = Cache(db)
    assert (await c2.get("a"))[0] == {"x": 1}  # survives restart via SQLite
    async with db.execute("PRAGMA journal_mode") as cur:
        assert (await cur.fetchone())[0] == "wal"
    async with db.execute("PRAGMA user_version") as cur:
        assert (await cur.fetchone())[0] == len(MIGRATIONS)
    await db.close()
