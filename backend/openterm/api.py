import asyncio
import contextlib

import orjson
from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from . import keys as keystore
from . import logbuf
from .alert_fired import announce, route_deliver
from .errors import DataError
from .http_util import (
    bt_error,
    data_errors,
    error,
    is_json_type,
    jobs_of,
    json_body,
    json_object,
    key_error,
    loopback,
    svc,
    user,
)
from .providers import keyed_status
from .redact import redact
from .responses import Orjson, OrjsonRoute
from .symbols import resolve
from .userdata import UserDataError

router = APIRouter(prefix="/api", route_class=OrjsonRoute)


@router.get("/quote")
async def quote(request: Request, symbols: str = Query(..., max_length=2000)):
    wanted = [s for s in (x.strip() for x in symbols.split(",")) if s][:200]
    if not wanted:
        return error(DataError("bad_request", "NO SYMBOLS"))
    return {"results": await svc(request).quotes(wanted)}


@router.get("/history")
@data_errors
async def history(request: Request, symbol: str = Query(..., max_length=32), range: str | None = None,
                  interval: str | None = None):
    return await svc(request).history(symbol, range, interval)


@router.get("/history/limits")
async def history_limits(request: Request, symbol: str = Query(..., max_length=32)):
    """How far back each intraday candle length reaches for this symbol, from the best source that can serve it right now
    (so the chart offers only what will work: 5 min over 1 year is fine for a source with deep minute data, not for Yahoo)."""
    return svc(request).router.history_limits(resolve(symbol))


@router.get("/profile")
@data_errors
async def profile(request: Request, symbol: str = Query(..., max_length=32)):
    return await svc(request).profile(symbol)


@router.get("/search")
@data_errors
async def search(request: Request, q: str = Query(..., max_length=64)):
    return await svc(request).search(q)


@router.get("/news")
@data_errors
async def news(
    request: Request,
    symbol: str | None = Query(None, max_length=24),
    q: str | None = Query(None, max_length=100),
    # Feed-table filters (news_tags.py). Any of the four switches NEWS to the pooled curated feeds; `q` then filters them by keywords.
    region: str | None = Query(None, max_length=8),
    sector: str | None = Query(None, max_length=16),
    commodity: str | None = Query(None, max_length=16),
    section: str | None = Query(None, max_length=16),
    limit: int | None = Query(None, ge=1, le=500),
):
    from .news_tags import clean_filters

    f = clean_filters(region, sector, commodity, section, q)
    if f.active and not (f.region or f.sector or f.commodity or f.section):
        f = None  # `q` alone keeps meaning "GDELT keyword search" (the old behaviour)
    return await svc(request).news(symbol, q, f, limit)


@router.get("/movers")
@data_errors
async def movers(request: Request):
    return await svc(request).movers()


@router.get("/crypto")
@data_errors
async def crypto(request: Request, vs: str = Query("USD", max_length=5)):
    return await svc(request).crypto(vs)


@router.get("/resolve")
async def resolve_symbol(symbol: str = Query(..., max_length=32)):
    return {"input": symbol, "symbol": resolve(symbol)}


@router.get("/sources")
async def sources(request: Request):
    s = svc(request)
    return {
        "providers": [{**p, "last_error": redact(p["last_error"])} if p.get("last_error") else p
                      for p in s.router.summary()],
        "keyed": await asyncio.to_thread(keyed_status, request.app.state.settings, request.app.state.keys)
        + [await ollama_row(request)],
        "order": s.router.order,
        "cache": s.stats(),
        "fixtures": request.app.state.settings.openterm_fixtures,
        "synthetic": request.app.state.settings.openterm_synthetic,
        "stream": request.app.state.hub.stats(),
    }


@router.get("/log")
async def log(after: int = 0):
    return {"records": logbuf.since(after)}


@router.get("/layouts")
async def layouts(request: Request):
    return {"layouts": await user(request).layouts()}


@router.get("/layouts/{name}")
async def layout(request: Request, name: str):
    try:
        return await user(request).layout(name)
    except UserDataError as e:
        return error(e)


@router.put("/layouts/{name}")
async def save_layout(request: Request, name: str):
    try:
        return await user(request).save_layout(name, await json_body(request, "state"))
    except UserDataError as e:
        return error(e)


@router.delete("/layouts/{name}")
async def delete_layout(request: Request, name: str):
    try:
        return {"deleted": await user(request).delete_layout(name)}
    except UserDataError as e:
        return error(e)


@router.get("/cmdhistory")
async def cmd_history(request: Request, limit: int = Query(500, ge=1, le=10_000)):
    return {"items": await user(request).history(limit)}


@router.post("/cmdhistory")
async def push_history(request: Request):
    try:
        cmds = await json_body(request, "cmds")
        if not isinstance(cmds, list) or not all(isinstance(c, str) for c in cmds):
            raise UserDataError("bad_request", "cmds MUST BE A LIST OF STRINGS")
        return {"added": await user(request).push_history(cmds[:1000])}
    except UserDataError as e:
        return error(e)


@router.get("/watchlists")
async def watchlists(request: Request):
    return {"watchlists": await user(request).watchlists()}


@router.get("/watchlists/{name}")
async def watchlist(request: Request, name: str):
    try:
        return await user(request).watchlist(name)
    except UserDataError as e:
        return error(e)


