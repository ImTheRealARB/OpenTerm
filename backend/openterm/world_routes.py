"""Phase 19 server side: `/api/world/...` (GP event markers now; ticks, holidays, world stats, energy, crypto depth, PRED later).

Thin routes over services; every answer is the standard envelope (source, as_of, age_s, stale) so panels label it like any other data.
"""

from fastapi import APIRouter, Query, Request

from .api import error, svc
from .service import DataError

router = APIRouter(prefix="/api/world")


@router.get("/events")
async def events(request: Request, symbol: str = Query(..., max_length=24)):
    """GP `EVT` markers: dividends, splits and the last four earnings dates."""
    try:
        return await svc(request).research.chart_events(symbol)
    except DataError as e:
        return error(e)
