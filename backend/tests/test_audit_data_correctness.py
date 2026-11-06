"""Audit A-2, A-3, A-4, B-2: ticks must not hide stale quotes, an expired Kite login must not poison caches or errors,
YTD must mean year to date, and derivatives functions must carry the freshness of their inputs."""

import datetime as dt
import time

import pytest

from openterm import ranges
from openterm.providers.base import ProviderError
from openterm.router import AllFailed
from openterm.streaming.tick import Tick

# --- A-2 ---------------------------------------------------------------------------------------------------------

def _seed_quote(svc, symbol="AAPL", **over):
    q = {"symbol": symbol, "price": 200.0, "high": 201.0, "low": 199.0, "volume": 1000, "source": "yahoo"}
    q.update(over)
    svc.cache.mem[f"q:{symbol}"] = ({"data": q, "fallback_from": []}, time.time())
    svc.rest_at[f"q:{symbol}"] = time.time()
    return q


@pytest.mark.parametrize("code,name", [("a", "alpaca:iex"), ("k", "kite:ticker"), ("y", "yahoo:stream"), ("s", "synthetic")])
def test_tick_source_is_named(client, code, name):
    svc = client.app.state.service
    q = _seed_quote(svc)
    svc.apply_tick(Tick("AAPL", 202.0, None, None, None, None, None, int(time.time() * 1000), code))
    assert q["source"] == name


def test_poll_tick_keeps_the_rest_source(client):
    svc = client.app.state.service
    q = _seed_quote(svc)
    svc.apply_tick(Tick("AAPL", 202.0, None, None, None, None, None, int(time.time() * 1000), "p"))
    assert q["source"] == "yahoo"


def test_tick_without_a_day_range_stretches_high_and_low(client):
    svc = client.app.state.service
    q = _seed_quote(svc)
    svc.apply_tick(Tick("AAPL", 210.0, None, None, None, None, None, int(time.time() * 1000), "a"))
    assert q["high"] == 210.0 and q["low"] == 199.0
    svc.apply_tick(Tick("AAPL", 190.0, None, None, None, None, None, int(time.time() * 1000), "a"))
    assert q["low"] == 190.0 and q["high"] == 210.0


def test_streamed_symbol_still_refreshes_its_rest_snapshot(client):
    """Ticks keep the price fresh, but volume / high / low come only from REST: it is re-fetched in the background."""
    svc = client.app.state.service
    _seed_quote(svc)
    svc.rest_at["q:AAPL"] = time.time() - svc.REST_REFRESH_S - 1  # the REST snapshot is old; the tick is fresh
    calls = []
    svc._background = lambda coro: (calls.append(1), coro.close())  # type: ignore[method-assign]
    import asyncio

    out = asyncio.run(svc.quotes(["AAPL"]))
    assert out["AAPL"]["stale"] is False  # the price is fresh, so it is not flagged stale
    assert calls, "a background REST refresh must be scheduled"


# --- A-3 ---------------------------------------------------------------------------------------------------------

def test_expired_login_does_not_turn_real_errors_into_provider_down():
    login = ("kite", ProviderError("login_expired", "KITE LOGIN EXPIRED"))
    depth = AllFailed([login, ("yahoo", ProviderError("depth", "5m ONLY AVAILABLE FOR THE LAST 60 DAYS"))])
    assert depth.kind == "bad_request" and "60 DAYS" in str(depth)
    missing = AllFailed([login, ("yahoo", ProviderError("not_found", "no such symbol"))])
    assert missing.kind == "not_found"
    down = AllFailed([login, ("yahoo", ProviderError("unavailable", "timeout"))])
    assert down.kind == "unavailable"


def test_history_limits_and_cache_key_ignore_an_expired_kite(client):
    router = client.app.state.service.router
    kite = router.providers["kite"]
    kite.why_down = lambda: "KITE LOGIN EXPIRED"  # type: ignore[method-assign]
    kite.supports = lambda cap, symbol=None: cap in ("history", "quotes")  # type: ignore[method-assign]
    kite.intraday_days = {"5m": 4200}
    sources = router.history_limits("RELIANCE.NS")["source"]
    assert "kite" not in sources
    kite.why_down = lambda: None  # type: ignore[method-assign]
    assert "kite" in router.history_limits("RELIANCE.NS")["source"]


# --- A-4 ---------------------------------------------------------------------------------------------------------

def test_ytd_is_year_to_date():
    assert ranges.range_days("ytd", dt.date(2026, 1, 1)) == 1
    assert ranges.range_days("ytd", dt.date(2026, 3, 15)) == 74  # 31 + 28 + 15
    assert ranges.range_days("ytd", dt.date(2026, 11, 6)) == 310
    assert ranges.range_days("1y") == 366


# --- B-2 ---------------------------------------------------------------------------------------------------------

def test_derivs_answer_carries_the_staleness_of_its_chain(client):
    fresh = client.get("/api/deriv/pcr", params={"symbol": "AAPL"}).json()
    assert fresh["stale"] is False
    svc = client.app.state.service
    key = "d:chain:AAPL:0"
    value, stored = svc.cache.mem[key]
    svc.cache.mem[key] = (value, stored - 10_000)  # the chain is now long past its 120 s freshness
    # The other expiries are cached too; age them all so the whole input set is stale.
    for k in [k for k in svc.cache.mem if k.startswith("d:chain:AAPL:")]:
        v, s = svc.cache.mem[k]
        svc.cache.mem[k] = (v, s - 10_000)
    old = client.get("/api/deriv/pcr", params={"symbol": "AAPL"}).json()
    assert old["stale"] is True
    assert old["age_s"] >= 9_000, "age must be the age of the oldest input, not 0"
