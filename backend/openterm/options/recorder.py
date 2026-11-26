"""Option chain recorder (Phase 28): a daily snapshot of the chains of one chosen watchlist, kept in SQLite.

Why: free chain sources give only today's chain, so a true IV rank, a term-structure history and "OI change since yesterday"
need OpenTerm's own record. Every number shown from here is labelled RECORDED BY OPENTERM SINCE <first day>.

Tables (migration 20): `chain_snaps` (day, symbol, expiry, side, strike -> IV, OI, volume) and `chain_atm` (day, symbol, expiry ->
spot, ATM IV, straddle move %). Which watchlist is recorded is kv key `chainrec` = {"watchlist": NAME}; absent = OFF (the default).

The chains come from the derivatives service (`Derivs.chain`), never straight from a provider. No pandas or numpy here.
"""

from __future__ import annotations

import logging
import operator
import re
import time
from datetime import UTC, datetime

import orjson

from ..errors import DataError
from ..redact import redact
from ..router import AllFailed
from . import analytics as an
from . import chain as ch
from . import tables as ot

log = logging.getLogger("openterm.chainrec")

KV_KEY = "chainrec"
KV_LAST = "chainrec:last"
MAX_EXPIRIES = 6          # the nearest six expiries are recorded
RANK_MIN_DAYS = 20        # IV rank uses the nearest expiry at least this many days out (the 30-day-ish point)
DAY = 86400.0
SNAP_RETENTION_DAYS = 400  # strike-level rows older than this are dropped after each run (a bit over one trading year)


def label(first_day: str | None) -> str:
    return f"RECORDED BY OPENTERM SINCE {first_day}" if first_day else "NOTHING RECORDED YET: TURN IT ON WITH OREC <WATCHLIST>"


def _epoch(day: str) -> float:
    return datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=UTC).timestamp()


# --- setting (kv) ---------------------------------------------------------------------------------------------------------

async def get_setting(db) -> dict:
    async with db.execute("SELECT value FROM kv WHERE key=?", (KV_KEY,)) as cur:
        row = await cur.fetchone()
    doc = orjson.loads(row[0]) if row else {}
    return {"watchlist": doc.get("watchlist")}