@router.put("/watchlists/{name}")
async def save_watchlist(request: Request, name: str):
    try:
        return await user(request).save_watchlist(name, await json_body(request, "symbols"))
    except UserDataError as e:
        return error(e)


@router.patch("/watchlists/{name}")
async def edit_watchlist(request: Request, name: str):
    try:
        body = await json_object(request)
        return await user(request).edit_watchlist(name, body.get("add"), body.get("remove"))
    except UserDataError as e:
        return error(e)


@router.delete("/watchlists/{name}")
async def delete_watchlist(request: Request, name: str):
    try:
        return {"deleted": await user(request).delete_watchlist(name)}
    except UserDataError as e:
        return error(e)


# --- Phase 6: SEC fundamentals / filings / insiders, Yahoo holders ---
@router.get("/fa")
@data_errors
async def fa(request: Request, symbol: str = Query(..., max_length=24), period: str = Query("A", max_length=1)):
    return await svc(request).fundamentals(symbol, period)


# --- Phase 13: research functions (EE, EEO, ANR, MGMT, ...) ---
@router.get("/research/{fn}")
@data_errors
async def research(
    request: Request, fn: str, symbol: str | None = Query(None, max_length=24), month: str | None = Query(None, max_length=7),
    index: str | None = Query(None, max_length=24), manager: str | None = Query(None, max_length=60),
):
    return await svc(request).research.run(fn, symbol=symbol, month=month, index=index, manager=manager)


@router.get("/valuation/{fn}")
@data_errors
async def valuation(request: Request, fn: str, symbol: str | None = Query(None, max_length=24)):
    query = {k: v for k, v in request.query_params.items() if k != "symbol"}
    return await svc(request).research.run_valuation(fn, symbol, query)


# --- Phase 14: options, rates, futures (OMON, PCR, OV, OVDV, SKEW, HIVG, OSA, YAS, SWPM, CDSW, FXFA, WIRP, CT, COT, RATES views) ---
@router.get("/deriv/{fn}")
@data_errors
async def deriv(request: Request, fn: str):
    params = {k.lower(): v for k, v in request.query_params.items()}
    return await svc(request).derivs.run(fn, **params)


# --- Phase 14 step 6: RATES views (the Treasury panel keeps GET /rates) ---
@router.get("/rates/curve")
@data_errors
async def rates_curve(request: Request, ccy: str = Query("", max_length=8), fit: str | None = Query(None, max_length=8)):
    return await svc(request).rates_views.curve(ccy, fit)


@router.get("/rates/spreads")
@data_errors
async def rates_spreads(request: Request):
    return await svc(request).rates_views.spreads()


@router.get("/rates/auctions")
@data_errors
async def rates_auctions(request: Request):
    return await svc(request).rates_views.auctions()


# --- Phase 9: screener (EQS) and peers (COMP) ---
@router.get("/screener")
@data_errors
async def screener(request: Request):
    return await svc(request).screener()


# --- Phase 7: macro ---
@router.get("/fred")
@data_errors
async def fred(request: Request, id: str = Query(..., max_length=40), range: str | None = Query(None, max_length=4)):
    return await svc(request).fred_series(id, range)


@router.get("/filings")
@data_errors
async def filings(
    request: Request, symbol: str = Query(..., max_length=24), form: str | None = Query(None, max_length=20)
):
    return await svc(request).filings(symbol, form)


@router.get("/macro")
@data_errors
async def macro(request: Request, q: str | None = Query(None, max_length=80)):
    return await svc(request).macro(q)


@router.get("/insiders")
@data_errors
async def insiders(request: Request, symbol: str = Query(..., max_length=24)):
    return await svc(request).insiders(symbol)


@router.get("/rates")
@data_errors
async def rates(request: Request):
    return await svc(request).rates()


@router.get("/holders")
@data_errors
async def holders(request: Request, symbol: str = Query(..., max_length=24)):
    return await svc(request).holders(symbol)


@router.get("/earnings")
@data_errors
async def earnings(request: Request, date: str | None = Query(None, max_length=10)):
    return await svc(request).earnings(date)


@router.get("/eco")
@data_errors
async def eco(request: Request, start: str | None = Query(None, max_length=10), days: int = Query(14, ge=1, le=62)):
    return await svc(request).eco(start, days)


# --- Phase 8: portfolios and alerts -----------------------------------------------------------
def portfolios(request: Request):
    from .portfolio import Portfolios

    return Portfolios(user(request).db)


def alerts_store(request: Request):
    from .portfolio import Alerts

    return Alerts(user(request).db)


@router.get("/portfolios")
async def list_portfolios(request: Request):
    return {"portfolios": await portfolios(request).all()}


@router.get("/portfolios/{name}")
async def get_portfolio(request: Request, name: str):
    try:
        return await portfolios(request).get(name)
    except UserDataError as e:
        return error(e)


@router.put("/portfolios/{name}")
async def put_portfolio(request: Request, name: str):
    try:
        body = await json_object(request)
        if "positions" not in body:
            raise UserDataError("bad_request", "BODY NEEDS positions")
        return await portfolios(request).put(name, body["positions"], body.get("base"))
    except UserDataError as e:
        return error(e)


@router.patch("/portfolios/{name}")
async def edit_portfolio(request: Request, name: str):
    try:
        b = await json_object(request)
        return await portfolios(request).edit(name, b.get("add"), b.get("set"), b.get("remove"), b.get("base"))
    except UserDataError as e:
        return error(e)


