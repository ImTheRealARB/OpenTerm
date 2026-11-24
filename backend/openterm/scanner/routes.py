"""Phase 27 routes: SCAN (`/api/scan`), saved and scheduled scans (`/api/scan/saved`) and index movers (`/api/mrr`).

A scan or MRR can take a minute cold (Yahoo's burst limit paces the bar downloads), far longer than one HTTP request should
wait. So POST starts a TASK and answers at once with its id; the panel polls `GET .../{id}` for progress ("142 OF 503 BARS"),
then the result. Tasks live in memory (`app.state.scan_tasks`, the last 30): a restart forgets them, a saved scan does not.

SCAN: bars (server) -> data file -> `scan.run` job (worker: the BT rule on each symbol's newest bar) -> result.
MRR: bars (server) -> returns over the period and contribution = index weight x return, in pure Python (no job needed).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from types import SimpleNamespace

import orjson
from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from ..barfetch import fetch_bars
from ..errors import DataError
from ..http_util import error, error_response
from ..redact import redact
from ..responses import Orjson, OrjsonRoute
from . import universe as U

log = logging.getLogger("openterm.scan")
router = APIRouter(route_class=OrjsonRoute)

MAX_TASKS = 30
SAVED_PREFIX = "scansaved:"
MRR_PERIODS = {"1D": 1, "1W": 5, "1M": 21, "3M": 63, "YTD": None, "1Y": 252}
MRR_RANGE = {"1D": "1M", "1W": "1M", "1M": "3M", "3M": "6M", "YTD": "1Y", "1Y": "2Y"}


class ScanBody(BaseModel):
    universe: str = Field(..., max_length=200)
    rule: str = Field(..., max_length=500)
    symbols: list[str] | None = Field(None, max_length=U.MAX_SYMBOLS)  # an EQS result, sent by the panel


class SavedBody(BaseModel):
    universe: str = Field(..., max_length=200)
    rule: str = Field(..., max_length=500)
    daily: str | None = Field(None, max_length=5)  # "HH:MM" server local time, Monday to Friday; None = not scheduled


def _bad(msg: str):
    return error_response(400, "bad_request", msg)


def _tasks(app) -> dict:
    if getattr(app.state, "scan_tasks", None) is None:
        app.state.scan_tasks = {}
    return app.state.scan_tasks


def _new_task(app, kind: str, **fields) -> dict:
    tasks = _tasks(app)
    while len(tasks) >= MAX_TASKS:
        tasks.pop(next(iter(tasks)))  # oldest first (dicts keep insertion order)
    t = {"id": uuid.uuid4().hex[:10], "kind": kind, "state": "fetching", "done": 0, "total": 0, "error": None,
         "result": None, "job_id": None, "created": time.time(), **fields}
    tasks[t["id"]] = t
    return t


async def resolve_universe(app, word: str, symbols: list[str] | None) -> tuple[list[str], dict[str, float | None], str]:
    """(symbols, weights by symbol (empty when the source has none), where the list came from)."""
    kind, value = U.parse(word)
    svc = app.state.service
    if kind == "list":
        return U.clean(symbols if symbols else value.split(",")), {}, "YOUR LIST"
    if kind == "wl":
        wl = await app.state.userdata.watchlist(value)
        return U.clean(wl["symbols"]), {}, f"WATCHLIST {wl['name']}"
    if kind == "memb":
        env = await svc.research.run("memb", index=value)
        members = U.memb_members(env["data"])
        syms = U.clean([s for s, _ in members])
        return syms, {s: w for s, w in members}, f"{value} MEMBERS (SEC N-PORT OF THE PROXY ETF)"
    nse = svc.router.providers["nseindices"]
    text = await nse.constituents(U.NIFTY[value])
    return U.clean(U.nifty_members(text)), {}, f"{value} MEMBERS (NSE INDICES LIST, FETCHED ON THIS COMPUTER)"


class _Counting:
    """The data service with a counter: every finished bar download moves the task's progress on."""

    def __init__(self, svc, task: dict):
        self.svc, self.task = svc, task

    async def history(self, symbol: str, range_: str, interval: str):
        try:
            return await self.svc.history(symbol, range_, interval)
        finally:
            self.task["done"] += 1


async def _bars(app, task: dict, symbols: list[str], range_: str) -> tuple[dict, dict]:
    task["total"] = len(symbols)
    envs, errs = await fetch_bars(_Counting(app.state.service, task), symbols, range_, tolerate=True)
    return envs, {s: redact(str(e)) for s, e in errs.items()}


# --- SCAN ------------------------------------------------------------------------------------------------------------

