"""Phase 8 user data in SQLite: portfolios (positions with average cost) and price / percent alerts.

Same conventions as `userdata.py`: names are 1-32 of A-Z 0-9 _ . -, symbols are resolved like the command line,
errors are `UserDataError` (mapped to HTTP status codes by `api.py`).
"""

import math
import re
import time

import aiosqlite
import orjson

from .symbols import resolve
from .userdata import SYMBOL_RE, UserDataError, layout_name

MAX_POSITIONS = 500
MAX_ALERTS = 200
MAX_NOTES = 200
MAX_ABS = 1e12
EPS = 1e-9
CCY_RE = re.compile(r"^[A-Za-z]{3}\Z")  # \Z, not `$`: `$` lets a trailing newline through
# Yahoo quotes some markets in minor units; keep their case, it carries the meaning (GBp = pence).
MINOR_UNITS = {"GBX": "GBp", "ZAC": "ZAc", "ILA": "ILA"}
OPS = (">", "<")
UNITS = ("price", "pct")


def portfolio_name(raw: str) -> str:
    return layout_name(raw, "PORTFOLIO")


def _number(x, what: str) -> float:
    if isinstance(x, bool) or not isinstance(x, int | float) or not math.isfinite(x) or abs(x) > MAX_ABS:
        raise UserDataError("bad_request", f"{what} MUST BE A FINITE NUMBER")
    return float(x)


def check_currency(raw, what: str = "CURRENCY") -> str | None:
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str) or not CCY_RE.match(raw):
        raise UserDataError("bad_request", f"{what}: 3 LETTERS, E.G. USD")
    if raw in ("GBp", "ZAc"):
        return raw
    return MINOR_UNITS.get(raw.upper(), raw.upper())


def check_position(raw) -> dict:
    if not isinstance(raw, dict):
        raise UserDataError("bad_request", "POSITION MUST BE AN OBJECT")
    sym = raw.get("symbol")
    if not isinstance(sym, str) or not sym.strip():
        raise UserDataError("bad_request", "POSITION NEEDS symbol")
    symbol = resolve(sym)
    if not SYMBOL_RE.match(symbol):
        raise UserDataError("bad_request", f"BAD SYMBOL: {symbol[:24]}")
    qty = _number(raw.get("qty"), f"{symbol} QTY")
    if abs(qty) < EPS:
        raise UserDataError("bad_request", f"{symbol} QTY MUST NOT BE ZERO")
    cost = raw.get("cost")
    if cost is not None:
        cost = _number(cost, f"{symbol} COST")
        if cost < 0:
            raise UserDataError("bad_request", f"{symbol} COST MUST NOT BE NEGATIVE")
    notes = raw.get("notes")
    if notes is not None and not isinstance(notes, str):
        raise UserDataError("bad_request", f"{symbol} NOTES MUST BE TEXT")
    notes = (notes or "").strip()[:MAX_NOTES] or None
    return {"symbol": symbol, "qty": qty, "cost": cost, "currency": check_currency(raw.get("currency")), "notes": notes}


def add_lot(cur: dict | None, lot: dict) -> dict | None:
    """Average-cost accounting. A lot on the same side averages the cost; a lot that reduces the position keeps
    the average cost; one that flips it starts at the lot's cost. Returns None when the position closes."""
    if cur is None:
        return dict(lot)
    if cur["currency"] and lot["currency"] and cur["currency"] != lot["currency"]:
        raise UserDataError("bad_request", f"{lot['symbol']}: CURRENCY {lot['currency']} DIFFERS FROM {cur['currency']}")
    q0, q1 = cur["qty"], lot["qty"]
    q = q0 + q1
    if abs(q) < EPS:
        return None
    if q0 * q1 > 0:
        both = cur["cost"] is not None and lot["cost"] is not None
        cost = (q0 * cur["cost"] + q1 * lot["cost"]) / q if both else None
    elif q * q0 > 0:
        cost = cur["cost"]
    else:
        cost = lot["cost"]
    return {
        "symbol": cur["symbol"], "qty": q, "cost": cost,
        "currency": cur["currency"] or lot["currency"], "notes": lot["notes"] or cur["notes"],
    }


