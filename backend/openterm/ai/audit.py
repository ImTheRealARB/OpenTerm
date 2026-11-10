"""Audit ledger for AI, SWARM, AI AUTO and BT runs: a hash chain in the `ai_ledger` table.

Each entry holds a run manifest (hash of the system prompt, hash of the offered tool registry, skill file hashes, app version, model) and metadata
(hash of the question and of the answer, tool calls with argument hashes, cost, grounding verdict). Prompts, questions, answers and tool results are NOT
stored here, only their hashes (the stored SWARM / AI AUTO runs keep events for replay; that is a separate table). Only when the user turns on `ai.storeText`
are the redacted question and answer also kept, in the side table `ai_ledger_text` keyed by `seq`: it is outside the hash, so purging it never breaks the chain. `hash` covers the entry and the previous
entry's hash, so changing or removing a middle entry breaks the chain from that point; verify() reports where. Removing the newest entries cannot be
detected from the table alone: note the head hash shown by AUDIT to detect that.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections.abc import AsyncIterator
from contextlib import aclosing

import aiosqlite
import orjson

from .. import __version__
from ..redact import redact
from . import skills
from . import tools as toolbox

log = logging.getLogger("openterm.ai.audit")
GENESIS = "0" * 64
MAX_TOOL_LINES = 60
MAX_STORED_TEXT = 20_000  # characters kept per prompt or answer when `ai.storeText` is on
FINAL_EVENTS = ("done", "swarm_done")


def sha(data: str | bytes) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def canonical(obj: object) -> str:
    return orjson.dumps(obj, option=orjson.OPT_SORT_KEYS).decode()


def manifest(prompt: str, tool_names: list[str] | None, model: str, provider: str) -> dict:
    """What the run was allowed to use: hashes of the prompt, the offered tools (name, description, schema) and the skill files."""
    names = sorted(tool_names if tool_names is not None else [t.name for t in toolbox.REGISTRY.values() if not (t.doc_only or t.web_only)])
    spec = [{"name": n, "description": toolbox.REGISTRY[n].description, "parameters": toolbox.REGISTRY[n].parameters} for n in names if n in toolbox.REGISTRY]
    mf = {"prompt_sha": sha(prompt), "tools": names, "tools_sha": sha(canonical(spec)),
          "skills": {n: h[:16] for n, h in skills.digests().items()}, "app": __version__, "model": model, "provider": provider}
    if ext := toolbox.external_for(tool_names):  # third-party MCP tools offered to this run: name -> hash of description and schema
        mf["external"] = {t.name: sha(canonical({"d": t.description, "p": t.parameters}))[:16] for t in sorted(ext, key=lambda t: t.name)}
    return mf


def entry_hash(prev: str, at: float, kind: str, ref: str, model: str, mf: str, meta: str) -> str:
    return sha(canonical({"prev": prev, "at": at, "kind": kind, "ref": ref, "model": model, "manifest": mf, "meta": meta}))


class AuditLog:
    def __init__(self, db: aiosqlite.Connection):
        self.db = db
        self.lock = asyncio.Lock()

    async def append(self, kind: str, ref: str, model: str, mf: dict, meta: dict) -> dict:
        mf_s, meta_s = canonical(mf), canonical(meta)
        async with self.lock:
            async with self.db.execute("SELECT hash FROM ai_ledger ORDER BY seq DESC LIMIT 1") as cur:
                row = await cur.fetchone()
            prev = row[0] if row else GENESIS
            at = round(time.time(), 3)
            h = entry_hash(prev, at, kind, ref, model, mf_s, meta_s)
            cur = await self.db.execute("INSERT INTO ai_ledger (at, kind, ref, model, manifest, meta, prev_hash, hash) VALUES (?,?,?,?,?,?,?,?)",
                                        (at, kind, ref, model, mf_s, meta_s, prev, h))
            await self.db.commit()
        return {"seq": cur.lastrowid, "hash": h, "prev_hash": prev}

    async def text_enabled(self) -> bool:
        """`ai.storeText` from the stored settings (off unless the user turned it on). A settings read failure means off."""
        from ..settings_store import SettingsStore

        try:
            ai = ((await SettingsStore(self.db).get()).get("settings") or {}).get("ai")
        except Exception:  # noqa: BLE001 - any settings read failure means off (never store text by accident)
            return False
        return isinstance(ai, dict) and ai.get("storeText") is True

    async def store_text(self, seq: int, question: str, answer: str) -> None:
        """Keeps the redacted prompt and answer for one ledger entry in the side table (never part of the hash chain)."""
        await self.db.execute("INSERT OR REPLACE INTO ai_ledger_text (seq, question, answer, stored_at) VALUES (?,?,?,?)",
                              (seq, redact(question)[:MAX_STORED_TEXT], redact(answer)[:MAX_STORED_TEXT], round(time.time(), 3)))
        await self.db.commit()

    async def text(self, seq: int) -> dict | None:
        async with self.db.execute("SELECT question, answer, stored_at FROM ai_ledger_text WHERE seq=?", (seq,)) as cur:
            r = await cur.fetchone()
        return {"seq": seq, "question": r[0], "answer": r[1], "stored_at": r[2]} if r else None

    async def purge_text(self, seq: int | None = None) -> int:
        """Deletes stored text (all of it, or one entry's). Returns how many rows went. The ledger itself is untouched, so the chain still verifies."""
        cur = await self.db.execute("DELETE FROM ai_ledger_text" + (" WHERE seq=?" if seq is not None else ""), (seq,) if seq is not None else ())
        await self.db.commit()
        return cur.rowcount

    @staticmethod
    def _row(r) -> dict:
        return {"seq": r[0], "at": r[1], "kind": r[2], "ref": r[3], "model": r[4], "manifest": orjson.loads(r[5]), "meta": orjson.loads(r[6]),
                "prev_hash": r[7], "hash": r[8]}

    async def entries(self, limit: int = 50) -> list[dict]:
        async with self.db.execute("SELECT seq, at, kind, ref, model, manifest, meta, prev_hash, hash FROM ai_ledger ORDER BY seq DESC LIMIT ?",
                                   (max(1, min(limit, 500)),)) as cur:
            rows = [self._row(r) for r in await cur.fetchall()]
        if rows:
            async with self.db.execute("SELECT seq FROM ai_ledger_text WHERE seq BETWEEN ? AND ?", (rows[-1]["seq"], rows[0]["seq"])) as cur:
                have = {r[0] for r in await cur.fetchall()}
            for e in rows:
                e["has_text"] = e["seq"] in have  # not part of the hashed entry: the chain verifies the same with or without it
        return rows

    async def verify(self) -> dict:
        """Walks the whole chain. {ok, count, head, broken_at, reason}: broken_at is the first seq whose link or hash does not match."""
        prev, count = GENESIS, 0
        async with self.db.execute("SELECT seq, at, kind, ref, model, manifest, meta, prev_hash, hash FROM ai_ledger ORDER BY seq") as cur:
            async for seq, at, kind, ref, model, mf, meta, prev_hash, h in cur:
                count += 1
                if prev_hash != prev:
                    return {"ok": False, "count": count, "head": prev, "broken_at": seq, "reason": "LINK TO THE PREVIOUS ENTRY DOES NOT MATCH (AN ENTRY WAS REMOVED OR REORDERED)"}
                if entry_hash(prev_hash, at, kind, ref, model, mf, meta) != h:
                    return {"ok": False, "count": count, "head": prev, "broken_at": seq, "reason": "ENTRY CONTENT DOES NOT MATCH ITS HASH (IT WAS CHANGED)"}
                prev = h
        return {"ok": True, "count": count, "head": prev, "broken_at": None, "reason": None}


def audit_of(app, db: aiosqlite.Connection) -> AuditLog:
    cur = getattr(app.state, "ai_audit", None)
    if cur is None or cur.db is not db:  # a new database (tests reuse the app object) gets its own log and lock
        app.state.ai_audit = AuditLog(db)
    return app.state.ai_audit


async def audited(ledger: AuditLog, events: AsyncIterator[dict], kind: str, mf: dict, question: str, ref: str = "") -> AsyncIterator[dict]:
    """Pass events through; at the final event write the ledger entry first (a ledger failure is logged, never shown as an answer problem)."""
    calls: list[dict] = []
    run_id = ref
    async with aclosing(events) as stream:  # closing this generator closes the run it wraps now, not when the garbage collector gets to it
        async for ev in stream:
            t = ev["type"]
            if t == "tool_call" and len(calls) < MAX_TOOL_LINES:
                calls.append({"id": ev["id"], "role": ev.get("role"), "name": ev["name"], "args_sha": sha(canonical(ev["args"])), "ok": None, "source": None,
                              **({"web": ev["web"]} if ev.get("web") else {})})  # web calls: the page's host and path (no query string), or "search"
            elif t == "tool_result":
                for c in calls:
                    if c["id"] == ev["id"] and c["role"] == ev.get("role") and c["ok"] is None:
                        c["ok"], c["source"] = ev["ok"], ev["source"]
            elif t == "saved":
                run_id = ev["run_id"]
            elif t in FINAL_EVENTS:
                answer = ev.get("answer") or ""
                meta = {"question_sha": sha(question), "answer_sha": sha(answer), "cost": ev.get("cost"), "grounded": ev.get("grounded"),
                        "unsourced": len(ev.get("unsourced") or []), "tool_calls": calls, "stopped": ev.get("stopped"), "failed_roles": ev.get("failed")}
                try:
                    entry = await ledger.append(kind, run_id, mf["model"], mf, meta)
                    if await ledger.text_enabled():
                        await ledger.store_text(entry["seq"], question, answer)
                except Exception:
                    log.exception("ai ledger append failed")
            yield ev
