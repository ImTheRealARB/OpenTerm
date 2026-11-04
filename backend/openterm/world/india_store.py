"""NSE archive day files in SQLite, one `kv` row per session. A day with data is `nse:eod:<YYYYMMDD>` holding a zlib-compressed msgpack
`{"d": ISO date, "at": fetched-at, "rows": {symbol: [o, h, l, c, v]}}`; a weekday the exchange was closed (the archive answered 404) is
`nse:gap:<YYYYMMDD>`. Telling them apart by key means the "which days do we know" question never decodes a day file.

It reuses the `kv` table, so there is no migration: `local_bars` is one blob per symbol that always shadows the live sources, which is the
opposite of a fallback.
"""

from __future__ import annotations

import asyncio
import time
import zlib
from datetime import date

import aiosqlite
import msgpack

DATA = "nse:eod:"
GAP = "nse:gap:"


def _key(prefix: str, day: date) -> str:
    return prefix + day.strftime("%Y%m%d")


def _day(key: str) -> date:
    return date(int(key[8:12]), int(key[12:14]), int(key[14:16]))


class DayStore:
    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def _put(self, key: str, blob: bytes) -> None:
        await self.db.execute("INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, blob))
        await self.db.commit()

    async def put_day(self, day: date, rows: dict[str, list]) -> None:
        await self._put(_key(DATA, day), zlib.compress(msgpack.packb({"d": day.isoformat(), "at": time.time(), "rows": rows})))

    async def put_gap(self, day: date) -> None:
        await self._put(_key(GAP, day), msgpack.packb({"at": time.time()}))

    async def known(self, since: date) -> dict[date, bool]:
        """day -> True (a file with data) or False (a gap), for the days from `since` on. Reads keys only."""
        out: dict[date, bool] = {}
        for prefix, has in ((DATA, True), (GAP, False)):
            async with self.db.execute("SELECT key FROM kv WHERE key >= ? AND key < ?", (_key(prefix, since), prefix + "~")) as cur:
                async for (key,) in cur:
                    out[_day(key)] = has
        return out

    async def rows(self, days: list[date]) -> tuple[dict[date, dict[str, list]], float | None]:
        """The rows of the given days with data, and when the newest of those files was fetched."""
        if not days:
            return {}, None
        want = {_key(DATA, d) for d in days}
        blobs: list[tuple[str, bytes]] = []
        async with self.db.execute("SELECT key, value FROM kv WHERE key >= ? AND key <= ? ORDER BY key", (min(want), max(want))) as cur:
            async for key, blob in cur:
                if key in want:
                    blobs.append((key, blob))
        # up to 250 zlib+msgpack decodes would block the event loop, so they run in a worker thread
        recs = await asyncio.to_thread(lambda: [msgpack.unpackb(zlib.decompress(b), raw=False) for _, b in blobs])
        out = {_day(key): rec["rows"] for (key, _), rec in zip(blobs, recs, strict=True)}
        fetched = recs[-1]["at"] if recs else None  # ascending keys: the last one is the newest day
        return out, fetched

    async def prune(self, before: date) -> None:
        """Forget day files older than the 250-session window, so the table cannot grow for ever."""
        for prefix in (DATA, GAP):
            await self.db.execute("DELETE FROM kv WHERE key >= ? AND key < ?", (prefix, _key(prefix, before)))
        await self.db.commit()
