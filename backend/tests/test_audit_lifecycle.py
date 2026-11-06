"""Audit C-1, C-2, C-3: shutdown waits for background work, forgetting a job also forgets the in-memory copy, news polls run at once."""

import asyncio
import time

from openterm.alerts_engine import AlertsEngine
from openterm.db import migrate, open_db
from openterm.jobs.runner import JobRunner
from openterm.jobs.store import JobStore


async def _runner(tmp_path):
    db = await open_db(tmp_path / "lc.db")
    await migrate(db)
    return db, JobRunner(JobStore(db), lambda frame: None, 1)


async def _finished(runner: JobRunner, job_id: str) -> None:
    for _ in range(1500):
        if job_id not in runner.jobs:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("job did not finish")


async def test_forget_drops_the_finished_copy_and_its_store_row(tmp_path):
    """C-2: a job finished but not yet stored was still the cached answer after its run was deleted, and its write came back."""
    db, runner = await _runner(tmp_path)
    try:
        params = {"steps": 1, "step_ms": 1, "tag": "forget"}
        first = await runner.submit("sleep", dict(params))
        await _finished(runner, first["id"])
        await runner.forget(runner.hash_for("sleep", params))
        assert first["id"] not in runner._done and not runner._persisting
        assert await runner.store.get(first["id"]) is None  # the late write did not bring it back
        again = await runner.submit("sleep", dict(params))
        assert again["id"] != first["id"] and not again.get("cached")  # really runs again
        await _finished(runner, again["id"])
    finally:
        await runner.aclose()
        await db.close()


async def test_clear_finished_waits_for_in_flight_writes(tmp_path):
    db, runner = await _runner(tmp_path)
    try:
        j = await runner.submit("sleep", {"steps": 1, "step_ms": 1, "tag": "clear"})
        await _finished(runner, j["id"])
        await runner.clear_finished()
        assert runner._done == {} and await runner.store.get(j["id"]) is None
    finally:
        await runner.aclose()
        await db.close()


async def test_aclose_waits_for_the_store_write_before_the_database_closes(tmp_path):
    """C-1: shutdown used to close SQLite while a finished job's write was still pending."""
    db, runner = await _runner(tmp_path)
    j = await runner.submit("sleep", {"steps": 1, "step_ms": 1, "tag": "close"})
    await _finished(runner, j["id"])
    await runner.aclose()
    assert not runner._bg and not runner._timers and not runner._pending_frame
    assert (await runner.store.get(j["id"]))["state"] == "done"
    await db.close()


class _Hub:
    def __init__(self):
        self.tick_listeners = []

    async def subscribe(self, client, symbols):
        client.symbols.update(symbols)

    async def unsubscribe(self, client, symbols):
        client.symbols.difference_update(symbols)

    def broadcast(self, frame):
        pass


async def test_engine_stop_waits_for_its_tasks(tmp_path):
    """C-1: stop() only cancelled; a cancelled fire task then touched the database after shutdown closed it."""
    db = await open_db(tmp_path / "e.db")
    await migrate(db)

    async def news_fetch(symbol):
        return {"data": {"items": []}, "stale": False}

    engine = AlertsEngine(db, _Hub(), lambda *a: None, news_fetch, fixtures=False)
    await engine.start()
    gate = asyncio.Event()

    async def slow():
        try:
            await gate.wait()
        finally:
            await asyncio.sleep(0)  # still running its cleanup when stop() is called

    t = asyncio.create_task(slow())
    engine._tasks.add(t)
    await asyncio.sleep(0)
    await engine.stop()
    assert t.done() and engine._news_task.done()
    await db.close()


async def test_news_poll_fetches_every_symbol_at_once(tmp_path, monkeypatch):
    """C-3: each stale answer waits STALE_NEWS_RETRY_S before the second look; that wait was paid once per symbol, in series."""
    monkeypatch.setattr("openterm.alerts_engine.STALE_NEWS_RETRY_S", 0.3)
    db = await open_db(tmp_path / "n.db")
    await migrate(db)

    async def news_fetch(symbol):
        return {"data": {"items": []}, "stale": True, "source": "rss"}

    engine = AlertsEngine(db, _Hub(), lambda *a: None, news_fetch, fixtures=False)
    for sym in ("AAPL", "MSFT", "NVDA", "TSLA"):
        await engine.news.create({"word": "RECALL", "symbol": sym})
    t0 = time.monotonic()
    await engine.poll_news()
    assert time.monotonic() - t0 < 0.9  # one 0.3 s wait in parallel, not 4 x 0.3 s
    await engine.stop()
    await db.close()
