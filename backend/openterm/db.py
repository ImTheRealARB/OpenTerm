"""SQLite (WAL) with forward-only migrations tracked in PRAGMA user_version."""

from pathlib import Path

import aiosqlite

MIGRATIONS: list[str] = [
    # 1: cache
    "CREATE TABLE cache (key TEXT PRIMARY KEY, value BLOB NOT NULL, stored_at REAL NOT NULL)",
    # 2: generic key/value settings
    "CREATE TABLE kv (key TEXT PRIMARY KEY, value BLOB NOT NULL)",
    # 3: named workspace layouts (state is the frontend's WorkspaceState as JSON)
    "CREATE TABLE layouts (name TEXT PRIMARY KEY, state BLOB NOT NULL, updated_at REAL NOT NULL)",
    # 4: command line history, oldest first by id
    "CREATE TABLE history (id INTEGER PRIMARY KEY AUTOINCREMENT, cmd TEXT NOT NULL, at REAL NOT NULL)",
    # 5: watchlists (symbols is a JSON array of canonical symbols, in display order)
    "CREATE TABLE watchlists (name TEXT PRIMARY KEY, symbols BLOB NOT NULL, updated_at REAL NOT NULL)",
    # 6: portfolios (Phase 8). positions is a JSON array of {symbol, qty, cost, currency, notes}, in display order
    "CREATE TABLE portfolios (name TEXT PRIMARY KEY, base TEXT NOT NULL, positions BLOB NOT NULL, updated_at REAL NOT NULL)",
    # 7: price / percent alerts (Phase 8). op '>' | '<', unit 'price' | 'pct' (vs previous close)
    (
        "CREATE TABLE alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, op TEXT NOT NULL, unit TEXT NOT NULL,"
        " value REAL NOT NULL, status TEXT NOT NULL, created_at REAL NOT NULL, triggered_at REAL, trigger_price REAL)"
    ),
    # 8: background jobs (Phase 11). params / result are JSON; the hash index is created by jobs/store.py
    (
        "CREATE TABLE jobs (id TEXT PRIMARY KEY, kind TEXT NOT NULL, hash TEXT NOT NULL, state TEXT NOT NULL,"
        " params BLOB NOT NULL, result BLOB, error TEXT, created_at REAL NOT NULL, started_at REAL, finished_at REAL)"
    ),
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
