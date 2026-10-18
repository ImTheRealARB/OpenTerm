"""Phase 19 server side: `/api/world/...` (GP event markers, GIP ticks now; holidays, world stats, energy, crypto depth, PRED later).

Thin routes over services; every answer is the standard envelope (source, as_of, age_s, stale) so panels label it like any other data.
"""

import time

from fastapi import APIRouter, Query, Request

from .api import error, svc
from .service import DataError
from .symbols import resolve
from .userdata import SYMBOL_RE, UserDataError
from .world.tickbuf import BARS, SOURCE_LABEL, bucket

router = APIRouter(prefix="/api/world")

STALE_TICKS_S = 300


@router.get("/events")
async def events(request: Request, symbol: str = Query(..., max_length=24)):
    """GP `EVT` markers: dividends, splits and the last four earnings dates."""
    try:
        return await svc(request).research.chart_events(symbol)
    except DataError as e:
        return error(e)


@router.get("/figi")
async def figi(request: Request, q: str = Query(..., max_length=600)):
    """SECF: ISIN / CUSIP / SEDOL / FIGI (space or comma separated, at most 25) mapped to listings by OpenFIGI."""
    from .world.figi import lookup

    try:
        return await lookup(svc(request), q)
    except DataError as e:
        return error(e)


@router.get("/holidays")
async def holidays(request: Request, mkt: str = Query("NY", max_length=2), year: int | None = Query(None, ge=2000, le=2040)):
    """Market-light holidays: NY by rule, LN / TK / HK / IN from Nager.Date public holidays (labelled)."""
    from .world.holidays import calendar

    try:
        return await calendar(svc(request), mkt, year or time.gmtime().tm_year)
    except DataError as e:
        return error(e)


@router.get("/stats")
async def world_stats(request: Request, country: str = Query("", max_length=40), ind: str = Query(..., max_length=80)):
    """ECST: one indicator for one country (World Bank, DBnomics as the second source) or any `DBN:<provider>/<dataset>/<series>`."""
    from .world.macro import ecst

    try:
        return await ecst(svc(request), country, ind)
    except DataError as e:
        return error(e)


@router.get("/weco")
async def world_weco(request: Request):
    """WECO: G20 headline indicators, each cell with its own data year."""
    from .world.macro import weco

    try:
        return await weco(svc(request))
    except DataError as e:
        return error(e)


@router.get("/cenb")
async def central_banks(request: Request):
    """CENB: policy rates and rate-decision dates of eight central banks."""
    from .world.macro import cenb_table

    try:
        return await cenb_table(svc(request))
    except DataError as e:
        return error(e)


@router.get("/ticks/{symbol}")
async def ticks(request: Request, symbol: str, bar: str = Query("5s", max_length=4)):
    """GIP: time-bucketed bars built from the live ticks this server has seen for the symbol (nothing is invented: no ticks = empty)."""
    try:
        sym = resolve(symbol)
        if not SYMBOL_RE.match(sym):
            raise UserDataError("bad_request", f"BAD SYMBOL: {symbol[:24]}")
        if bar not in BARS:
            raise UserDataError("bad_request", f"BAR MUST BE ONE OF {' '.join(BARS)}")
    except UserDataError as e:
        return error(e)
    ring = request.app.state.hub.tickbuf.get(sym)
    now = time.time()
    if ring is None or not len(ring):
        data = {"symbol": sym, "bar_s": BARS[bar], "ticks": 0, "since_ms": None, "last_ms": None, "synthetic": False,
                "t": [], "o": [], "h": [], "l": [], "c": [], "v": None, "sessions": 0, "source_code": None}
        return {"data": data, "source": "TICKS (NONE SEEN YET)", "as_of": now, "age_s": 0.0, "stale": False, "fallback_from": []}
    t, p, v = ring.view()
    bars = bucket(t, p, v, BARS[bar])
    last = ring.last_ms / 1000
    label = SOURCE_LABEL.get(ring.src, ring.src.upper())
    data = {"symbol": sym, "bar_s": BARS[bar], "ticks": len(ring), "since_ms": ring.since_ms, "last_ms": ring.last_ms,
            "synthetic": ring.src == "s", "sessions": ring.sessions, "source_code": ring.src, **bars}
    age = max(0.0, now - last)
    return {"data": data, "source": f"TICKS · {label}", "as_of": last, "age_s": round(age, 2), "stale": age > STALE_TICKS_S, "fallback_from": []}