def check_positions(raw) -> list[dict]:
    """Validated positions in order; repeated symbols are combined as lots (a CSV may list one buy per line)."""
    if not isinstance(raw, list):
        raise UserDataError("bad_request", "POSITIONS MUST BE A LIST")
    if len(raw) > MAX_POSITIONS * 4:
        raise UserDataError("too_large", f"PORTFOLIO OVER {MAX_POSITIONS} POSITIONS")
    out: dict[str, dict] = {}
    for p in map(check_position, raw):
        merged = add_lot(out.get(p["symbol"]), p)
        if merged is None:
            out.pop(p["symbol"], None)
        else:
            out[p["symbol"]] = merged
    if len(out) > MAX_POSITIONS:
        raise UserDataError("too_large", f"PORTFOLIO OVER {MAX_POSITIONS} POSITIONS")
    return list(out.values())


def check_alert(body: dict) -> tuple[str, str, str, float]:
    sym = body.get("symbol")
    if not isinstance(sym, str) or not sym.strip():
        raise UserDataError("bad_request", "ALERT NEEDS symbol")
    symbol = resolve(sym)
    if not SYMBOL_RE.match(symbol):
        raise UserDataError("bad_request", f"BAD SYMBOL: {symbol[:24]}")
    op, unit = body.get("op"), body.get("unit", "price")
    if op not in OPS:
        raise UserDataError("bad_request", "op MUST BE > OR <")
    if unit not in UNITS:
        raise UserDataError("bad_request", "unit MUST BE price OR pct")
    value = _number(body.get("value"), "VALUE")
    if unit == "price" and value <= 0:
        raise UserDataError("bad_request", "PRICE LEVEL MUST BE ABOVE 0")
    if unit == "pct" and (abs(value) < EPS or abs(value) > 1000):
        raise UserDataError("bad_request", "PERCENT MUST BE NON-ZERO AND AT MOST 1000")
    return symbol, op, unit, value


ALERT_COLS = "id, symbol, op, unit, value, status, created_at, triggered_at, trigger_price"


def _alert(row) -> dict:
    return dict(zip(ALERT_COLS.split(", "), row, strict=True))


class Portfolios:
    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def all(self) -> list[dict]:
        async with self.db.execute("SELECT name, base, positions, updated_at FROM portfolios ORDER BY name") as cur:
            rows = await cur.fetchall()
        return [{"name": n, "base": b, "count": len(orjson.loads(p)), "updated_at": at} for n, b, p, at in rows]

    async def _get(self, name: str) -> dict | None:
        async with self.db.execute("SELECT base, positions, updated_at FROM portfolios WHERE name=?", (name,)) as cur:
            row = await cur.fetchone()
        return {"name": name, "base": row[0], "positions": orjson.loads(row[1]), "updated_at": row[2]} if row else None

    async def get(self, raw_name: str) -> dict:
        name = portfolio_name(raw_name)
        got = await self._get(name)
        if not got:
            raise UserDataError("not_found", f"NO PORTFOLIO {name}")
        return got

    async def _store(self, name: str, base: str, positions: list[dict]) -> dict:
        now = time.time()
        await self.db.execute(
            "INSERT INTO portfolios (name, base, positions, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET base=excluded.base, positions=excluded.positions, "
            "updated_at=excluded.updated_at",
            (name, base, orjson.dumps(positions), now),
        )
        await self.db.commit()
        return {"name": name, "base": base, "positions": positions, "updated_at": now}

    async def put(self, raw_name: str, positions, base=None) -> dict:
        """Replaces every position (CSV import with REPLACE, undo)."""
        name = portfolio_name(raw_name)
        cur = await self._get(name)
        new_base = check_currency(base, "BASE") or (cur["base"] if cur else "USD")
        return await self._store(name, new_base, check_positions(positions))

    async def edit(self, raw_name: str, add=None, set_=None, remove=None, base=None) -> dict:
        """remove (symbols), then set (upsert whole positions), then add (lots). add or set creates the portfolio."""
        name = portfolio_name(raw_name)
        if add is None and set_ is None and remove is None and base is None:
            raise UserDataError("bad_request", "BODY NEEDS add, set, remove OR base")
        if remove is not None and (not isinstance(remove, list) or not all(isinstance(x, str) for x in remove)):
            raise UserDataError("bad_request", "remove MUST BE A LIST OF SYMBOLS")
        if add is not None and (not isinstance(add, list) or len(add) > MAX_POSITIONS):
            raise UserDataError("bad_request", f"add MUST BE A LIST OF AT MOST {MAX_POSITIONS} POSITIONS")
        plus = [check_position(p) for p in add or []]
        upsert = check_positions(set_) if set_ is not None else []
        minus = {resolve(x) for x in remove or [] if x.strip()}
        new_base = check_currency(base, "BASE")
        cur = await self._get(name)
        if cur is None and not plus and not upsert:
            raise UserDataError("not_found", f"NO PORTFOLIO {name}")
        positions = {p["symbol"]: p for p in (cur["positions"] if cur else []) if p["symbol"] not in minus}
        for p in upsert:
            positions[p["symbol"]] = p
        for lot in plus:
            merged = add_lot(positions.get(lot["symbol"]), lot)
            if merged is None:
                positions.pop(lot["symbol"], None)
            else:
                positions[lot["symbol"]] = merged
        if len(positions) > MAX_POSITIONS:
            raise UserDataError("too_large", f"PORTFOLIO OVER {MAX_POSITIONS} POSITIONS")
        return await self._store(name, new_base or (cur["base"] if cur else "USD"), list(positions.values()))

    async def delete(self, raw_name: str) -> str:
        name = portfolio_name(raw_name)
        cur = await self.db.execute("DELETE FROM portfolios WHERE name=?", (name,))
        await self.db.commit()
        if cur.rowcount == 0:
            raise UserDataError("not_found", f"NO PORTFOLIO {name}")
        return name


