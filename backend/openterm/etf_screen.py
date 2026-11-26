"""FSRC engine: collects the fee, size and category of every US ETF in a slow background job and serves what it has so far.

Why a background job: there is no "all ETFs with their fees" download. The list of ETFs comes from one file (Nasdaq Trader, one
call), but each fund's expense ratio and total assets need ONE Yahoo call per fund, about 5,800 of them. At the pace Yahoo
tolerates (about 3 a second) that is 30 to 40 minutes, far too long to hold an HTTP request open. So:

  * the first request starts a job on the app's scheduler (`step()` runs every few seconds and fetches a small batch);
  * each batch adds rows; the panel polls `snapshot()` and shows the rows loaded so far, labelled PARTIAL;
  * progress is saved to the cache every few hundred rows and read back at start-up, so a restart carries on instead of
    starting again, and a row is only fetched again once it is a day old.

Nothing here makes up a number. A fund Yahoo has no data for is counted ("no data"), not shown with blanks; a transient failure
is retried and, if it keeps failing, counted as "failed".
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import deque
from datetime import UTC, datetime

from apscheduler.jobstores.base import JobLookupError

from . import errkinds as K
from .errors import DataError
from .redact import redact
from .router import AllFailed
from .service import envelope

log = logging.getLogger("openterm.fsrc")

DAY_S = 86_400.0  # a fetched row is good for a day (fees and fund sizes change slowly)
RETRY_FAILED_S = 3_600.0  # a symbol that kept failing waits an hour before the next try
TICK_S = 4  # the scheduler runs `step` this often (a run that is still going is not started twice)
BATCH = 40  # symbols per step
CONCURRENCY = 3  # calls in flight at once. The pace itself (3 a second) is the provider's own token bucket, `YahooFundsProvider.rate`
PAUSE_S = 90.0  # how long to leave Yahoo alone after it rate-limits us or fails several calls in a row
FAIL_STREAK = 8  # this many transient failures in a row = Yahoo is down or blocking: pause
MAX_ATTEMPTS = 3  # tries per symbol per pass before it is put on the "failed, retry in an hour" list
SAVE_EVERY = 150  # rows between saves of the progress to the cache
CACHE_KEY = "fsrc:rows"
JOB_ID = "fsrc"

# A stored row: [fee percent, total assets $, category, family, fetched-at epoch seconds]
Row = list


class FundScreener:
    """One per app (`app.state.fsrc`). Built lazily by the first FSRC request, see `etf_routes.engine_of`."""

    def __init__(self, service, scheduler):
        self.svc = service
        self.sched = scheduler
        self.run = uuid.uuid4().hex[:8]  # a client holding rows from another run must start over (see `snapshot`)
        self.names: dict[str, str] = {}  # symbol -> name, every ETF the symbol file lists
        self.rows: dict[str, Row] = {}
        self.nodata: dict[str, float] = {}  # symbol -> when Yahoo last said it has no fund data for it
        self.failed: dict[str, tuple[float, str]] = {}  # symbol -> (when, why) it kept failing
        self.log: list[str] = []  # symbols in the order their rows were loaded (a reload appends again): the delta feed
        self.todo: deque[str] = deque()
        self.attempts: dict[str, int] = {}
        self.universe_source = ""
        self.file_stamp: str | None = None
        self.updated_at = 0.0
        self.paused_until = 0.0
        self.note: str | None = None
        self._restored = False
        self._job_on = False
        self._unsaved = 0
        self._lock = asyncio.Lock()

    # --- what a symbol needs -------------------------------------------------------------------------------------------
    def _needs(self, sym: str, now: float) -> bool:
        row = self.rows.get(sym)
        if row is not None and now - row[4] < DAY_S:
            return False
        if now - self.nodata.get(sym, 0.0) < DAY_S:
            return False
        failed = self.failed.get(sym)
        return not (failed is not None and now - failed[0] < RETRY_FAILED_S)

    # --- start-up, universe, scheduling --------------------------------------------------------------------------------
    async def ensure(self) -> None:
        """Called on every poll: restores saved progress once, makes sure the symbol list is known and the job is running while
        there is work. Cheap when everything is loaded (one pass over the symbols). Raises DataError when there is no symbol
        list at all (nothing to show and nothing to fetch)."""
        async with self._lock:
            if not self._restored:
                await self._restore()
            try:
                await self._load_universe()
            except DataError:
                if not self.names:
                    raise  # no list and nothing saved: the panel shows the error with its source
                self.note = "SYMBOL LIST NOT REFRESHED, USING THE SAVED ONE"  # older list still usable: say so, keep going
            now = time.time()
            if not self._job_on and not self.todo:
                self.todo = deque(s for s in self.names if self._needs(s, now))
            if self.todo and not self._job_on:
                self._start_job()

    async def _load_universe(self) -> None:
        router = self.svc.router

        async def fetch() -> dict:
            data, failed = await router.call("etf_universe", lambda p: p.etf_universe())
            return {"data": data, "fallback_from": failed}

        env = await self.svc.swr("etf:universe", DAY_S, fetch)
        data = env["data"]
        self.names = {e["symbol"]: e["name"] for e in data["etfs"]}
        self.universe_source = data["source"]
        self.file_stamp = data.get("file_stamp")
        if self.note and self.note.startswith("SYMBOL LIST"):
            self.note = None

    def _start_job(self) -> None:
        self._job_on = True
        # The first run is NOW (an interval job otherwise waits one interval), the next ones every TICK_S while work remains.
        self.sched.add_job(self.step, "interval", seconds=TICK_S, id=JOB_ID, max_instances=1, coalesce=True,
                           replace_existing=True, next_run_time=datetime.now(UTC))

    def _stop_job(self) -> None:
        self._job_on = False
        try:
            self.sched.remove_job(JOB_ID)
        except JobLookupError:
            pass  # already gone (shutdown, or a second finish): nothing to remove

    # --- the job -------------------------------------------------------------------------------------------------------
    async def step(self) -> None:
        """One batch. A failure that is not "this fund has no data" is recorded, never swallowed silently: see `note`."""
        now = time.time()
        if now < self.paused_until:
            return
        if self.note and self.note.startswith("YAHOO"):
            self.note = None  # a pause note ends with the pause
        batch = [self.todo.popleft() for _ in range(min(BATCH, len(self.todo)))]
        if not batch:
            self._finish()
            return
        gate = asyncio.Semaphore(CONCURRENCY)
        streak = 0
        halted = False
        retry: list[str] = []

        async def one(sym: str) -> None:
            nonlocal streak, halted
            async with gate:
                if halted:  # a rate limit or a failure streak stopped the batch: put the rest back, untouched
                    retry.append(sym)
                    return
                try:
                    row, _ = await self.svc.router.call("fund_profile", lambda p: p.fund_profile(sym))
                except AllFailed as e:
                    kinds = {err.kind for _, err in e.errors}
                    if kinds and kinds <= {K.NOT_FOUND, K.UNSUPPORTED}:
                        self.nodata[sym] = time.time()  # Yahoo has no fund data for it (an ETN, a very new fund)
                        streak = 0
                        self._unsaved += 1
                        return
                    streak += 1
                    reason = redact("; ".join(f"{n}: {err.kind} ({err})" for n, err in e.errors) or "no answer")
                    if K.RATE_LIMITED in kinds or streak >= FAIL_STREAK:
                        halted = True
                        self.paused_until = time.time() + PAUSE_S
                        self.note = f"YAHOO NOT ANSWERING ({reason[:80]}): PAUSED {int(PAUSE_S)} S"
                    self._count_failure(sym, reason, retry)
                    return
                streak = 0
                self._store(sym, row)

        await asyncio.gather(*(one(s) for s in batch))
        self.todo.extend(retry)  # failures go to the back of the line
        if self._unsaved >= SAVE_EVERY:
            self._save()
        if not self.todo:
            self._finish()

    def _count_failure(self, sym: str, reason: str, retry: list[str]) -> None:
        self.attempts[sym] = self.attempts.get(sym, 0) + 1
        if self.attempts[sym] >= MAX_ATTEMPTS:
            self.failed[sym] = (time.time(), reason)  # stop asking for an hour; it is counted in the panel
            self.attempts.pop(sym, None)
        else:
            retry.append(sym)

    def _store(self, sym: str, row: dict) -> None:
        now = time.time()
        self.rows[sym] = [row["fee"], row["aum"], row["category"], row["family"], now]
        self.failed.pop(sym, None)
        self.attempts.pop(sym, None)
        self.log.append(sym)
        self.updated_at = now
        self._unsaved += 1

    def _finish(self) -> None:
        self._stop_job()
        self._save()

    # --- saving and restoring ------------------------------------------------------------------------------------------
    def _save(self) -> None:
        self.svc.cache.put(CACHE_KEY, {"rows": dict(self.rows), "nodata": dict(self.nodata), "failed": dict(self.failed)})
        self._unsaved = 0

    async def _restore(self) -> None:
        self._restored = True
        entry = await self.svc.cache.get(CACHE_KEY)
        if entry is None:
            return
        saved = entry[0]
        try:
            # Rows are [fee, aum, category, family, fetched_at]; anything else (an older layout) is dropped, never half-read.
            self.rows = {s: r for s, r in (saved.get("rows") or {}).items() if isinstance(r, list) and len(r) == 5}
            self.nodata = {s: float(t) for s, t in (saved.get("nodata") or {}).items()}
            self.failed = {s: (float(v[0]), str(v[1])) for s, v in (saved.get("failed") or {}).items()}
        except (AttributeError, TypeError, ValueError, IndexError) as e:
            # A cache entry this code cannot read is just a cache miss: log it and load everything again.
            log.warning("saved FSRC progress unreadable (%s): loading again", type(e).__name__)
            self.rows, self.nodata, self.failed = {}, {}, {}
        self.log = sorted(self.rows, key=lambda s: self.rows[s][4])  # oldest first, so a later reload lands later
        self.updated_at = max((r[4] for r in self.rows.values()), default=0.0)

    # --- what the panel gets -------------------------------------------------------------------------------------------
    def snapshot(self, run: str | None, after: int) -> dict:
        """The rows loaded since `after` (a number this method returned as `seq`), as [symbol, name, fee, aum, category, family].

        A client that sends a different `run` (the server restarted) or a position past the end of the log gets everything
        (`reset: true`): it must drop what it holds first. Otherwise it gets only the new rows, so a 5,800-row table is not sent
        again on every poll."""
        reset = run != self.run or after < 0 or after > len(self.log)
        seen: set[str] = set()
        rows: list[list] = []
        for sym in self.log[0 if reset else after :]:
            name = self.names.get(sym)
            if sym in seen or name is None:  # a fund no longer in the symbol file is not shown
                continue
            seen.add(sym)
            fee, aum, cat, fam, _ = self.rows[sym]
            rows.append([sym, name, fee, aum, cat, fam])
        loaded = sum(1 for s in self.rows if s in self.names)
        now = time.time()
        state = "paused" if now < self.paused_until else "loading" if (self.todo or self._job_on) else "complete"
        return {
            "run": self.run, "reset": reset, "seq": len(self.log), "rows": rows,
            "universe": len(self.names), "loaded": loaded,
            "nodata": sum(1 for s in self.nodata if s in self.names),
            "failed": sum(1 for s in self.failed if s in self.names),
            "state": state, "partial": state != "complete", "note": self.note,
            "universe_source": self.universe_source, "file_stamp": self.file_stamp,
        }

    def payload(self, run: str | None, after: int) -> dict:
        """`snapshot` wrapped in the standard answer envelope (source, as_of, age_s, stale), as every data route returns it."""
        data = self.snapshot(run, after)
        provider = self.svc.router.providers.get("yahoo_funds")
        value = {"data": data, "source": provider.source if provider else "yahoo_funds", "fallback_from": []}
        # STALE = we want to refresh but cannot (Yahoo paused us): what is shown is older than it should be.
        return envelope(value, self.updated_at or time.time(), stale=data["state"] == "paused")