@router.delete("/portfolios/{name}")
async def delete_portfolio(request: Request, name: str):
    try:
        return {"deleted": await portfolios(request).delete(name)}
    except UserDataError as e:
        return error(e)


def engine_of(request: Request):
    """Phase 20: the server-side alert engine (alerts_engine.py). It owns firing; the routes below keep it in step."""
    return request.app.state.alerts_engine


@router.get("/alerts/engine")
async def alerts_engine_state(request: Request):
    """Engine state for the ALRT panel: running, watched symbols, last tick age, matches it refused to act on (and why)."""
    return engine_of(request).state()


@router.get("/alerts")
async def list_alerts(request: Request):
    return {"alerts": await alerts_store(request).all()}


@router.post("/alerts")
async def create_alert(request: Request):
    try:
        alert = await alerts_store(request).create(await json_object(request))
        await engine_of(request).sync()  # start watching the new alert's symbol
        return alert
    except UserDataError as e:
        return error(e)


@router.delete("/alerts")
async def clear_alerts(request: Request, status: str = Query(...)):
    if status != "triggered":
        return error(UserDataError("bad_request", "ONLY status=triggered CAN BE CLEARED"))
    return {"deleted": await alerts_store(request).clear_triggered()}


@router.delete("/alerts/{alert_id}")
async def delete_alert(request: Request, alert_id: int):
    try:
        deleted = await alerts_store(request).delete(alert_id)
        await engine_of(request).sync()  # stop watching a symbol nobody needs any more
        return {"deleted": deleted}
    except UserDataError as e:
        return error(e)


@router.post("/alerts/{alert_id}/trigger")
async def trigger_alert(request: Request, alert_id: int):
    try:
        body = await json_object(request)
        result = await alerts_store(request).trigger(alert_id, body.get("price"), body.get("at"))
        await engine_of(request).sync()
        # Phase 20: the server engine fires real data itself. This route is used by a browser only for labelled test data
        # (SYNTHETIC ticks, fixture mode), which must never be pushed to a phone: the browser says so with `synthetic`.
        # Exactly once per firing (`changed`), pushed to email/Telegram/webhook in the background by the shared fired path.
        # No `broadcast` here: the calling browser already knows; only the engine pushes an `A` frame.
        if not body.get("synthetic"):
            announce("alert", result, route_deliver(request.app))
        return result
    except UserDataError as e:
        return error(e)


@router.post("/alerts/{alert_id}/rearm")
async def rearm_alert(request: Request, alert_id: int):
    try:
        alert = await alerts_store(request).rearm(alert_id)
        await engine_of(request).sync()  # a rearmed alert is active again: watch its symbol
        return alert
    except UserDataError as e:
        return error(e)


# --- Phase 13: news keyword alerts (ALRT NEWS WORD [SYM]); evaluated in the browser on each news refresh ---
def news_alerts_store(request: Request):
    from .news_alerts import NewsAlerts

    return NewsAlerts(user(request).db)


@router.get("/newsalerts")
async def list_news_alerts(request: Request):
    return {"alerts": await news_alerts_store(request).all()}


@router.post("/newsalerts")
async def create_news_alert(request: Request):
    try:
        return await news_alerts_store(request).create(await json_object(request))
    except UserDataError as e:
        return error(e)


@router.delete("/newsalerts")
async def clear_news_alerts(request: Request, status: str = Query(...)):
    if status != "triggered":
        return error(UserDataError("bad_request", "ONLY status=triggered CAN BE CLEARED"))
    return {"deleted": await news_alerts_store(request).clear_triggered()}


@router.delete("/newsalerts/{alert_id}")
async def delete_news_alert(request: Request, alert_id: int):
    try:
        return {"deleted": await news_alerts_store(request).delete(alert_id)}
    except UserDataError as e:
        return error(e)


@router.post("/newsalerts/{alert_id}/trigger")
async def trigger_news_alert(request: Request, alert_id: int):
    try:
        body = await json_object(request)
        result = await news_alerts_store(request).trigger(alert_id, body.get("headline"), body.get("url"), body.get("at"))
        announce("news", result, route_deliver(request.app))  # same fired path as the engine, minus its `A` frame
        return result
    except UserDataError as e:
        return error(e)


@router.post("/newsalerts/{alert_id}/rearm")
async def rearm_news_alert(request: Request, alert_id: int):
    try:
        return await news_alerts_store(request).rearm(alert_id)
    except UserDataError as e:
        return error(e)


@router.get("/peers")
@data_errors
async def peers(request: Request, symbol: str = Query(..., max_length=24)):
    return await svc(request).peers(symbol)


# --- Phase 10: settings ---
@router.get("/settings")
async def get_settings_doc(request: Request):
    from .settings_store import SettingsStore

    return await SettingsStore(user(request).db).get()


@router.put("/settings")
async def put_settings_doc(request: Request):
    from .settings_store import VERSION, SettingsStore

    try:
        body = await json_object(request)
        if "settings" not in body:
            raise UserDataError("bad_request", "BODY NEEDS settings")
        return await SettingsStore(user(request).db).put(body["settings"], body.get("version", VERSION))
    except UserDataError as e:
        return error(e)


# --- Phase 19: GP drawings (kv, per symbol) ---
@router.get("/drawings/{symbol}")
async def drawings_get(request: Request, symbol: str):
    from .drawings import DrawingsStore

    try:
        return await DrawingsStore(user(request).db).get(symbol)
    except UserDataError as e:
        return error(e)


