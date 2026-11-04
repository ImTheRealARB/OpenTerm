"""Regression tests for the backend bug sweep (see docs/review/cloud/BACKEND_BUGS.md)."""

import asyncio
import time

import orjson

from openterm.cache import Cache
from openterm.db import open_db


# --- 1. cache pruning ---------------------------------------------------------------------
async def test_cache_prune_by_age_and_size(tmp_path):
    db = await open_db(tmp_path / "t.db")
    c = Cache(db, flush_s=0.0)
    now = time.time()
    c.put("old", {"x": 1}, stored_at=now - 40 * 86400)  # older than the age limit
    c.put("new1", {"pad": "x" * 1000}, stored_at=now - 20)
    c.put("new2", {"pad": "y" * 1000}, stored_at=now - 10)
    await c.flush()
    removed = await c.prune(max_age_s=30 * 86400, max_bytes=10_000_000)
    assert removed == 1
    assert (await Cache(db).get("old")) is None and (await Cache(db).get("new1")) is not None
    # size cap: the oldest rows go first until the table fits
    removed = await c.prune(max_age_s=30 * 86400, max_bytes=1500)
    assert removed == 1
    assert (await Cache(db).get("new1")) is None and (await Cache(db).get("new2")) is not None
    assert "old" not in c.mem and "new1" not in c.mem  # memory layer forgets pruned keys too
    await db.close()


def test_scheduler_registers_cache_prune():
    from openterm import scheduler

    async def go():
        sched = scheduler.start(object(), Cache(None))  # router is only used by the job's args
        try:
            assert sched.get_job("cache_prune") is not None
        finally:
            sched.shutdown(wait=False)

    asyncio.run(go())


# --- 2. Yahoo quote batches are paced ---------------------------------------------------------
async def test_yahoo_quotes_chunks_are_paced(monkeypatch):
    from openterm.providers import yahoo

    monkeypatch.setattr(yahoo, "SPARK_GAP_S", 0.01)
    p = yahoo.YahooProvider(None)
    live = peak = 0
    sizes: list[int] = []

    async def fake_spark(symbols):
        nonlocal live, peak
        live += 1
        peak = max(peak, live)
        sizes.append(len(symbols))
        await asyncio.sleep(0.01)
        live -= 1
        return []

    monkeypatch.setattr(p, "_spark", fake_spark)
    await p.quotes([f"S{i}" for i in range(300)])
    assert max(sizes) <= 100 and sum(sizes) == 300
    assert peak <= yahoo.SPARK_PARALLEL  # never all chunks at once


# --- 3. coalescing survives a cancelled leader ----------------------------------------------------
async def test_once_waiter_survives_cancelled_leader():
    from openterm.service import DataService

    svc = DataService(None, Cache(None))
    calls = 0

    async def fetch():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return {"data": 1}

    leader = asyncio.create_task(svc._once("k", fetch))
    await asyncio.sleep(0.01)
    waiter = asyncio.create_task(svc._once("k", fetch))
    await asyncio.sleep(0.01)
    leader.cancel()
    assert (await waiter) == {"data": 1}  # used to raise CancelledError
    assert calls == 1 and "k" not in svc._inflight


# --- 4. DayStore decodes off the event loop ----------------------------------------------------------
async def test_daystore_rows_decode_off_loop(tmp_path, monkeypatch):
    import threading
    from datetime import date

    from openterm.world import india_store

    db = await open_db(tmp_path / "d.db")
    store = india_store.DayStore(db)
    await store.put_day(date(2026, 10, 15), {"AAA": [1, 2, 0.5, 1.5, 10]})
    await store.put_day(date(2026, 10, 16), {"AAA": [2, 3, 1, 2.5, 20]})
    real, threads = india_store.msgpack.unpackb, []

    def spy(*a, **kw):
        threads.append(threading.current_thread())
        return real(*a, **kw)

    monkeypatch.setattr(india_store.msgpack, "unpackb", spy)
    rows, at = await store.rows([date(2026, 10, 15), date(2026, 10, 16)])
    assert len(rows) == 2 and at is not None
    assert threads and all(t is not threading.main_thread() for t in threads)
    await db.close()


# --- 5. ATTR return measures ---------------------------------------------------------------------
def test_dietz_not_computable_after_big_withdrawal():
    from openterm.quantjobs.attr import return_measures

    # 1000 at the start, 1500 withdrawn on day 1 of 10 (weight 0.9): Dietz denominator is 1000 - 1500 < 0
    rows = {r["measure"]: r for r in return_measures([
        {"date": "2026-01-01", "value": 1000, "flow": 0},
        {"date": "2026-01-02", "value": 100, "flow": -1500},
        {"date": "2026-01-11", "value": 110, "flow": 0},
    ])}
    assert rows["MODIFIED DIETZ"]["value"] is None and "NOT DEFINED" in rows["MODIFIED DIETZ"]["note"]


def test_return_measures_empty_start_value():
    from openterm.quantjobs.attr import return_measures

    rows = {r["measure"]: r for r in return_measures([
        {"date": "2026-01-01", "value": 0, "flow": 0},
        {"date": "2026-02-01", "value": 100, "flow": 100},
    ])}
    assert rows["SIMPLE"]["value"] is None and rows["TWR"]["value"] is None  # no ZeroDivisionError


def test_xirr_finds_root_when_ends_have_same_sign():
    from datetime import date

    from openterm.quantjobs.attr import xirr

    # -100 now, +230 in a year, -132 in two years: roots at 10% and 20% (two roots) -> ambiguous -> None
    assert xirr([(date(2026, 1, 1), -100.0), (date(2027, 1, 1), 230.0), (date(2028, 1, 1), -132.0)]) is None
    # one clean root
    r = xirr([(date(2026, 1, 1), -100.0), (date(2027, 1, 1), 110.0)])
    assert abs(r - 0.10) < 1e-6
    # no sign change in the scan range -> explicit None, not a wrong root
    assert xirr([(date(2026, 1, 1), -100.0), (date(2027, 1, 1), -50.0)]) is None
