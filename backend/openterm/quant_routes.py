"""Phase 15 server side (spec decisions B, C, D, E, F, L): `POST /api/quant/{fn}` and the valuation table routes.

The server parses the JSON object, reads the portfolio, fetches the bars (router, cache, fixtures), writes a content-addressed data file
and submits an internal job (`risk.run`, `opt.run`, `attr.run`); the job never touches the network. numpy / pandas / scipy are never imported
here (they load in the job worker): only `quantjobs.sectors`, a table of constants, is.
"""

import asyncio
import math
import re
import time
from datetime import date

import orjson
from fastapi import APIRouter, Request

from .api import bt_of, error, jobs_of, json_object, portfolios, svc, user
from .jobs.kinds import BadParams
from .quantjobs import sectors as sx
from .ranges import normalize
from .responses import Orjson
from .service import DataError
from .symbols import resolve
from .userdata import UserDataError

router = APIRouter(prefix="/api")

LIVE = ("risk", "opt", "attr")  # fact, ql, alpha, regime answer 404 until their build steps land
KNOWN = ("risk", "opt", "attr", "fact", "ql", "alpha", "regime")
OPT_METHODS = ("EQVOL", "RP", "MV", "MAXDIV", "HRP", "TURN")
MINOR = {"GBp": ("GBP", 0.01), "ZAc": ("ZAR", 0.01), "ILA": ("ILS", 0.01)}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_VALS = 5000
MAX_ABS = 1e15


def _bad(msg: str) -> UserDataError:
    return UserDataError("bad_request", msg)


def _num(body: dict, key: str, lo: float, hi: float, default, integer: bool = False):
    v = body.get(key)
    if v is None or v == "":
        return default
    if isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(v) or not lo <= v <= hi or (integer and v != int(v)):
        raise _bad(f"{key.upper()} MUST BE {'AN INTEGER' if integer else 'A NUMBER'} {lo:g}-{hi:g}")
    return int(v) if integer else float(v)


def _range(body: dict, default: str) -> str:
    raw = str(body.get("range") or default).upper()
    try:
        normalize(raw, "1d")
    except ValueError as e:
        raise _bad(f"RANGE: {e}") from None
    return raw


def _symbol(body: dict, key: str, default: str | None) -> str | None:
    v = body.get(key)
    if v is None or v == "":
        return default
    if not isinstance(v, str) or not v.strip():
        raise _bad(f"{key.upper()} MUST BE A SYMBOL")
    return None if v.strip().upper() == "NONE" else resolve(v.strip().upper())


async def _pick(request: Request, body: dict) -> tuple[dict | None, str | None]:
    """The portfolio to run on (decision C): the named one; else the only one, else MAIN; else (None, NOT RUNNABLE reason)."""
    store = portfolios(request)
    name = body.get("portfolio")
    if name not in (None, ""):
        if not isinstance(name, str):
            raise _bad("PORTFOLIO MUST BE A NAME")
        return await store.get(name), None
    names = [p["name"] for p in await store.all()]
    if len(names) == 1 or "MAIN" in names:
        return await store.get(names[0] if len(names) == 1 else "MAIN"), None
    if not names:
        return None, "NOT RUNNABLE: NO PORTFOLIO YET, CREATE ONE WITH PORT"
    return None, f"NOT RUNNABLE: CHOOSE A PORTFOLIO: {', '.join(names)}"


async def _bars(request: Request, symbols: list[str], range_: str, tolerate: bool = False) -> tuple[dict, dict]:
    """(envelopes by symbol, DataErrors by symbol). Without `tolerate` the first failure is raised, named."""
    gate = asyncio.Semaphore(4)  # Yahoo's bucket is 4 requests/s: a wider burst trips its breaker, so a rate-limited call waits and retries

    async def one(sym: str, i: int) -> dict:
        await asyncio.sleep(max(0, i - 5) * 0.26)  # past the burst of 8, stay under 4 requests/s (a 429 opens the breaker for 5 s)
        async with gate:
            for attempt in range(4):
                try:
                    return await svc(request).history(sym, range_, "1d")
                except DataError as e:
                    if e.kind != "unavailable" or attempt == 3:
                        raise
                    await asyncio.sleep(0.6)
            raise AssertionError("unreachable")

    res = await asyncio.gather(*(one(s, i) for i, s in enumerate(symbols)), return_exceptions=True)
    ok: dict = {}
    bad: dict = {}
    for sym, r in zip(symbols, res, strict=True):
        if isinstance(r, DataError):
            bad[sym] = r
        elif isinstance(r, BaseException):
            raise r
        else:
            ok[sym] = r
    if bad and not tolerate:
        sym, e = next(iter(bad.items()))
        raise DataError(e.kind, f"{sym}: {e}", getattr(e, "detail", None))
    return ok, bad