class Alerts:
    """States: active -> triggered (trigger price + time recorded once) -> active again on rearm."""

    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def all(self) -> list[dict]:
        async with self.db.execute(f"SELECT {ALERT_COLS} FROM alerts ORDER BY id") as cur:
            return [_alert(r) for r in await cur.fetchall()]

    async def _one(self, alert_id: int) -> dict:
        async with self.db.execute(f"SELECT {ALERT_COLS} FROM alerts WHERE id=?", (alert_id,)) as cur:
            row = await cur.fetchone()
        if not row:
            raise UserDataError("not_found", f"NO ALERT {alert_id}")
        return _alert(row)

    async def create(self, body: dict) -> dict:
        symbol, op, unit, value = check_alert(body)
        async with self.db.execute("SELECT COUNT(*) FROM alerts") as cur:
            (n,) = await cur.fetchone()
        if n >= MAX_ALERTS:
            raise UserDataError("too_large", f"OVER {MAX_ALERTS} ALERTS. ALRT CLEAR REMOVES TRIGGERED ONES")
        cur = await self.db.execute(
            "INSERT INTO alerts (symbol, op, unit, value, status, created_at) VALUES (?, ?, ?, ?, 'active', ?)",
            (symbol, op, unit, value, time.time()),
        )
        await self.db.commit()
        return await self._one(cur.lastrowid)

    async def trigger(self, alert_id: int, price, at=None) -> dict:
        """Marks an active alert triggered. A second report (another tab) changes nothing: changed=False."""
        price = _number(price, "PRICE")
        when = _number(at, "AT") if at is not None else time.time()
        cur = await self.db.execute(
            "UPDATE alerts SET status='triggered', trigger_price=?, triggered_at=? WHERE id=? AND status='active'",
            (price, when, alert_id),
        )
        await self.db.commit()
        return {"alert": await self._one(alert_id), "changed": cur.rowcount == 1}

    async def rearm(self, alert_id: int) -> dict:
        await self._one(alert_id)
        await self.db.execute(
            "UPDATE alerts SET status='active', trigger_price=NULL, triggered_at=NULL WHERE id=?", (alert_id,)
        )
        await self.db.commit()
        return await self._one(alert_id)

    async def delete(self, alert_id: int) -> int:
        cur = await self.db.execute("DELETE FROM alerts WHERE id=?", (alert_id,))
        await self.db.commit()
        if cur.rowcount == 0:
            raise UserDataError("not_found", f"NO ALERT {alert_id}")
        return alert_id

    async def clear_triggered(self) -> int:
        cur = await self.db.execute("DELETE FROM alerts WHERE status='triggered'")
        await self.db.commit()
        return cur.rowcount
