"""Audit group 6: router / service / shutdown (H-01, H-02, H-03, H-04, H-05, H-09, M-03).

Every test uses fake providers and, where time matters, an injected clock: no network, no long sleeps, no TTL races.
"""

import asyncio
import contextlib
import time
from types import SimpleNamespace

import httpx
import pytest

from openterm import router as router_mod
from openterm.cache import Cache
from openterm.db import open_db
from openterm.errors import DataError
from openterm.models import Quote
from openterm.providers.base import Provider, ProviderError
from openterm.router import MAX_COOLDOWN_S, AllFailed, Health, Router
from openterm.service import DataService
from openterm.streaming.hub import Hub
from openterm.streaming.tick import Tick


class Fake(Provider):
    """Scriptable provider: `behaviour` is an exception to raise, or None to answer."""

    capabilities = frozenset({"quotes", "history"})
    rate = (1000.0, 1000)

    def __init__(self, name, behaviour=None):
        self.name = name
        super().__init__(http=None)  # type: ignore[arg-type]
        self.behaviour = behaviour
        self.calls = 0
        self.started = asyncio.Event()
        self.gate: asyncio.Event | None = None  # when set, quotes() waits for it

    async def quotes(self, symbols):
        self.calls += 1
        self.started.set()
        if self.gate is not None:
            await self.gate.wait()
        if isinstance(self.behaviour, Exception):
            raise self.behaviour
        return [Quote(symbol=s, price=1.0, source=self.name, as_of=time.time()) for s in symbols]


def make(*providers):
    order = {"quotes": [p.name for p in providers], "history": [p.name for p in providers]}
    router = Router({p.name: p for p in providers}, order)
    return DataService(router, Cache(None)), router


@pytest.fixture
def clock(monkeypatch):
    """The router's own clock, moved by hand (`clock[0] += 11`)."""
    now = [1_000_000.0]
    monkeypatch.setattr(router_mod, "time", SimpleNamespace(time=lambda: now[0], perf_counter=time.perf_counter))
    return now


# --- H-01: the back-off exponent overflowed after ~1025 straight failures ---------------------------------------------

def test_h01_backoff_never_overflows():
    h = Health()
    h.consecutive = 5000  # a provider that has been failing for hours (the 30 s probe loop keeps counting)
    h.fail(ProviderError("unavailable", "still down"))  # `5.0 * 2 ** 5000` raised OverflowError here
    assert 0 < h.down_until - time.time() <= MAX_COOLDOWN_S + 1


# --- H-02: a tripped sole provider was retried on every single call ---------------------------------------------------

async def test_h02_sole_provider_breaker_stays_open_between_trials(clock):
    bad = Fake("a", ProviderError("unavailable", "boom"))
    _, router = make(bad)
    for _ in range(3):
        with pytest.raises(AllFailed):
            await router.call("quotes", lambda p: p.quotes(["X"]))
    assert router.health["a"].down and bad.calls == 3

    for _ in range(25):  # same instant: the breaker is open, nobody reaches the provider
        with pytest.raises(AllFailed) as e:
            await router.call("quotes", lambda p: p.quotes(["X"]))
    assert bad.calls == 3
    assert e.value.kind == "unavailable" and str(e.value) == "PROVIDER DOWN"  # a reason, not "NO PROVIDER SUPPORTS THIS SYMBOL"

    clock[0] += router_mod.HALF_OPEN_GAP_S + 1  # half-open: ONE trial call goes through, the rest are still refused
    for _ in range(25):
        with pytest.raises(AllFailed):
            await router.call("quotes", lambda p: p.quotes(["X"]))
    assert bad.calls == 4


async def test_h02_batch_quotes_also_stay_closed(clock):
    bad = Fake("a", ProviderError("unavailable", "boom"))
    _, router = make(bad)
    for _ in range(3):
        await router.quotes(["X"])
    assert router.health["a"].down and bad.calls == 3
    for _ in range(10):
        found, errors = await router.quotes(["X", "Y"])
    assert bad.calls == 3 and not found
    assert errors["X"].kind == "unavailable" and str(errors["X"]) == "PROVIDER DOWN"


