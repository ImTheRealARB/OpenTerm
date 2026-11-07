"""Phase 19 server side: `/api/world/...` (GP event markers, GIP ticks now; holidays, world stats, energy, crypto depth, PRED later).

Thin routes over services; every answer is the standard envelope (source, as_of, age_s, stale) so panels label it like any other data.
"""

import time

from fastapi import APIRouter, Query, Request

from .http_util import data_errors, error, svc
from .responses import OrjsonRoute
from .symbols import resolve
from .userdata import SYMBOL_RE, UserDataError
from .world.tickbuf import BARS, SOURCE_LABEL, bucket

router = APIRouter(prefix="/api/world", route_class=OrjsonRoute)

STALE_TICKS_S = 300


@router.get("/events")
@data_errors
async def events(request: Request, symbol: str = Query(..., max_length=24)):
    """GP `EVT` markers: dividends, splits and the last four earnings dates."""
    return await svc(request).research.chart_events(symbol)


@router.get("/figi")
@data_errors
async def figi(request: Request, q: str = Query(..., max_length=600)):
    """SECF: ISIN / CUSIP / SEDOL / FIGI (space or comma separated, at most 25) mapped to listings by OpenFIGI."""
    from .world.figi import lookup

    return await lookup(svc(request), q)


@router.get("/holidays")
@data_errors
async def holidays(request: Request, mkt: str = Query("NY", max_length=2), year: int | None = Query(None, ge=2000, le=2040)):
    """Market-light holidays: NY by rule, IN by partial rule (fixed dates, no festivals; labelled), LN / TK / HK from Nager.Date public holidays (labelled)."""
    from .world.holidays import calendar

    return await calendar(svc(request), mkt, year or time.gmtime().tm_year)


@router.get("/stats")
@data_errors
async def world_stats(request: Request, country: str = Query("", max_length=40), ind: str = Query(..., max_length=80)):
    """ECST: one indicator for one country (World Bank, DBnomics as the second source) or any `DBN:<provider>/<dataset>/<series>`."""
    from .world.macro import ecst

    return await ecst(svc(request), country, ind)


@router.get("/dbsearch")
@data_errors
async def dbnomics_search(request: Request, q: str = Query("", max_length=160), dataset: str = Query("", max_length=120), offset: int = Query(0, ge=0, le=100000)):
    """DBSRCH: DBnomics datasets matching the words in `q`; with `dataset=<provider>/<code>`, the matching series of that dataset (open one with ECST DBN:...)."""
    from .world.macro import dbsearch_svc

    return await dbsearch_svc(svc(request), q, dataset, offset)


@router.get("/weco")
@data_errors
async def world_weco(request: Request):
    """WECO: G20 headline indicators, each cell with its own data year."""
    from .world.macro import weco

    return await weco(svc(request))


@router.get("/cenb")
@data_errors
async def central_banks(request: Request):
    """CENB: policy rates and rate-decision dates of eight central banks."""
    from .world.macro import cenb_table

    return await cenb_table(svc(request))


@router.get("/nrg")
@data_errors
async def energy_board(request: Request):
    """NRG: crude, natural gas, refined products and retail fuel prices from FRED's keyless CSV."""
    from .world.commodity import nrg

    return await nrg(svc(request))


@router.get("/ship")
@data_errors
async def ship_board(request: Request):
    """SHIP: daily ship transits through 28 sea chokepoints (IMF PortWatch, satellite AIS, weekly, 8 to 12 days behind)."""
    from .world.shipsvc import ship

    return await ship(svc(request))


@router.get("/ports")
@data_errors
async def ports_board(request: Request, q: str = Query("", max_length=120)):
    """PORTS: daily port calls and trade estimates (IMF PortWatch, satellite AIS, weekly). Bare = the 25 busiest ports; `q` = ports matching its words."""
    from .world.portssvc import ports_board as board

    return await board(svc(request), q)


@router.get("/mf")
@data_errors
async def mutual_fund(request: Request, q: str = Query(..., max_length=120)):
    """MF: Indian mutual funds from MFapi.in. `q` = a scheme code (the fund: NAV history and returns) or words (a search of scheme names)."""
    from .world.mfundsvc import mf

    return await mf(svc(request), q)


