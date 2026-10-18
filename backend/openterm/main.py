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
from .ai import routes_run
from .ai.routes import router as ai_router
from .api import router as api_router
from .bt.localdata import LocalData
from .cache import Cache
from .config import ROOT, get_settings, load_yaml
from .db import open_db
from .kite_routes import router as kite_router
from .quant_routes import router as quant_router
from .responses import Orjson
from .router import Router
from .service import DataService
from .streaming.hub import Client, Hub
from .streaming.upstream import NullStream, Poller, SyntheticStream, YahooStream
from .symbols import resolve
from .userdata import UserData
from .world_routes import router as world_router

STARTED = time.time()
DEFAULT_ORDER = {
    "quotes": ["yahoo", "nasdaq"], "history": ["binance_klines", "yahoo", "nasdaq"], "search": ["yahoo"], "profile": ["yahoo", "nasdaq"],
    "news_top": ["rss"], "news_symbol": ["yahoo_rss", "gdelt"], "news_keyword": ["gdelt"],
    "movers": ["nasdaq"], "crypto": ["coingecko", "binance"],
}
# --- Phase 9 ---
DEFAULT_ORDER.update({"screener": ["nasdaq_screener"], "peers": ["yahoo_peers"]})
MAX_SUBS_PER_CLIENT = 2000
# --- Phase 19 (capabilities fill in step by step; all keyless) ---
DEFAULT_ORDER["figi"] = ["openfigi"]
DEFAULT_ORDER |= {"holidays": ["nager"], "worldstats": ["worldbank", "dbnomics"], "worldstats_latest": ["worldbank"],
                  "worldstats_countries": ["worldbank"], "worldstats_dbn": ["dbnomics"], "policy_rates": ["policy_rates"]}
DEFAULT_ORDER |= {"weather_geocode": ["openmeteo"], "weather_forecast": ["openmeteo"], "nws_alerts": ["nws"]}
# Step 9: the NSE archive is the LAST history source (Yahoo answers first; it only serves `.NS` at `1d`); AMFI NAV for the SECF fund rows
DEFAULT_ORDER["history"] = [*DEFAULT_ORDER["history"], "nse_archive"]
DEFAULT_ORDER["mfnav"] = ["amfi"]
# --- Phase 13: research functions (capability -> providers, keyless first) ---
DEFAULT_ORDER |= {
    "estimates": ["yahoo_research"], "ratings": ["yahoo_research"], "officers": ["yahoo_research"],
    "keystats": ["yahoo_research"], "fund_info": ["yahoo_research"], "corp_events": ["yahoo_research"],
    "dividends": ["nasdaq_research", "yahoo_research"], "splits": ["yahoo_research"], "ipo": ["nasdaq_research"],
    "short_interest": ["nasdaq_research", "yahoo_research"], "short_volume": ["finra"],
    "etf_holdings": ["sec_nport"], "manager_13f": ["sec_13f"],
}
# --- Phase 13 step 6: keyed sources sit after the keyless ones; inert without a key ---
DEFAULT_ORDER["ratings"] = ["yahoo_research", "finnhub"]
DEFAULT_ORDER["surprises"] = ["yahoo_research", "finnhub"]
DEFAULT_ORDER["news_top"] = ["rss", "finnhub", "alpaca"]
DEFAULT_ORDER["news_symbol"] = ["yahoo_rss", "finnhub", "alpaca", "gdelt"]
# --- Phase 14: option chains (Yahoo first; Tradier is a keyed fallback) ---
DEFAULT_ORDER["option_chain"] = ["yahoo_options", "tradier"]
DEFAULT_ORDER["crypto_options"] = ["deribit"]
# --- Phase 14 step 6: RATES views ---
DEFAULT_ORDER |= {"curve_eur": ["ecb"], "curve_gbp": ["boe"], "curve_cad": ["boc"], "curve_jpy": ["mof"],
                  "credit_spreads": ["fred_oas"], "auctions": ["treasurydirect"]}
# --- Phase 14 step 7: futures, COT, FOMC ---
DEFAULT_ORDER |= {"futures_contract": ["yahoo_futures"], "cot_history": ["cftc"], "cot_markets": ["cftc"], "fomc_dates": ["fomc"]}
# --- Phase 15: Fama-French factors (FACT) ---
DEFAULT_ORDER["factors"] = ["kenfrench"]
# --- Phase 19 step 8: PRED ---
DEFAULT_ORDER |= {"pred_poly": ["polymarket"], "pred_poly_market": ["polymarket"], "pred_poly_history": ["polymarket"],
                  "pred_kalshi": ["kalshi"], "pred_kalshi_market": ["kalshi"], "pred_kalshi_candles": ["kalshi"]}
