"""Phase 26 strategy lab routes: the optimiser (`POST /api/bt/opt`) and paper forward tests (`/api/bt/fwd`).

Both reuse the backtester's request builder (`api._bt_params`), so an optimisation runs on exactly the bars, costs, stops and
labels a BT run of the same command would. The heavy work runs in job workers (`bt.opt`, `bt.fwdsig`); this module only
validates, writes the data file and keeps the forward tests' small state in the `kv` table (key `btfwd:<id>`, no migration).

Forward tests are play money in OpenTerm's own book (`bt/fwd.py`): nothing here reaches a broker or ORD (NO LIVE ORDERS).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid
from types import SimpleNamespace

import orjson
from fastapi import APIRouter, Request

from .api import _bt_params, bt_of
from .bt import fwd, optspace
from .errors import DataError
from .http_util import bt_error, error, jobs_of, json_object, svc
from .redact import redact
from .responses import Orjson, OrjsonRoute
from .symbols import resolve
from .userdata import UserDataError

log = logging.getLogger("openterm.btlab")
router = APIRouter(prefix="/api/bt", route_class=OrjsonRoute)

FITS = ("SHARPE", "SORTINO", "CALMAR", "PF", "NET", "RETURN")
KV_PREFIX = "btfwd:"
MAX_FWD = 50  # forward tests kept at once (active or stopped)
FWD_EVERY_MIN = 15  # the scheduler's check interval while the server runs


def _int(body: dict, key: str, lo: int, hi: int, default: int) -> int:
    from .bt.store import BtError

    v = body.get(key, default)
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise BtError("bad_request", f"{key.upper()} MUST BE AN INTEGER {lo}-{hi}")
    return v


# --- optimiser ---------------------------------------------------------------------------------------------------------

@router.post("/opt")
async def bt_opt(request: Request):
    """Body: the BT run body (symbols, interval, range, options) + `rule` (with ranges) or `strategy` (+ `ranges`
    {NAME: "{lo..hi:step}"} for a Python strategy), `method` GRID|RANDOM|GA, `n`, `pop`, `gen`, `seed`, `fit`, `wf`, `anchored`."""
    from .bt.rules import RuleError
    from .bt.store import BtError

    try:
        body = await json_object(request)
        strategy = None
        if body.get("strategy"):
            saved = await bt_of(request).strategy(str(body["strategy"]))
            strategy = saved["name"]
            if saved["kind"] == "rule":
                raise BtError("bad_request", f"@{strategy} IS A SAVED RULE: WRITE THE RULE WITH RANGES, E.G. BT OPT AAPL SMA{{10..50:5}}>SMA{{50..200:25}}")
            ranges = body.get("ranges") or {}
            if not isinstance(ranges, dict) or not ranges:
                raise BtError("bad_request", f"GIVE THE RANGES OF @{strategy}'S CONSTANTS, E.G. BT OPT AAPL @{strategy} FAST={{10..50:5}}")
            template, kind = optspace.code_template(saved["code"], {str(k).upper(): str(v) for k, v in ranges.items()}), "code"
        elif body.get("rule"):
            template, kind = str(body["rule"]), "rule"
        else:
            raise BtError("bad_request", "SEND A RULE WITH RANGES OR A SAVED PYTHON STRATEGY WITH RANGES")
        parts, space = optspace.parse(template)
        method = str(body.get("method") or "GRID").upper()
        if method not in optspace.METHODS:
            raise BtError("bad_request", f"METHOD MUST BE {' OR '.join(optspace.METHODS)}")
        fit = str(body.get("fit") or "SHARPE").upper()
        if fit not in FITS:
            raise BtError("bad_request", f"FIT MUST BE {' OR '.join(FITS)}")
        n, pop, gen = _int(body, "n", 2, optspace.GRID_CAP, 200), _int(body, "pop", 4, 200, 40), _int(body, "gen", 1, 100, 25)
        if method == "GA" and pop * gen > optspace.GRID_CAP:
            raise BtError("bad_request", f"POP x GEN IS {pop * gen:,}, AT MOST {optspace.GRID_CAP:,} BACKTESTS")
        seed, wf = _int(body, "seed", 0, 2**31 - 1, 1), _int(body, "wf", 0, 12, 0)
        budget = optspace.search_size(method, space, n, pop, gen)
        first = optspace.render(parts, space, tuple(0 for _ in space))  # validates the template with real values
        base = {k: body[k] for k in ("symbols", "interval", "range", "options") if k in body}
        base["rule" if kind == "rule" else "code"] = first
        p = await _bt_params(request, base)
    except optspace.SpaceError as e:
        return bt_error(BtError("bad_request", str(e)))
    except (BtError, RuleError) as e:
        return bt_error(e)
    except (DataError, UserDataError) as e:
        return error(e)
    if p["engine"] == "options":
        return bt_error(BtError("bad_request", "BT OPT TAKES A RULE OR A PYTHON STRATEGY, NOT MKT=OPTIONS"))
    params = {k: p[k] for k in ("data_path", "data_sha", "short", "engine", "config", "bars_per_year", "adjusted",
                                "memory_limit_mb", "labels") if k in p}
    if p.get("stops"):
        params["stops"] = p["stops"]
    params.update(template=template, kind=kind, method=method, fit=fit, seed=seed, n=n, pop=pop, gen=gen, wf=wf,
                  anchored=bool(body.get("anchored")), budget=budget,
                  meta={"symbols": p["meta"]["symbols"], "interval": p["meta"]["interval"], "range": p["meta"]["range"],
                        "strategy": strategy})
    stable = {k: v for k, v in params.items() if k != "labels"}
    params["opt_id"] = hashlib.sha256(orjson.dumps(stable, option=orjson.OPT_SORT_KEYS)).hexdigest()[:16]
    job = await jobs_of(request).submit("bt.opt", params, internal=True)
    return Orjson({**job, "opt_id": params["opt_id"], "budget": budget})


# --- paper forward tests -----------------------------------------------------------------------------------------------

async def _load(db, fwd_id: str) -> dict | None:
    async with db.execute("SELECT value FROM kv WHERE key=?", (KV_PREFIX + fwd_id,)) as cur:
        row = await cur.fetchone()
    return orjson.loads(row[0]) if row else None


async def _save(db, state: dict) -> None:
    await db.execute("INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                     (KV_PREFIX + state["id"], orjson.dumps(state)))
    await db.commit()


async def _all(db) -> list[dict]:
    async with db.execute("SELECT value FROM kv WHERE key LIKE ? ORDER BY key", (KV_PREFIX + "%",)) as cur:
        return [orjson.loads(r[0]) for r in await cur.fetchall()]


def _hook(app) -> None:
    """Registers the bt.fwdsig on-done hook once: a finished signal job advances its forward test and refreshes the
    comparison before the job shows done (so the panel's next GET already sees it)."""
    jobs = app.state.jobs
    if "bt.fwdsig" in jobs.on_done:
        return

    async def on_done(job: dict, result: dict) -> dict:
        db = app.state.userdata.db
        state = await _load(db, result["fwd_id"])
        if state is None or state["status"] != "active":
            return {"fwd_id": result["fwd_id"], "applied": False}
        sig, t, o, c = result["signal"], result["t"], result["o"], result["c"]
        fwd.step(state, t, o, sig, time.time())
        state["backtest"] = fwd.compare(state, t, o, c, sig)
        await _save(db, state)
        return {"fwd_id": state["id"], "applied": True, "decisions": len(state["decisions"])}

    jobs.on_done["bt.fwdsig"] = on_done


async def _submit_step(app, state: dict) -> dict:
    """Fetch the bars, write the data file and submit the signal job of one forward test (raises DataError / BtError)."""
    _hook(app)
    req = SimpleNamespace(app=app)  # bt_of / svc only read `.app`; the scheduler has no Request
    saved = await bt_of(req).strategy(state["strategy"])
    env = await svc(req).history(state["symbol"], fwd.HISTORY_RANGE[state["interval"]], state["interval"])
    sha, path = await asyncio.to_thread(bt_of(req).write_data, {"bars": {state["symbol"]: env["data"]}})
    params ={"fwd_id": state["id"], "data_path": str(path), "data_sha": sha, "short": False,
              **({"rule": saved["code"]} if saved["kind"] == "rule" else {"code": saved["code"]})}
    return await app.state.jobs.submit("bt.fwdsig", params, internal=True)


@router.get("/fwd")
async def fwd_list(request: Request):
    return {"tests": [fwd.summary(s) for s in await _all(request.app.state.userdata.db)]}


@router.post("/fwd")
async def fwd_create(request: Request):
    """Body: {symbol, strategy (a saved name), interval 1D|1W, cash}. Starts a forward test and its first check."""
    from .bt.store import BtError

    try:
        body = await json_object(request)
        symbol = resolve(str(body.get("symbol") or "").strip().upper())
        if not symbol:
            raise BtError("bad_request", "USAGE: BT LIVE <SYMBOL> @<SAVED STRATEGY> [1D|1W] [CASH=n]")
        saved = await bt_of(request).strategy(str(body.get("strategy") or ""))
        interval = str(body.get("interval") or "1D").upper()
        if interval not in fwd.BAR_SECONDS:
            raise BtError("bad_request", "BT LIVE INTERVAL MUST BE 1D OR 1W")
        cash = body.get("cash", 100_000)
        if isinstance(cash, bool) or not isinstance(cash, int | float) or not 1 <= cash <= 1e12:
            raise BtError("bad_request", "CASH MUST BE A NUMBER 1-1E12")
        db = request.app.state.userdata.db
        if len(await _all(db)) >= MAX_FWD:
            raise BtError("bad_request", f"AT MOST {MAX_FWD} FORWARD TESTS: DELETE ONE WITH BT LIVE DEL <ID>")
        state = fwd.new_state(uuid.uuid4().hex[:8], symbol, saved["name"], interval, float(cash), time.time())
        await _save(db, state)
        job = await _submit_step(request.app, state)
    except BtError as e:
        return bt_error(e)
    except (DataError, UserDataError) as e:
        return error(e)
    return Orjson({"test": fwd.summary(state), "job": job})


@router.get("/fwd/{fwd_id}")
async def fwd_get(request: Request, fwd_id: str):
    from .bt.store import BtError

    state = await _load(request.app.state.userdata.db, fwd_id)
    if state is None:
        return bt_error(BtError("not_found", f"NO FORWARD TEST {fwd_id[:12]}"))
    return Orjson({**state, "summary": fwd.summary(state)})


@router.post("/fwd/{fwd_id}/step")
async def fwd_step(request: Request, fwd_id: str):
    from .bt.store import BtError

    db = request.app.state.userdata.db
    state = await _load(db, fwd_id)
    if state is None:
        return bt_error(BtError("not_found", f"NO FORWARD TEST {fwd_id[:12]}"))
    if state["status"] != "active":
        return bt_error(BtError("bad_request", f"FORWARD TEST {fwd_id} IS STOPPED"))
    try:
        job = await _submit_step(request.app, state)
    except BtError as e:
        return bt_error(e)
    except (DataError, UserDataError) as e:
        state["error"] = redact(str(e))
        await _save(db, state)
        return error(e)
    return Orjson(job)


@router.post("/fwd/{fwd_id}/stop")
async def fwd_stop(request: Request, fwd_id: str):
    from .bt.store import BtError

    db = request.app.state.userdata.db
    state = await _load(db, fwd_id)
    if state is None:
        return bt_error(BtError("not_found", f"NO FORWARD TEST {fwd_id[:12]}"))
    state["status"] = "stopped"
    await _save(db, state)
    return Orjson(fwd.summary(state))


@router.delete("/fwd/{fwd_id}")
async def fwd_delete(request: Request, fwd_id: str):
    db = request.app.state.userdata.db
    await db.execute("DELETE FROM kv WHERE key=?", (KV_PREFIX + fwd_id,))
    await db.commit()
    return {"deleted": fwd_id}


async def step_all(app) -> None:
    """The scheduler's job (every FWD_EVERY_MIN minutes): submit a check for every active forward test. A failure is written
    on that test (shown in its row) and logged; it never stops the others."""
    for state in await _all(app.state.userdata.db):
        if state["status"] != "active":
            continue
        try:
            await _submit_step(app, state)
        except Exception as e:  # noqa: BLE001 - one test's data failure must not stop the other tests
            state["error"] = redact(str(e))
            await _save(app.state.userdata.db, state)
            log.warning("forward test %s check failed: %s", state["id"], redact(str(e)))
