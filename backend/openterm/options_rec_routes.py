"""Phase 28: the option chain recorder and the OSCAN option scan, both read from OpenTerm's own SQLite snapshots.

GET/PUT /api/options/recorder           status; PUT {"watchlist": NAME | null} turns it on / off (loopback only)
POST    /api/options/recorder/run       snapshot the chosen watchlist now (loopback only)
GET     /api/options/recorder/{symbol}  IV rank, percentile, term-structure history, days recorded
GET     /api/options/scan               OSCAN: `universe` + `filter`, no live chain downloads
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from .errors import DataError
from .http_util import error, error_response, loopback
from .options import recorder as rec
from .responses import OrjsonRoute
from .scanner import routes as scan_routes
from .scanner import universe as U
from .symbols import resolve
from .userdata import UserDataError

router = APIRouter(route_class=OrjsonRoute)


class RecorderBody(BaseModel):
    watchlist: str | None = Field(None, max_length=32)  # null = off


def _db(request: Request):
    return request.app.state.userdata.db


async def _status(request: Request) -> dict:
    db = _db(request)
    first = await rec.first_day(db)
    return {**await rec.get_setting(db), "last": await rec.get_last(db), "first_day": first, "label": rec.label(first),
            "schedule": "WEEKDAYS 16:45 US EASTERN, NOT IN FIXTURE MODE"}


@router.get("/api/options/recorder")
async def recorder_status(request: Request):
    return await _status(request)


@router.put("/api/options/recorder")
async def recorder_set(request: Request, body: RecorderBody):
    if not loopback(request):
        return error_response(403, "forbidden", "THE CHAIN RECORDER CAN ONLY BE CHANGED FROM THIS COMPUTER")
    name = None
    if body.watchlist and body.watchlist.strip().upper() not in ("OFF", ""):
        try:
            name = (await request.app.state.userdata.watchlist(body.watchlist))["name"]  # must exist
        except UserDataError as e:
            return error(e)
    await rec.set_setting(_db(request), name)
    return await _status(request)


@router.post("/api/options/recorder/run")
async def recorder_run(request: Request):
    if not loopback(request):
        return error_response(403, "forbidden", "THE CHAIN RECORDER CAN ONLY BE RUN FROM THIS COMPUTER")
    try:
        result = await rec.run_all(request.app)
    except (DataError, UserDataError) as e:
        return error(e)
    if result["watchlist"] is None:
        return error_response(400, "bad_request", "THE CHAIN RECORDER IS OFF: OREC <WATCHLIST> TURNS IT ON")
    return {**result, **await _status(request)}


@router.get("/api/options/recorder/{symbol}")
async def recorder_symbol(request: Request, symbol: str):
    sym = resolve(symbol.strip().upper())
    db = _db(request)
    stats = await rec.symbol_stats(db, sym)
    if stats is None:
        return {"symbol": sym, "recorded": False, "label": rec.label(await rec.first_day(db)),
                "message": f"NOT RECORDED: {sym} IS NOT IN THE RECORDED WATCHLIST (OREC <WATCHLIST>)"}
    return {**stats, "recorded": True, "label": rec.label(stats["first_day"]),
            "rank_note": f"IV RANK FROM {stats['rank_days']} RECORDED DAYS (NEAREST EXPIRY AT LEAST {rec.RANK_MIN_DAYS} DAYS OUT)"}


@router.get("/api/options/scan")
async def options_scan(request: Request, universe: str, filter: str = ""):
    try:
        terms = rec.parse_filter(filter)
        syms, _, source = await scan_routes.resolve_universe(request.app, universe, None)
    except (rec.FilterError, U.UniverseError) as e:
        return error_response(400, "bad_request", str(e))
    except UserDataError as e:
        return error(e)
    db = _db(request)
    rows, missing = [], []
    for s in syms:
        st = await rec.symbol_stats(db, s)
        if st is None:
            missing.append(s)
            continue
        if rec.matches(st, terms):
            rows.append({k: v for k, v in st.items() if k != "term"})
    first = await rec.first_day(db)
    return {"universe": source, "filter": filter.upper(), "checked": len(syms) - len(missing), "matched": len(rows), "rows": rows,
            "not_recorded": missing, "label": rec.label(first),
            "note": "FROM THE CHAIN RECORDER'S SNAPSHOTS ONLY: A SYMBOL WITH NO SNAPSHOT SHOWS NOT RECORDED"}
