"""Two-level cache: bounded in-memory LRU in front of SQLite. Writes are batched off the request path."""

import asyncio
import logging
import time
from collections import OrderedDict
from typing import Any

import aiosqlite
import orjson

log = logging.getLogger("openterm.cache")

CACHE_MAX_AGE_S = 30 * 86400  # rows older than 30 days are never useful: even "stale" answers are shown with their age
CACHE_MAX_BYTES = 200 * 1024 * 1024  # keep the cache table under ~200 MB; the oldest rows go first

Entry = tuple[Any, float]  # (value, stored_at epoch s)


class Cache:
    def __init__(self, db: aiosqlite.Connection | None, max_entries: int = 5000, flush_s: float = 0.25):
        self.db = db
        self.max_entries = max_entries
        self.flush_s = flush_s
        self.mem: OrderedDict[str, Entry] = OrderedDict()
        self._dirty: dict[str, Entry] = {}
        self._flusher: asyncio.Task | None = None
        self.hits = 0
        self.misses = 0

    def _remember(self, key: str, entry: Entry) -> None:
        self.mem[key] = entry
        self.mem.move_to_end(key)
        while len(self.mem) > self.max_entries:
            self.mem.popitem(last=False)

    async def get(self, key: str) -> Entry | None:
        entry = self.mem.get(key)
        if entry is not None:
            self.mem.move_to_end(key)
            self.hits += 1
            return entry
        if self.db is not None:
            async with self.db.execute("SELECT value, stored_at FROM cache WHERE key=?", (key,)) as cur:
                row = await cur.fetchone()
            if row:
                entry = (orjson.loads(row[0]), row[1])
                self._remember(key, entry)
                self.hits += 1
                return entry
        self.misses += 1
        return None

    async def get_many(self, keys: list[str]) -> dict[str, Entry]:
        """Same answers as get() for each key, but the memory misses share one SQLite query (per 500 keys)
        instead of one thread round trip each. Missing keys are left out of the result."""
        out: dict[str, Entry] = {}
        need: list[str] = []
        for key in dict.fromkeys(keys):
            entry = self.mem.get(key)
            if entry is not None:
                self.mem.move_to_end(key)
                self.hits += 1
                out[key] = entry
            else:
                need.append(key)
        if need and self.db is not None:
            for i in range(0, len(need), 500):
                chunk = need[i : i + 500]
                marks = ",".join("?" * len(chunk))
                async with self.db.execute(f"SELECT key, value, stored_at FROM cache WHERE key IN ({marks})", chunk) as cur:
                    rows = await cur.fetchall()
                for key, blob, stored_at in rows:
                    entry = (orjson.loads(blob), stored_at)
                    self._remember(key, entry)
                    self.hits += 1
                    out[key] = entry
        self.misses += len(need) - sum(1 for k in need if k in out)
        return out

    def put(self, key: str, value: Any, stored_at: float | None = None) -> None:
        entry = (value, stored_at or time.time())
        self._remember(key, entry)
        if self.db is not None:
            self._dirty[key] = entry
            if self._flusher is None or self._flusher.done():
                self._flusher = asyncio.create_task(self._flush_later())

    async def _flush_later(self) -> None:
        await asyncio.sleep(self.flush_s)
        await self.flush()

    async def flush(self) -> None:
        if not self._dirty or self.db is None:
            return
        rows, self._dirty = self._dirty, {}
        try:
            await self.db.executemany(
                "INSERT OR REPLACE INTO cache (key, value, stored_at) VALUES (?, ?, ?)",
                [(k, orjson.dumps(v), t) for k, (v, t) in rows.items()],
            )
            await self.db.commit()
        except Exception:
            log.exception("cache flush failed; %d entries kept in memory only", len(rows))

    async def prune(self, max_age_s: float = CACHE_MAX_AGE_S, max_bytes: int = CACHE_MAX_BYTES) -> int:
        """Deletes cache rows older than max_age_s, then the oldest rows until the table is under max_bytes.
        Returns how many rows were removed. Without this the SQLite file only ever grows."""
        if self.db is None:
            return 0
        await self.flush()  # pending writes are part of the table too
        removed = 0
        try:
            cur = await self.db.execute("DELETE FROM cache WHERE stored_at < ?", (time.time() - max_age_s,))
            removed += cur.rowcount
            async with self.db.execute("SELECT COALESCE(SUM(LENGTH(value) + LENGTH(key)), 0) FROM cache") as c2:
                total = (await c2.fetchone())[0]
            if total > max_bytes:
                # walk from the oldest row and delete until enough bytes are freed
                async with self.db.execute("SELECT key, LENGTH(value) + LENGTH(key) FROM cache ORDER BY stored_at") as c3:
                    rows = await c3.fetchall()
                doomed: list[str] = []
                for key, size in rows:
                    if total <= max_bytes:
                        break
                    doomed.append(key)
                    total -= size
                for i in range(0, len(doomed), 500):  # chunks keep us under SQLite's variable limit
                    chunk = doomed[i : i + 500]
                    await self.db.execute(f"DELETE FROM cache WHERE key IN ({','.join('?' * len(chunk))})", chunk)
                removed += len(doomed)
                for key in doomed:
                    self.mem.pop(key, None)
            await self.db.commit()
        except Exception:
            log.exception("cache prune failed")
            return removed
        for key in [k for k, (_, t) in self.mem.items() if t < time.time() - max_age_s]:
            del self.mem[key]  # forget aged entries in memory too
        return removed

    @property
    def hit_pct(self) -> float | None:
        total = self.hits + self.misses
        return self.hits / total * 100 if total else None