# --- Phase 19 step 7: crypto depth (Binance first; OKX when Binance fails, e.g. HTTP 451), liquidations (OKX only), DefiLlama ---
DEFAULT_ORDER |= {"crypto_depth": ["binance_deriv", "okx"], "crypto_funding": ["binance_deriv", "okx"], "crypto_funding_detail": ["binance_deriv", "okx"],
                  "crypto_liq": ["okx"], "stablecoins": ["defillama"], "yields": ["defillama"]}
# --- Phase 19: GP event markers ---
DEFAULT_ORDER["earnings_history"] = ["nasdaq_research"]
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
    order["history"] = ["kite", *[n for n in order.get("history", []) if n != "kite"]]  # Phase 15: Kite first, only while logged in
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

    # --- Phase 14: options, rates, futures ---
    from .derivs.service import Derivs

    service.derivs = Derivs(service, settings.openterm_fixtures, db)

    from .rates.service import RatesViews

    service.rates_views = RatesViews(service)

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
    # Phase 13: real-time IEX trades when Alpaca keys are set (APIKEYS); inert and invisible otherwise
    from .streaming.iex import IexPoller

    def prev_close(symbol: str) -> float | None:
        entry = service.cache.mem.get(f"q:{symbol}")
        return ((entry[0].get("data") or {}).get("prev_close")) if entry else None

    alpaca = router.providers.get("alpaca")
    iex = IexPoller(emit, alpaca, prev_close) if alpaca is not None and not settings.openterm_fixtures else None
    # Phase 15: Zerodha Kite Connect (read-only). The key store is built here so the Kite session and ticker exist before the hub.
    from .kite.session import KiteSession
    from .kite.ws import KiteTicker

    store = keys.from_settings(settings)
    kite = router.providers["kite"]
    kite.attach(KiteSession(store), db)
    router.providers["nse_archive"].attach(db)  # Phase 19 step 9: day files are kept in the kv table
    ticker = KiteTicker(emit, kite.session, kite.instruments, prev_close) if not settings.openterm_fixtures else None
    hub = Hub(yahoo, poller, synthetic, on_tick=service.apply_tick, iex=iex, kite=ticker)
    hub_ref.append(hub)
    for part in (yahoo, poller, synthetic, iex, ticker, hub):
        if part:
            part.start()

    app.state.settings = settings
    app.state.service = service
    app.state.hub = hub
    app.state.userdata = UserData(db)

    # --- Phase 11: key store. Key tests use the fixture transport in fixture mode. ---
    redact.install()
    app.state.keys = store
    app.state.kite = kite
    keys_http = httpx.AsyncClient(transport=providers.fixture_transport()) if settings.openterm_fixtures else http
    app.state.keys_http = keys_http
    app.state.llm = None  # LLM gateway: built on first use (api.llm_of)
    app.state.bt = None  # BT store: built on first use (api.bt_of)

    def on_key_change(name: str) -> None:
        # Providers built at startup read their key from Settings; a key set in APIKEYS is applied here.
        if name == "fred" and "fred" in router.providers:
            router.providers["fred"]._key = (store.get("fred") or {}).get("FRED_API_KEY") or ""
        if name in ("finnhub", "alpaca", "tradier") and name in router.providers:  # Phase 13/14: keyed sources
            router.providers[name].set_keys(store.get(name))
        if name == "kite":  # Phase 15: a new key or secret drops the login; the session re-reads the store
            kite.session.reload()

    app.state.on_key_change = on_key_change

    async def apply_stored_keys() -> None:
        # Keyring-stored keys load after startup so cold start never imports or waits on the keyring.
        await asyncio.sleep(2.0)
        for name in ("fred", "finnhub", "alpaca", "tradier"):
            await asyncio.to_thread(on_key_change, name)

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
        for part in (hub, ticker, iex, synthetic, poller, yahoo):
            if part:
                await part.stop()
        await router.providers["nse_archive"].close()
        await cache.flush()
        await http.aclose()
        await db.close()


app = FastAPI(title=APP_NAME, version=__version__, default_response_class=Orjson, lifespan=lifespan)
app.add_middleware(perf.TimingMiddleware)
app.include_router(api_router)
app.include_router(quant_router)
app.include_router(world_router)
app.include_router(kite_router)
app.include_router(ai_router)
app.include_router(routes_run.theses_router)


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
    src: y = Yahoo stream, p = REST poll fallback, a = Alpaca IEX (RT IEX), k = Zerodha Kite ticker (RT KITE), s = SYNTHETIC test data.
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
