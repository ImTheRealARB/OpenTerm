"""Applies a broker's lots to a portfolio and keeps the sync log.

A synced lot carries `source` ("kite" | "ibkr") and `synced_at`. A re-sync removes every lot of that source from the portfolio and writes
the fresh ones, so it never duplicates; lots without that source (manual, or another broker's) are never touched. When a fresh lot's
symbol is already held by a lot of another origin it is NOT merged: it is listed as a conflict and the portfolio stays as it was for it.
Every run, good or bad, is recorded in the `kv` table (newest 20 per broker) with counts, the difference against the previous sync and
the errors, so the SYNC panel can show the last sync and its age.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

import aiosqlite
import orjson

from ..errors import DataError
from ..portfolio import Portfolios, add_lot, portfolio_name
from ..redact import redact
from ..userdata import UserDataError
from . import FIXTURE_LABEL  # noqa: F401  (re-exported so tests label their data the same way)

BROKERS = ("kite", "ibkr")
LOG_KEEP = 20
GATEWAY_KEY = "ibkr:gateway_url"
DEFAULT_BASE = {"kite": "INR", "ibkr": "USD"}
DEFAULT_PORTFOLIO = {"kite": "KITE", "ibkr": "IBKR"}
QTY_EPS = 1e-9


def _log_key(broker: str) -> str:
    return f"sync:log:{broker}"


def combine(lots: list[dict]) -> tuple[list[dict], list[str]]:
    """One lot per symbol (a broker may list a symbol twice: two accounts, holdings plus a position). Same-currency lots average the
    cost; a lot in another currency than the first is returned as a conflict message."""
    out: dict[str, dict] = {}
    clashes: list[str] = []
    for lot in lots:
        cur = out.get(lot["symbol"])
        try:
            merged = add_lot(cur, lot)
        except UserDataError:
            clashes.append(f"{lot['symbol']}: SECOND LOT IN {lot['currency']} DIFFERS FROM {cur['currency']}, NOT IMPORTED")
            continue
        if merged is None:
            out.pop(lot["symbol"], None)
        else:
            out[lot["symbol"]] = merged
    return list(out.values()), clashes


def diff(previous: dict[str, dict], fresh: dict[str, dict]) -> dict:
    """What changed between the previous synced lots and the new ones, by symbol."""
    added = sorted(s for s in fresh if s not in previous)
    removed = sorted(s for s in previous if s not in fresh)
    changed = []
    for s in sorted(set(fresh) & set(previous)):
        a, b = previous[s], fresh[s]
        if abs(a["qty"] - b["qty"]) > QTY_EPS or a.get("cost") != b.get("cost"):
            changed.append({"symbol": s, "qty_from": a["qty"], "qty_to": b["qty"], "cost_from": a.get("cost"), "cost_to": b.get("cost")})
    return {"added": added, "removed": removed, "changed": changed}


class BrokerSync:
    def __init__(self, db: aiosqlite.Connection):
        self.db = db
        self.portfolios = Portfolios(db)
        self.lock = asyncio.Lock()

    # --- kv helpers ---
    async def _kv_get(self, key: str):
        async with self.db.execute("SELECT value FROM kv WHERE key=?", (key,)) as cur:
            row = await cur.fetchone()
        return orjson.loads(row[0]) if row else None

    async def _kv_put(self, key: str, value) -> None:
        await self.db.execute("INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                              (key, orjson.dumps(value)))
        await self.db.commit()

    async def gateway_url(self) -> str:
        from .ibkr import DEFAULT_GATEWAY_URL, GatewayUrlError, validate_gateway_url

        stored = await self._kv_get(GATEWAY_KEY)
        try:
            return validate_gateway_url(stored) if stored else DEFAULT_GATEWAY_URL
        except GatewayUrlError:  # a bad value somehow stored (edited database): fall back, never connect to it
            return DEFAULT_GATEWAY_URL

    async def set_gateway_url(self, raw) -> str:
        from .ibkr import GatewayUrlError, validate_gateway_url

        try:
            url = validate_gateway_url(raw)
        except GatewayUrlError as e:
            raise UserDataError("bad_request", str(e)) from None
        await self._kv_put(GATEWAY_KEY, url)
        return url

    # --- log ---
    async def log(self, broker: str) -> list[dict]:
        return await self._kv_get(_log_key(broker)) or []

    async def _record(self, broker: str, rec: dict) -> None:
        entries = [rec, *await self.log(broker)][:LOG_KEEP]
        await self._kv_put(_log_key(broker), entries)

    async def status(self, broker: str) -> dict:
        entries = await self.log(broker)
        last_ok = next((e for e in entries if e["ok"]), None)
        last = entries[0] if entries else None
        return {"broker": broker, "last": last, "last_ok": last_ok, "last_error": last if last and not last["ok"] else None,
                "runs": len(entries)}

    # --- apply ---
    async def apply(self, broker: str, raw_portfolio: str, lots: list[dict], *, skipped=(), warnings=(), meta=None,
                    base: str | None = None, label: str | None = None) -> dict:
        """Replaces the portfolio's lots of `broker` with `lots`. Returns the sync record (also logged)."""
        name = portfolio_name(raw_portfolio)
        now = time.time()
        stamp = datetime.fromtimestamp(now, UTC).strftime("%Y-%m-%d %H:%M")
        note = f"{(label or broker).upper()} SYNC {stamp}Z"
        async with self.lock:
            cur = await self.portfolios._get(name)
            existing = cur["positions"] if cur else []
            previous = {p["symbol"]: p for p in existing if p.get("source") == broker}
            others = [p for p in existing if p.get("source") != broker]
            held = {p["symbol"] for p in others}
            combined, clashes = combine(lots)
            conflicts = [f"{lot['symbol']}: HELD BY A MANUAL OR OTHER-BROKER LOT IN {name}, NOT IMPORTED" for lot in combined if lot["symbol"] in held]
            fresh = [{**lot, "source": broker, "synced_at": now, "notes": note} for lot in combined if lot["symbol"] not in held]
            positions = [*others, *fresh]
            stored = await self.portfolios.put(name, positions, cur["base"] if cur else (base or DEFAULT_BASE[broker]))
            fresh_by = {p["symbol"]: p for p in fresh}
            rec = {
                "broker": broker, "portfolio": name, "at": now, "ok": True, "error": None, "base": stored["base"],
                "counts": {"fetched": len(lots), "imported": len(fresh), "skipped": len(skipped), "conflicts": len(conflicts) + len(clashes),
                          "manual_kept": len(others), "previous": len(previous)},
                "diff": diff(previous, fresh_by),
                "skipped": list(skipped)[:50], "conflicts": [*conflicts, *clashes][:50], "warnings": list(warnings)[:50],
                **(meta or {}),
            }
            await self._record(broker, rec)
        return rec

    async def fail(self, broker: str, raw_portfolio: str, error: Exception) -> dict:
        """Records a failed run (nothing in the portfolio changed) and returns the record."""
        try:
            name = portfolio_name(raw_portfolio)
        except UserDataError:
            name = str(raw_portfolio)[:32]
        rec = {"broker": broker, "portfolio": name, "at": time.time(), "ok": False, "error": redact(str(error)),
               "kind": getattr(error, "kind", "unavailable"), "counts": None, "diff": None, "skipped": [], "conflicts": [], "warnings": []}
        async with self.lock:
            await self._record(broker, rec)
        return rec