@router.put("/drawings/{symbol}")
async def drawings_put(request: Request, symbol: str):
    from .drawings import DrawingsStore

    try:
        body = await json_object(request)
        if "drawings" not in body:
            raise UserDataError("bad_request", "BODY NEEDS drawings")
        return await DrawingsStore(user(request).db).put(symbol, body["drawings"])
    except UserDataError as e:
        return error(e)


# --- Indicator library presets (kv `ind_presets`) ---
@router.get("/indicator-presets")
async def ind_presets_list(request: Request):
    from .indicator_presets import PresetStore

    return Orjson({"presets": await PresetStore(user(request).db).list()})


@router.get("/indicator-presets/{name}")
async def ind_presets_get(request: Request, name: str):
    from .indicator_presets import PresetStore

    try:
        return Orjson(await PresetStore(user(request).db).get(name))
    except UserDataError as e:
        return error(e)


@router.put("/indicator-presets/{name}")
async def ind_presets_put(request: Request, name: str):
    from .indicator_presets import PresetStore

    try:
        body = await json_object(request)
        if "items" not in body:
            raise UserDataError("bad_request", "BODY NEEDS items")
        return Orjson(await PresetStore(user(request).db).put(name, body["items"]))
    except UserDataError as e:
        return error(e)


@router.delete("/indicator-presets/{name}")
async def ind_presets_delete(request: Request, name: str):
    from .indicator_presets import PresetStore

    try:
        return Orjson(await PresetStore(user(request).db).delete(name))
    except UserDataError as e:
        return error(e)


# --- Phase 11: key store (APIKEYS). Values go in, never out. ---
def key_row(st: dict) -> dict:
    spec = keystore.KEY_SPECS[st["name"]]
    return {**st, "fields": list(spec.fields), "purpose": spec.purpose, "phase": spec.phase, "signup": spec.signup}


def keys_of(request: Request) -> keystore.KeyStore:
    return request.app.state.keys


@router.get("/keys")
async def keys_list(request: Request):
    rows = await asyncio.to_thread(keys_of(request).statuses)
    return {"keys": [key_row(r) for r in rows], "spend": await llm_of(request).spend_status()}


async def _test(request: Request, name: str) -> dict:
    st = await keystore.run_test(keys_of(request), name, request.app.state.keys_http,
                                 fixtures=request.app.state.settings.openterm_fixtures)
    request.app.state.on_key_change(name)
    return key_row(st)


@router.put("/keys/{name}")
async def keys_put(request: Request, name: str):
    if not loopback(request):
        return key_error("forbidden", "KEYS CAN ONLY BE CHANGED FROM THIS MACHINE")
    if name not in keystore.KEY_SPECS:
        return key_error("unknown_provider", f"UNKNOWN PROVIDER {name.upper()}")
    if not is_json_type(request):
        return key_error("bad_request", "CONTENT-TYPE MUST BE application/json")
    try:
        body = orjson.loads(await request.body())
    except orjson.JSONDecodeError:
        body = None
    if not isinstance(body, dict) or not isinstance(body.get("fields"), dict):
        return key_error("bad_request", "BODY MUST BE {fields: {ENV_NAME: value}}")
    try:
        await asyncio.to_thread(keys_of(request).set, name, body["fields"])
    except keystore.KeyStoreError as e:
        return key_error(e.kind, str(e))
    return await _test(request, name)


@router.post("/keys/{name}/test")
async def keys_test(request: Request, name: str):
    if name not in keystore.KEY_SPECS:
        return key_error("unknown_provider", f"UNKNOWN PROVIDER {name.upper()}")
    return await _test(request, name)


@router.delete("/keys/{name}")
async def keys_delete(request: Request, name: str):
    if not loopback(request):
        return key_error("forbidden", "KEYS CAN ONLY BE CHANGED FROM THIS MACHINE")
    try:
        await asyncio.to_thread(keys_of(request).delete, name)
    except keystore.KeyStoreError as e:
        return key_error(e.kind, str(e))
    request.app.state.on_key_change(name)
    return key_row(await asyncio.to_thread(keys_of(request).status, name))


# --- Phase 11: background jobs ---
@router.post("/jobs")
async def jobs_submit(request: Request):
    from .jobs.kinds import BadParams

    try:
        body = await json_object(request)
    except UserDataError as e:
        return error(e)
    try:
        return await jobs_of(request).submit(str(body.get("kind", "")), body.get("params", {}))
    except BadParams as e:
        return error(DataError("bad_request", str(e)))


@router.get("/jobs")
async def jobs_list(request: Request):
    return {"jobs": await jobs_of(request).list()}


@router.get("/jobs/{job_id}")
async def jobs_get(request: Request, job_id: str):
    job = await jobs_of(request).get(job_id)
    return job if job else error(DataError("not_found", "NO SUCH JOB"))


@router.delete("/jobs/{job_id}")
async def jobs_cancel(request: Request, job_id: str):
    job = jobs_of(request).cancel(job_id)
    if job is None:
        return error(DataError("not_found", "JOB IS NOT RUNNING"))
    return job


@router.delete("/jobs")
async def jobs_clear(request: Request, state: str = "finished"):
    if state != "finished":
        return error(DataError("bad_request", "ONLY state=finished CAN BE CLEARED"))
    return {"cleared": await jobs_of(request).clear_finished()}


