"""Imported bars (IMPORT) in SQLite, served as the `local` history source. A symbol that exists here always answers
from here (labelled LOCAL DATA), so an import shadows a same-named real ticker; `IMPORT DEL` removes it.
"""

from __future__ import annotations

import datetime as dt
import time
import zlib

import aiosqlite
import msgpack

from ..models import Bars
from ..ranges import _RANGE_DAYS

#: Local data is daily; coarser bars are built from it, finer ones do not exist.
INTERVALS = ("1d", "1wk", "1mo")


class LocalError(ValueError):
    pass


def _group(day: dt.date, interval: str):
    if interval == "1wk":
        iso = day.isocalendar()
        return iso.year, iso.week
    if interval == "1mo":
        return day.year, day.month
    return day


def _resample(cols: dict, interval: str) -> dict:
    if interval == "1d":
        return cols
    out: dict = {"t": [], "o": [], "h": [], "l": [], "c": [], "v": [] if cols["v"] is not None else None}
    last = None
    for i, d in enumerate(cols["d"]):
        key = _group(dt.date.fromisoformat(d), interval)
        if key != last:
            last = key
            out["t"].append(cols["t"][i])
            out["o"].append(cols["o"][i])
            out["h"].append(cols["h"][i])
            out["l"].append(cols["l"][i])
            out["c"].append(cols["c"][i])
            if out["v"] is not None:
                out["v"].append(cols["v"][i] or 0)
        else:
            out["h"][-1] = max(out["h"][-1], cols["h"][i])
            out["l"][-1] = min(out["l"][-1], cols["l"][i])
            out["c"][-1] = cols["c"][i]
            if out["v"] is not None:
                out["v"][-1] += cols["v"][i] or 0
    return out


class LocalData:
    def __init__(self, db: aiosqlite.Connection):
        self.db = db
        self.symbols: set[str] = set()

    async def load(self) -> None:
        async with self.db.execute("SELECT symbol FROM local_bars") as cur:
            self.symbols = {r[0] for r in await cur.fetchall()}

    async def save(self, symbol: str, cols: dict) -> dict:
        blob = zlib.compress(msgpack.packb(cols))
        now = time.time()
        await self.db.execute(
            "INSERT OR REPLACE INTO local_bars (symbol, bars, rows, first_date, last_date, created_at) VALUES (?,?,?,?,?,?)",
            (symbol, blob, len(cols["t"]), cols["d"][0], cols["d"][-1], now))
        await self.db.commit()
        self.symbols.add(symbol)
        return {"symbol": symbol, "rows": len(cols["t"]), "first_date": cols["d"][0], "last_date": cols["d"][-1],
                "volume": cols["v"] is not None, "label": "LOCAL DATA", "created_at": now}

    async def delete(self, symbol: str) -> bool:
        cur = await self.db.execute("DELETE FROM local_bars WHERE symbol=?", (symbol,))
        await self.db.commit()
        self.symbols.discard(symbol)
        return cur.rowcount > 0

    async def listing(self) -> list[dict]:
        async with self.db.execute(
                "SELECT symbol, rows, first_date, last_date, created_at FROM local_bars ORDER BY symbol") as cur:
            return [{"symbol": s, "rows": n, "first_date": a, "last_date": b, "created_at": t, "label": "LOCAL DATA"}
                    for s, n, a, b, t in await cur.fetchall()]

    async def history(self, symbol: str, range_: str, interval: str) -> tuple[dict, float]:
        """-> (Bars as a dict, when the file was imported). The range counts back from the last imported bar."""
        if interval not in INTERVALS:
            raise LocalError("LOCAL DATA IS DAILY: USE 1D, 1W OR 1MO")
        async with self.db.execute("SELECT bars, created_at FROM local_bars WHERE symbol=?", (symbol,)) as cur:
            row = await cur.fetchone()
        if row is None:
            raise LocalError(f"NO LOCAL DATA FOR {symbol}")
        cols = msgpack.unpackb(zlib.decompress(row[0]), raw=False)
        cols = _resample(cols, interval)
        keep = 0
        days = _RANGE_DAYS.get(range_)
        if days is not None and range_ != "max":
            cutoff = cols["t"][-1] - days * 86_400
            keep = next((i for i, t in enumerate(cols["t"]) if t >= cutoff), 0)
        sl = slice(keep, None)
        bars = Bars.model_construct(
            symbol=symbol, range=range_, interval=interval, currency=None, exchange="LOCAL DATA", tz="UTC",
            t=cols["t"][sl], o=cols["o"][sl], h=cols["h"][sl], l=cols["l"][sl], c=cols["c"][sl],
            v=[int(x) if x is not None else None for x in cols["v"][sl]] if cols["v"] is not None else [None] * len(cols["t"][sl]),
            source="local", as_of=row[1],
        )
        return bars.model_dump(), row[1]
