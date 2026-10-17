"""User data in SQLite: named workspace layouts, command line history and watchlists."""

import re
import time

import aiosqlite
import orjson

from .symbols import resolve

NAME_RE = re.compile(r"^[A-Z0-9][A-Z0-9_.-]{0,31}$")
SYMBOL_RE = re.compile(r"^[A-Z0-9^][A-Z0-9^=.&-]{0,23}$")
MAX_STATE_BYTES = 64_000
HISTORY_MAX = 500
MAX_CMD_LEN = 500
MAX_WATCHLIST = 500


class UserDataError(Exception):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def layout_name(raw: str, what: str = "LAYOUT") -> str:
    name = raw.strip().upper()
    if not NAME_RE.match(name):
        raise UserDataError("bad_request", f"{what} NAME: 1-32 OF A-Z 0-9 _ . -")
    return name


def watchlist_name(raw: str) -> str:
    return layout_name(raw, "WATCHLIST")


def check_symbols(raw) -> list[str]:
    """Canonical symbols (aliases resolved like the command line does), deduplicated, order kept."""
    if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
        raise UserDataError("bad_request", "SYMBOLS MUST BE A LIST OF STRINGS")
    out = list(dict.fromkeys(resolve(x) for x in raw if x.strip()))
    bad = [x for x in out if not SYMBOL_RE.match(x)]
    if bad:
        raise UserDataError("bad_request", f"BAD SYMBOL: {bad[0][:24]}")
    if len(out) > MAX_WATCHLIST:
        raise UserDataError("too_large", f"WATCHLIST OVER {MAX_WATCHLIST} SYMBOLS")
    return out


def check_state(state) -> bytes:
    """Shape check only. The frontend validates the tree in depth before applying a layout."""
    if not (isinstance(state, dict) and isinstance(state.get("layout"), dict) and isinstance(state.get("panels"), dict)):
        raise UserDataError("bad_request", "LAYOUT STATE NEEDS layout AND panels")
    blob = orjson.dumps(state)
    if len(blob) > MAX_STATE_BYTES:
        raise UserDataError("too_large", f"LAYOUT STATE OVER {MAX_STATE_BYTES // 1000} KB")
    return blob


class UserData:
    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def layouts(self) -> list[dict]:
        async with self.db.execute("SELECT name, state, updated_at FROM layouts ORDER BY name") as cur:
            rows = await cur.fetchall()
        return [
            {"name": name, "panels": len(orjson.loads(state).get("panels", {})), "updated_at": at}
            for name, state, at in rows
        ]

    async def layout(self, raw_name: str) -> dict:
        name = layout_name(raw_name)
        async with self.db.execute("SELECT state, updated_at FROM layouts WHERE name=?", (name,)) as cur:
            row = await cur.fetchone()
        if not row:
            raise UserDataError("not_found", f"NO LAYOUT {name}")
        return {"name": name, "state": orjson.loads(row[0]), "updated_at": row[1]}

    async def save_layout(self, raw_name: str, state) -> dict:
        name = layout_name(raw_name)
        blob = check_state(state)
        now = time.time()
        await self.db.execute(
            "INSERT INTO layouts (name, state, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET state=excluded.state, updated_at=excluded.updated_at",
            (name, blob, now),
        )
        await self.db.commit()
        return {"name": name, "updated_at": now}

    async def delete_layout(self, raw_name: str) -> str:
        name = layout_name(raw_name)
        cur = await self.db.execute("DELETE FROM layouts WHERE name=?", (name,))
        await self.db.commit()
        if cur.rowcount == 0:
            raise UserDataError("not_found", f"NO LAYOUT {name}")
        return name

    async def history(self, limit: int = HISTORY_MAX) -> list[str]:
        async with self.db.execute(
            "SELECT cmd FROM (SELECT id, cmd FROM history ORDER BY id DESC LIMIT ?) ORDER BY id", (limit,)
        ) as cur:
            return [r[0] for r in await cur.fetchall()]

    async def push_history(self, cmds: list[str]) -> int:
        """Appends commands, skipping blanks and consecutive repeats, and keeps the newest HISTORY_MAX."""
        async with self.db.execute("SELECT cmd FROM history ORDER BY id DESC LIMIT 1") as cur:
            row = await cur.fetchone()
        last = row[0] if row else None
        now = time.time()
        rows = []
        for raw in cmds:
            cmd = raw.strip()[:MAX_CMD_LEN]
            if cmd and cmd != last:
                rows.append((cmd, now))
                last = cmd
        if rows:
            await self.db.executemany("INSERT INTO history (cmd, at) VALUES (?, ?)", rows)
            await self.db.execute(
                "DELETE FROM history WHERE id <= (SELECT id FROM history ORDER BY id DESC LIMIT 1 OFFSET ?)",
                (HISTORY_MAX,),
            )
            await self.db.commit()
        return len(rows)

    # --- watchlists -------------------------------------------------------------------------
    async def watchlists(self) -> list[dict]:
        async with self.db.execute("SELECT name, symbols, updated_at FROM watchlists ORDER BY name") as cur:
            rows = await cur.fetchall()
        return [{"name": n, "count": len(orjson.loads(sy)), "updated_at": at} for n, sy, at in rows]

    async def _watchlist(self, name: str) -> list[str] | None:
        async with self.db.execute("SELECT symbols FROM watchlists WHERE name=?", (name,)) as cur:
            row = await cur.fetchone()
        return orjson.loads(row[0]) if row else None

    async def watchlist(self, raw_name: str) -> dict:
        name = watchlist_name(raw_name)
        async with self.db.execute("SELECT symbols, updated_at FROM watchlists WHERE name=?", (name,)) as cur:
            row = await cur.fetchone()
        if not row:
            raise UserDataError("not_found", f"NO WATCHLIST {name}")
        return {"name": name, "symbols": orjson.loads(row[0]), "updated_at": row[1]}

    async def _store(self, name: str, symbols: list[str]) -> dict:
        now = time.time()
        await self.db.execute(
            "INSERT INTO watchlists (name, symbols, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET symbols=excluded.symbols, updated_at=excluded.updated_at",
            (name, orjson.dumps(symbols), now),
        )
        await self.db.commit()
        return {"name": name, "symbols": symbols, "updated_at": now}

    async def save_watchlist(self, raw_name: str, symbols) -> dict:
        return await self._store(watchlist_name(raw_name), check_symbols(symbols))

    async def edit_watchlist(self, raw_name: str, add=None, remove=None) -> dict:
        """Adds (appended, existing ones keep their place) and removes symbols. Adding creates the list."""
        name = watchlist_name(raw_name)
        if add is None and remove is None:
            raise UserDataError("bad_request", "BODY NEEDS add OR remove")
        plus, minus = check_symbols(add or []), set(check_symbols(remove or []))
        current = await self._watchlist(name)
        if current is None and not plus:
            raise UserDataError("not_found", f"NO WATCHLIST {name}")
        merged = [s for s in dict.fromkeys([*(current or []), *plus]) if s not in minus]
        if len(merged) > MAX_WATCHLIST:
            raise UserDataError("too_large", f"WATCHLIST OVER {MAX_WATCHLIST} SYMBOLS")
        return await self._store(name, merged)

    async def delete_watchlist(self, raw_name: str) -> str:
        name = watchlist_name(raw_name)
        cur = await self.db.execute("DELETE FROM watchlists WHERE name=?", (name,))
        await self.db.commit()
        if cur.rowcount == 0:
            raise UserDataError("not_found", f"NO WATCHLIST {name}")
        return name