# --- Phase 11: LLM gateway (no AI functions yet: health, spend and the cap) ---
def llm_of(request: Request):
    """The gateway is built on first use, so cold start never imports it."""
    app = request.app
    if getattr(app.state, "llm", None) is None:
        from .llm.client import Gateway

        app.state.llm = Gateway(app.state.keys, app.state.keys_http, user(request).db,
                                app.state.settings.yaml.get("llm") or {})
    return app.state.llm


async def ollama_row(request: Request) -> dict:
    state, detail = await llm_of(request).ollama_status()
    return {"name": "ollama", "status": state, "note": f"Local AI models, no key. {detail}"}


@router.get("/llm/health")
async def llm_health(request: Request):
    return await llm_of(request).health()


@router.put("/llm/cap")
async def llm_cap(request: Request):
    from .llm import spend

    if not loopback(request):
        return key_error("forbidden", "THE SPEND CAP CAN ONLY BE CHANGED FROM THIS MACHINE")
    try:
        body = await json_object(request)
    except UserDataError as e:
        return error(e)
    cap = body.get("cap")
    if isinstance(cap, bool) or not isinstance(cap, int | float) or not 0 <= cap <= spend.MAX_CAP:
        return key_error("bad_request", f"CAP MUST BE A NUMBER FROM 0 TO {spend.MAX_CAP:.0f} (US$ PER DAY)")
    await spend.set_cap(user(request).db, round(float(cap), 2))
    return await llm_of(request).spend_status()

# --- Phase 12: backtester (BT). The server parses and checks; bars are fetched here; the job runs in a worker. ---
BT_HEADLINE = "HISTORICAL SIMULATION, NOT A FORECAST"


def bt_of(request: Request):
    """BtStore, built on first use; also registers the bt.run on-done hook (stores the run before 'done' shows)."""
    app = request.app
    if getattr(app.state, "bt", None) is None:
        from pathlib import Path

        from .bt.store import CARD_METRICS, BtStore

        db_path = app.state.settings.openterm_db_path
        data_dir = (Path(db_path).parent if db_path != ":memory:" else Path("data")) / "bt_data"
        store = BtStore(user(request).db, data_dir)

        async def on_done(job: dict, result: dict) -> dict:
            p = job["params"]
            await store.save_run(result, p["meta"], p["config"], p["data_sha"], job["hash"])
            try:  # the audit ledger records every BT run (hashes only); a ledger failure never loses the run
                from . import __version__
                from .ai.audit import audit_of, canonical, sha

                await audit_of(app, user(request).db).append(
                    "bt", result["run_id"], "-", {"app": __version__, "engine": "bt"},
                    {"job_hash": job["hash"], "data_sha": p["data_sha"], "config_sha": sha(canonical(p["config"])), "metrics": {k: result["metrics"].get(k) for k in CARD_METRICS}})
            except Exception:
                import logging

                logging.getLogger("openterm.api").exception("audit ledger entry for a BT run failed")
            return {"run_id": result["run_id"], "metrics": {k: result["metrics"].get(k) for k in CARD_METRICS}}

        jobs_of(request).on_done["bt.run"] = on_done
        app.state.bt = store
    return app.state.bt


def _opt_num(opts: dict, key: str, lo: float, hi: float, default=None):
    v = opts.get(key, default)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int | float) or not lo <= v <= hi:
        from .bt.store import BtError

        raise BtError("bad_request", f"OPTION {key.upper()} MUST BE A NUMBER {lo:g}-{hi:g}")
    return v


