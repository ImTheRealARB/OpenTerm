"""JRNL routes (`/api/journal/*`): import a broker file, list fills, the analysis (round trips, stats, diagnostics) and the Shadow Account job.

The server parses and matches in plain Python; the Shadow Account fetches daily bars here, writes them to a content-addressed data file and
submits an internal `journal.shadow` job, so pandas and the backtester load in a worker, never in the request thread (as BT and the quant jobs do).
"""

import asyncio
import statistics
from datetime import date

from fastapi import APIRouter, Query, Request

from .api import bt_of
from .barfetch import fetch_bars
from .bt import catalog
from .errors import DataError
from .http_util import error, jobs_of, json_object, loopback, svc, user
from .jobs.kinds import BadParams
from .journal import roundtrips
from .journal.parsers import BROKERS, JournalError, inspect, parse
from .journal.store import MAX_FILLS_SHOWN, JournalStore
from .responses import Orjson, OrjsonRoute
from .symbols import resolve
from .userdata import UserDataError

router = APIRouter(prefix="/api/journal", route_class=OrjsonRoute)
HEADLINE = "HISTORICAL SIMULATION, NOT A FORECAST"
MIN_TRIPS = 5
RULES = ("hold", "stop_target")


def store_of(request: Request) -> JournalStore:
    return JournalStore(user(request).db)


def local_only() -> Orjson:
    return Orjson({"error": "THE JOURNAL CAN ONLY BE CHANGED FROM THIS MACHINE", "kind": "forbidden"}, status_code=403)


def bad(msg: str, detail: str | None = None) -> Orjson:
    return Orjson({"error": msg, "kind": "bad_request", **({"detail": detail} if detail else {})}, status_code=400)


async def _text_body(request: Request) -> tuple[dict, str]:
    body = await json_object(request)
    text = body.get("text")
    if not isinstance(text, str) or not text.strip():
        raise UserDataError("bad_request", "BODY NEEDS text: THE FILE'S CONTENT")
    return body, text


@router.post("/preview")
async def journal_preview(request: Request):
    """What a file looks like: the broker it is detected as, its columns and a guessed mapping (the generic mapping step)."""
    try:
        _, text = await _text_body(request)
        return inspect(text)
    except JournalError as e:
        return bad(str(e), e.detail)
    except UserDataError as e:
        return error(e)


@router.post("/import")
async def journal_import(request: Request):
    if not loopback(request):
        return local_only()
    try:
        body, text = await _text_body(request)
        mapping = body.get("mapping")
        if mapping is not None and not isinstance(mapping, dict):
            raise UserDataError("bad_request", "MAPPING MUST BE AN OBJECT {field: column}")
        broker, trades, ignored = parse(text, str(body.get("broker") or "auto").lower(), mapping, body.get("date_order"),
                                        str(body.get("currency") or "USD"))
    except JournalError as e:
        return bad(str(e), e.detail)
    except UserDataError as e:
        return error(e)
    out = await store_of(request).add(trades, broker, str(body.get("name") or f"pasted {broker}"), ignored)
    return {**out, "first": min(t.time for t in trades), "last": max(t.time for t in trades)}


@router.get("/summary")
async def journal_summary(request: Request):
    return {**await store_of(request).summary(), "brokers": list(BROKERS)}


@router.get("/trades")
async def journal_trades(request: Request, currency: str | None = Query(None, max_length=3), symbol: str | None = Query(None, max_length=32)):
    fills = await store_of(request).fills(currency.upper() if currency else None, symbol.upper() if symbol else None)
    return {"fills": fills[-MAX_FILLS_SHOWN:], "total": len(fills), "truncated": len(fills) > MAX_FILLS_SHOWN}


@router.get("/analysis")
async def journal_analysis(request: Request, currency: str | None = Query(None, max_length=3)):
    try:
        return await store_of(request).analysis(currency.upper() if currency else None)
    except KeyError:
        return bad(f"NO TRADES IN {currency.upper() if currency else ''}")


@router.delete("/trades")
async def journal_clear(request: Request, broker: str | None = Query(None, max_length=16)):
    if not loopback(request):
        return local_only()
    return {"deleted": await store_of(request).clear(broker.lower() if broker else None)}


# --- Shadow Account -----------------------------------------------------------------------------------------------------------------------
def _covering_range(first: date) -> str:
    days = (date.today() - first).days + 45
    for r, n in (("1Y", 366), ("2Y", 731), ("3Y", 1096), ("5Y", 1827), ("10Y", 3653), ("20Y", 7305)):
        if days <= n:
            return r
    return "MAX"


def _num(body: dict, key: str, lo: float, hi: float, default):
    v = body.get(key)
    if v is None or v == "":
        return default
    if isinstance(v, bool) or not isinstance(v, int | float) or not lo <= v <= hi:
        raise UserDataError("bad_request", f"{key.upper()} MUST BE A NUMBER {lo:g}-{hi:g}")
    return float(v)