async def test_h02_recovery_closes_the_breaker(clock):
    flaky = Fake("a", ProviderError("unavailable", "boom"))
    _, router = make(flaky)
    for _ in range(3):
        with pytest.raises(AllFailed):
            await router.call("quotes", lambda p: p.quotes(["X"]))
    flaky.behaviour = None  # the outage ends
    clock[0] += router_mod.HALF_OPEN_GAP_S + 1
    got, _ = await router.call("quotes", lambda p: p.quotes(["X"]))  # the half-open trial succeeds
    assert got[0].symbol == "X" and not router.health["a"].down


async def test_h02_a_healthy_provider_is_never_gated(clock):
    bad, good = Fake("a", ProviderError("unavailable", "boom")), Fake("b")
    _, router = make(bad, good)
    for _ in range(6):
        got, _ = await router.call("quotes", lambda p: p.quotes(["X"]))
        assert got[0].source == "b"


# --- H-03: ticks never reached a quote cached under a source preference ------------------------------------------------

def test_h03_ticks_fold_into_the_scoped_quote_key():
    svc, router = make(Fake("a"))
    router.prefs = {"history": "a"}  # any saved SETTINGS SOURCE preference changes every cache key
    svc.cache.mem[svc._qkey("AAPL")] = ({"data": {"symbol": "AAPL", "price": 200.0, "high": 201.0, "low": 199.0}}, time.time())
    svc.apply_tick(Tick("AAPL", 202.0, None, None, None, None, None, int(time.time() * 1000), "y"))
    assert svc.cached_quote("AAPL")["price"] == 202.0


# --- H-04: a cancelled caller handed CancelledError to everyone waiting on the same quote ------------------------------

async def test_h04_cancelling_one_caller_does_not_fail_the_others():
    prov = Fake("a")
    prov.gate = asyncio.Event()
    svc, _ = make(prov)
    first = asyncio.create_task(svc.quotes(["ZZ1"]))
    await prov.started.wait()
    second = asyncio.create_task(svc.quotes(["ZZ1"]))  # joins the first caller's in-flight fetch
    for _ in range(5):
        await asyncio.sleep(0)
    first.cancel()  # a closed browser tab
    with contextlib.suppress(asyncio.CancelledError):
        await first
    prov.gate.set()
    res = await asyncio.wait_for(second, 2)
    assert "error" not in res["ZZ1"], res["ZZ1"]
    assert res["ZZ1"]["data"]["price"] == 1.0
    assert svc._inflight == {}  # the batch finished and cleaned up although its first caller was gone


# --- H-05: shutdown left background tasks and the cache flusher running past the closed DB -----------------------------

async def test_h05_service_aclose_cancels_background_work():
    svc, _ = make(Fake("a"))
    forever = asyncio.Event()
    svc._background(forever.wait())
    task = next(iter(svc._bg))
    await svc.aclose()
    assert task.cancelled() and not svc._bg


async def test_h05_cache_aclose_flushes_and_stops_the_flusher(tmp_path):
    db = await open_db(tmp_path / "c.db")
    cache = Cache(db, flush_s=60.0)  # the flusher would sleep a minute
    cache.put("k", {"v": 1})
    flusher = cache._flusher
    assert flusher is not None and not flusher.done()
    await cache.aclose()
    assert flusher.done()
    async with db.execute("SELECT COUNT(*) FROM cache WHERE key='k'") as cur:
        assert (await cur.fetchone())[0] == 1  # the pending write was still saved
    await db.close()


@pytest.fixture
def shutdown_calls(monkeypatch):
    """Requested BEFORE `client`, so it is torn down AFTER the app's lifespan has ended: it sees what shutdown did."""
    calls: list[str] = []
    real_service, real_cache = DataService.aclose, Cache.aclose

    async def service_aclose(self):
        calls.append("service")
        await real_service(self)

    async def cache_aclose(self):
        calls.append("cache")
        await real_cache(self)

    monkeypatch.setattr(DataService, "aclose", service_aclose, raising=False)
    monkeypatch.setattr(Cache, "aclose", cache_aclose, raising=False)
    yield calls
    assert calls == ["service", "cache"], "lifespan shutdown must stop the service's tasks, then close the cache"