def _slim(env: dict) -> dict:
    d = env["data"]
    return {"t": d["t"], "c": d["c"]}


def _labels(request: Request, envs: dict[str, dict]) -> dict:
    return {"sources": [{"symbol": s, "name": e.get("source"), "as_of": e.get("as_of"), "age_s": e.get("age_s"), "stale": bool(e.get("stale"))}
                        for s, e in envs.items()],
            "fallback_from": sorted({n for e in envs.values() for n in (e.get("fallback_from") or [])}),
            "fixtures": bool(request.app.state.settings.openterm_fixtures)}


async def _positions(request: Request, pf: dict) -> tuple[list[dict], dict, bool, str | None]:
    """(positions [{symbol, qty, ccy}], fx rates by currency, mixed currencies, NOT RUNNABLE reason). Decision C: values at the last FX rate."""
    base = pf["base"].upper()
    pos = [{"symbol": p["symbol"], "qty": p["qty"], "ccy": p.get("currency")} for p in pf["positions"]]
    if not pos:
        return pos, {}, False, "NOT RUNNABLE: THE PORTFOLIO HAS NO POSITIONS"
    fx: dict[str, float] = {}
    mixed = False
    for ccy in sorted({p["ccy"] for p in pos if p["ccy"]}):
        major, scale = MINOR.get(ccy, (ccy.upper(), 1.0))
        if major == base:
            if scale != 1.0:
                fx[ccy] = scale
            continue
        mixed = True
        pair = f"{major}{base}=X"
        try:
            env = await svc(request).history(pair, "1Y", "1d")
            closes = [c for c in env["data"]["c"] if c]
        except DataError:
            closes = []
        if not closes:
            return pos, {}, True, f"NOT RUNNABLE: NO FX RATE {major} TO {base} ({pair}) TO VALUE THE {ccy} POSITIONS"
        fx[ccy] = float(closes[-1]) * scale
    return pos, fx, mixed, None


async def _submit(request: Request, kind: str, params: dict) -> Orjson:
    try:
        return Orjson(await jobs_of(request).submit(kind, params, internal=True))
    except BadParams as e:
        return error(DataError("bad_request", str(e)))


async def _stored(request: Request, payload: dict) -> tuple[str, str]:
    sha, path = await asyncio.to_thread(bt_of(request).write_data, payload)
    return sha, str(path)


# --- RISK ---------------------------------------------------------------------------------------------------------------------------
async def build_risk(request: Request, body: dict) -> dict:
    raw = _num(body, "conf", 0.5, 99.9, 95.0)
    conf = raw * 100 if raw < 1 else raw
    hor = _num(body, "hor", 1, 60, 1, integer=True)
    range_ = _range(body, "3Y")
    bench = _symbol(body, "bench", "SPY")
    pf, why = await _pick(request, body)
    if pf is None:
        return {"not_runnable": why}
    pos, fx, mixed, why = await _positions(request, pf)
    if why:
        return {"not_runnable": why}
    syms = [p["symbol"] for p in pos]
    envs, _ = await _bars(request, syms, range_)
    stress = envs if range_ == "20Y" else (await _bars(request, syms, "20Y", tolerate=True))[0]
    bench_env = (await _bars(request, [bench], range_, tolerate=True))[0] if bench else {}
    payload = {"bars": {s: _slim(e) for s, e in envs.items()}, "stress": {s: _slim(e) for s, e in stress.items()},
               "bench": _slim(bench_env[bench]) if bench in bench_env else None, "fx": fx}
    sha, path = await _stored(request, payload)
    return {"name": pf["name"], "base": pf["base"], "positions": pos, "range": range_, "bench": bench, "conf": conf, "hor": hor,
            "mixed_ccy": mixed, "data_path": path, "data_sha": sha, "labels": _labels(request, {**envs, **bench_env})}


