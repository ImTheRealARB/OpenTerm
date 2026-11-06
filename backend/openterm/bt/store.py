"""BT storage (server side, no pandas): strategies and runs in SQLite (migration 9), input bars in data files.

Data files are content-addressed (`<sha256>.msgpack` next to the database) so a job's params stay small and the
data hash is part of the job hash: same strategy + same bars = cached run. Files older than a day are swept.
"""

from __future__ import annotations

import hashlib
import time
import uuid
import zlib
from pathlib import Path

import aiosqlite
import msgpack
import orjson

KEEP_RUNS = 200
DATA_TTL_S = 86_400
NAME_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789_-")
CARD_METRICS = ("final_value", "total_return", "annual_return", "max_drawdown", "sharpe", "sortino", "calmar",
                "win_rate", "profit_factor", "trade_count", "benchmark_return", "excess_return")


class BtError(Exception):
    """kind: bad_request | not_found"""

    def __init__(self, kind: str, message: str, detail: str | None = None, col: int | None = None):
        super().__init__(message)
        self.kind, self.detail, self.col = kind, detail, col


def _pack(obj) -> bytes:
    return zlib.compress(msgpack.packb(obj, use_bin_type=True), 3)


def _unpack(blob: bytes):
    return msgpack.unpackb(zlib.decompress(blob), raw=False)


def strategy_name(name: str) -> str:
    n = (name or "").strip().lower()
    if not 1 <= len(n) <= 40 or set(n) - NAME_CHARS:
        raise BtError("bad_request", "STRATEGY NAMES ARE 1-40 LETTERS, DIGITS, _ OR -")
    return n


