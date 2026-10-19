"""Two-level cache: bounded in-memory LRU in front of SQLite. Writes are batched off the request path."""

import asyncio
import logging
import time
from collections import OrderedDict
from typing import Any

import aiosqlite
import orjson

log = logging.getLogger("openterm.cache")

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

    @property
    def hit_pct(self) -> float | None:
        total = self.hits + self.misses
        return self.hits / total * 100 if total else None
