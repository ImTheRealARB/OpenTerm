"""Local IV30 snapshots (spec decision I): the free sources have no IV history, so one point per symbol per day is kept here and
labelled LOCAL SNAPSHOTS wherever it is used. Table `iv_snapshots` (migration 12)."""

from __future__ import annotations

import time

import aiosqlite


async def record(db: aiosqlite.Connection, symbol: str, day: str, iv30: float) -> None:
    """One row per (symbol, day); a later fetch the same day replaces the value."""
    await db.execute("INSERT OR REPLACE INTO iv_snapshots (symbol, day, iv30, at) VALUES (?, ?, ?, ?)", (symbol, day, iv30, time.time()))
    await db.commit()


async def history(db: aiosqlite.Connection, symbol: str) -> list[tuple[str, float]]:
    async with db.execute("SELECT day, iv30 FROM iv_snapshots WHERE symbol = ? ORDER BY day", (symbol,)) as cur:
        return [(r[0], float(r[1])) async for r in cur]
