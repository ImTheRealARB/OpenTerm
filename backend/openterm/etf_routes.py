"""FSRC (ETF screener) route: `GET /api/etf/screener`.

The data is built slowly in the background (`etf_screen.FundScreener`), so this route never waits for it. Each call answers at
once with what is loaded so far, plus progress. A client keeps `run` and `seq` from the answer and sends them back as `run=` and
`after=` to get only the rows added since; the first call (or one after a server restart) gets every row loaded so far.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from .etf_screen import FundScreener
from .http_util import data_errors, svc
from .responses import OrjsonRoute

router = APIRouter(prefix="/api/etf", route_class=OrjsonRoute)


def engine_of(request: Request) -> FundScreener:
    """The app's one FundScreener, built on the first FSRC request (nothing runs, and nothing is fetched, until someone asks)."""
    app = request.app
    if getattr(app.state, "fsrc", None) is None:
        app.state.fsrc = FundScreener(svc(request), app.state.scheduler)
    return app.state.fsrc


@router.get("/screener")
@data_errors
async def etf_screener(request: Request, run: str | None = Query(None, max_length=16), after: int = Query(0, ge=0, le=1_000_000)):
    engine = engine_of(request)
    await engine.ensure()  # restores saved progress, loads the symbol list, starts the background job while there is work
    return engine.payload(run, after)