@router.get("/wetr")
@data_errors
async def weather_board(request: Request, place: str = Query("", max_length=80)):
    """WETR: demand-city degree-day basket; with a place name or `lat,lon`, its 7-day forecast and (US, with SEC_USER_AGENT) NWS alerts."""
    from .world.commodity import wetr

    return await wetr(svc(request), place)


@router.get("/pred")
@data_errors
async def pred_markets(request: Request, q: str = Query("", max_length=120)):
    """PRED: Polymarket and Kalshi markets (read only), filtered by the words of `q`, biggest volume first. Labelled MARKET-IMPLIED PROBABILITY, NOT A FORECAST."""
    from .world.pred import pred

    return await pred(svc(request), q)


@router.get("/pred/detail")
@data_errors
async def pred_market_detail(request: Request, source: str = Query(..., max_length=12), id: str = Query(..., max_length=160)):
    """PRED `Enter`: one market's outcome table and, where the source gives one, its price history."""
    from .world.pred import pred_detail

    return await pred_detail(svc(request), source.strip().lower(), id.strip())


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


@router.get("/mfnav")
@data_errors
async def mf_nav(request: Request, q: str = Query(..., max_length=80)):
    """SECF fund rows: Indian mutual fund schemes from AMFI's daily NAV file, by name words, ISIN (INF...) or scheme code."""
    from .world.mf import lookup

    return await lookup(svc(request), q)


@router.get("/cdep")
@data_errors
async def crypto_depth(request: Request, pair: str = Query("BTCUSDT", max_length=24)):
    """CDEP: spot order book depth (Binance, OKX when Binance fails): cumulative ladder, spread, imbalance."""
    from .world.crypto import cdep

    return await cdep(svc(request), pair)


@router.get("/fund")
@data_errors
async def crypto_funding(request: Request, sym: str = Query("", max_length=24)):
    """FUND: perpetual funding (annualised from each venue's interval) and basis; with a coin, its last 30 funding prints."""
    from .world.crypto import fund

    return await fund(svc(request), sym)


@router.get("/liq")
@data_errors
async def crypto_liquidations(request: Request, sym: str = Query("BTC", max_length=24)):
    """LIQ: the latest filled liquidation orders of a USDT perpetual on OKX (Binance has no REST history)."""
    from .world.crypto import liq

    return await liq(svc(request), sym)


@router.get("/stbl")
@data_errors
async def stablecoins(request: Request, chain: str = Query("", max_length=24)):
    """STBL: stablecoin supply by coin and by chain (DefiLlama)."""
    from .world.crypto import stbl

    return await stbl(svc(request), chain)


@router.get("/defi")
@data_errors
async def defi_yields(request: Request, q: str = Query("", max_length=40)):
    """DEFI: yield pools over US$1M TVL (DefiLlama), by chain or project, highest APY first."""
    from .world.crypto import defi

    return await defi(svc(request), q)


@router.get("/trade")
@data_errors
async def trade_flows(request: Request, reporter: str = Query(..., max_length=24), partner: str = Query("WLD", max_length=24),
                      hs: str = Query("TOTAL", max_length=10), years: int = Query(5, ge=1, le=12)):
    """TRADE: exports and imports between two countries by HS product, per year (UN Comtrade, free key UN_COMTRADE_KEY, 424 without it)."""
    from .world.usdata import trade

    return await trade(svc(request), request.app.state.keys, reporter, partner, hs, years)


@router.get("/usmac")
@data_errors
async def us_macro(request: Request, src: str = Query(..., max_length=8), q: str = Query("", max_length=120), years: int = Query(3, ge=1, le=20)):
    """USMAC: US series from BLS (jobs, prices; BLS_API_KEY), BEA (GDP, trade, industry; BEA_API_KEY) or Census (retail sales, trade by
    country; CENSUS_API_KEY). Every series carries its own latest period. 424 KEY REQUIRED without the key."""
    from .world.usdata import usmac

    return await usmac(svc(request), request.app.state.keys, src, q, years)


@router.get("/ukco")
@data_errors
async def uk_company(request: Request, q: str = Query(..., max_length=120)):
    """UKCO: UK Companies House. A company number gives profile + officers + filings; a name gives a search. 424 KEY REQUIRED without COMPANIES_HOUSE_KEY."""
    from .world.uk_company import ukco

    return await ukco(svc(request), q)


