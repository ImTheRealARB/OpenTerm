import asyncio
import contextlib
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import orjson
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from . import APP_NAME, __version__, keys, logbuf, perf, providers, redact, scheduler
from .api import router as api_router
from .bt.localdata import LocalData
from .cache import Cache
from .config import ROOT, get_settings, load_yaml
from .db import open_db
from .responses import Orjson
from .router import Router
from .service import DataService
from .streaming.hub import Client, Hub
from .streaming.upstream import NullStream, Poller, SyntheticStream, YahooStream
from .symbols import resolve
from .userdata import UserData

STARTED = time.time()
DEFAULT_ORDER = {
    "quotes": ["yahoo", "nasdaq"], "history": ["binance_klines", "yahoo", "nasdaq"], "search": ["yahoo"], "profile": ["yahoo", "nasdaq"],
    "news_top": ["rss"], "news_symbol": ["yahoo_rss", "gdelt"], "news_keyword": ["gdelt"],
    "movers": ["nasdaq"], "crypto": ["coingecko", "binance"],
}
# --- Phase 9 ---
DEFAULT_ORDER.update({"screener": ["nasdaq_screener"], "peers": ["yahoo_peers"]})
MAX_SUBS_PER_CLIENT = 2000
# --- Phase 13: research functions (capability -> providers, keyless first) ---
DEFAULT_ORDER |= {
    "estimates": ["yahoo_research"], "ratings": ["yahoo_research"], "officers": ["yahoo_research"],
    "keystats": ["yahoo_research"], "fund_info": ["yahoo_research"], "corp_events": ["yahoo_research"],
    "dividends": ["nasdaq_research", "yahoo_research"], "splits": ["yahoo_research"], "ipo": ["nasdaq_research"],
    "short_interest": ["nasdaq_research", "yahoo_research"], "short_volume": ["finra"],
    "etf_holdings": ["sec_nport"], "manager_13f": ["sec_13f"],
}
# --- Phase 6: SEC / ownership ---
DEFAULT_ORDER |= {"fundamentals": ["sec"], "filings": ["sec"], "insiders": ["sec", "yahoo_own"], "holders": ["yahoo_own"]}


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
    order = {**DEFAULT_ORDER, **(cfg.get("providers") or {})}
    if settings.openterm_synthetic:
        order = {k: [*v, "synthetic"] if k in ("quotes", "history") else v for k, v in order.items()}
    router = Router(
        providers.build(settings, http, fixtures=settings.openterm_fixtures, synthetic=settings.openterm_synthetic),
        order,
    )
    c = cfg.get("cache") or {}
    cache = Cache(db, max_entries=c.get("lru_entries", 5000))
    service = DataService(router, cache, ttl={
        "quote": c.get("quote_ttl_s", 5), "intraday": c.get("intraday_ttl_s", 60),
        "daily": c.get("daily_ttl_s", 3600), "search": c.get("search_ttl_s", 86400),
        "news": c.get("news_ttl_s", 120), "movers": c.get("movers_ttl_s", 60), "crypto": c.get("crypto_ttl_s", 60),
    })
    # --- Phase 6: SEC / ownership TTLs ---
    service.ttl.update({k: c.get(f"{k}_ttl_s", v) for k, v in service.PHASE6_TTL.items()})

    # --- Phase 13: research functions ---
    from .research.service import Research

    service.research = Research(service)

    # --- Phase 12: imported bars (IMPORT) ---
    service.local = LocalData(db)
    await service.local.load()

    # --- Phase 9 ---
    service.ttl.update({"screener": c.get("screener_ttl_s", 900), "peers": c.get("peers_ttl_s", 86400)})

    # Streaming: one upstream subscription per symbol, whatever the number of clients and panels.
    hub_ref: list[Hub] = []

    def emit(tick):
        hub_ref[0].emit(tick)

    yahoo = NullStream() if settings.openterm_fixtures else YahooStream(emit)
    poller = Poller(emit, service.quotes, active=lambda: yahoo.status != "OK" and not settings.openterm_fixtures)
    synthetic = SyntheticStream(emit, settings.openterm_synthetic_tps) if settings.openterm_synthetic else None
    hub = Hub(yahoo, poller, synthetic, on_tick=service.apply_tick)
    hub_ref.append(hub)
    for part in (yahoo, poller, synthetic, hub):
        if part:
            part.start()

    app.state.settings = settings
    app.state.service = service
    app.state.hub = hub
    app.state.userdata = UserData(db)

    # --- Phase 11: key store. Key tests use the fixture transport in fixture mode. ---
    redact.install()
    app.state.keys = store = keys.from_settings(settings)
    keys_http = httpx.AsyncClient(transport=providers.fixture_transport()) if settings.openterm_fixtures else http
    app.state.keys_http = keys_http
    app.state.llm = None  # LLM gateway: built on first use (api.llm_of)
    app.state.bt = None  # BT store: built on first use (api.bt_of)

    def on_key_change(name: str) -> None:
        # Providers built at startup read their key from Settings; a key set in APIKEYS is applied here.
        if name == "fred" and "fred" in router.providers:
            router.providers["fred"]._key = (store.get("fred") or {}).get("FRED_API_KEY") or ""

    app.state.on_key_change = on_key_change

    async def apply_stored_keys() -> None:
        # Keyring-stored keys load after startup so cold start never imports or waits on the keyring.
        await asyncio.sleep(2.0)
        await asyncio.to_thread(on_key_change, "fred")

    key_loader = asyncio.create_task(apply_stored_keys())

    # --- Phase 11: job runner (worker processes start on the first job) ---
    from .jobs.runner import JobRunner
    from .jobs.store import JobStore

    app.state.jobs = jobs = JobRunner(JobStore(db), hub.broadcast, settings.openterm_job_workers)
    sched = scheduler.start(router)
    mount_static(app, settings.openterm_static_dir)  # Phase 10: built frontend (Docker / desktop)
    try:
        yield
    finally:
        sched.shutdown(wait=False)
        key_loader.cancel()
        await asyncio.to_thread(jobs.close)
        if keys_http is not http:
            await keys_http.aclose()
        for part in (hub, synthetic, poller, yahoo):
            if part:
                await part.stop()
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
    """One multiplexed socket per browser. Frames are compact JSON arrays.

    client -> ["sub", [symbols]] | ["unsub", [symbols]] | ["ping", client_ts]
    server -> ["T", [[symbol, price, change, change_pct, volume, high, low, time_ms, src], ...]]
              ["pong", client_ts, server_ts_ms]
              ["J", {id, kind, state, progress, msg, cached}]  (Phase 11 job progress, to every client, <= 10/s/job)
    src: y = Yahoo stream, p = REST poll fallback, s = SYNTHETIC test data.
    """
    await socket.accept()
    hub: Hub = socket.app.state.hub
    client = Client(socket)
    hub.clients.add(client)
    sender = asyncio.create_task(client.sender())
    try:
        while True:
            msg = orjson.loads(await socket.receive_text())
            if not isinstance(msg, list) or not msg:
                continue
            op = msg[0]
            if op == "ping":
                await client.send_json(["pong", msg[1], time.time() * 1000])
            elif op in ("sub", "unsub") and len(msg) > 1 and isinstance(msg[1], list):
                symbols = [resolve(str(s)) for s in msg[1][:MAX_SUBS_PER_CLIENT]]
                if op == "sub":
                    room = MAX_SUBS_PER_CLIENT - len(client.symbols)
                    await hub.subscribe(client, symbols[: max(0, room)])
                else:
                    await hub.unsubscribe(client, symbols)
    except (WebSocketDisconnect, orjson.JSONDecodeError):
        pass
    finally:
        sender.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await sender
        await hub.disconnect(client)


# --- Phase 7: macro ---
DEFAULT_ORDER.update({
    "fred_series": ["fred", "fred_csv"], "fred_search": ["fred"], "yield_curve": ["treasury", "fred_csv"],
    "earnings": ["nasdaq_earnings"], "eco_calendar": ["agency_ics", "fred"],
})

# --- Phase 10: static frontend ---
def mount_static(application: FastAPI, directory: str) -> bool:
    """Serves the built frontend at "/" when OPENTERM_STATIC_DIR is set (Docker, desktop build).

    Mounted from the lifespan so it lands after every API and WebSocket route, whatever order modules
    register them in. Dev mode leaves the setting empty and Vite serves the frontend.
    """
    if not directory:
        return False
    from fastapi.staticfiles import StaticFiles

    path = Path(directory)
    path = path if path.is_absolute() else ROOT / path
    if not (path / "index.html").is_file():
        logging.getLogger(__name__).warning("OPENTERM_STATIC_DIR %s has no index.html; not serving it", path)
        return False
    if any(getattr(r, "name", None) == "frontend" for r in application.router.routes):
        return True  # a second lifespan run (tests) reuses the mount
    application.mount("/", StaticFiles(directory=path, html=True), name="frontend")
    return True