async def set_setting(db, watchlist: str | None) -> None:
    if watchlist is None:
        await db.execute("DELETE FROM kv WHERE key=?", (KV_KEY,))
    else:
        await db.execute("INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                         (KV_KEY, orjson.dumps({"watchlist": watchlist})))
    await db.commit()


async def get_last(db) -> dict | None:
    async with db.execute("SELECT value FROM kv WHERE key=?", (KV_LAST,)) as cur:
        row = await cur.fetchone()
    return orjson.loads(row[0]) if row else None


# --- writing a snapshot ---------------------------------------------------------------------------------------------------

async def record_symbol(derivs, db, symbol: str, day: str) -> dict:
    """Snapshots the nearest expiries of one symbol for `day` (replacing that day's rows). Returns {expiries, rows}.
    An expiry whose chain fails is left out; a symbol with no chain at all raises (the caller reports it)."""
    now = derivs.now()
    base = (await derivs.chain(symbol))["data"]
    picked = sorted(e for e in base["expirations"] if e + 20 * 3600 >= now)[:MAX_EXPIRIES]
    if not picked:
        raise DataError("not_found", f"NO LISTED EXPIRIES FOR {symbol}")
    expiries = rows_n = 0
    for epoch in picked:
        try:
            c = base if epoch == base["expiry"] else (await derivs.chain(symbol, epoch))["data"]
        except (DataError, AllFailed):
            continue
        T = ch.years_to_expiry(epoch, now)
        r, _, _, q, _ = await derivs.rate_and_yield(symbol, T, None)
        S = c["spot"]
        calls = ot.side_rows(c["calls"], "call", S, T, r, q or 0.0, "ALL")
        puts = ot.side_rows(c["puts"], "put", S, T, r, q or 0.0, "ALL")
        atm = ch.atm_iv(calls, puts, S)
        em = an.expected_move(S, T, calls, puts, atm)
        await db.execute("DELETE FROM chain_snaps WHERE day=? AND symbol=? AND expiry=?", (day, symbol, epoch))
        data = [(day, symbol, epoch, kind, x["strike"], x["iv"], x["oi"], x["volume"])
                for kind, rows in (("call", calls), ("put", puts)) for x in rows]
        await db.executemany("INSERT INTO chain_snaps (day, symbol, expiry, kind, strike, iv, oi, volume) VALUES (?,?,?,?,?,?,?,?)", data)
        await db.execute("INSERT OR REPLACE INTO chain_atm (day, symbol, expiry, spot, atm_iv, em_pct) VALUES (?,?,?,?,?,?)",
                         (day, symbol, epoch, S, atm, None if em["straddle_pct"] is None else em["straddle_pct"] * 100.0))
        expiries += 1
        rows_n += len(data)
    if not expiries:
        raise DataError("unavailable", f"NO CHAIN COULD BE READ FOR {symbol}")
    await db.commit()
    return {"expiries": expiries, "rows": rows_n}


async def run_all(app) -> dict:
    """Records every symbol of the chosen watchlist, one after another. {recorded, failed, day, watchlist}; OFF = nothing happens."""
    db = app.state.userdata.db
    name = (await get_setting(db))["watchlist"]
    if not name:
        return {"watchlist": None, "recorded": [], "failed": [], "day": None}
    derivs = app.state.service.derivs
    symbols = (await app.state.userdata.watchlist(name))["symbols"]
    day = derivs.today().isoformat()
    done: list[str] = []
    failed: list[dict] = []
    for sym in symbols:
        try:
            await record_symbol(derivs, db, sym, day)
            done.append(sym)
        except (DataError, AllFailed) as e:   # one bad symbol never stops the rest; the status shows it
            failed.append({"symbol": sym, "error": redact(str(e))})
    out = {"watchlist": name, "day": day, "recorded": done, "failed": failed, "at": time.time()}
    await db.execute("INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                     (KV_LAST, orjson.dumps(out)))
    await db.commit()
    pruned = await prune(db, day)
    log.info("chain recorder %s: %d recorded, %d failed, %d old strike rows dropped", name, len(done), len(failed), pruned)
    return out


async def prune(db, today: str) -> int:
    """Deletes strike rows (`chain_snaps`) older than `SNAP_RETENTION_DAYS`; returns how many went (audit L-01).

    Why only that table: it holds ~1,000 rows per symbol per day and grew without limit. `chain_atm` is one small row per expiry per
    day and is the IV rank / term history, so it stays. The previous-day OI comparison needs only the newest earlier day."""
    cutoff = datetime.fromtimestamp(_epoch(today) - SNAP_RETENTION_DAYS * DAY, UTC).strftime("%Y-%m-%d")
    cur = await db.execute("DELETE FROM chain_snaps WHERE day < ?", (cutoff,))
    await db.commit()
    return cur.rowcount


async def scheduled_run(app) -> None:
    """The apscheduler job: weekdays after the US close. OFF (no watchlist chosen) does nothing."""
    await run_all(app)


# --- reading ---------------------------------------------------------------------------------------------------------------

async def first_day(db, symbol: str | None = None) -> str | None:
    sql, args = ("SELECT MIN(day) FROM chain_atm WHERE symbol=?", (symbol,)) if symbol else ("SELECT MIN(day) FROM chain_atm", ())
    async with db.execute(sql, args) as cur:
        (d,) = await cur.fetchone()
    return d


async def prev_oi(db, symbol: str, expiry: int, today: str) -> tuple[dict | None, str | None]:
    """({(kind, strike): oi}, day) from the latest snapshot of this expiry BEFORE `today`, or (None, None)."""
    async with db.execute("SELECT MAX(day) FROM chain_snaps WHERE symbol=? AND expiry=? AND day<?", (symbol, int(expiry), today)) as cur:
        (day,) = await cur.fetchone()
    if day is None:
        return None, None
    async with db.execute("SELECT kind, strike, oi FROM chain_snaps WHERE symbol=? AND expiry=? AND day=?", (symbol, int(expiry), day)) as cur:
        return {(k, s): oi async for k, s, oi in cur}, day


async def term_history(db, symbol: str) -> list[dict]:
    """ATM IV per expiry per recorded day: [{day, points: [{expiry, days, atm_iv}]}], oldest first."""
    async with db.execute("SELECT day, expiry, atm_iv FROM chain_atm WHERE symbol=? ORDER BY day, expiry", (symbol,)) as cur:
        rows = await cur.fetchall()
    by: dict[str, list[dict]] = {}
    for day, expiry, iv in rows:
        by.setdefault(day, []).append({"expiry": expiry, "days": round((expiry - _epoch(day)) / DAY), "atm_iv": iv})
    return [{"day": d, "points": p} for d, p in by.items()]


def rank_series(terms: list[dict]) -> list[tuple[str, float]]:
    """One ATM IV per day: the nearest recorded expiry at least RANK_MIN_DAYS out. A day with none is left out (never filled)."""
    out = []
    for t in terms:
        for p in t["points"]:
            if p["days"] >= RANK_MIN_DAYS and p["atm_iv"] is not None:
                out.append((t["day"], p["atm_iv"]))
                break
    return out


async def symbol_stats(db, symbol: str) -> dict | None:
    """Everything the recorder knows about one symbol, or None when it was never recorded."""
    terms = await term_history(db, symbol)
    if not terms:
        return None
    series = rank_series(terms)
    now_iv = series[-1][1] if series else None
    rank, pct = an.iv_rank([v for _, v in series], now_iv)
    latest = terms[-1]
    day = latest["day"]
    async with db.execute("SELECT em_pct, spot FROM chain_atm WHERE symbol=? AND day=? ORDER BY expiry LIMIT 1", (symbol, day)) as cur:
        em_pct, spot = await cur.fetchone()
    async with db.execute("SELECT kind, SUM(COALESCE(oi,0)) FROM chain_snaps WHERE symbol=? AND day=? GROUP BY kind", (symbol, day)) as cur:
        oi = dict(await cur.fetchall())
    co, po = oi.get("call", 0), oi.get("put", 0)
    return {"symbol": symbol, "day": day, "spot": spot, "atm_iv": now_iv, "iv_rank": rank, "iv_percentile": pct,
            "rank_days": len(series), "days_recorded": len(terms), "em_pct": em_pct, "oi": co + po, "call_oi": co, "put_oi": po,
            "pcr": po / co if co else None, "first_day": terms[0]["day"], "term": terms}


# --- OSCAN filter ---------------------------------------------------------------------------------------------------------

FIELDS = {"EM": "em_pct", "OI": "oi", "PCR": "pcr"}  # IVR is the rank x 100
OPS = {">=": operator.ge, "<=": operator.le, ">": operator.gt, "<": operator.lt}
_TERM = re.compile(r"^(IVR|EM|OI|PCR)(>=|<=|>|<)(-?\d+(?:\.\d+)?)$")
USAGE = "OSCAN <UNIVERSE> [IVR>50] [EM>5] [OI>1000] [PCR>1.2]: IVR in percent, EM = nearest-expiry straddle move in percent"


class FilterError(ValueError):
    """Shown to the user as is."""


def parse_filter(text: str) -> list[tuple[str, str, float]]:
    """'IVR>50 EM>5' -> [("IVR", ">", 50.0), ("EM", ">", 5.0)]. Blank = no filter. All terms must hold."""
    out = []
    for tok in (text or "").upper().replace(" AND ", " ").replace(",", " ").split():
        m = _TERM.match(tok)
        if not m:
            raise FilterError(f"BAD FILTER {tok[:20]}: {USAGE}")
        out.append((m.group(1), m.group(2), float(m.group(3))))
    return out


def value_of(stats: dict, name: str) -> float | None:
    if name == "IVR":
        return None if stats["iv_rank"] is None else stats["iv_rank"] * 100.0
    return stats[FIELDS[name]]


def matches(stats: dict, terms: list[tuple[str, str, float]]) -> bool:
    """A missing number fails its term (never guessed)."""
    for name, op, val in terms:
        have = value_of(stats, name)
        if have is None or not OPS[op](have, val):
            return False
    return True
