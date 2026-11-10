"""SQLite store for the journal (tables `journal_trades`, `journal_imports`; migration 18) and the analysis built from it."""

from __future__ import annotations

import time

import aiosqlite

from . import diagnostics, roundtrips
from .parsers import Trade

COLS = "id, ts, time, symbol, side, qty, price, fee, currency, broker, order_id, trade_id, mult, import_id"
MAX_TRIPS_SHOWN = 5000
MAX_FILLS_SHOWN = 20000


class JournalStore:
    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def add(self, trades: list[Trade], broker: str, name: str, ignored: int) -> dict:
        """Stores new fills; a fill already stored (same de-duplication key) is skipped and counted."""
        cur = await self.db.execute(
            "INSERT INTO journal_imports (at, broker, name, rows, added, duplicates, ignored) VALUES (?,?,?,?,0,0,?)",
            (time.time(), broker, name[:120], len(trades), ignored))
        import_id = cur.lastrowid
        before = self.db.total_changes
        await self.db.executemany(
            "INSERT OR IGNORE INTO journal_trades (dkey, ts, time, symbol, side, qty, price, fee, currency, broker, order_id, trade_id, mult, import_id)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(t.dkey, t.ts, t.time, t.symbol, t.side, t.qty, t.price, t.fee, t.currency, t.broker, t.order_id, t.trade_id, t.mult, import_id)
             for t in trades])
        added = self.db.total_changes - before
        await self.db.execute("UPDATE journal_imports SET added=?, duplicates=? WHERE id=?", (added, len(trades) - added, import_id))
        await self.db.commit()
        return {"import_id": import_id, "broker": broker, "rows": len(trades), "added": added, "duplicates": len(trades) - added, "ignored": ignored}

    async def fills(self, currency: str | None = None, symbol: str | None = None) -> list[dict]:
        sql, args = f"SELECT {COLS} FROM journal_trades", []
        where = []
        if currency:
            where.append("currency=?")
            args.append(currency)
        if symbol:
            where.append("symbol=?")
            args.append(symbol)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY ts, id"
        async with self.db.execute(sql, args) as cur:
            names = [d[0] for d in cur.description]
            return [dict(zip(names, r, strict=True)) async for r in cur]

    async def summary(self) -> dict:
        async with self.db.execute("SELECT broker, currency, COUNT(*), MIN(time), MAX(time) FROM journal_trades GROUP BY broker, currency") as cur:
            groups = [{"broker": b, "currency": c, "fills": n, "first": lo, "last": hi} async for b, c, n, lo, hi in cur]
        async with self.db.execute("SELECT id, at, broker, name, rows, added, duplicates, ignored FROM journal_imports ORDER BY id DESC LIMIT 20") as cur:
            names = [d[0] for d in cur.description]
            imports = [dict(zip(names, r, strict=True)) async for r in cur]
        return {"fills": sum(g["fills"] for g in groups), "groups": groups, "imports": imports}

    async def clear(self, broker: str | None = None) -> int:
        cur = await self.db.execute("DELETE FROM journal_trades" + (" WHERE broker=?" if broker else ""), (broker,) if broker else ())
        if not broker:
            await self.db.execute("DELETE FROM journal_imports")
        await self.db.commit()
        return cur.rowcount

    async def analysis(self, currency: str | None = None) -> dict:
        fills = await self.fills()
        if not fills:
            return {"empty": True, "currencies": [], "currency": None}
        trips, positions = roundtrips.match(fills)
        n_fills: dict[str, int] = {}
        n_trips: dict[str, int] = {}
        for f in fills:
            n_fills[f["currency"]] = n_fills.get(f["currency"], 0) + 1
        for t in trips:
            n_trips[t["currency"]] = n_trips.get(t["currency"], 0) + 1
        currencies = sorted(n_fills, key=lambda c: (-n_trips.get(c, 0), -n_fills[c], c))
        if currency and currency not in n_fills:
            raise KeyError(currency)
        cur = currency or currencies[0]
        mine = [t for t in trips if t["currency"] == cur]
        shown = mine[-MAX_TRIPS_SHOWN:]
        return roundtrips.clean({
            "empty": False, "currency": cur,
            "currencies": [{"currency": c, "fills": n_fills[c], "round_trips": n_trips.get(c, 0)} for c in currencies],
            "stats": roundtrips.stats(mine), "round_trips": shown, "round_trips_total": len(mine),
            "open_positions": [p for p in positions if p["currency"] == cur],
            "diagnostics": diagnostics.diagnose(mine, cur),
            "labels": {"note": "FIFO ROUND TRIPS FROM YOUR FILLS, NET OF FEES IN THE FILE. NO CURRENCY IS CONVERTED. OPEN POSITIONS ARE NOT MARKED TO ANY PRICE.",
                       "times": "TIMES ARE THE BROKER FILE'S OWN CLOCK"},
        })
