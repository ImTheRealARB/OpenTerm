"""SQLite storage for AI runs (SWARM / AI AUTO event logs, replayed without calling a model) and THESIS notes.

Pure aiosqlite and orjson: no model, no network. A stored run keeps every event except `token` (the `role_done` / `done` events carry the
full text), so a replay shows exactly what the run produced, labelled as a replay.
"""

from __future__ import annotations

import re
import secrets
import time

import aiosqlite
import orjson

STATUSES = ("open", "confirmed", "invalidated", "closed")
SYMBOL_RE = re.compile(r"^[A-Za-z0-9.^=\-]{1,12}$")
RUN_ID_RE = re.compile(r"^[0-9a-f]{12}$")
MAX_TEXT = 2000
MAX_RUNS_PER_THESIS = 10
KEEP_RUNS = 200


class StoreError(Exception):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


class AiStore:
    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    # --- runs ---------------------------------------------------------------------------------------------------------------------
    async def save_run(self, kind: str, title: str, symbol: str | None, events: list[dict]) -> str:
        run_id = secrets.token_hex(6)
        keep = [e for e in events if e.get("type") != "token"]
        await self.db.execute("INSERT INTO ai_runs (id, kind, title, symbol, created_at, events) VALUES (?,?,?,?,?,?)",
                              (run_id, kind, title[:120], symbol, time.time(), orjson.dumps(keep).decode()))
        await self.db.execute("DELETE FROM ai_runs WHERE id NOT IN (SELECT id FROM ai_runs ORDER BY created_at DESC LIMIT ?)", (KEEP_RUNS,))
        await self.db.commit()
        return run_id

    async def runs(self, kind: str | None = None) -> list[dict]:
        sql = "SELECT id, kind, title, symbol, created_at FROM ai_runs" + (" WHERE kind=?" if kind else "") + " ORDER BY created_at DESC LIMIT 50"
        async with self.db.execute(sql, (kind,) if kind else ()) as cur:
            rows = await cur.fetchall()
        return [{"id": r[0], "kind": r[1], "title": r[2], "symbol": r[3], "created_at": r[4]} for r in rows]

    async def run(self, run_id: str) -> dict | None:
        if not RUN_ID_RE.match(run_id or ""):
            return None
        async with self.db.execute("SELECT id, kind, title, symbol, created_at, events FROM ai_runs WHERE id=?", (run_id,)) as cur:
            r = await cur.fetchone()
        return None if r is None else {"id": r[0], "kind": r[1], "title": r[2], "symbol": r[3], "created_at": r[4], "events": orjson.loads(r[5])}

    # --- theses -------------------------------------------------------------------------------------------------------------------
    @staticmethod
    def _row(r) -> dict:
        return {"id": r[0], "symbol": r[1], "status": r[2], "text": r[3], "invalidation": r[4], "run_ids": orjson.loads(r[5]),
                "created_at": r[6], "updated_at": r[7]}

    async def theses(self, symbol: str | None = None) -> list[dict]:
        sql = "SELECT id, symbol, status, text, invalidation, run_ids, created_at, updated_at FROM theses"
        args: tuple = ()
        if symbol:
            sql += " WHERE symbol=?"
            args = (symbol.upper(),)
        async with self.db.execute(sql + " ORDER BY updated_at DESC, id DESC", args) as cur:
            return [self._row(r) for r in await cur.fetchall()]

    async def thesis(self, tid: int) -> dict | None:
        async with self.db.execute("SELECT id, symbol, status, text, invalidation, run_ids, created_at, updated_at FROM theses WHERE id=?", (tid,)) as cur:
            r = await cur.fetchone()
        return None if r is None else self._row(r)

    @staticmethod
    def _text(value, what: str, required: bool) -> str:
        if value is None and not required:
            return ""
        if not isinstance(value, str) or (required and not value.strip()) or len(value) > MAX_TEXT:
            raise StoreError("bad_request", f"{what} MUST BE {'1' if required else '0'}-{MAX_TEXT} CHARACTERS")
        return value.strip()

    def _run_ids(self, value) -> list[str]:
        if not isinstance(value, list) or not all(isinstance(x, str) and RUN_ID_RE.match(x) for x in value) or len(value) > MAX_RUNS_PER_THESIS:
            raise StoreError("bad_request", f"run_ids MUST BE A LIST OF UP TO {MAX_RUNS_PER_THESIS} RUN IDS")
        return list(dict.fromkeys(value))

    async def add_thesis(self, body: dict) -> dict:
        symbol = str(body.get("symbol") or "").strip().upper()
        if not SYMBOL_RE.match(symbol):
            raise StoreError("bad_request", "SYMBOL IS NOT VALID")
        text = self._text(body.get("text"), "TEXT", True)
        invalidation = self._text(body.get("invalidation"), "INVALIDATION", False)
        run_ids = self._run_ids(body.get("run_ids") or [])
        now = time.time()
        cur = await self.db.execute("INSERT INTO theses (symbol, status, text, invalidation, run_ids, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                                    (symbol, "open", text, invalidation, orjson.dumps(run_ids).decode(), now, now))
        await self.db.commit()
        return await self.thesis(cur.lastrowid)  # type: ignore[return-value]

    async def update_thesis(self, tid: int, body: dict) -> dict | None:
        cur = await self.thesis(tid)
        if cur is None:
            return None
        if "status" in body:
            if body["status"] not in STATUSES:
                raise StoreError("bad_request", f"STATUS MUST BE ONE OF {', '.join(s.upper() for s in STATUSES)}")
            cur["status"] = body["status"]
        if "text" in body:
            cur["text"] = self._text(body["text"], "TEXT", True)
        if "invalidation" in body:
            cur["invalidation"] = self._text(body["invalidation"], "INVALIDATION", False)
        if "run_ids" in body:
            cur["run_ids"] = self._run_ids(body["run_ids"])
        await self.db.execute("UPDATE theses SET status=?, text=?, invalidation=?, run_ids=?, updated_at=? WHERE id=?",
                              (cur["status"], cur["text"], cur["invalidation"], orjson.dumps(cur["run_ids"]).decode(), time.time(), tid))
        await self.db.commit()
        return await self.thesis(tid)

    async def delete_thesis(self, tid: int) -> bool:
        cur = await self.db.execute("DELETE FROM theses WHERE id=?", (tid,))
        await self.db.commit()
        return cur.rowcount > 0
