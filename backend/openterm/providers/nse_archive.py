"""NSE end-of-day bars built from the exchange's public archive (Phase 19 step 9): a `history` fallback for `.NS` symbols at `1d` only.

NSE publishes one CM bhavcopy file per trading day (`nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_<YYYYMMDD>_F_0000.csv.zip`,
a zip holding one CSV of every cash-market instrument). There is no per-symbol endpoint, so a series is BUILT day by day: each file is
fetched once, reduced to its EQ and BE rows and kept in SQLite (`world/india_store.py`, the `kv` table). A weekday that answers 404 is a
market holiday: it is remembered as a gap, never an error. Weekends are never requested. The last 250 sessions are kept.

Choices (all in DATA_LIMITS.md):
- It sits LAST in the `history` chain, so Yahoo answers whenever it can; this adapter only runs after Yahoo (and the others) failed.
- Politeness: 2 requests a second, at most 3 at once, and at most `FETCH_PER_REQUEST` (12) new day files per history request, newest first.
  The first answer therefore holds what exists (at least a few weeks) and says so: `NSE ARCHIVE, EOD, built from N daily files (INCOMPLETE)`.
  A single background task then fetches the rest (a few files per second, stops at the first error and rests 2 minutes) so later requests
  find it complete. The 250-session cap and the 275-weekday walk bound the total at about 275 files, once.
- A 404 for a day within the last 2 days is "not published yet" (the file appears in the evening): it is retried later and never cached as a gap.
- The prices are the day's raw prices. NSE does not adjust them for splits or bonus issues, so a series that spans one has a jump.
- A User-Agent with a contact string stalls NSE's edge (no answer until the read times out); a plain `OpenTerm` answers in about 0.3 s. No cookie,
  no captcha and no bot check was met. If the host ever starts demanding one, this adapter is switched off (remove it from the history order).
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime, timedelta
from typing import ClassVar

import httpx

from ..models import Bars
from ..world.india import (
    IST,
    bhavcopy_url,
    build_columns,
    label,
    nse_symbol,
    parse_bhavcopy,
    plan,
    unzip_bhavcopy,
)
from ..world.india_store import DayStore
from .base import HISTORY, Provider, ProviderError

log = logging.getLogger("openterm.nse_archive")

FIXTURE_TODAY = date(2026, 10, 17)  # fixture mode replays recordings made on this date, so "today" is pinned to it
WINDOW_DAYS = 400  # day files older than this are forgotten (250 sessions are about 365 calendar days)
PUBLISH_LAG = timedelta(days=2)  # a 404 younger than this is "not published yet", not a holiday
RETRY_PENDING_S = 1800.0
BACKOFF_S = 120.0


class NseArchiveProvider(Provider):
    name = "nse_archive"
    label = "NSE archive: daily bhavcopy files (end of day)"
    capabilities = frozenset({HISTORY})
    markets = "NSE equities (.NS), 1d bars only, the last 250 sessions, raw (unadjusted) prices; built day by day from the exchange's public archive"
    terms = "Public NSE archive files (nsearchives.nseindia.com), no key, no cookie. A fallback for when Yahoo cannot answer."
    rate = (2.0, 3)
    max_wait = 5.0
    timeout = 20.0
    headers: ClassVar[dict[str, str]] = {"User-Agent": "OpenTerm", "Accept": "*/*"}
    FETCH_PER_REQUEST = 12
    BACKGROUND_BATCH = 6
    CONCURRENCY = 3

    def __init__(self, http: httpx.AsyncClient, source: str | None = None):
        super().__init__(http, source)
        self.fixtures = (source or "").endswith(":fixture")
        self.store: DayStore | None = None
        self.clock = (lambda: FIXTURE_TODAY) if self.fixtures else (lambda: datetime.now(IST).date())
        self.background = not self.fixtures
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self._rest_until = 0.0
        self._pending: dict[date, float] = {}
        self.last_error: ProviderError | None = None

    def attach(self, db) -> None:
        """Called by the lifespan once the database exists: nothing works before this."""
        self.store = DayStore(db)

    async def close(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    def supports(self, capability: str, symbol: str | None = None) -> bool:
        return capability in self.capabilities and self.store is not None and symbol is not None and nse_symbol(symbol) is not None

    # --- one day file ---------------------------------------------------------------------------------------------
    async def fetch_day(self, day: date) -> dict[str, list] | None:
        """The EQ/BE rows of `day`, or None when the archive has no file (404: a market holiday, or not published yet)."""
        try:
            content = await self.get_bytes(bhavcopy_url(day))
        except ProviderError as e:
            if e.kind == "not_found":
                return None
            raise
        try:
            traded, rows = parse_bhavcopy(unzip_bhavcopy(content))
        except ValueError as e:
            raise ProviderError("unavailable", str(e)) from e
        if traded != day:
            raise ProviderError("unavailable", f"FILE FOR {day.isoformat()} CARRIES TRADE DATE {traded.isoformat()}")
        return rows

    # --- building ---------------------------------------------------------------------------------------------------
    async def extend(self, budget: int) -> tuple[ProviderError | None, int]:
        """Fetch up to `budget` of the newest unknown days. -> (the error that stopped it, unknown days still to fetch)."""
        assert self.store is not None
        async with self._lock:
            now = time.time()
            today = self.clock()
            if now < self._rest_until:
                return self.last_error, -1
            known = await self.store.known(today - timedelta(days=WINDOW_DAYS))
            _, missing = plan(today, known)
            todo = [d for d in missing if now - self._pending.get(d, 0.0) > RETRY_PENDING_S][:budget]
            sem = asyncio.Semaphore(self.CONCURRENCY)

            async def one(d: date) -> dict[str, list] | None:
                async with sem:
                    return await self.fetch_day(d)

            results = await asyncio.gather(*(one(d) for d in todo), return_exceptions=True)
            error: ProviderError | None = None
            resolved: set[date] = set()
            for d, res in zip(todo, results, strict=True):
                if isinstance(res, ProviderError):
                    error = error or res
                elif isinstance(res, BaseException):
                    raise res
                elif res is None:
                    if d <= today - PUBLISH_LAG:
                        await self.store.put_gap(d)
                        resolved.add(d)
                    else:
                        self._pending[d] = now
                else:
                    await self.store.put_day(d, res)
                    self._pending.pop(d, None)
                    resolved.add(d)
            if error is not None:
                self.last_error = error
                self._rest_until = time.time() + BACKOFF_S
                log.warning("nse archive: %s %s", error.kind, error)
            if resolved:
                await self.store.prune(today - timedelta(days=WINDOW_DAYS + 30))
            left = [d for d in missing if d <= today - PUBLISH_LAG and d not in resolved]
            return error, len(left)

    async def _build(self) -> None:
        try:
            while True:
                error, left = await self.extend(self.BACKGROUND_BATCH)
                if error is not None or left <= 0:
                    return
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("nse archive background build failed")

    # --- history ------------------------------------------------------------------------------------------------------
    async def history(self, symbol: str, range_: str, interval: str) -> Bars:
        nsym = nse_symbol(symbol)
        if nsym is None:
            raise ProviderError("unsupported", "NSE ARCHIVE COVERS .NS SYMBOLS ONLY")
        if interval != "1d":
            raise ProviderError("unsupported", "NSE ARCHIVE HAS DAILY (1D) BARS ONLY")
        if self.store is None:
            raise ProviderError("unavailable", "NSE ARCHIVE STORE NOT READY")
        error, left = await self.extend(self.FETCH_PER_REQUEST)
        today = self.clock()
        known = await self.store.known(today - timedelta(days=WINDOW_DAYS))
        used, missing = plan(today, known)
        rows, fetched = await self.store.rows(used)
        cols = build_columns(rows, nsym, range_)
        partial = any(d <= today - PUBLISH_LAG for d in missing)
        if cols is None:
            if error is not None and not rows:
                raise error
            raise ProviderError("not_found", f"{nsym} HAS NO EQ/BE ROW IN THE {len(rows)} NSE ARCHIVE FILES BUILT SO FAR")
        if partial and self.background and error is None and left != 0 and (self._task is None or self._task.done()):
            self._task = asyncio.ensure_future(self._build())
        return Bars(
            symbol=symbol.upper(), range=range_, interval="1d", currency="INR", exchange="NSE (RAW CLOSES, NOT ADJUSTED FOR SPLITS OR BONUS)",
            tz="Asia/Kolkata", **cols, source=label(len(rows), partial), as_of=fetched or time.time(),
        )

    async def probe(self) -> None:
        d = self.clock()
        for _ in range(10):  # the newest weekday that has a file
            d -= timedelta(days=1)
            if d.weekday() < 5 and await self.fetch_day(d) is not None:
                return
        raise ProviderError("unavailable", "NO BHAVCOPY FILE IN THE LAST 10 WEEKDAYS")