def _hook(app, kind: str = "scan.run") -> None:
    """The on-done hook of scan.run / scan.cols: the finished job's result lands on its task before the job shows done."""
    jobs = app.state.jobs
    if kind in jobs.on_done:
        return

    async def on_done(job: dict, result: dict) -> dict:
        for t in _tasks(app).values():
            if t["job_id"] == job["id"]:
                t["result"], t["state"] = result, "done"
        return {"matched": result["matched"], "checked": result["checked"]} if kind == "scan.run" else {"rows": len(result["rows"])}

    jobs.on_done[kind] = on_done


async def start_scan(app, universe_word: str, rule: str, symbols: list[str] | None = None) -> dict:
    """Validates, creates the task and starts it in the background (raises RuleError / UniverseError / DataError)."""
    from ..bt import rules

    node = rules.parse(rule)
    syms, _, source = await resolve_universe(app, universe_word, symbols)
    task = _new_task(app, "scan", universe=universe_word.upper(), rule=rule, source=source)
    task["runner"] = asyncio.create_task(_run_job(app, task, "scan.run", syms, U.range_for(rules.max_period(node)),
                                                  {"rule": rule}))
    return task


async def _run_job(app, task: dict, kind: str, syms: list[str], range_: str, params: dict) -> None:
    """The shared body of a SCAN and an indicator-columns task: bars (server) -> data file -> job (worker) -> result."""
    try:
        _hook(app, kind)
        envs, errs = await _bars(app, task, syms, range_)
        from ..api import bt_of

        sha, path = await asyncio.to_thread(bt_of(SimpleNamespace(app=app)).write_data, {"bars": {s: envs[s]["data"] for s in envs}})
        labels = {"prices": "RAW CLOSES", "bars": f"DAILY, {range_}", "source": task["source"],
                  "fixtures": "RECORDED FIXTURE DATA" if app.state.settings.openterm_fixtures else ""}
        task["state"] = "running"
        job = await app.state.jobs.submit(kind, {"data_path": str(path), "data_sha": sha, **params,
                                                 "failed": {**(params.get("failed") or {}), **errs}, "labels": labels},
                                          internal=True)
        task["job_id"] = job["id"]
        if job.get("state") == "done" and job.get("result"):  # the same request already ran on these bars: the job cache answered
            task["result"], task["state"] = job["result"], "done"
    except Exception as e:  # noqa: BLE001 - shown on the task (the panel's ERR line), never lost
        task["state"], task["error"] = "error", redact(str(e))
        log.warning("%s task %s failed: %s", kind, task["id"], task["error"])


def _public(t: dict) -> dict:
    return {k: v for k, v in t.items() if k != "runner"}


@router.post("/api/scan")
async def scan_start(request: Request, body: ScanBody):
    from ..bt.rules import RuleError

    try:
        task = await start_scan(request.app, body.universe, body.rule, body.symbols)
    except RuleError as e:
        return error_response(400, "bad_request", str(e))
    except U.UniverseError as e:
        return _bad(str(e))
    except DataError as e:
        return error(e)
    return Orjson(_public(task))


class ColsBody(BaseModel):
    symbols: list[str] = Field(..., min_length=1, max_length=200)
    cols: str = Field(..., max_length=200)


@router.post("/api/scan/cols")
async def cols_start(request: Request, body: ColsBody):
    """Indicator columns for a WL / Q grid (`COLS=RSI14,PCT_SMA200`): a task like SCAN's, polled at /api/scan/task/{id}."""
    from ..bt.rules import RuleError
    from . import cols as C

    try:
        spec = C.parse(body.cols)
    except RuleError as e:
        return _bad(str(e))
    # A grid row can be a formula (AAPL/MSFT) or junk: that row gets a note, the others still get their columns.
    syms, skipped = [], {}
    for s in body.symbols:
        try:
            syms += [x for x in U.clean([s]) if x not in syms]
        except U.UniverseError:
            skipped[str(s).upper()[:24]] = "NOT A PLAIN SYMBOL: NO INDICATOR COLUMNS"
    if not syms:
        return _bad("NO PLAIN SYMBOLS TO COMPUTE COLUMNS FOR")
    app = request.app
    task = _new_task(app, "cols", cols=body.cols.upper(), source="YOUR LIST")
    task["runner"] = asyncio.create_task(_run_job(app, task, "scan.cols", syms, U.range_for(C.max_period(spec)),
                                                  {"cols": body.cols.upper(), "failed": skipped}))
    return Orjson(_public(task))


