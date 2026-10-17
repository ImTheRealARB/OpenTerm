"""SQLite (WAL) with forward-only migrations tracked in PRAGMA user_version."""

from pathlib import Path

import aiosqlite

MIGRATIONS: list[str] = [
    # 1: cache
    "CREATE TABLE cache (key TEXT PRIMARY KEY, value BLOB NOT NULL, stored_at REAL NOT NULL)",
    # 2: generic key/value settings
    "CREATE TABLE kv (key TEXT PRIMARY KEY, value BLOB NOT NULL)",
]


async def open_db(path: str | Path) -> aiosqlite.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(path)
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA synchronous=NORMAL")
    await migrate(db)
    return db


async def migrate(db: aiosqlite.Connection) -> int:
    async with db.execute("PRAGMA user_version") as cur:
        (version,) = await cur.fetchone()
    for i, sql in enumerate(MIGRATIONS[version:], start=version + 1):
        await db.execute(sql)
        await db.execute(f"PRAGMA user_version={i}")
    await db.commit()
    return len(MIGRATIONS)
