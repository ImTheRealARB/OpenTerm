"""Review sprint (area backend-compute): job runner races and leaks. Direct JobRunner, no HTTP, no network."""

import asyncio

from openterm.db import migrate, open_db
from openterm.jobs.runner import JobRunner
from openterm.jobs.store import JobStore


async def _runner(tmp_path, workers: int = 1):
    db = await open_db(tmp_path / "rv.db")
    await migrate(db)
    return db, JobRunner(JobStore(db), lambda frame: None, workers)


async def _wait(runner: JobRunner, job_id: str, timeout: float = 15.0) -> dict:
    end = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < end:
        j = await runner.get(job_id)
        if j and j["state"] in ("done", "error", "cancelled"):
            return j
        await asyncio.sleep(0.02)
    raise AssertionError(f"job {job_id} did not finish: {await runner.get(job_id)}")


async def test_concurrent_identical_submits_run_once(tmp_path):
    """Two submits of the same work, racing through the cache lookup, used to start two jobs."""
    db, runner = await _runner(tmp_path, workers=2)
    try:
        params = {"steps": 3, "step_ms": 20, "tag": "race"}
        a, b = await asyncio.gather(runner.submit("sleep", dict(params)), runner.submit("sleep", dict(params)))
        assert a["id"] == b["id"]
        assert len(runner.jobs) == 1
        await _wait(runner, a["id"])
    finally:
        runner.close()
        await db.close()


async def test_submit_right_after_finish_hits_the_result_not_a_rerun(tmp_path):
    """A job that finished but is not yet in the store is still the answer to an identical submit."""
    db, runner = await _runner(tmp_path)
    try:
        params = {"steps": 1, "step_ms": 1, "tag": "fresh"}
        first = await runner.submit("sleep", dict(params))
        # poll the in-memory view only: stop as soon as the runner has it finished
        for _ in range(500):
            if first["id"] in runner._done or first["id"] not in runner.jobs:
                break
            await asyncio.sleep(0.01)
        again = await runner.submit("sleep", dict(params))
        assert again["id"] == first["id"] or again.get("cached")
        await _wait(runner, first["id"])
    finally:
        runner.close()
        await db.close()


async def test_pool_survives_repeated_worker_deaths(tmp_path):
    """The reader remembered dead workers by id(): a new worker allocated at a freed address was then ignored forever."""
    db, runner = await _runner(tmp_path)
    try:
        for i in range(6):
            j = await runner.submit("sleep", {"steps": 3, "step_ms": 1, "crash_at": 1, "tag": f"c{i}"})
            r = await _wait(runner, j["id"])
            assert r["state"] == "error" and "WORKER DIED" in r["error"]
        ok = await runner.submit("sleep", {"steps": 2, "step_ms": 1, "tag": "after"})
        r = await _wait(runner, ok["id"], timeout=8.0)
        assert r["state"] == "done"
    finally:
        runner.close()
        await db.close()


async def test_pool_does_not_key_dead_workers_by_id(tmp_path, monkeypatch):
    """Simulates id() reuse (every object has the same id): a replacement worker must still be read."""
    import openterm.jobs.runner as runner_mod

    monkeypatch.setattr(runner_mod, "id", lambda _o: 7, raising=False)
    db, runner = await _runner(tmp_path)
    try:
        j = await runner.submit("sleep", {"steps": 3, "step_ms": 1, "crash_at": 1, "tag": "x"})
        assert (await _wait(runner, j["id"]))["state"] == "error"
        ok = await runner.submit("sleep", {"steps": 2, "step_ms": 1, "tag": "after"})
        assert (await _wait(runner, ok["id"], timeout=8.0))["state"] == "done"
    finally:
        runner.close()
        await db.close()


async def test_recent_listing_skips_result_blobs_but_keeps_rows(tmp_path):
    db = await open_db(tmp_path / "rc.db")
    await migrate(db)
    store = JobStore(db)
    await store.save({"id": "a", "kind": "sleep", "hash": "h", "state": "done", "params": {"x": 1}, "result": {"big": [1] * 1000},
                      "error": None, "created_at": 1, "started_at": 1, "finished_at": 2})
    rows = await store.recent(5)
    assert [r["id"] for r in rows] == ["a"] and rows[0]["params"] == {"x": 1} and "result" not in rows[0]
    assert (await store.get("a"))["result"] == {"big": [1] * 1000}
    await db.close()
