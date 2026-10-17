import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import orjson
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from . import APP_NAME, __version__, logbuf, perf, providers, scheduler
from .api import router as api_router
from .cache import Cache
from .config import ROOT, get_settings, load_yaml
from .db import open_db
from .responses import Orjson
from .router import Router
from .service import DataService

STARTED = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logbuf.install()
    settings = get_settings()
    cfg = load_yaml()
    db_path = Path(settings.openterm_db_path)
    db = await open_db(db_path if db_path.is_absolute() or str(db_path) == ":memory:" else ROOT / db_path)
    http = httpx.AsyncClient(
        http2=True, limits=httpx.Limits(max_connections=50, max_keepalive_connections=20), timeout=6.0
    )
    order = cfg.get("providers") or {"quotes": ["yahoo", "nasdaq"], "history": ["yahoo", "nasdaq"], "search": ["yahoo"]}
    router = Router(providers.build(settings, http, fixtures=settings.openterm_fixtures), order)
    c = cfg.get("cache") or {}
    cache = Cache(db, max_entries=c.get("lru_entries", 5000))
    app.state.settings = settings
    app.state.service = DataService(router, cache, ttl={
        "quote": c.get("quote_ttl_s", 5), "intraday": c.get("intraday_ttl_s", 60),
        "daily": c.get("daily_ttl_s", 3600), "search": c.get("search_ttl_s", 86400),
    })
    sched = scheduler.start(router)
    try:
        yield
    finally:
        sched.shutdown(wait=False)
        await cache.flush()
        await http.aclose()
        await db.close()


app = FastAPI(title=APP_NAME, version=__version__, default_response_class=Orjson, lifespan=lifespan)
app.add_middleware(perf.TimingMiddleware)
app.include_router(api_router)


@app.get("/api/health")
async def health() -> dict:
    return {"ok": True, "app": APP_NAME, "version": __version__, "uptime_s": time.time() - STARTED}


@app.get("/api/perf")
async def perf_summary() -> dict:
    return perf.summary()


@app.websocket("/ws")
async def ws(socket: WebSocket) -> None:
    """Multiplexed stream. Phase 1-2: ping/pong only; subscribe/unsubscribe land in phase 3.

    Frames are compact JSON arrays: ["pong", client_ts, server_ts].
    """
    await socket.accept()
    try:
        while True:
            msg = orjson.loads(await socket.receive_text())
            if msg and msg[0] == "ping":
                await socket.send_text(orjson.dumps(["pong", msg[1], time.time() * 1000]).decode())
    except WebSocketDisconnect:
        pass
