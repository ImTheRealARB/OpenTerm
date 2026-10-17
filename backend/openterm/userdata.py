"""User data in SQLite: named workspace layouts and command line history."""

import re
import time

import aiosqlite
import orjson

NAME_RE = re.compile(r"^[A-Z0-9][A-Z0-9_.-]{0,31}$")
MAX_STATE_BYTES = 64_000
HISTORY_MAX = 500
MAX_CMD_LEN = 500


class UserDataError(Exception):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def layout_name(raw: str) -> str:
    name = raw.strip().upper()
    if not NAME_RE.match(name):
        raise UserDataError("bad_request", "LAYOUT NAME: 1-32 OF A-Z 0-9 _ . -")
    return name


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
