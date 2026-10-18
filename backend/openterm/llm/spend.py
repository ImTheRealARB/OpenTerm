"""Daily AI spend cap. Spend per local date in `kv` key `llm_spend:<YYYY-MM-DD>`, the cap in `llm_cap` (US$).

Before a call: refuse when today's spend plus the worst case (`max_tokens` at the output price) passes the cap.
After a call: add the real cost. A model with no known price is refused (the cap could not be kept), unless it is local.
"""

from __future__ import annotations

import datetime as dt

import aiosqlite
import orjson

DEFAULT_CAP = 1.0
MAX_CAP = 1000.0
CAP_KEY = "llm_cap"


def check(spent: float, cap: float, max_tokens: int, price: dict | None, local: bool) -> str | None:
    """-> None when the call may go ahead, else the refusal text."""
    if local:
        return None
    if price is None:
        return "PRICE UNKNOWN"
    if spent + max_tokens * float(price.get("output", 0.0)) / 1e6 > cap:
        return "SPEND CAP REACHED"
    return None


def cost(prompt_tokens: int, completion_tokens: int, price: dict) -> float:
    return (prompt_tokens * float(price.get("input", 0.0)) + completion_tokens * float(price.get("output", 0.0))) / 1e6


def _today() -> str:
    return dt.date.today().isoformat()  # local date: the cap resets at local midnight


async def _get(db: aiosqlite.Connection, key: str):
    async with db.execute("SELECT value FROM kv WHERE key=?", (key,)) as cur:
        row = await cur.fetchone()
    return orjson.loads(row[0]) if row else None


async def _put(db: aiosqlite.Connection, key: str, value) -> None:
    await db.execute("INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                     (key, orjson.dumps(value)))
    await db.commit()


async def today(db: aiosqlite.Connection, day: str | None = None) -> float:
    return float(await _get(db, f"llm_spend:{day or _today()}") or 0.0)


async def add(db: aiosqlite.Connection, amount: float, day: str | None = None) -> float:
    # One statement, so two calls finishing at once cannot lose an increment.
    key = f"llm_spend:{day or _today()}"
    await db.execute(
        "INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value="
        "CAST(CAST(CAST(kv.value AS TEXT) AS REAL) + CAST(CAST(excluded.value AS TEXT) AS REAL) AS TEXT)",
        (key, orjson.dumps(max(0.0, float(amount)))))
    await db.commit()
    return await today(db, day)


async def get_cap(db: aiosqlite.Connection) -> float:
    v = await _get(db, CAP_KEY)
    return float(v) if isinstance(v, int | float) else DEFAULT_CAP


async def set_cap(db: aiosqlite.Connection, cap: float) -> float:
    await _put(db, CAP_KEY, float(cap))
    return float(cap)