# --- the two sources -------------------------------------------------------------------------------------------------------------------

async def fetch_kite(kite, include_positions: bool) -> tuple[list[dict], list[dict], list[str], dict]:
    """Reads Kite holdings (and optionally net positions) with the existing client and daily login. Raises DataError."""
    from .kite_map import map_holdings, map_positions

    if kite.session is None:
        raise DataError("unavailable", "KITE IS NOT STARTED")
    kite.session.auth()  # KEY REQUIRED / LOGGED OUT / EXPIRED say so before any call
    holdings = await kite.client.get_json("/portfolio/holdings")
    lots, skipped, warnings = map_holdings(holdings)
    n_pos = 0
    if include_positions:
        pos_lots, pos_skipped = map_positions(await kite.client.get_json("/portfolio/positions"))
        lots += pos_lots
        skipped += pos_skipped
        n_pos = len(pos_lots)
    return lots, skipped, warnings, {"holdings": len(lots) - n_pos, "positions": n_pos, "include_positions": include_positions}


async def fetch_ibkr(gateway, only_account: str | None) -> tuple[list[dict], list[dict], list[str], dict]:
    from .ibkr import map_cash, map_position

    await gateway.check()
    accounts = await gateway.accounts()
    if only_account:
        if only_account not in accounts:
            raise DataError("not_found", f"IBKR: NO ACCOUNT {only_account[:24]} IN THIS LOGIN")
        accounts = [only_account]
    lots, skipped, warnings, cash = [], [], [], []
    for acct in accounts:
        for row in await gateway.positions(acct):
            lot, why, warn = map_position(row)
            if lot:
                lots.append(lot)
            if why:
                skipped.append({"symbol": why.split(":")[0], "reason": why, "account": acct})
            if warn and warn not in warnings:
                warnings.append(warn)
        cash.append({"account": acct, "rows": map_cash(await gateway.ledger(acct))})
    return lots, skipped, warnings, {"accounts": accounts, "cash": cash}