@router.get("/addr")
@data_errors
async def evm_address(request: Request, q: str = Query(..., max_length=120)):
    """ADDR: an EVM address (balance, last 20 transactions, gas) or `GAS`, on Ethereum or a named chain (Etherscan V2). 424 KEY REQUIRED without ETHERSCAN_KEY."""
    from .world.chain import addr

    return await addr(svc(request), q)


@router.get("/flt")
@data_errors
async def flights_live(request: Request, q: str = Query(..., max_length=80)):
    """FLT: live aircraft from OpenSky inside a city preset, a BOX you give, or a CALLSIGN prefix (a whole-world call, 4 credits). Works without a key
    (anonymous, 400 credits a day); OPENSKY_CLIENT_ID + OPENSKY_CLIENT_SECRET raise the limit. Positions are as reported by transponders: partial coverage."""
    from .world.flightssvc import flt

    return await flt(svc(request), q)


@router.get("/ais")
@data_errors
async def ais_ships(request: Request, q: str = Query(..., max_length=80)):
    """AIS: ship positions inside a chokepoint preset or a BOX you give (AISstream, free key AISSTREAM_API_KEY). Listens a few seconds, newest position per ship.
    424 KEY REQUIRED without the key. Positions are as reported by ships: delayed, switchable off, spoofable, partial."""
    from .world.ais import snapshot

    return await snapshot(svc(request), q)


# --- MAP layers: each is one small route; the vessels layer reuses /ais above ------------------------------------------------
@router.get("/geo/quakes")
@data_errors
async def geo_quakes(request: Request):
    """MAP earthquakes layer: USGS M4.5+ quakes of the past 7 days (keyless)."""
    from .world.geosvc import quakes

    return await quakes(svc(request))


@router.get("/usasp")
@data_errors
async def us_spending(request: Request, q: str = Query("", max_length=120)):
    """USASP: US federal spending (USASpending.gov, keyless). Empty / AGENCY = top awarding agencies; `AGENCY:<name>` = that agency's top contract recipients; words = top recipients and awards."""
    from .world.usgovsvc import usasp

    return await usasp(svc(request), q)


@router.get("/geo/events")
@data_errors
async def geo_events(request: Request):
    """MAP natural-events layer: NASA EONET open events without wildfires (keyless)."""
    from .world.geosvc import events

    return await events(svc(request))


@router.get("/fedreg")
@data_errors
async def federal_register(request: Request, q: str = Query("", max_length=120)):
    """FEDREG: Federal Register documents, newest first (keyless). Optional leading type word RULE / PROPOSED / NOTICE / PRESDOC, then search words."""
    from .world.usgovsvc import fedreg_search

    return await fedreg_search(svc(request), q)


@router.get("/geo/ports")
@data_errors
async def geo_ports(request: Request):
    """MAP ports layer: the busiest 100 ports with coordinates and average daily port calls (IMF PortWatch, keyless)."""
    from .world.geosvc import ports_map

    return await ports_map(svc(request))


@router.get("/fec")
@data_errors
async def campaign_finance(request: Request, q: str = Query(..., max_length=120)):
    """FEC: OpenFEC. A name searches candidates and committees; an FEC id (H8CA12345 / C00123456) gives its totals by cycle. 424 KEY REQUIRED without FEC_API_KEY."""
    from .world.usgovsvc import fec_view

    return await fec_view(svc(request), q)


@router.get("/geo/chokepoints")
@data_errors
async def geo_chokepoints(request: Request):
    """MAP chokepoints layer: the AIS preset boxes as rectangles (static, no network)."""
    from .world.geosvc import chokepoints

    return await chokepoints(svc(request))


@router.get("/congress")
@data_errors
async def congress_bills(request: Request, q: str = Query("", max_length=120)):
    """CONGRESS: Congress.gov bills. Empty = latest updated; words = title filter over the latest 250; `HR 1234` = one bill with its sponsor. 424 KEY REQUIRED without CONGRESS_API_KEY."""
    from .world.usgovsvc import congress_view

    return await congress_view(svc(request), q)