@router.get("/api/scan/task/{task_id}")
async def scan_task(request: Request, task_id: str):
    t = _tasks(request.app).get(task_id)
    if t is None:
        return error_response(404, "not_found", f"NO SCAN TASK {task_id[:12]} (TASKS ARE FORGOTTEN ON A RESTART)")
    return Orjson(_public(t))


# --- saved and scheduled scans -----------------------------------------------------------------------------------------

def _daily(v: str | None) -> tuple[int, int] | None:
    if not v:
        return None
    try:
        h, m = (int(x) for x in v.split(":"))
    except ValueError:
        raise ValueError("DAILY= IS HH:MM, E.G. 22:15") from None
    if not (0 <= h < 24 and 0 <= m < 60):
        raise ValueError("DAILY= IS HH:MM, E.G. 22:15")
    return h, m


async def saved_all(db) -> list[dict]:
    async with db.execute("SELECT value FROM kv WHERE key LIKE ? ORDER BY key", (SAVED_PREFIX + "%",)) as cur:
        return [orjson.loads(r[0]) for r in await cur.fetchall()]


def schedule_saved(app, saved: list[dict]) -> None:
    """(Re)registers one weekday cron job per scheduled scan (`scan:<NAME>`) and removes the ones no longer scheduled."""
    sched = getattr(app.state, "scheduler", None)
    if sched is None:
        return
    want = {f"scan:{s['name']}": s for s in saved if s.get("daily")}
    for job in sched.get_jobs():
        if job.id.startswith("scan:") and job.id not in want:
            job.remove()
    for jid, s in want.items():
        h, m = _daily(s["daily"])
        sched.add_job(run_saved, "cron", day_of_week="mon-fri", hour=h, minute=m, args=[app, s["name"]], id=jid,
                      replace_existing=True, max_instances=1, coalesce=True)


async def run_saved(app, name: str) -> dict:
    """Runs a saved scan to the end and sends the matches through DELIVERY (kind "scan"). Used by the schedule and by
    `POST /api/scan/saved/{name}/run`."""
    from .. import delivery

    rows = [s for s in await saved_all(app.state.userdata.db) if s["name"] == name]
    if not rows:
        raise DataError("not_found", f"NO SAVED SCAN {name}")
    s = rows[0]
    task = await start_scan(app, s["universe"], s["rule"])
    with contextlib.suppress(Exception):
        await task["runner"]
    for _ in range(1800):  # the job part: at most 30 minutes
        if task["state"] in ("done", "error"):
            break
        await asyncio.sleep(1)
    if task["state"] != "done":
        text = f"SCAN {name} FAILED: {task['error'] or 'TIMED OUT'}"
        await delivery.dispatch(app, "scan", name, f"SCAN {name}: FAILED", text, {"kind": "scan"})
        return {"task": task["id"], "sent": False, "error": text}
    res = task["result"]
    hits = [r for r in res["rows"] if r["matched"]]
    lines = [f"{r['symbol']}  " + "  ".join(f"{k}={v:.2f}" for k, v in r["values"].items() if v is not None) for r in hits[:50]]
    text = (f"SCAN {name}: {s['universe']} {s['rule']}\n{len(hits)} OF {res['checked']} MATCH"
            + (f" ({res['failed']} WITHOUT DATA)" if res["failed"] else "") + "\n" + "\n".join(lines))
    await delivery.dispatch(app, "scan", name, f"SCAN {name}: {len(hits)} MATCHES", text, {"kind": "scan"})
    return {"task": task["id"], "sent": True, "matched": len(hits)}


@router.get("/api/scan/saved")
async def saved_list(request: Request):
    return {"saved": await saved_all(request.app.state.userdata.db)}


