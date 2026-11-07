"""Daily brief routes (Phase 17 C): read the last brief, build one now (optionally sending it)."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from . import brief
from .http_util import loopback
from .responses import Orjson, OrjsonRoute

router = APIRouter(prefix="/api/brief", route_class=OrjsonRoute)


@router.get("")
async def get_brief(request: Request):
    return Orjson({"brief": await brief.last(request.app)})


@router.post("/run")
async def run_brief(request: Request, send: int = Query(0, ge=0, le=1)):
    # Building is harmless, but sending pushes to the user's channels, so the whole route is local-only.
    if not loopback(request):
        return Orjson({"error": "THE BRIEF CAN ONLY BE RUN FROM THIS MACHINE", "kind": "forbidden"}, status_code=403)
    built, delivered = await brief.run(request.app, bool(send))
    return Orjson({"brief": built, "delivered": delivered})
