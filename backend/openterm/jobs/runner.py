"""Job runner: a small pool of long-lived worker processes (spawn), started on the first job.

Why not ProcessPoolExecutor: it cannot kill one running task. Here each worker has its own task pipe, result pipe
and cancel flag, so a cancel can ask nicely (the flag) and, after HARD_CANCEL_S, terminate that worker and spawn a
fresh one. One reader thread waits on every result pipe and process sentinel and hands events to the event loop.
"""

import asyncio
import contextlib
import logging
import multiprocessing as mp
import os
import threading
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from multiprocessing.connection import wait

from ..redact import redact
from . import job_hash
from .kinds import KINDS, BadParams
from .store import JobStore
from .worker import worker_main

log = logging.getLogger("openterm.jobs")
HARD_CANCEL_S = 2.0
FRAME_GAP_S = 0.1  # at most 10 progress frames per second per job; the last one is always sent
FINISHED = ("done", "error", "cancelled")
PUBLIC = ("id", "kind", "label", "params", "state", "progress", "msg", "cached", "error", "created_at", "started_at",
          "finished_at")


def default_workers() -> int:
    return max(1, min(4, (os.cpu_count() or 2) - 1))


class Worker:
    def __init__(self, ctx, wid: int):
        self.wid = wid
        task_r, self.tasks = ctx.Pipe(duplex=False)
        self.results, result_w = ctx.Pipe(duplex=False)
        self.cancel = ctx.Value("b", 0, lock=False)
        self.proc = ctx.Process(target=worker_main, args=(task_r, result_w, self.cancel), daemon=True,
                                name=f"openterm-job-{wid}")
        self.proc.start()
        task_r.close()
        result_w.close()
        self.job: str | None = None
        self.retired = False  # terminated on purpose: its death is not a crash

    def stop(self) -> None:
        self.retired = True
        with contextlib.suppress(Exception):
            self.tasks.send(None)
        self.proc.join(0.5)
        if self.proc.is_alive():
            self.proc.terminate()
            self.proc.join(0.5)
        for c in (self.tasks, self.results):
            with contextlib.suppress(Exception):
                c.close()