@router.put("/api/scan/saved/{name}")
async def saved_put(request: Request, name: str, body: SavedBody):
    from ..bt import rules

    n = name.strip().upper()
    if not n or len(n) > 30 or not n.replace("_", "").replace("-", "").isalnum():
        return _bad("A SCAN NAME IS 1-30 LETTERS, DIGITS, _ OR -")
    try:
        rules.parse(body.rule)
        U.parse(body.universe)
        _daily(body.daily)
    except (rules.RuleError, U.UniverseError, ValueError) as e:
        return _bad(str(e))
    db = request.app.state.userdata.db
    doc = {"name": n, "universe": body.universe.upper(), "rule": body.rule, "daily": body.daily, "updated": time.time()}
    await db.execute("INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                     (SAVED_PREFIX + n, orjson.dumps(doc)))
    await db.commit()
    schedule_saved(request.app, await saved_all(db))
    return doc


@router.delete("/api/scan/saved/{name}")
async def saved_delete(request: Request, name: str):
    db = request.app.state.userdata.db
    await db.execute("DELETE FROM kv WHERE key=?", (SAVED_PREFIX + name.strip().upper(),))
    await db.commit()
    schedule_saved(request.app, await saved_all(db))
    return {"deleted": name.strip().upper()}


@router.post("/api/scan/saved/{name}/run")
async def saved_run(request: Request, name: str):
    """Runs a saved scan now and sends it (the same path the daily schedule takes)."""
    try:
        return await run_saved(request.app, name.strip().upper())
    except DataError as e:
        return error(e)


# --- MRR: index movers over a period -----------------------------------------------------------------------------------

def movers(data: dict[str, dict], weights: dict[str, float | None], period: str) -> list[dict]:
    """{symbol: columnar daily bars} -> rows with the return over `period` and, when the index weight is known, the
    contribution (weight x return, as a ratio of the index). Pure Python. YTD starts from the last bar of the previous year."""
    back = MRR_PERIODS[period]
    out = []
    for sym, b in data.items():
        t, c = b.get("t") or [], b.get("c") or []
        pairs = [(ti, ci) for ti, ci in zip(t, c, strict=False) if ci is not None]
        ret = None
        if len(pairs) >= 2:
            last_t, last = pairs[-1]
            if back is None:
                year = time.gmtime(last_t).tm_year
                prev = [ci for ti, ci in pairs if time.gmtime(ti).tm_year < year]
                start = prev[-1] if prev else None
            else:
                start = pairs[-1 - back][1] if len(pairs) > back else None
            ret = last / start - 1 if start else None
        w = weights.get(sym)
        out.append({"symbol": sym, "return": ret, "weight": w, "contrib": w * ret if (w is not None and ret is not None) else None,
                    "last": pairs[-1][1] if pairs else None})
    out.sort(key=lambda r: (r["contrib"] if r["contrib"] is not None else (r["return"] or 0.0) * 1e-9), reverse=True)
    return out


async def _run_mrr(app, task: dict, syms: list[str], weights: dict) -> None:
    try:
        envs, errs = await _bars(app, task, syms, MRR_RANGE[task["period"]])
        rows = movers({s: e["data"] for s, e in envs.items()}, weights, task["period"])
        rows += [{"symbol": s, "return": None, "weight": weights.get(s), "contrib": None, "last": None, "note": f"NO DATA: {e}"}
                 for s, e in errs.items()]
        with_w = [r for r in rows if r["contrib"] is not None]
        task["result"] = {"rows": rows, "weighted": bool(weights), "sum_contrib": sum(r["contrib"] for r in with_w) if with_w else None,
                          "up": sum(1 for r in rows if (r["return"] or 0) > 0), "down": sum(1 for r in rows if (r["return"] or 0) < 0),
                          "failed": len(errs), "fixtures": bool(app.state.settings.openterm_fixtures)}
        task["state"] = "done"
    except Exception as e:  # noqa: BLE001 - shown on the task
        task["state"], task["error"] = "error", redact(str(e))


@router.post("/api/mrr")
async def mrr_start(request: Request, universe: str = Query(..., max_length=200), period: str = Query("1D", max_length=4)):
    p = period.upper()
    if p not in MRR_PERIODS:
        return _bad(f"PERIOD MUST BE {' '.join(MRR_PERIODS)}")
    try:
        syms, weights, source = await resolve_universe(request.app, universe, None)
    except U.UniverseError as e:
        return _bad(str(e))
    except DataError as e:
        return error(e)
    task = _new_task(request.app, "mrr", universe=universe.upper(), period=p, source=source)
    task["runner"] = asyncio.create_task(_run_mrr(request.app, task, syms, weights))
    return Orjson(_public(task))


@router.get("/api/scan/nifty")
async def nifty_list(request: Request, index: str = Query("NIFTY50", max_length=10)):
    """IMAP NIFTY: the index members with their industry (NSE Indices' list has no weights or market caps)."""
    file = U.NIFTY.get(index.upper())
    if file is None:
        return _bad(f"INDEX MUST BE {' OR '.join(U.NIFTY)}")
    try:
        text = await request.app.state.service.router.providers["nseindices"].constituents(file)
        rows = U.nifty_rows(text)
    except U.UniverseError as e:
        return _bad(str(e))
    except DataError as e:
        return error(e)
    return {"index": index.upper(), "rows": rows, "source": f"{index.upper()} MEMBERS (NSE INDICES LIST)"}


@router.get("/api/mrr/task/{task_id}")
async def mrr_task(request: Request, task_id: str):
    return await scan_task(request, task_id)