async def _bt_params(request: Request, body: dict) -> dict:
    import hashlib

    from .bt import catalog, rules, sandbox
    from .bt.store import BtError

    syms = body.get("symbols")
    if not isinstance(syms, list) or not 1 <= len(syms) <= 100 or not all(isinstance(s, str) and s.strip() for s in syms):
        raise BtError("bad_request", "SYMBOLS MUST BE A LIST OF 1-100 SYMBOLS")
    symbols = list(dict.fromkeys(resolve(s.strip().upper()) for s in syms))
    interval = str(body.get("interval") or "1D").upper()
    if interval not in rules.INTERVALS:
        raise BtError("bad_request", f"BT INTERVAL MUST BE {' OR '.join(rules.INTERVALS)}")
    range_ = str(body.get("range") or "5Y").upper()
    opts = body.get("options") or {}
    if not isinstance(opts, dict):
        raise BtError("bad_request", "OPTIONS MUST BE AN OBJECT")
    cash = _opt_num(opts, "cash", 1, 1e12, 100_000)
    fees = _opt_num(opts, "fees_bps", 0, 1000, 0)
    slip = _opt_num(opts, "slip_bps", 0, 1000)
    limit_s = _opt_num(opts, "time_limit_s", 1, 60, 60)
    mem_mb = _opt_num(opts, "memory_limit_mb", 64, 1024, 1024)
    warmup = _opt_num(opts, "warmup_bars", 0, 10_000)
    short, adjusted = bool(opts.get("short", False)), bool(opts.get("adjusted", True))
    bench = opts.get("bench")
    if bench is not None and (not isinstance(bench, str) or not bench.strip()):
        raise BtError("bad_request", "OPTION BENCH MUST BE A SYMBOL")

    is_opt = str(opts.get("engine") or "").lower() == "options"
    structure = None
    sources = [k for k in ("rule", "code", "strategy") if body.get(k)]
    if is_opt:  # MKT=options: an OSA structure replaces the rule (decision N)
        structure = body.get("structure")
        miss = catalog.options_missing(structure)
        if len(symbols) != 1:
            miss.insert(0, "symbols (exactly one underlying)")
        if miss:
            raise BtError("bad_request", "NOT RUNNABLE: MISSING " + ", ".join(miss))
        if structure["exercise_style"] not in catalog.OPTIONS_STYLES:
            raise BtError("bad_request", f"NOT RUNNABLE: exercise_style MUST BE {' OR '.join(catalog.OPTIONS_STYLES)}")
        if sources or short or slip is not None:
            raise BtError("bad_request", "OPTIONS TAKES A STRUCTURE ONLY (NO RULE, CODE, SHORT OR SLIP)")
        structure = {k: structure[k] for k in ("legs", "open_date", "close_date", "risk_free_rate", "contract_multiplier",
                                               "exercise_style") if structure.get(k) not in (None, "")}
        sources = ["structure"]
    elif len(sources) != 1:
        raise BtError("bad_request", "SEND EXACTLY ONE OF RULE, CODE OR STRATEGY")
    rule = code = None
    strategy = None
    if is_opt:
        pass
    elif body.get("rule"):
        rule = str(body["rule"])
        rules.parse(rule)
    else:
        if body.get("strategy"):
            saved = await bt_of(request).strategy(str(body["strategy"]))
            strategy = saved["name"]
            rule, code = (saved["code"], None) if saved["kind"] == "rule" else (None, saved["code"])
        else:
            code = str(body["code"])
        if code is not None:
            try:
                sandbox.check(code)
            except sandbox.SandboxError as e:
                raise BtError("bad_request", "STRATEGY REJECTED", detail=str(e)) from None
        else:
            rules.parse(rule)

    engine = catalog.engine_for(symbols, opts.get("engine"))
    if engine not in catalog.BUILT:
        raise BtError("bad_request", f"ENGINE {engine.upper()} IS NOT BUILT (HAVE {', '.join(sorted(catalog.BUILT)).upper()})")
    if slip is not None and engine == "forex":
        raise BtError("bad_request", "SLIP DOES NOT APPLY TO FOREX (ITS COST IS A SPREAD AND SLIPPAGE IN PIPS)")

    s = svc(request)
    wanted = symbols + ([resolve(bench.strip().upper())] if bench else [])
    results = await asyncio.gather(*(s.history(x, range_, interval) for x in wanted), return_exceptions=True)
    for sym, r in zip(wanted, results, strict=True):
        if isinstance(r, DataError):
            raise DataError(r.kind, f"{sym}: {r}") from None
        if isinstance(r, BaseException):
            raise r
    envs = dict(zip(wanted, results, strict=True))
    payload = {"bars": {x: envs[x]["data"] for x in symbols}, "bench": envs[wanted[-1]]["data"] if bench else None,
               "bench_symbol": wanted[-1] if bench else None}
    store = bt_of(request)
    sha, path = await asyncio.to_thread(store.write_data, payload)

    config: dict = {"initial_cash": float(cash)}
    if is_opt:
        config.update(codes=symbols, commission=fees / 1e4, options_config={
            k: structure[k] for k in ("risk_free_rate", "contract_multiplier", "exercise_style")})
    if slip is not None:
        for key in catalog.SLIPPAGE_KEYS.get(engine, ()):
            config[key] = slip / 1e4
    if engine in ("crypto", "composite"):
        config["interval"] = interval  # sets how many 8-hour funding settlements one bar spans
        config["funding_rate"] = 0.0  # spot has no funding; perpetual bars carry their own recorded rate
    if fees:
        config["fees_bps"] = fees
    if warmup:
        config["warmup_bars"] = int(warmup)
    fixtures = request.app.state.settings.openterm_fixtures
    labels = {
        "headline": BT_HEADLINE, "engine": engine, "fees_bps": fees or 0,
        "slip_bps": slip if slip is not None else catalog.DEFAULT_SLIP_BPS.get(engine, 0), "costs": catalog.COSTS.get(engine, ""),
        "warmup_bars": int(warmup or 0), "short": short, "prices": "ADJ" if adjusted else "RAW",
        "sources": [{"symbol": x, "name": envs[x].get("source"), "as_of": envs[x].get("as_of"),
                     "age_s": envs[x].get("age_s"), "stale": envs[x].get("stale", False)} for x in wanted],
        "benchmark": wanted[-1] if bench else "EQUAL-WEIGHT BUY AND HOLD OF THE TRADED SYMBOLS",
        **({"model": catalog.OPTIONS_LABEL, "commission": f"FEES= {fees or 0:g} BPS OF PREMIUM", "slippage": "NONE MODELLED",
            "default_iv": 0.3, "iv_note": "HISTORICAL VOL (30 BARS); 0.30 UNTIL A FULL WINDOW EXISTS"} if is_opt else {}),
        "data_note": " ".join(n for n in (
            "RECORDED FIXTURE DATA" if fixtures else "",
            "LOCAL DATA (IMPORTED BY YOU, NOT FROM A MARKET SOURCE)" if any(
                str(envs[x].get("source")) == "local" for x in wanted) else "") if n),
    }
    meta = {"rule": rule, "strategy": strategy, "code": code, "symbols": symbols, "interval": interval,
            "range": range_, "engine": engine, "short": short, "bench": wanted[-1] if bench else None,
            **({"structure": structure} if is_opt else {})}
    params = {"data_path": str(path), "data_sha": sha, "short": short, "engine": engine, "config": config,
              "bars_per_year": catalog.bars_per_year(engine, interval),
              "adjusted": adjusted, "time_limit_s": limit_s, "memory_limit_mb": int(mem_mb), "labels": labels,
              "meta": meta, **({"structure": structure} if is_opt else {"rule": rule} if rule else {"code": code})}
    stable = {k: v for k, v in params.items() if k != "labels"}  # labels carry data age: not part of the identity
    params["run_id"] = hashlib.sha256(orjson.dumps(stable, option=orjson.OPT_SORT_KEYS)).hexdigest()[:16]
    return params


