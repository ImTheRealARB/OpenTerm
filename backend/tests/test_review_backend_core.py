"""Review sprint, area backend-core: regression tests for bugs found in hub, scheduler, cache and the ws handler."""

import pytest

from openterm.cache import Cache
from openterm.db import open_db
from openterm.providers.base import Provider, ProviderError
from openterm.router import Router
from openterm.scheduler import probe_down_providers
from openterm.streaming.hub import Client, Hub
from openterm.streaming.upstream import Poller


class _Sink:
    """Stands in for yahoo / poller: records the symbol set the hub asked for last."""

    status = "OK"
    messages = 0

    def __init__(self):
        self.symbols: set[str] = set()

    async def set_symbols(self, symbols):
        self.symbols = set(symbols)


def _hub() -> Hub:
    return Hub(_Sink(), _Sink())


# --- hub: a symbol repeated inside one frame must count once -----------------------------------------


async def test_duplicate_symbols_in_one_sub_frame_do_not_leak_upstream_refs():
    hub = _hub()
    client = Client(None)
    hub.clients.add(client)
    await hub.subscribe(client, ["AAPL", "AAPL", "MSFT"])
    assert hub.refs == {"AAPL": 1, "MSFT": 1}
    await hub.disconnect(client)
    assert hub.refs == {}
    assert hub.yahoo.symbols == set()


async def test_duplicate_symbols_in_one_unsub_frame_do_not_crash_or_steal_refs():
    hub = _hub()
    a, b = Client(None), Client(None)
    await hub.subscribe(a, ["AAPL"])
    await hub.subscribe(b, ["AAPL"])
    await hub.unsubscribe(a, ["AAPL", "AAPL"])  # used to raise KeyError and drop b's reference too
    assert hub.refs == {"AAPL": 1}
    assert hub.yahoo.symbols == {"AAPL"}


# --- poller: last-price memory follows the subscription ----------------------------------------------


async def test_poller_forgets_prices_of_unsubscribed_symbols():
    p = Poller(lambda t: None, None, lambda: False)
    p._last.update({"AAPL": 1.0, "MSFT": 2.0})
    await p.set_symbols({"AAPL"})
    assert set(p._last) == {"AAPL"}


# --- scheduler: a provider with no probe() must not be punished by the probe loop ---------------------


class _NoProbe(Provider):
    name = "noprobe"
    capabilities = frozenset({"quotes"})

    def __init__(self):
        super().__init__(None)  # no HTTP client needed


async def test_probe_loop_skips_providers_without_a_probe():
    router = Router({"noprobe": _NoProbe()}, {"quotes": ["noprobe"]})
    h = router.health["noprobe"]
    for _ in range(3):
        h.fail(ProviderError("unavailable", "boom"))
    down_until, consecutive, calls = h.down_until, h.consecutive, h.calls
    await probe_down_providers(router)
    # the probe loop used to call the missing probe(), count a fresh failure and push the cooldown out for ever
    assert (h.down_until, h.consecutive, h.calls) == (down_until, consecutive, calls)


async def test_probe_loop_still_probes_providers_that_have_one():
    class _Probe(_NoProbe):
        async def probe(self):
            return None

    router = Router({"noprobe": _Probe()}, {"quotes": ["noprobe"]})
    h = router.health["noprobe"]
    for _ in range(3):
        h.fail(ProviderError("unavailable", "boom"))
    assert h.down
    await probe_down_providers(router)
    assert not h.down and h.consecutive == 0


# --- cache.get_many: same answers as get(), one SQLite query --------------------------------------------


@pytest.fixture
async def cache(tmp_path):
    db = await open_db(tmp_path / "c.db")
    c = Cache(db, max_entries=3)
    yield c
    await c.flush()
    await db.close()


async def test_get_many_matches_get_and_hits_sqlite_once(cache):
    for i in range(6):
        cache.put(f"k{i}", {"v": i}, stored_at=100.0 + i)
    await cache.flush()
    assert len(cache.mem) == 3  # k3..k5 in memory, k0..k2 only in SQLite
    real, calls = cache.db.execute, []

    def counting(sql, *a, **kw):
        calls.append(sql)
        return real(sql, *a, **kw)

    cache.db.execute = counting
    got = await cache.get_many(["k5", "k0", "k1", "nope", "k0"])
    assert len(calls) == 1
    assert got["k5"] == ({"v": 5}, 105.0)
    assert got["k0"] == ({"v": 0}, 100.0)
    assert got["k1"] == ({"v": 1}, 101.0)
    assert "nope" not in got
    assert cache.hits == 3 and cache.misses == 1  # the repeated k0 counts once
    assert "k0" in cache.mem  # promoted like get() does
    assert await cache.get_many([]) == {}


async def test_get_many_handles_more_keys_than_sqlite_variable_limit(cache):
    keys = [f"bulk{i}" for i in range(2500)]
    cache.max_entries = 10
    for k in keys:
        cache.put(k, 1, stored_at=1.0)
    await cache.flush()
    cache.mem.clear()
    got = await cache.get_many(keys)
    assert len(got) == 2500


# --- ws: a malformed ping must not kill the socket --------------------------------------------------------


def test_ws_ping_without_timestamp_keeps_the_socket_open(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_text('["ping"]')
        ws.send_text('["ping", 5]')
        frame = ws.receive_json()
        while frame[0] != "pong" or frame[1] != 5:  # a bare ping is ignored; the next real one is answered
            frame = ws.receive_json()
        assert frame[0] == "pong"
