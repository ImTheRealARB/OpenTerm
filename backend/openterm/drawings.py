"""GP drawings (Phase 19): trend line, horizontal line, fib retracement, stored per symbol in `kv` under `drawings:<SYMBOL>`.

A drawing is anchored in (time, price), never in pixels or bar numbers, so it survives a change of range or interval. Strict
validation: unknown fields are refused so a typo is never stored silently.
"""

import math
import time

import aiosqlite
import orjson

from .symbols import resolve
from .userdata import SYMBOL_RE, UserDataError

MAX_DRAWINGS = 200
POINTS = {"TREND": 2, "HLINE": 1, "FIB": 2}
ID_MAX = 24


def _bad(msg: str) -> UserDataError:
    return UserDataError("bad_request", f"DRAWINGS: {msg}")


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def validate(raw) -> list[dict]:
    if not isinstance(raw, list):
        raise _bad("drawings MUST BE A LIST")
    if len(raw) > MAX_DRAWINGS:
        raise UserDataError("too_large", f"DRAWINGS: OVER {MAX_DRAWINGS} PER SYMBOL")
    out: list[dict] = []
    seen: set[str] = set()
    for d in raw:
        if not isinstance(d, dict) or set(d) != {"id", "kind", "pts"}:
            raise _bad("EACH DRAWING NEEDS id, kind AND pts ONLY")
        did, kind, pts = d["id"], d["kind"], d["pts"]
        if not isinstance(did, str) or not 1 <= len(did) <= ID_MAX:
            raise _bad(f"id MUST BE 1-{ID_MAX} CHARACTERS")
        if did in seen:
            raise _bad(f"DUPLICATE id {did[:12]}")
        seen.add(did)
        if kind not in POINTS:
            raise _bad(f"kind MUST BE ONE OF {' '.join(POINTS)}")
        if not isinstance(pts, list) or len(pts) != POINTS[kind]:
            raise _bad(f"{kind} NEEDS {POINTS[kind]} POINT(S)")
        clean = []
        for p in pts:
            if not isinstance(p, dict) or set(p) != {"t", "p"} or not _num(p["t"]) or not _num(p["p"]) or p["t"] < 0:
                raise _bad("EACH POINT NEEDS FINITE t (EPOCH SECONDS >= 0) AND p")
            clean.append({"t": p["t"], "p": p["p"]})
        out.append({"id": did, "kind": kind, "pts": clean})
    return out


def key_of(raw_symbol: str) -> str:
    symbol = resolve(raw_symbol)
    if not SYMBOL_RE.match(symbol):
        raise _bad(f"BAD SYMBOL: {raw_symbol[:24]}")
    return symbol


class DrawingsStore:
    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def get(self, raw_symbol: str) -> dict:
        symbol = key_of(raw_symbol)
        async with self.db.execute("SELECT value FROM kv WHERE key=?", (f"drawings:{symbol}",)) as cur:
            row = await cur.fetchone()
        if not row:
            return {"symbol": symbol, "drawings": [], "updated_at": None}
        doc = orjson.loads(row[0])
        return {"symbol": symbol, "drawings": doc.get("drawings", []), "updated_at": doc.get("updated_at")}

    async def put(self, raw_symbol: str, drawings) -> dict:
        symbol = key_of(raw_symbol)
        clean = validate(drawings)
        doc = {"drawings": clean, "updated_at": time.time()}
        await self.db.execute(
            "INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (f"drawings:{symbol}", orjson.dumps(doc)),
        )
        await self.db.commit()
        return {"symbol": symbol, **doc}
