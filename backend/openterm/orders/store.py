"""SQLite side of orders: the mandate, the live switch and the kill switch (kv rows), the sent-orders log behind the daily cap, and the record of
fills already added to a portfolio. The tables come from migration 19 (db.py)."""

from __future__ import annotations

import time

import aiosqlite
import orjson

from . import mandate as mandate_mod
from .errors import OrderError

K_MANDATE, K_SETTINGS, K_KILL = "orders.mandate", "orders.settings", "orders.kill"


def today() -> str:
    return time.strftime("%Y-%m-%d")  # the machine's local day


class OrdersStore:
    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def _get(self, key: str, default: dict) -> dict:
        async with self.db.execute("SELECT value FROM kv WHERE key=?", (key,)) as cur:
            row = await cur.fetchone()
        if not row:
            return dict(default)
        try:
            v = orjson.loads(row[0])
        except orjson.JSONDecodeError:
            return dict(default)
        return v if isinstance(v, dict) else dict(default)

    async def _put(self, key: str, value: dict) -> None:
        await self.db.execute("INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, orjson.dumps(value)))
        await self.db.commit()

    # --- mandate ---
    async def mandate(self) -> mandate_mod.Mandate:
        raw = await self._get(K_MANDATE, {})
        try:
            return mandate_mod.parse(raw)
        except OrderError:  # a damaged stored document must not become a permissive one: the default allows nothing
            return mandate_mod.Mandate()

    async def set_mandate(self, raw) -> mandate_mod.Mandate:
        m = mandate_mod.parse(raw)
        await self._put(K_MANDATE, m.public())
        return m

    # --- live switch ---
    async def live_enabled(self) -> bool:
        return (await self._get(K_SETTINGS, {})).get("live") is True

    async def set_live(self, on: bool) -> None:
        await self._put(K_SETTINGS, {"live": bool(on), "at": time.time()})

    # --- kill switch ---
    async def kill(self) -> dict:
        return await self._get(K_KILL, {"on": False})

    async def set_kill(self, on: bool) -> dict:
        v = {"on": bool(on), "at": time.time()}
        await self._put(K_KILL, v)
        return v

    # --- sent orders ---
    async def log_order(self, broker: str, mode: str, client_id: str, broker_order_id: str | None, symbol: str, side: str, qty: float, status: str) -> None:
        await self.db.execute("INSERT INTO orders_log (at, day, broker, mode, client_id, broker_order_id, symbol, side, qty, status) VALUES (?,?,?,?,?,?,?,?,?,?)",
                              (time.time(), today(), broker, mode, client_id, broker_order_id, symbol, side, qty, status))
        await self.db.commit()

    async def trades_today(self) -> int:
        async with self.db.execute("SELECT COUNT(*) FROM orders_log WHERE day=?", (today(),)) as cur:
            (n,) = await cur.fetchone()
        return int(n)

    # --- fills added to a portfolio ---
    async def imported_ids(self, broker: str) -> set[str]:
        async with self.db.execute("SELECT fill_id FROM orders_imported WHERE broker=?", (broker,)) as cur:
            return {r[0] for r in await cur.fetchall()}

    async def mark_imported(self, broker: str, fills: list[dict], portfolio: str) -> None:
        now = time.time()
        await self.db.executemany("INSERT OR IGNORE INTO orders_imported (broker, fill_id, portfolio, order_id, at) VALUES (?,?,?,?,?)",
                                  [(broker, f["fill_id"], portfolio, str(f.get("order_id") or ""), now) for f in fills])
        await self.db.commit()
