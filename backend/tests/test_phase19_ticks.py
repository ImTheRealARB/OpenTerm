"""Phase 19 step 3: the tick ring buffer behind GIP (`/api/world/ticks/{symbol}`)."""

import math

import pytest

from openterm.streaming.tick import Tick
from openterm.world.tickbuf import SESSION_GAP_MS, TickBuffers, TickRing, bucket


def tk(sym: str, price: float, ms: int, vol: int | None = None, src: str = "s") -> Tick:
    return Tick(sym, price, None, None, vol, None, None, ms, src)


def test_ring_keeps_only_the_newest_cap_ticks():
    ring = TickRing(cap=5)
    for i in range(12):
        ring.add(1000 * i, 10.0 + i, None, "y")
    t, p, v = ring.view()
    assert t == [7000, 8000, 9000, 10000, 11000]
    assert p == [17.0, 18.0, 19.0, 20.0, 21.0]
    assert all(math.isnan(x) for x in v)
    assert len(ring) == 5
    assert ring.total == 12


def test_a_long_gap_starts_a_new_session():
    ring = TickRing(cap=100)
    ring.add(1_000, 1.0, None, "y")
    ring.add(61_000, 2.0, None, "y")
    assert ring.sessions == 1 and ring.since_ms == 1_000
    ring.add(61_000 + SESSION_GAP_MS + 1, 3.0, None, "y")
    t, p, _ = ring.view()
    assert p == [3.0] and ring.sessions == 2 and ring.since_ms == t[0]


def test_bucket_ohlc_by_time_not_by_arrival_order():
    t = [900, 0, 400, 1100, 61_000]
    p = [9.0, 10.0, 12.0, 11.0, 20.0]
    one = bucket(t, p, [math.nan] * 5, 1)
    assert one["t"] == [0, 1, 61]
    assert (one["o"], one["h"], one["l"], one["c"]) == ([10.0, 11.0, 20.0], [12.0, 11.0, 20.0], [9.0, 11.0, 20.0], [9.0, 11.0, 20.0])
    minute = bucket(t, p, [math.nan] * 5, 60)
    assert minute["t"] == [0, 60]
    assert (minute["o"], minute["h"], minute["l"], minute["c"]) == ([10.0, 20.0], [12.0, 20.0], [9.0, 20.0], [11.0, 20.0])
    assert minute["v"] is None  # no volume anywhere: the column is hidden, not zero-filled


def test_equal_timestamps_keep_arrival_order():
    r = bucket([5, 5, 5], [1.0, 3.0, 2.0], [math.nan] * 3, 1)
    assert (r["o"], r["h"], r["l"], r["c"]) == ([1.0], [3.0], [1.0], [2.0])


def test_volume_is_the_increase_of_cumulative_day_volume():
    t = [0, 1000, 2000, 3000, 4000, 5000]
    v = [100.0, 150.0, 150.0, 200.0, math.nan, 260.0]
    r = bucket(t, [1.0] * 6, v, 2)
    assert r["t"] == [0, 2, 4]
    assert r["v"] == [50.0, 50.0, 60.0]  # a tick without volume keeps the last known total


def test_a_falling_cumulative_volume_is_a_new_day_not_negative_volume():
    r = bucket([0, 1000, 2000], [1.0] * 3, [500.0, 600.0, 40.0], 1)
    assert r["v"] == [0.0, 100.0, 0.0]


def test_buffers_skip_bad_prices_and_evict_the_quietest_symbol():
    bufs = TickBuffers(cap=10, max_symbols=3)
    for i, s in enumerate(["A", "B", "C"]):
        bufs.add(tk(s, 10.0, 1000 + i))
    bufs.add(tk("B", 11.0, 5000))
    bufs.add(tk("A", 0.0, 6000))
    bufs.add(tk("A", float("nan"), 6000))
    bufs.add(tk("A", -1.0, 6000))
    assert len(bufs.get("A")) == 1
    bufs.add(tk("D", 9.0, 7000))
    assert bufs.get("D") is not None and bufs.get("A") is None  # A had the oldest last tick
    assert set(bufs.symbols()) == {"B", "C", "D"}


def test_buffers_remember_the_source_of_the_last_tick():
    bufs = TickBuffers()
    bufs.add(tk("X", 1.0, 1, src="y"))
    bufs.add(tk("X", 1.1, 2, src="p"))
    assert bufs.get("X").src == "p"


def test_route_is_empty_before_any_tick_then_fills_and_labels_synthetic(client):
    r = client.get("/api/world/ticks/SYN0001", params={"bar": "1s"})
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["ticks"] == 0 and d["t"] == [] and d["since_ms"] is None
    with client.websocket_connect("/ws") as ws:
        ws.send_text('["sub", ["SYN0001"]]')
        for _ in range(60):
            if ws.receive_json()[0] == "T":
                break
    env = client.get("/api/world/ticks/SYN0001", params={"bar": "1s"}).json()
    d = env["data"]
    assert d["ticks"] >= 1 and d["synthetic"] is True and d["bar_s"] == 1
    assert len(d["t"]) == len(d["o"]) == len(d["h"]) == len(d["l"]) == len(d["c"]) >= 1
    assert d["t"] == sorted(d["t"]) and d["since_ms"] > 0
    assert env["source"] and "SYNTHETIC" in env["source"].upper()
    assert env["stale"] is False


def test_route_validates_input(client):
    assert client.get("/api/world/ticks/AAPL", params={"bar": "3s"}).status_code == 400
    assert client.get("/api/world/ticks/BAD SYM!").status_code in (400, 404, 422)
    ok = client.get("/api/world/ticks/AAPL")  # default bar; nobody subscribed: empty, never invented
    assert ok.status_code == 200 and ok.json()["data"]["ticks"] == 0


@pytest.mark.parametrize("bar,secs", [("1s", 1), ("5s", 5), ("15s", 15), ("1m", 60)])
def test_bar_sizes(client, bar, secs):
    assert client.get("/api/world/ticks/SYN0001", params={"bar": bar}).json()["data"]["bar_s"] == secs