# --- OPT ----------------------------------------------------------------------------------------------------------------------------
async def build_opt(request: Request, body: dict) -> dict:
    method = str(body.get("method") or "RP").upper()
    if method not in OPT_METHODS:
        raise _bad(f"METHOD MUST BE {', '.join(OPT_METHODS)}")
    cap = _num(body, "cap", 0.0001, 1, None)
    lookback = _num(body, "lookback", 20, 2500, 252, integer=True)
    rf = _num(body, "rf", 0, 0.5, 0.0)
    tc = _num(body, "tc", 0, 10, 0.0)
    range_ = _range(body, "1Y" if lookback <= 200 else "2Y" if lookback <= 480 else "5Y" if lookback <= 1200 else "10Y")
    pf, why = await _pick(request, body)
    if pf is None:
        return {"not_runnable": why}
    pos, fx, mixed, why = await _positions(request, pf)
    if why:
        return {"not_runnable": why}
    if cap is not None and cap * len(pos) < 1.0 - 1e-9:
        raise _bad(f"CAP MUST BE AT LEAST 1/N ({1 / len(pos):.4f}) FOR {len(pos)} HOLDINGS")
    envs, _ = await _bars(request, [p["symbol"] for p in pos], range_)
    sha, path = await _stored(request, {"bars": {s: _slim(e) for s, e in envs.items()}, "fx": fx})
    return {"name": pf["name"], "base": pf["base"], "positions": pos, "method": method, "cap": cap, "lookback": lookback, "rf": rf, "tc": tc,
            "range": range_, "mixed_ccy": mixed, "data_path": path, "data_sha": sha, "labels": _labels(request, envs)}


# --- ATTR ---------------------------------------------------------------------------------------------------------------------------
async def _sector_map(request: Request, symbols: list[str]) -> dict[str, str] | None:
    """Screener sector (Nasdaq names) per symbol as a canonical sector; None when the screener is unavailable."""
    try:
        uni = (await svc(request).screener())["data"]
    except DataError:
        return None
    i = uni["columns"].index("sector")
    sectors = uni["sectors"]
    wanted = set(symbols)
    return {r[0]: sx.canonical(sectors[r[i]]) for r in uni["rows"] if r[0] in wanted}


async def _bench_weights(request: Request, bench: str) -> tuple[dict[str, float] | None, dict]:
    from .research.fund_parse import fund_facts

    s = svc(request)

    async def fetch() -> dict:
        summary, failed = await s.router.call("fund_info", lambda p: p.fund(bench), bench)
        return {"data": {"sectors": fund_facts(summary)["sectors"]}, "fallback_from": failed, "source": "yahoo_research"}

    try:
        env = await s._swr(f"q:fundsectors:{bench}", 3600.0, fetch)
    except DataError:
        return None, {}
    return sx.bench_weights(env["data"]["sectors"]), env


async def _read_vals(request: Request, name: str) -> list[dict]:
    async with user(request).db.execute("SELECT value FROM kv WHERE key=?", (f"port_vals:{name}",)) as cur:
        row = await cur.fetchone()
    return orjson.loads(row[0]).get("rows", []) if row else []