class JobRunner:
    def __init__(self, store: JobStore, broadcast: Callable[[list], None], workers: int = 0):
        self.store = store
        self.broadcast = broadcast
        self.size = workers or default_workers()
        self.jobs: dict[str, dict] = {}  # queued + running (finished ones live in the store)
        self._done: dict[str, dict] = {}  # finished, until the store write lands
        self.queue: deque[str] = deque()
        self.workers: list[Worker] = []
        self.loop: asyncio.AbstractEventLoop | None = None
        self._ctx = mp.get_context("spawn")
        self._wake_r = self._wake_w = None
        self._reader: threading.Thread | None = None
        self._closing = False
        self._last_frame: dict[str, float] = {}
        self._pending_frame: dict[str, asyncio.TimerHandle] = {}
        self._timers: dict[str, list[asyncio.TimerHandle]] = {}
        # kind -> async hook(job, result) -> result to keep, run before a done job becomes visible (bt.run stores
        # its run here, so GET /api/bt/runs/{id} works the moment the job says done)
        self.on_done: dict[str, Callable[[dict, object], Awaitable[object]]] = {}

    # --- pool --------------------------------------------------------------------------------------------------
    def _start_pool(self) -> None:
        if self.workers or self._closing:
            return
        self.loop = asyncio.get_running_loop()
        self._wake_r, self._wake_w = self._ctx.Pipe(duplex=False)
        self.workers = [Worker(self._ctx, i) for i in range(self.size)]
        self._reader = threading.Thread(target=self._read, name="openterm-job-reader", daemon=True)
        self._reader.start()
        log.info("job pool started with %d workers", self.size)

    def _wake(self) -> None:
        with contextlib.suppress(Exception):
            self._wake_w.send(1)

    def _read(self) -> None:
        """Reader thread: blocks on all result pipes + process sentinels + the wake pipe."""
        dead: set[int] = set()
        while not self._closing:
            ws = list(self.workers)
            waitables = {self._wake_r: None}
            for w in ws:
                if id(w) in dead:
                    continue
                waitables[w.results] = w
                waitables[w.proc.sentinel] = w
            try:
                ready = wait(list(waitables))
            except OSError:
                continue
            for obj in ready:
                if obj is self._wake_r:
                    with contextlib.suppress(Exception):
                        self._wake_r.recv()
                    continue
                w = waitables[obj]
                if w is None or id(w) in dead:
                    continue
                if obj is w.results:
                    try:
                        msg = w.results.recv()
                    except (EOFError, OSError):
                        dead.add(id(w))
                        self.loop.call_soon_threadsafe(self._on_death, w)
                        continue
                    self.loop.call_soon_threadsafe(self._on_msg, w, msg)
                else:
                    # Drain whatever the worker sent before it died, then report the death.
                    with contextlib.suppress(EOFError, OSError):
                        while w.results.poll():
                            self.loop.call_soon_threadsafe(self._on_msg, w, w.results.recv())
                    dead.add(id(w))
                    self.loop.call_soon_threadsafe(self._on_death, w)

    def _replace(self, w: Worker) -> None:
        if self._closing:
            return
        i = self.workers.index(w)
        self.workers[i] = Worker(self._ctx, w.wid)
        self._wake()
        self._dispatch()

    # --- events (event loop thread) ---------------------------------------------------------------------------
    def _on_msg(self, w: Worker, msg: tuple) -> None:
        kind, job_id, payload = msg[0], msg[1], msg[2:]
        job = self.jobs.get(job_id)
        if job is None or w.job != job_id:
            return
        if kind == "progress":
            job["progress"], job["msg"] = max(job["progress"], min(1.0, payload[0])), payload[1]
            self._frame(job)
            return
        w.job = None
        if kind == "done" and job["kind"] in self.on_done:
            job["msg"] = "STORING"
            self.loop.create_task(self._finish_hooked(job, payload[0]))
        elif kind == "done":
            self._finish(job, "done", result=payload[0])
        elif kind == "error":
            self._finish(job, "error", error=redact(payload[0]))
        else:
            self._finish(job, "cancelled")
        self._dispatch()

    async def _finish_hooked(self, job: dict, result) -> None:
        try:
            result = await self.on_done[job["kind"]](job, result)
        except Exception as e:  # noqa: BLE001 - reported on the job
            log.exception("on_done hook failed for job %s", job["id"])
            self._finish(job, "error", error=redact(f"COULD NOT STORE THE RESULT: {type(e).__name__}: {e}"[:300]))
        else:
            self._finish(job, "done", result=result)

    def _on_death(self, w: Worker) -> None:
        if w.retired or w not in self.workers:
            return
        job = self.jobs.get(w.job) if w.job else None
        w.job = None
        log.warning("job worker %d died (exit %s)", w.wid, w.proc.exitcode)
        if job:
            self._finish(job, "error", error="WORKER DIED")
        self._replace(w)

    def _kill(self, job_id: str, state: str, error: str | None = None) -> None:
        """Terminates the worker running job_id (after a cancel that was ignored, or a time limit)."""
        job = self.jobs.get(job_id)
        w = next((w for w in self.workers if w.job == job_id), None)
        if job is None or w is None:
            return
        w.retired, w.job = True, None
        w.proc.terminate()
        self._finish(job, state, error=error)
        self._replace(w)

    def _dispatch(self) -> None:
        for w in self.workers:
            if not self.queue:
                return
            if w.job is None and not w.retired:
                job = self.jobs[self.queue.popleft()]
                w.job = job["id"]
                job["state"], job["started_at"] = "running", time.time()
                try:
                    w.tasks.send((job["id"], job["kind"], job["params"]))
                except OSError:
                    w.job = None
                    self.queue.appendleft(job["id"])
                    continue
                limit = KINDS[job["kind"]].time_limit_s
                if isinstance(job["params"], dict) and isinstance(job["params"].get("time_limit_s"), int | float):
                    limit = max(0.5, min(limit, float(job["params"]["time_limit_s"])))
                self._timers.setdefault(job["id"], []).append(
                    self.loop.call_later(limit, self._kill, job["id"], "error", "TIME LIMIT"))
                self._frame(job, force=True)

    # --- frames ----------------------------------------------------------------------------------------------
    @staticmethod
    def wire(job: dict) -> list:
        return ["J", {k: job[k] for k in ("id", "kind", "state", "progress", "msg", "cached")}]

    def _frame(self, job: dict, force: bool = False) -> None:
        jid = job["id"]
        now = time.monotonic()
        wait_s = FRAME_GAP_S - (now - self._last_frame.get(jid, 0.0))
        if force or wait_s <= 0:
            if (h := self._pending_frame.pop(jid, None)) is not None:
                h.cancel()
            self._last_frame[jid] = now
            self.broadcast(self.wire(job))
        elif jid not in self._pending_frame:
            def flush() -> None:
                self._pending_frame.pop(jid, None)
                self._last_frame[jid] = time.monotonic()
                self.broadcast(self.wire(job))

            self._pending_frame[jid] = self.loop.call_later(wait_s, flush)

    def _finish(self, job: dict, state: str, result=None, error: str | None = None) -> None:
        jid = job["id"]
        for h in self._timers.pop(jid, []):
            h.cancel()
        job.update(state=state, result=result, error=error, finished_at=time.time())
        if state == "done":
            job["progress"] = 1.0
        self.jobs.pop(jid, None)
        self._done[jid] = job
        self._frame(job, force=True)
        self._last_frame.pop(jid, None)
        self.loop.create_task(self._persist(job))

    async def _persist(self, job: dict) -> None:
        try:
            await self.store.save(job)
            await self.store.trim()
        except Exception:
            log.exception("could not store job %s", job["id"])
        finally:
            self._done.pop(job["id"], None)

    # --- public API ------------------------------------------------------------------------------------------
    @staticmethod
    def hash_for(kind: str, params: dict) -> str:
        k = KINDS[kind]
        return job_hash(kind, k.version, k.hash_view(params), k.fingerprint(params))

    async def submit(self, kind: str, params, internal: bool = False) -> dict:
        if kind not in KINDS or (KINDS[kind].internal and not internal):
            raise BadParams(f"UNKNOWN JOB KIND {str(kind).upper()}")
        k = KINDS[kind]
        params = k.validate(params)
        h = job_hash(kind, k.version, k.hash_view(params), k.fingerprint(params))
        for job in self.jobs.values():
            if job["hash"] == h:
                return self.public(job)  # the same work is already queued or running
        if (cached := await self.store.done_by_hash(h)) is not None:
            return {**self.public(self._from_store(cached)), "cached": True, "result": cached["result"]}
        job = {"id": uuid.uuid4().hex[:12], "kind": kind, "label": k.label, "params": params, "hash": h,
               "state": "queued", "progress": 0.0, "msg": "", "cached": False, "error": None, "result": None,
               "created_at": time.time(), "started_at": None, "finished_at": None}
        self.jobs[job["id"]] = job
        self.queue.append(job["id"])
        self._start_pool()
        self._frame(job, force=True)
        self._dispatch()
        return self.public(job)

    def cancel(self, job_id: str) -> dict | None:
        job = self.jobs.get(job_id)
        if job is None:
            return None
        if job["state"] == "queued":
            with contextlib.suppress(ValueError):
                self.queue.remove(job_id)
            self._finish(job, "cancelled")
            return self.public(job)
        w = next((w for w in self.workers if w.job == job_id), None)
        if w is not None:
            w.cancel.value = 1
            job["msg"] = "CANCELLING"
            self._timers.setdefault(job_id, []).append(
                self.loop.call_later(HARD_CANCEL_S, self._kill, job_id, "cancelled"))
        return self.public(job)

    async def get(self, job_id: str) -> dict | None:
        if job_id in self.jobs:
            return {**self.public(self.jobs[job_id]), "result": None}
        if job_id in self._done:
            return {**self.public(self._done[job_id]), "result": self._done[job_id]["result"]}
        stored = await self.store.get(job_id)
        return {**self.public(self._from_store(stored)), "result": stored["result"]} if stored else None

    async def list(self) -> list[dict]:
        live = [self.public(j) for j in self.jobs.values()]
        done = [self.public(j) for j in self._done.values()]
        ids = {j["id"] for j in done}
        stored = [self.public(self._from_store(r)) for r in await self.store.recent(50) if r["id"] not in ids]
        return sorted(live, key=lambda j: -j["created_at"]) + done + stored

    async def clear_finished(self) -> int:
        return await self.store.clear()

    @staticmethod
    def public(job: dict) -> dict:
        return {k: job.get(k) for k in PUBLIC}

    @staticmethod
    def _from_store(row: dict) -> dict:
        kind = KINDS.get(row["kind"])
        return {**row, "label": kind.label if kind else row["kind"].upper(), "cached": False,
                "progress": 1.0 if row["state"] == "done" else 0.0, "msg": ""}

    def close(self) -> None:
        self._closing = True
        if self._wake_w is not None:
            self._wake()
        for w in self.workers:
            w.stop()
        if self._reader is not None:
            self._reader.join(1.0)
        self.workers = []