@router.post("/bt/run")
async def bt_run(request: Request):
    from .bt.rules import RuleError
    from .bt.store import BtError

    try:
        params = await _bt_params(request, await json_object(request))
    except (BtError, RuleError) as e:
        return bt_error(e)
    except (DataError, UserDataError) as e:
        return error(e)
    jobs, store = jobs_of(request), bt_of(request)
    if not await store.has_run(params["run_id"]):  # a deleted or trimmed run must not come back from the job cache
        await jobs.forget(jobs.hash_for("bt.run", params))
    # run_id is known before the job runs. A cached answer also carries the stored run, so opening it costs no
    # second request.
    job = {**await jobs.submit("bt.run", params, internal=True), "run_id": params["run_id"]}
    if job.get("state") == "done":
        with contextlib.suppress(BtError):
            job["run"] = await store.run(params["run_id"])
    return Orjson(job)  # a Response skips FastAPI's jsonable_encoder walk over every equity point


@router.get("/bt/runs")
async def bt_runs(request: Request):
    return {"runs": await bt_of(request).runs()}


@router.get("/bt/runs/{run_id}")
async def bt_run_get(request: Request, run_id: str):
    from .bt.store import BtError

    try:
        return Orjson(await bt_of(request).run(run_id))  # skips jsonable_encoder (see bt_run)
    except BtError as e:
        return bt_error(e)


def _val_int(body: dict, key: str, lo: int, hi: int, default: int) -> int:
    v = body.get(key, default)
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        from .bt.store import BtError

        raise BtError("bad_request", f"{key.upper()} MUST BE AN INTEGER {lo}-{hi}")
    return v


async def _bt_validate(request: Request, run_id: str, kind: str):
    """Copy the stored run into the params of a bt.mc / bt.wf job and submit it."""
    from .bt import catalog
    from .bt.store import BtError

    try:
        body = await json_object(request)
        run = await bt_of(request).run(run_id)
        common = {"run_id": run_id, "initial_cash": float(run["config"].get("initial_cash", 100_000)),
                  "bars_per_year": catalog.bars_per_year(run["engine"], str(run["interval"] or "1D")),
                  "equity": run["equity"], "trades": run["trades"], "labels": run["labels"] or {}}
        if kind == "bt.mc":
            conf = body.get("confidence", 0.95)
            if isinstance(conf, bool) or not isinstance(conf, int | float) or not 0.5 <= conf <= 0.999:
                raise BtError("bad_request", "CONFIDENCE MUST BE A NUMBER 0.5-0.999")
            params = {**common, "n_simulations": _val_int(body, "n_simulations", 100, 10_000, 1000),
                      "n_bootstrap": _val_int(body, "n_bootstrap", 100, 10_000, 1000), "confidence": float(conf),
                      "seed": _val_int(body, "seed", 0, 2**31 - 1, 42)}
        else:
            params = {**common, "n_windows": _val_int(body, "n_windows", 2, 12, 5)}
    except BtError as e:
        return bt_error(e)
    except UserDataError as e:
        return error(e)
    return Orjson(await jobs_of(request).submit(kind, params, internal=True))


@router.post("/bt/runs/{run_id}/mc")
async def bt_run_mc(request: Request, run_id: str):
    return await _bt_validate(request, run_id, "bt.mc")


@router.post("/bt/runs/{run_id}/wf")
async def bt_run_wf(request: Request, run_id: str):
    return await _bt_validate(request, run_id, "bt.wf")


def local_of(request: Request):
    return svc(request).local


@router.post("/bt/import")
async def bt_import(request: Request, symbol: str = ""):
    """Body: the CSV text (date,open,high,low,close[,volume]). Replaces any earlier import of the symbol."""
    from .bt import csvimport
    from .bt.store import BtError

    try:
        sym = csvimport.symbol_name(symbol)
        raw = await request.body()
        if len(raw) > 20_000_000:
            raise BtError("too_large", "CSV IS OVER 20 MB")
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise BtError("bad_request", "CSV REJECTED", detail="THE FILE IS NOT UTF-8 TEXT") from None
        try:
            cols = csvimport.parse_bars(text)
        except csvimport.CsvError as e:
            raise BtError("bad_request", "CSV REJECTED", detail=str(e)) from None
    except csvimport.CsvError as e:
        return bt_error(BtError("bad_request", str(e)))
    except BtError as e:
        return bt_error(e)
    return await local_of(request).save(sym, cols)


