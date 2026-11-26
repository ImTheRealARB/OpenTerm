"""Phase 30 routes: `/api/macrod/...` (MMR NOWC ECFC FOMC WB CRPR FWCV BTMM WCRS CDR CTM TSYS NRGF AGRI RE WPE). WIRP's meeting odds
ride on the existing `/api/deriv/wirp`. Every answer is the standard research envelope whose `data` is a table payload drawn by the
shared ResearchPanel. All the work is in macrod/service.py; these are thin routes."""

from fastapi import APIRouter, Query, Request

from .http_util import data_errors, svc
from .macrod import service as S
from .responses import OrjsonRoute

router = APIRouter(prefix="/api/macrod", route_class=OrjsonRoute)


@router.get("/mmr")
@data_errors
async def mmr(request: Request):
    """MMR: overnight reference rates (SOFR, TGCR, BGCR, EFFR, OBFR, ESTR, SONIA) with history."""
    return await S.mmr(svc(request))


@router.get("/nowc")
@data_errors
async def nowc(request: Request):
    """NOWC: Atlanta Fed GDPNow, the current quarter's path and past quarters' first / final nowcasts vs the BEA advance estimate."""
    return await S.nowc(svc(request))


@router.get("/ecfc")
@data_errors
async def ecfc(request: Request):
    """ECFC: IMF WEO, OECD Economic Outlook, Philadelphia Fed SPF medians and the FOMC SEP."""
    return await S.ecfc(svc(request))


@router.get("/fomc")
@data_errors
async def fomc(request: Request):
    """FOMC: calendar with links, the latest statement and its word diff vs the previous one, SEP dots."""
    return await S.fomc(svc(request))


@router.get("/wb")
@data_errors
async def wb(request: Request):
    """WB: world 10-year (and 2-year where free) government bond yields, daily or monthly per row."""
    return await S.wb(svc(request))


@router.get("/crpr")
@data_errors
async def crpr(request: Request):
    """CRPR: ICE BofA option-adjusted credit spreads (FRED keeps the last three years)."""
    return await S.crpr(svc(request))


@router.get("/re")
@data_errors
async def re_board(request: Request):
    """RE: US housing board from FRED."""
    return await S.re_board(svc(request))


@router.get("/fwcv")
@data_errors
async def fwcv(request: Request):
    """FWCV: forward rates bootstrapped from the US Treasury par curve."""
    return await S.fwcv(svc(request))


@router.get("/btmm")
@data_errors
async def btmm(request: Request, country: str = Query("US", max_length=4)):
    """BTMM: one-country monitor (US, IN, UK, EA, JP)."""
    return await S.btmm(svc(request), country)


@router.get("/wcrs")
@data_errors
async def wcrs(request: Request, sort: str = Query("1M", max_length=4)):
    """WCRS: currencies ranked by return vs USD and vs INR over 1W..1Y."""
    return await S.wcrs(svc(request), sort)


@router.get("/cdr")
@data_errors
async def cdr(request: Request, year: int | None = Query(None, ge=2000, le=2040)):
    """CDR: exchange holidays, early closes and regular hours for the market-light exchanges."""
    return await S.cdr(svc(request), year)


@router.get("/ctm")
@data_errors
async def ctm(request: Request, root: str = Query("CL", max_length=4)):
    """CTM: contracts of one futures root with last trade and first notice dates (rules table)."""
    return S.ctm(root)


@router.get("/tsys")
@data_errors
async def tsys(request: Request, kind: str = Query("", max_length=5)):
    """TSYS: Treasury securities auctioned in the last 90 days and announced auctions (TreasuryDirect)."""
    return await S.tsys(svc(request), kind)


@router.get("/nrgf")
@data_errors
async def nrgf(request: Request):
    """NRGF: EIA weekly petroleum status and gas storage (free key EIA_API_KEY)."""
    return await S.nrgf(svc(request))


@router.get("/agri")
@data_errors
async def agri(request: Request):
    """AGRI: WASDE US wheat / corn / soybean tables, plus NASS crop condition with a free key."""
    return await S.agri(svc(request))


@router.get("/wpe")
@data_errors
async def wpe(request: Request):
    """WPE: world index valuation through index ETFs (P/E, P/B, P/S, yield), labelled PROXY."""
    return await S.wpe(svc(request))


@router.get("/res")
@data_errors
async def res(request: Request, src: str | None = Query(None, max_length=10), q: str = Query("", max_length=80),
              days: int | None = Query(None, ge=1, le=3650)):
    """RES (Phase 32): free institutional research (BIS, Fed, ECB, RBI, arXiv q-fin), newest first, filtered by words and days."""
    from .errors import DataError
    from .macrod.boards import RES_FEEDS

    key = (src or "").upper() or None
    if key is not None and key not in RES_FEEDS:
        raise DataError("bad_request", f"SOURCE MUST BE ONE OF {' '.join(RES_FEEDS)}")
    return await S.res(svc(request), key, q.strip(), days)