class BtStore:
    def __init__(self, db: aiosqlite.Connection, data_dir: Path):
        self.db = db
        self._indexed = False
        self.data_dir = Path(data_dir)
        self._swept = 0.0

    # --- data files ---
    def write_data(self, payload: dict) -> tuple[str, Path]:
        blob = msgpack.packb(payload, use_bin_type=True)
        sha = hashlib.sha256(blob).hexdigest()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        path = self.data_dir / f"{sha}.msgpack"
        if not path.exists():
            tmp = path.with_suffix(f".{uuid.uuid4().hex}.tmp")  # unique: concurrent writers of the same data must not share a temp file
            tmp.write_bytes(blob)
            try:
                tmp.replace(path)
            except OSError:  # Windows: a concurrent writer of the same content just replaced it and still holds it open
                tmp.unlink(missing_ok=True)
                if not path.exists():
                    raise
        else:
            path.touch()
        now = time.time()
        if now - self._swept > 3600:
            self._swept = now
            for f in [*self.data_dir.glob("*.msgpack"), *self.data_dir.glob("*.tmp")]:  # .tmp: left by a crash mid-write
                try:
                    if now - f.stat().st_mtime > DATA_TTL_S:
                        f.unlink(missing_ok=True)
                except OSError:  # gone already (another writer swept it) or still open on Windows: next hour
                    continue
        return sha, path

    # --- strategies ---
    async def strategies(self) -> list[dict]:
        async with self.db.execute("SELECT name, kind, updated_at FROM strategies ORDER BY name") as cur:
            return [{"name": n, "kind": k, "updated_at": u} for n, k, u in await cur.fetchall()]

    async def strategy(self, name: str) -> dict:
        n = strategy_name(name)
        async with self.db.execute("SELECT code, kind, updated_at FROM strategies WHERE name=?", (n,)) as cur:
            row = await cur.fetchone()
        if row is None:
            raise BtError("not_found", f"NO STRATEGY {n}")
        return {"name": n, "code": row[0], "kind": row[1], "updated_at": row[2]}

    async def put_strategy(self, name: str, code: str, kind: str) -> dict:
        n, now = strategy_name(name), time.time()
        await self.db.execute(
            "INSERT INTO strategies (name, code, kind, created_at, updated_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET code=excluded.code, kind=excluded.kind, updated_at=excluded.updated_at",
            (n, code, kind, now, now))
        await self.db.commit()
        return {"name": n, "kind": kind, "updated_at": now}

    async def delete_strategy(self, name: str) -> None:
        n = strategy_name(name)
        cur = await self.db.execute("DELETE FROM strategies WHERE name=?", (n,))
        await self.db.commit()
        if cur.rowcount == 0:
            raise BtError("not_found", f"NO STRATEGY {n}")

    # --- runs ---
    async def _index(self) -> None:
        """Covering index for the run list and the keep-200 trim, created on first use (no migration), like jobs_recent.

        SQLite stores a row's columns in order and `created_at` / `meta` come after the equity and trade blobs, so without
        it both queries walked every stored run's blob overflow pages (audit E-2).
        """
        if not self._indexed:
            await self.db.execute("CREATE INDEX IF NOT EXISTS bt_runs_recent ON bt_runs (created_at DESC, id, metrics, meta)")
            self._indexed = True

    async def save_run(self, result: dict, meta: dict, config: dict, data_sha: str, job_hash: str) -> None:
        equity = {"equity": result["equity"], "benchmark": result.get("benchmark") or []}
        await self._index()
        await self.db.execute(
            "INSERT OR REPLACE INTO bt_runs (id, strategy, config, data_fingerprint, metrics, equity, trades, created_at,"
            " job_hash, meta) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (result["run_id"], meta.get("strategy"), orjson.dumps(config), data_sha, orjson.dumps(result["metrics"]),
             _pack(equity), _pack(result["trades"]), time.time(), job_hash,
             orjson.dumps({**meta, "labels": result["labels"]})))
        await self.db.execute(
            "DELETE FROM bt_runs WHERE id NOT IN (SELECT id FROM bt_runs ORDER BY created_at DESC LIMIT ?)", (KEEP_RUNS,))
        await self.db.commit()

    async def has_run(self, run_id: str) -> bool:
        async with self.db.execute("SELECT 1 FROM bt_runs WHERE id=?", (run_id,)) as cur:
            return await cur.fetchone() is not None

    @staticmethod
    def _card(rid, metrics, meta, created_at) -> dict:
        m = orjson.loads(metrics)
        meta = orjson.loads(meta)
        return {"id": rid, **{k: meta.get(k) for k in ("rule", "strategy", "symbols", "interval", "range", "engine")},
                "labels": meta.get("labels"), "created_at": created_at,
                "metrics": {k: m.get(k) for k in CARD_METRICS if k in m}}

    async def runs(self, limit: int = KEEP_RUNS) -> list[dict]:
        await self._index()
        async with self.db.execute("SELECT id, metrics, meta, created_at FROM bt_runs ORDER BY created_at DESC LIMIT ?",
                                   (limit,)) as cur:
            return [self._card(*r) for r in await cur.fetchall()]

    async def run(self, run_id: str) -> dict:
        async with self.db.execute("SELECT id, metrics, meta, created_at, equity, trades, config, job_hash FROM bt_runs "
                                   "WHERE id=?", (run_id,)) as cur:
            row = await cur.fetchone()
        if row is None:
            raise BtError("not_found", f"NO RUN {run_id}")
        out = self._card(*row[:4])
        eq = _unpack(row[4])
        meta = orjson.loads(row[2])
        out.update(metrics=orjson.loads(row[1]), equity=eq["equity"], benchmark=eq["benchmark"],
                   trades=_unpack(row[5]), config=orjson.loads(row[6]), code=meta.get("code"))
        return out

    async def delete_run(self, run_id: str) -> str | None:
        """-> the run's job hash (the caller forgets the cached job too)."""
        async with self.db.execute("SELECT job_hash FROM bt_runs WHERE id=?", (run_id,)) as cur:
            row = await cur.fetchone()
        if row is None:
            raise BtError("not_found", f"NO RUN {run_id}")
        await self.db.execute("DELETE FROM bt_runs WHERE id=?", (run_id,))
        await self.db.commit()
        return row[0]