async def build_attr(request: Request, body: dict) -> dict:
    range_ = _range(body, "1Y")
    bench = _symbol(body, "bench", "SPY")
    if bench is None:
        raise _bad("BENCH MUST BE A SYMBOL")
    pf, why = await _pick(request, body)
    if pf is None:
        return {"not_runnable": why}
    pos, fx, mixed, why = await _positions(request, pf)
    if why:
        return {"not_runnable": why}
    syms = [p["symbol"] for p in pos]
    sector_of = await _sector_map(request, syms)
    bench_w, bench_env = await _bench_weights(request, bench)
    held = set((sector_of or {}).values())
    need = sorted((held | set(bench_w or {})) & set(sx.SPDR))
    envs, _ = await _bars(request, syms, range_)
    etf, _ = await _bars(request, [sx.SPDR[k] for k in need], range_, tolerate=True)
    by_sec = {k: etf[sx.SPDR[k]] for k in need if sx.SPDR[k] in etf}
    vals = await _read_vals(request, pf["name"])
    payload = {"bars": {s: _slim(e) for s, e in envs.items()}, "etf": {k: _slim(e) for k, e in by_sec.items()}, "fx": fx}
    sha, path = await _stored(request, payload)
    labels = _labels(request, {**envs, **{sx.SPDR[k]: e for k, e in by_sec.items()}, **({f"{bench} SECTORS": bench_env} if bench_env else {})})
    return {"name": pf["name"], "base": pf["base"], "positions": pos, "bench": bench, "range": range_, "sector_of": sector_of or {},
            "bench_weights": bench_w, "vals": vals,
            **({} if sector_of is not None else {"sector_problem": "NOT RUNNABLE: THE SCREENER (SECTORS) IS UNAVAILABLE"}), "mixed_ccy": mixed, "data_path": path, "data_sha": sha, "labels": labels}


BUILD = {"risk": ("risk.run", build_risk), "opt": ("opt.run", build_opt), "attr": ("attr.run", build_attr)}


@router.post("/quant/{fn}")
async def quant_run(request: Request, fn: str):
    if fn not in LIVE:
        return error(DataError("not_found", f"NO QUANT FUNCTION {fn.upper()}" + (" YET" if fn in KNOWN else "")))
    kind, build = BUILD[fn]
    try:
        body = await json_object(request)
        params = await build(request, body)
    except (UserDataError, DataError) as e:
        return error(e)
    return await _submit(request, kind, params)


# --- valuation table (PORT ATTR RETURNS): kv key port_vals:<NAME>, no migration -------------------------------------------------------
def check_vals(rows) -> list[dict]:
    if not isinstance(rows, list) or len(rows) > MAX_VALS:
        raise _bad(f"ROWS MUST BE A LIST OF AT MOST {MAX_VALS} VALUATIONS")
    seen: set[str] = set()
    out = []
    for r in rows:
        if not isinstance(r, dict):
            raise _bad("EACH ROW MUST BE AN OBJECT WITH date, value AND flow")
        d = r.get("date")
        try:
            if not isinstance(d, str) or not DATE_RE.match(d):
                raise ValueError
            date.fromisoformat(d)
        except ValueError:
            raise _bad(f"BAD DATE: {str(d)[:24]} (USE YYYY-MM-DD)") from None
        if d in seen:
            raise _bad(f"DUPLICATE DATE {d}")
        seen.add(d)
        value, flow = r.get("value"), r.get("flow", 0)
        flow = 0 if flow is None else flow
        if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value) or not 0 < value <= MAX_ABS:
            raise _bad(f"{d} VALUE MUST BE A POSITIVE NUMBER")
        if isinstance(flow, bool) or not isinstance(flow, int | float) or not math.isfinite(flow) or abs(flow) > MAX_ABS:
            raise _bad(f"{d} FLOW MUST BE A NUMBER")
        out.append({"date": d, "value": float(value), "flow": float(flow)})
    return sorted(out, key=lambda x: x["date"])


@router.get("/portfolios/{name}/vals")
async def vals_get(request: Request, name: str):
    try:
        pf = await portfolios(request).get(name)
        return {"name": pf["name"], "rows": await _read_vals(request, pf["name"])}
    except UserDataError as e:
        return error(e)


@router.put("/portfolios/{name}/vals")
async def vals_put(request: Request, name: str):
    try:
        pf = await portfolios(request).get(name)
        body = await json_object(request)
        if "rows" not in body:
            raise _bad("BODY NEEDS rows")
        rows = check_vals(body["rows"])
        db = user(request).db
        await db.execute("INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                         (f"port_vals:{pf['name']}", orjson.dumps({"rows": rows, "updated_at": time.time()})))
        await db.commit()
        return {"name": pf["name"], "rows": rows}
    except UserDataError as e:
        return error(e)