@router.get("/bt/import")
async def bt_import_list(request: Request):
    return {"symbols": await local_of(request).listing()}


@router.delete("/bt/import/{symbol}")
async def bt_import_delete(request: Request, symbol: str):
    from .bt.store import BtError

    if not await local_of(request).delete(symbol.strip().upper()):
        return bt_error(BtError("not_found", f"NO LOCAL DATA FOR {symbol.upper()}"))
    return {"deleted": symbol.upper()}


@router.get("/bt/runs/{run_id}/export")
async def bt_run_export(request: Request, run_id: str, fmt: str = "csv", part: str = "trades"):
    from .bt import export
    from .bt.store import BtError

    try:
        run = await bt_of(request).run(run_id)
        if fmt == "csv":
            if part not in export.PARTS:
                raise BtError("bad_request", f"PART MUST BE {', '.join(export.PARTS).upper()}")
            body, name = export.run_csv(run, part), f"BT_{run_id}_{part}.csv"
        elif fmt == "pine":
            if not run.get("rule"):
                raise BtError("bad_request", "PINE EXPORT NEEDS A RULE STRATEGY",
                              detail="PYTHON STRATEGIES CANNOT BE TRANSLATED FAITHFULLY: EXPORT CSV, OR WRITE IT AS A RULE")
            lab = run["labels"] or {}
            body = export.pine_script(run["rule"], short=bool(lab.get("short")), cash=float(run["config"].get("initial_cash", 100_000)),
                                      fees_bps=float(lab.get("fees_bps") or 0), symbols=run["symbols"], interval=str(run["interval"]))
            name = f"BT_{run_id}.pine"
        else:
            raise BtError("bad_request", "FMT MUST BE CSV OR PINE")
    except BtError as e:
        return bt_error(e)
    return Response(body, media_type="text/plain; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/bt/compare")
async def bt_compare(request: Request, a: str = "", b: str = ""):
    from .bt.store import BtError

    try:
        if not a or not b:
            raise BtError("bad_request", "COMPARE NEEDS TWO RUN IDS (a= AND b=)")
        ra, rb = await bt_of(request).run(a), await bt_of(request).run(b)
    except BtError as e:
        return bt_error(e)
    num = lambda v: isinstance(v, int | float) and not isinstance(v, bool)
    diff = {k: rb["metrics"][k] - v for k, v in ra["metrics"].items() if num(v) and num(rb["metrics"].get(k))}
    return Orjson({"a": ra, "b": rb, "diff": diff})  # b minus a


@router.delete("/bt/runs/{run_id}")
async def bt_run_delete(request: Request, run_id: str):
    from .bt.store import BtError

    try:
        h = await bt_of(request).delete_run(run_id)
    except BtError as e:
        return bt_error(e)
    if h:
        await jobs_of(request).forget(h)
    return {"deleted": run_id}


@router.get("/bt/strategies")
async def bt_strategies(request: Request):
    return {"strategies": await bt_of(request).strategies()}


@router.get("/bt/templates")
async def bt_templates():
    # Starter strategies for the editor (plain text, see bt/templates.py).
    from .bt.templates import TEMPLATES

    return {"templates": TEMPLATES}


@router.post("/bt/check")
async def bt_check(request: Request):
    """Dry-run the sandbox check on editor text. Saves nothing and runs nothing, so any caller may use it.
    A rejected strategy is still HTTP 200 with ok=false: the text is a normal answer, not a failed request."""
    from .bt import sandbox
    from .bt.store import BtError

    try:
        body = await json_object(request)
        code = body.get("code")
        if not isinstance(code, str):
            raise BtError("bad_request", "CODE MUST BE A STRING")
    except BtError as e:
        return bt_error(e)
    except UserDataError as e:
        return error(e)
    try:
        sandbox.check(code)
    except sandbox.SandboxError as e:
        return {"ok": False, "error": redact(str(e))}
    return {"ok": True}


@router.get("/bt/strategies/{name}")
async def bt_strategy_get(request: Request, name: str):
    from .bt.store import BtError

    try:
        return await bt_of(request).strategy(name)
    except BtError as e:
        return bt_error(e)


@router.put("/bt/strategies/{name}")
async def bt_strategy_put(request: Request, name: str):
    from .bt import rules, sandbox
    from .bt.store import BtError

    if not loopback(request):
        return key_error("forbidden", "STRATEGIES CAN ONLY BE CHANGED FROM THIS MACHINE")
    try:
        body = await json_object(request)
        if isinstance(body.get("rule"), str) and body["rule"].strip():
            rules.parse(body["rule"])
            return await bt_of(request).put_strategy(name, body["rule"].strip(), "rule")
        code = body.get("code")
        try:
            sandbox.check(code)
        except sandbox.SandboxError as e:
            raise BtError("bad_request", "STRATEGY REJECTED", detail=str(e)) from None
        return await bt_of(request).put_strategy(name, code, "python")
    except (BtError, rules.RuleError) as e:
        return bt_error(e)
    except UserDataError as e:
        return error(e)


@router.delete("/bt/strategies/{name}")
async def bt_strategy_delete(request: Request, name: str):
    from .bt.store import BtError

    if not loopback(request):
        return key_error("forbidden", "STRATEGIES CAN ONLY BE CHANGED FROM THIS MACHINE")
    try:
        await bt_of(request).delete_strategy(name)
    except BtError as e:
        return bt_error(e)
    return {"deleted": name}
