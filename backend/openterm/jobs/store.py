"""Finished jobs in SQLite (migration 8), trimmed to the newest KEEP."""

import aiosqlite
import orjson

KEEP = 200
MAX_RESULT_BYTES = 8 * 1024 * 1024
COLS = ("id", "kind", "hash", "state", "params", "result", "error", "created_at", "started_at", "finished_at")


class JobStore:
    def __init__(self, db: aiosqlite.Connection):
        self.db = db
        self._indexed = False

    async def _index(self) -> None:
        if not self._indexed:
            await self.db.execute("CREATE INDEX IF NOT EXISTS jobs_hash ON jobs (hash)")
            # Covers `recent` (every column but params and result): SQLite stores columns in order, so reading a column
            # after the result blob would otherwise walk the blob's overflow pages for every listed row.
            await self.db.execute("CREATE INDEX IF NOT EXISTS jobs_recent ON jobs "
                                  "(finished_at DESC, id, kind, hash, state, error, created_at, started_at)")
            self._indexed = True

    async def save(self, job: dict) -> None:
        await self._index()
        result = orjson.dumps(job["result"]) if job.get("result") is not None else None
        if result is not None and len(result) > MAX_RESULT_BYTES:
            result = None  # too big to cache: the job stays listed, a rerun recomputes
        await self.db.execute(
            f"INSERT OR REPLACE INTO jobs ({', '.join(COLS)}) VALUES ({', '.join('?' * len(COLS))})",
            (job["id"], job["kind"], job["hash"], job["state"], orjson.dumps(job.get("params") or {}), result,
             job.get("error"), job["created_at"], job.get("started_at"), job.get("finished_at")),
        )
        await self.db.commit()

    async def forget(self, h: str) -> None:
        """Drops finished jobs with this hash, so the next identical submit runs again (e.g. its BT run was deleted)."""
        await self._index()
        await self.db.execute("DELETE FROM jobs WHERE hash=?", (h,))
        await self.db.commit()

    @staticmethod
    def _row(r, with_result: bool = True) -> dict:
        d = dict(zip(COLS, r, strict=True))
        d["params"] = orjson.loads(d["params"])
        d["result"] = orjson.loads(d["result"]) if with_result and d["result"] is not None else None
        if not with_result:
            d.pop("result")
        return d

    async def get(self, job_id: str) -> dict | None:
        async with self.db.execute(f"SELECT {', '.join(COLS)} FROM jobs WHERE id = ?", (job_id,)) as cur:
            r = await cur.fetchone()
        return self._row(r) if r else None

    async def done_by_hash(self, h: str) -> dict | None:
        await self._index()
        async with self.db.execute(
            f"SELECT {', '.join(COLS)} FROM jobs WHERE hash = ? AND state = 'done' AND result IS NOT NULL"
            " ORDER BY finished_at DESC LIMIT 1", (h,),
        ) as cur:
            r = await cur.fetchone()
        return self._row(r) if r else None

    async def recent(self, limit: int = 50) -> list[dict]:
        await self._index()
        cols = ", ".join("NULL" if c == "result" else c for c in COLS)  # a listing never needs the (large) result blobs
        async with self.db.execute(f"SELECT {cols} FROM jobs ORDER BY finished_at DESC LIMIT ?", (limit,)) as cur:
            return [self._row(r, with_result=False) for r in await cur.fetchall()]

    async def count(self) -> int:
        async with self.db.execute("SELECT COUNT(*) FROM jobs") as cur:
            return (await cur.fetchone())[0]

    async def trim(self, keep: int = KEEP) -> None:
        await self.db.execute(
            "DELETE FROM jobs WHERE id NOT IN (SELECT id FROM jobs ORDER BY finished_at DESC LIMIT ?)", (keep,)
        )
        await self.db.commit()

    async def clear(self) -> int:
        cur = await self.db.execute("DELETE FROM jobs")
        await self.db.commit()
        return cur.rowcount