def test_h05_lifespan_shutdown_closes_service_then_cache(shutdown_calls, client):
    assert client.get("/api/health").json()["ok"] is True


# --- H-09: an older upstream sync could overwrite a newer one ---------------------------------------------------------

class _Upstream:
    def __init__(self, gate: asyncio.Event | None = None):
        self.symbols: set[str] = set()
        self.gate = gate
        self.entered = asyncio.Event()
        self._first = True

    async def set_symbols(self, symbols):
        if self.gate is not None and self._first:
            self._first = False
            self.entered.set()
            await self.gate.wait()  # the slow Yahoo reconnect
        self.symbols = set(symbols)


async def test_h09_overlapping_syncs_end_on_the_newest_symbol_set():
    gate = asyncio.Event()
    yahoo, poller = _Upstream(gate), _Upstream()
    hub = Hub(yahoo, poller)
    one, two = SimpleNamespace(symbols=set()), SimpleNamespace(symbols=set())
    first = asyncio.create_task(hub.subscribe(one, ["AAA"]))
    await yahoo.entered.wait()  # sync #1 has read {AAA} and is stuck inside Yahoo
    second = asyncio.create_task(hub.subscribe(two, ["BBB"]))
    for _ in range(5):
        await asyncio.sleep(0)
    gate.set()
    await asyncio.gather(first, second)
    assert poller.symbols == {"AAA", "BBB"}  # the stale sync #1 used to land last and drop BBB
    assert yahoo.symbols == {"AAA", "BBB"}


# --- M-03: Yahoo fan-out, Kite 429 kind, sequential probes ------------------------------------------------------------

async def test_m03_yahoo_chart_fallback_is_bounded():
    from openterm.providers import yahoo as yahoo_mod

    p = yahoo_mod.YahooProvider(None)  # type: ignore[arg-type]
    live = peak = 0

    async def spark_refused(chunk):
        raise ProviderError("unavailable", "spark blocked")

    async def chart(symbol):
        nonlocal live, peak
        live += 1
        peak = max(peak, live)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        live -= 1
        return Quote(symbol=symbol, price=1.0, source="yahoo", as_of=time.time())

    p._spark = spark_refused  # type: ignore[method-assign]
    p._quote_via_chart = chart  # type: ignore[method-assign]
    got = await p.quotes([f"S{i}" for i in range(60)])
    assert len(got) == 60
    assert peak <= yahoo_mod.SPARK_PARALLEL * 2, peak  # 60 symbols used to start 60 chart calls at once


async def test_m03_kite_429_is_rate_limited_not_unavailable():
    from openterm.kite.client import KiteClient
    from openterm.providers.kite import _kind

    session = SimpleNamespace(auth=lambda: ("key", "tok"), mark_expired=lambda: None)
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(429, text="slow down")))
    try:
        with pytest.raises(DataError) as e:
            await KiteClient(session, http).get_json("/quote")  # type: ignore[arg-type]
    finally:
        await http.aclose()
    assert e.value.kind == "rate_limited"
    assert _kind(e.value) == "rate_limited"  # the provider keeps the kind, so the breaker trips at once and honours the limit


async def test_m03_probes_run_side_by_side():
    from openterm.scheduler import probe_down_providers

    started = 0
    all_started = asyncio.Event()

    class Probe(Fake):
        async def probe(self):
            nonlocal started
            started += 1
            if started == 3:
                all_started.set()
            await all_started.wait()  # one at a time would wait here for ever

    provs = [Probe(n) for n in ("a", "b", "c")]
    _, router = make(*provs)
    for p in provs:
        for _ in range(3):
            router.health[p.name].fail(ProviderError("unavailable", "boom"))
    await asyncio.wait_for(probe_down_providers(router), 3)
    assert all(not router.health[p.name].down for p in provs)
