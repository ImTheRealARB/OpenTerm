"""Phase 29 routes: `/api/filings/...` (FTS, MA, LEGAL, BIO, RELS, ESG).

Every answer is the standard research envelope: `data` is a table payload (backend/openterm/research/table.py) that the shared
ResearchPanel draws, next to source, as_of, age_s and stale. All the work is in `filings/service.py`; these are thin routes.
"""

from fastapi import APIRouter, Query, Request

from .errors import DataError
from .filings import esg as _esg
from .filings import service
from .http_util import data_errors, svc
from .responses import OrjsonRoute

router = APIRouter(prefix="/api/filings", route_class=OrjsonRoute)


@router.get("/fts")
@data_errors
async def fts(request: Request, q: str = Query("", max_length=200), forms: str = Query("", max_length=80),
              start: str = Query("", max_length=10), end: str = Query("", max_length=10), symbol: str = Query("", max_length=24)):
    """FTS: SEC EDGAR full-text search (words, form list, date range, one company)."""
    return await service.fts(svc(request), q, forms, start, end, symbol)


@router.get("/ma")
@data_errors
async def ma(request: Request, symbol: str = Query("", max_length=24), start: str = Query("", max_length=10), end: str = Query("", max_length=10)):
    """MA: deal filings. With a symbol, from that company's filing list; without, market-wide from the full-text search."""
    return await service.ma(svc(request), symbol, start, end)


@router.get("/legal")
@data_errors
async def legal(request: Request, symbol: str = Query(..., max_length=24)):
    """LEGAL: SEC litigation releases and administrative proceedings by company name, plus CourtListener dockets (free key)."""
    return await service.legal(svc(request), symbol)


@router.get("/bio")
@data_errors
async def bio(request: Request, q: str = Query(..., max_length=80), start: str = Query("", max_length=10), end: str = Query("", max_length=10)):
    """BIO: Form 3/4/5 filings of one reporting owner, by CIK or name."""
    return await service.bio(svc(request), q, start, end)


@router.get("/rels")
@data_errors
async def rels(request: Request, symbol: str = Query(..., max_length=24)):
    """RELS: other tickers of the same issuer (SEC) and the listings of this ticker (OpenFIGI)."""
    return await service.rels(svc(request), symbol)


@router.get("/esg")
@data_errors
async def esg(request: Request, symbol: str = Query("", max_length=24), name: str = Query("", max_length=80),
              year: int = Query(_esg.LATEST_YEAR, ge=2010, le=2100)):
    """ESG: EPA greenhouse-gas emissions of US facilities whose parent text matches the company name (emissions only, no score)."""
    if not symbol and not name:
        raise DataError("bad_request", "GIVE A SYMBOL OR NAME=<COMPANY>")
    return await service.esg(svc(request), symbol, name, year)