def shadow_rule(body: dict, trips: list[dict]) -> dict:
    """The rule to replay. Its numbers come from the user's own trips unless typed: hold = the median holding time in days (at least 1),
    stop = the median loss in percent, target = twice the stop."""
    kind = str(body.get("rule") or "hold").lower()
    if kind not in RULES:
        raise UserDataError("bad_request", f"RULE MUST BE {' OR '.join(RULES)}")
    med_days = statistics.median(t["hold_s"] for t in trips) / 86400
    losses = [abs(t["pnl_pct"]) * 100 for t in trips if t["pnl"] < 0]
    stop_auto = min(30.0, max(0.5, round(statistics.median(losses), 1))) if losses else 2.0
    hold = _num(body, "hold_days", 1, 250, max(1, round(med_days)))
    stop = _num(body, "stop_pct", 0.1, 50, stop_auto)
    target = _num(body, "target_pct", 0.1, 200, round(2 * stop, 1))
    if kind == "hold":
        return {"kind": "hold", "hold_days": int(hold), "text": f"HOLD EVERY ENTRY {int(hold)} TRADING DAYS"}
    return {"kind": "stop_target", "stop_pct": stop, "target_pct": target, "max_days": 60,
            "text": f"STOP {stop:g}% (YOUR MEDIAN LOSS UNLESS TYPED), TARGET {target:g}%, AT MOST 60 DAYS; CHECKED ON DAILY CLOSES"}


@router.post("/shadow")
async def journal_shadow(request: Request):
    try:
        body = await json_object(request)
        fills = await store_of(request).fills()
        trips, _ = roundtrips.match(fills)
        n_by: dict[str, int] = {}
        for t in trips:
            n_by[t["currency"]] = n_by.get(t["currency"], 0) + 1
        cur = str(body.get("currency") or "").upper() or max(n_by, key=lambda c: (n_by[c], c), default="")
        mine = [t for t in trips if t["currency"] == cur]
        if len(mine) < MIN_TRIPS:
            raise UserDataError("bad_request", f"NOT RUNNABLE: {len(mine)} ROUND TRIPS{' IN ' + cur if cur else ''}, NEED {MIN_TRIPS}. IMPORT MORE TRADES")
        rule = shadow_rule(body, mine)
        fees = _num(body, "fees_bps", 0, 1000, 0.0)
        max_syms = int(_num(body, "max_symbols", 1, 12, 8))
        count: dict[str, int] = {}
        for t in mine:
            count[t["symbol"]] = count.get(t["symbol"], 0) + 1
        picked = sorted(count, key=lambda s: (-count[s], s))[:max_syms]
        rows = [t for t in mine if t["symbol"] in picked]
        first = date.fromisoformat(min(t["entry_time"][:10] for t in rows))
        range_ = _covering_range(first)
        sym_of = {s: resolve(s) for s in picked}
        envs, errs = await fetch_bars(svc(request), sorted(set(sym_of.values())), range_, tolerate=True)
        skipped = [{"symbol": s, "why": str(errs[sym_of[s]]).upper()[:160]} for s in picked if sym_of[s] in errs]
        have = {s: sym_of[s] for s in picked if sym_of[s] in envs}
        if not have:
            raise DataError("unavailable", "NO DAILY BARS FOR ANY OF YOUR SYMBOLS: " + "; ".join(f"{k['symbol']}: {k['why']}" for k in skipped))
        engine = catalog.engine_for(sorted(have.values()))
        if engine not in catalog.BUILT or engine == "options":
            raise UserDataError("bad_request", f"ENGINE {engine.upper()} CANNOT RUN THE SHADOW ACCOUNT")
        payload = {"bars": {have[s]: envs[have[s]]["data"] for s in have}}
        sha, path = await asyncio.to_thread(bt_of(request).write_data, payload)
        trip_rows = [{"symbol": have[t["symbol"]], "entry": t["entry_time"][:10], "exit": t["exit_time"][:10],
                      "dir": 1 if t["side"] == "long" else -1, "pnl": t["pnl"]} for t in rows if t["symbol"] in have]
        params = {
            "data_path": str(path), "data_sha": sha, "trips": trip_rows, "rule": rule, "engine": engine, "currency": cur,
            "config": {"initial_cash": 100_000.0, **({"fees_bps": fees} if fees else {})}, "bars_per_year": 365 if engine == "crypto" else 252,
            "skipped": skipped,
            "labels": {"headline": HEADLINE, "engine": engine, "fees_bps": fees, "costs": catalog.COSTS.get(engine, ""),
                       "sources": [{"symbol": have[s], "name": envs[have[s]].get("source"), "as_of": envs[have[s]].get("as_of"),
                                    "age_s": envs[have[s]].get("age_s"), "stale": bool(envs[have[s]].get("stale"))} for s in have],
                       "fixtures": bool(request.app.state.settings.openterm_fixtures)},
        }
        return Orjson(await jobs_of(request).submit("journal.shadow", params, internal=True))
    except (UserDataError, DataError) as e:
        return error(e)
    except BadParams as e:
        return error(DataError("bad_request", str(e)))
