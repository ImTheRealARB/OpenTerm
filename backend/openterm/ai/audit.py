"""Audit ledger for AI, SWARM, AI AUTO and BT runs: a hash chain in the `ai_ledger` table.

Each entry holds a run manifest (hash of the system prompt, hash of the offered tool registry, skill file hashes, app version, model) and metadata
(hash of the question and of the answer, tool calls with argument hashes, cost, grounding verdict). Prompts, questions, answers and tool results are NOT
stored here, only their hashes (the stored SWARM / AI AUTO runs keep events for replay; that is a separate table). `hash` covers the entry and the previous
entry's hash, so changing or removing a middle entry breaks the chain from that point; verify() reports where. Removing the newest entries cannot be
detected from the table alone: note the head hash shown by AUDIT to detect that.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections.abc import AsyncIterator

import aiosqlite
import orjson

from .. import __version__
from . import skills
from . import tools as toolbox

log = logging.getLogger("openterm.ai.audit")
GENESIS = "0" * 64
MAX_TOOL_LINES = 60
FINAL_EVENTS = ("done", "swarm_done")


def sha(data: str | bytes) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def canonical(obj: object) -> str:
    return orjson.dumps(obj, option=orjson.OPT_SORT_KEYS).decode()


def manifest(prompt: str, tool_names: list[str] | None, model: str, provider: str) -> dict:
    """What the run was allowed to use: hashes of the prompt, the offered tools (name, description, schema) and the skill files."""
    names = sorted(tool_names if tool_names is not None else [t.name for t in toolbox.REGISTRY.values() if not t.doc_only])
    spec = [{"name": n, "description": toolbox.REGISTRY[n].description, "parameters": toolbox.REGISTRY[n].parameters} for n in names if n in toolbox.REGISTRY]
    return {"prompt_sha": sha(prompt), "tools": names, "tools_sha": sha(canonical(spec)),
            "skills": {n: sha(skills.get(n) or "")[:16] for n in skills.names()}, "app": __version__, "model": model, "provider": provider}


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

    @staticmethod
    def _row(r) -> dict:
        return {"seq": r[0], "at": r[1], "kind": r[2], "ref": r[3], "model": r[4], "manifest": orjson.loads(r[5]), "meta": orjson.loads(r[6]),
                "prev_hash": r[7], "hash": r[8]}

    async def entries(self, limit: int = 50) -> list[dict]:
        async with self.db.execute("SELECT seq, at, kind, ref, model, manifest, meta, prev_hash, hash FROM ai_ledger ORDER BY seq DESC LIMIT ?",
                                   (max(1, min(limit, 500)),)) as cur:
            return [self._row(r) for r in await cur.fetchall()]

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
    async for ev in events:
        t = ev["type"]
        if t == "tool_call" and len(calls) < MAX_TOOL_LINES:
            calls.append({"id": ev["id"], "role": ev.get("role"), "name": ev["name"], "args_sha": sha(canonical(ev["args"])), "ok": None, "source": None})
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
                await ledger.append(kind, run_id, mf["model"], mf, meta)
            except Exception:
                log.exception("ai ledger append failed")
        yield ev
