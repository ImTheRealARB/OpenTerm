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

from . import cachekeys as ck
from .api import bt_of, portfolios
from .barfetch import fetch_bars
from .errors import DataError
from .http_util import error, jobs_of, json_object, svc, user
from .jobs.kinds import BadParams
from .quantjobs import sectors as sx
from .ranges import normalize
from .responses import Orjson, OrjsonRoute
from .symbols import resolve
from .userdata import UserDataError

router = APIRouter(prefix="/api", route_class=OrjsonRoute)

QL_CALCS = ("GARCH", "OU", "COINT", "HEDGE", "COPULA", "ROLL", "AMIHUD", "KYLE", "VPIN", "EVENT", "DSR", "ADF", "HVAR")
QL_PAIR = ("COINT", "HEDGE", "COPULA")
QL_VOLUME = ("AMIHUD", "KYLE", "VPIN")  # these need the daily volume column
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
    """(envelopes by symbol, DataErrors by symbol). Without `tolerate` the first failure is raised, named.

    The pacing (Yahoo's burst limit, retry and pause) lives in `barfetch.py`, shared by every multi-symbol route.
    """
    return await fetch_bars(svc(request), symbols, range_, tolerate)


def _slim(env: dict) -> dict:
    d = env["data"]
    return {"t": d["t"], "c": d["c"]}


def _labels(request: Request, envs: dict[str, dict]) -> dict:
    return {"sources": [{"symbol": s, "name": e.get("source"), "as_of": e.get("as_of"), "age_s": e.get("age_s"), "stale": bool(e.get("stale"))}
                        for s, e in envs.items()],
            "fallback_from": sorted({n for e in envs.values() for n in (e.get("fallback_from") or [])}),
            "fixtures": bool(request.app.state.settings.openterm_fixtures)}


def _holdings(pf: dict) -> tuple[list[dict], str | None]:
    """(positions [{symbol, qty, ccy}], NOT RUNNABLE reason). `ccy` is the typed currency; `_fx` fills the gaps from the bars."""
    pos = [{"symbol": p["symbol"], "qty": p["qty"], "ccy": p.get("currency")} for p in pf["positions"]]
    return pos, None if pos else "NOT RUNNABLE: THE PORTFOLIO HAS NO POSITIONS"


async def _fx(request: Request, pf: dict, pos: list[dict], envs: dict[str, dict]) -> tuple[dict, bool, str | None]:
    """(fx rates by currency, mixed currencies, NOT RUNNABLE reason). Decision C: values at the last FX rate.

    A holding added without a currency (`PORT MAIN ADD RELIANCE.NS 10 1300`) takes the currency its price bars are quoted in,
    as the PORT panel does with the quote; before audit B-1 such a holding was valued as if it were in the base currency
    (a rupee price read as dollars). Mutates `pos` so the job sees the resolved currency. A source that names no currency
    (None, or SYNTHETIC's ISO "XXX" = no currency) still counts as the base currency, as before.
    """
    for p in pos:
        if not p["ccy"]:
            bar_ccy = ((envs.get(p["symbol"]) or {}).get("data") or {}).get("currency")
            p["ccy"] = bar_ccy if bar_ccy and bar_ccy != "XXX" else None
    base = pf["base"].upper()
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
            return {}, True, f"NOT RUNNABLE: NO FX RATE {major} TO {base} ({pair}) TO VALUE THE {ccy} POSITIONS"
        fx[ccy] = float(closes[-1]) * scale
    return fx, mixed, None


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
    pos, why = _holdings(pf)
    if why:
        return {"not_runnable": why}
    syms = [p["symbol"] for p in pos]
    envs, _ = await _bars(request, syms, range_)
    fx, mixed, why = await _fx(request, pf, pos, envs)
    if why:
        return {"not_runnable": why}
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
    pos, why = _holdings(pf)
    if why:
        return {"not_runnable": why}
    if cap is not None and cap * len(pos) < 1.0 - 1e-9:
        raise _bad(f"CAP MUST BE AT LEAST 1/N ({1 / len(pos):.4f}) FOR {len(pos)} HOLDINGS")
    envs, _ = await _bars(request, [p["symbol"] for p in pos], range_)
    fx, mixed, why = await _fx(request, pf, pos, envs)
    if why:
        return {"not_runnable": why}
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
        env = await s.swr(ck.quant("fundsectors", bench), 3600.0, fetch)
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
    pos, why = _holdings(pf)
    if why:
        return {"not_runnable": why}
    syms = [p["symbol"] for p in pos]
    sector_of = await _sector_map(request, syms)
    bench_w, bench_env = await _bench_weights(request, bench)
    held = set((sector_of or {}).values())
    need = sorted((held | set(bench_w or {})) & set(sx.SPDR))
    envs, _ = await _bars(request, syms, range_)
    fx, mixed, why = await _fx(request, pf, pos, envs)
    if why:
        return {"not_runnable": why}
    etf, _ = await _bars(request, [sx.SPDR[k] for k in need], range_, tolerate=True)
    by_sec = {k: etf[sx.SPDR[k]] for k in need if sx.SPDR[k] in etf}
    vals = await _read_vals(request, pf["name"])
    payload = {"bars": {s: _slim(e) for s, e in envs.items()}, "etf": {k: _slim(e) for k, e in by_sec.items()}, "fx": fx}
    sha, path = await _stored(request, payload)
    labels = _labels(request, {**envs, **{sx.SPDR[k]: e for k, e in by_sec.items()}, **({f"{bench} SECTORS": bench_env} if bench_env else {})})
    return {"name": pf["name"], "base": pf["base"], "positions": pos, "bench": bench, "range": range_, "sector_of": sector_of or {},
            "bench_weights": bench_w, "vals": vals,
            **({} if sector_of is not None else {"sector_problem": "NOT RUNNABLE: THE SCREENER (SECTORS) IS UNAVAILABLE"}), "mixed_ccy": mixed, "data_path": path, "data_sha": sha, "labels": labels}


# --- FACT ---------------------------------------------------------------------------------------------------------------------------
FACTOR_TTL = 86400.0


async def _factors(request: Request) -> dict:
    """The Ken French daily factors (columnar, percent) through the router and the 24 h SWR cache."""
    s = svc(request)

    async def fetch() -> dict:
        out, failed = await s.router.call("factors", lambda p: p.factors())
        return {"data": {"dates": out["dates"], "cols": out["cols"]}, "source": out["source"], "fallback_from": failed}

    try:
        return await s.swr(ck.quant("kenfrench"), FACTOR_TTL, fetch)
    except DataError as e:
        raise DataError(e.kind, f"FACTOR DATA (KEN FRENCH): {e}", getattr(e, "detail", None)) from None


def _ymd(epoch: int) -> int:
    return int(time.strftime("%Y%m%d", time.gmtime(epoch)))


async def build_fact(request: Request, body: dict) -> dict:
    range_ = _range(body, "3Y")
    raw = body.get("symbol")
    pf = None
    sym = None
    if body.get("portfolio") not in (None, "") or raw in (None, ""):
        pf, why = await _pick(request, body)
        if pf is None:
            return {"not_runnable": why}
    else:
        if not isinstance(raw, str) or not raw.strip():
            raise _bad("SYMBOL MUST BE A SYMBOL OR A PORTFOLIO NAME")
        names = {p["name"].upper(): p["name"] for p in await portfolios(request).all()}
        if raw.strip().upper() in names:
            pf = await portfolios(request).get(names[raw.strip().upper()])
        else:
            sym = resolve(raw.strip().upper())
    if pf is not None:
        pos, why = _holdings(pf)
        if why:
            return {"not_runnable": why}
        syms = [p["symbol"] for p in pos]
        envs, _ = await _bars(request, syms, range_)
        fx, mixed, why = await _fx(request, pf, pos, envs)
        if why:
            return {"not_runnable": why}
        non_us = any("." in x for x in syms) or any(p["ccy"] not in (None, "", "USD") for p in pos)
        who: dict = {"name": pf["name"], "base": pf["base"], "positions": pos, "mixed_ccy": mixed}
    else:
        envs, _ = await _bars(request, [sym], range_)
        cur = envs[sym]["data"].get("currency")
        non_us = "." in sym or (cur not in (None, "", "USD", "XXX"))
        fx = {}
        who = {"symbol": sym}
    fenv = await _factors(request)
    first = min((_ymd(t) for e in envs.values() for t in e["data"]["t"][:1]), default=0)
    d = fenv["data"]
    i0 = next((i for i, x in enumerate(d["dates"]) if x >= first), len(d["dates"]))
    factors = {"dates": d["dates"][i0:], "cols": {k: v[i0:] for k, v in d["cols"].items()}}
    sha, path = await _stored(request, {"bars": {s: _slim(e) for s, e in envs.items()}, "factors": factors, "fx": fx})
    labels = _labels(request, envs)
    labels["sources"].append({"symbol": "KEN FRENCH", "name": fenv.get("source"), "as_of": fenv.get("as_of"), "age_s": fenv.get("age_s"),
                              "stale": bool(fenv.get("stale"))})
    labels["fallback_from"] = sorted({*labels["fallback_from"], *(fenv.get("fallback_from") or [])})
    age = fenv.get("age_s")
    label = (f"FACTORS FROM {str(fenv.get('source')).upper()}" + (f", AGE {age:.0f}s" if isinstance(age, int | float) else "")
             + (", STALE: OLDER THAN THEIR 24 H CACHE LIFETIME" if fenv.get("stale") else ""))
    return {**who, "range": range_, "non_us": non_us, "factor_label": label, "data_path": path, "data_sha": sha, "labels": labels}


# --- QL -----------------------------------------------------------------------------------------------------------------------------
def _ql_range(calc: str, body: dict, when: str | None, est: int) -> str:
    if body.get("range"):
        return _range(body, "1Y")
    if calc == "EVENT" and when:
        years = (date.today() - date.fromisoformat(when)).days / 365.25 + (est + 40) / 252
        return next((r for r, y in (("1Y", 1), ("2Y", 2), ("3Y", 3), ("5Y", 5), ("10Y", 10)) if years <= y), "20Y")
    return "3Y" if calc in ("GARCH", "HVAR") else "2Y" if calc == "EVENT" else "1Y"


def _ql_win(body: dict) -> list[int]:
    w = body.get("win")
    if w in (None, ""):
        return [-5, 5]
    parts = w if isinstance(w, list) else str(w).split(",")
    try:
        a, b = (int(str(x).strip()) for x in parts)
    except ValueError:
        raise _bad("WIN MUST BE TWO WHOLE NUMBERS LIKE -5,5") from None
    if not -250 <= a <= b <= 250:
        raise _bad("WIN MUST BE START,END WITH -250 <= START <= END <= 250")
    return [a, b]


async def build_ql(request: Request, body: dict) -> dict:
    calc = str(body.get("calc") or "").strip().upper()
    if calc not in QL_CALCS:
        raise _bad(f"CALC MUST BE {', '.join(QL_CALCS)}")
    raw = body.get("symbols", body.get("symbol"))
    raw = [] if raw in (None, "") else [raw] if isinstance(raw, str) else raw
    if not isinstance(raw, list) or len(raw) > 4 or not all(isinstance(x, str) and x.strip() for x in raw):
        raise _bad("SYMBOLS MUST BE A LIST OF AT MOST 4 SYMBOLS")
    symbols = [resolve(x.strip().upper()) for x in raw]
    h = _num(body, "h", 1, 60, 5, integer=True)
    conf = _num(body, "conf", 50, 99.9, 95.0)
    hor = _num(body, "hor", 1, 60, 1, integer=True)
    buckets = _num(body, "buckets", 2, 1000, 50, integer=True)
    est = _num(body, "est", 30, 2000, 120, integer=True)
    sr = _num(body, "sr", -10, 10, None)
    n = _num(body, "n", 1, 1e9, None, integer=True)
    t = _num(body, "t", 2, 1e9, None, integer=True)
    skew = _num(body, "skew", -50, 50, 0.0)
    kurt = _num(body, "kurt", 1, 1000, 3.0)
    trial = _num(body, "trial_sr_std", 0, 10, None)
    win = _ql_win(body)
    when = body.get("date")
    if when not in (None, ""):
        try:
            if not isinstance(when, str) or not DATE_RE.match(when):
                raise ValueError
            date.fromisoformat(when)
        except ValueError:
            raise _bad(f"BAD DATE: {str(when)[:24]} (USE YYYY-MM-DD)") from None
    else:
        when = None
    bench = _symbol(body, "bench", "SPY")
    need = 2 if calc in QL_PAIR else 1
    if calc == "DSR":
        missing = [k.upper() for k, v in (("sr", sr), ("n", n), ("t", t)) if v is None]
    else:
        missing = [f"SYMBOL{i + 1}" if need > 1 else "SYMBOL" for i in range(len(symbols), need)]
        if calc == "EVENT" and when is None:
            missing.append("DATE")
    base = {"calc": calc, "symbols": symbols}
    if missing:
        return {**base, "not_runnable": f"NOT RUNNABLE: MISSING {', '.join(missing)}"}
    if calc == "DSR":
        return {**base, "sr": sr, "n": n, "t": t, "skew": skew, "kurt": kurt, **({"trial_sr_std": trial} if trial is not None else {})}
    range_ = _ql_range(calc, body, when, est)
    use = symbols[:need]
    want = use + ([bench] if calc == "EVENT" and bench and bench not in use else [])
    envs, _ = await _bars(request, want, range_)
    keep = ("t", "c", "v") if calc in QL_VOLUME else ("t", "c")
    sha, path = await _stored(request, {"bars": {s: {k: e["data"][k] for k in keep} for s, e in envs.items()}})
    params = {**base, "symbols": use, "range": range_, "data_path": path, "data_sha": sha, "labels": _labels(request, envs)}
    if calc == "GARCH":
        params["h"] = h
    elif calc == "HVAR":
        params.update(conf=conf, hor=hor)
    elif calc == "VPIN":
        params["buckets"] = buckets
    elif calc == "EVENT":
        params.update(date=when, bench=bench or "SPY", win=win, est=est)
    return params


# --- ALPHA / CORR REGIME ------------------------------------------------------------------------------------------------------------
ALPHA_FAMILIES = ("core", "alpha101", "qlib158", "academic", "gtja191")  # core = the first 29, the default; ALL = every ported factor
MAX_REGIME = 50
TOP_N = 100


def _symbol_list(raw: str) -> list[str]:
    out = list(dict.fromkeys(resolve(x.strip().upper()) for x in raw.split(",") if x.strip()))
    if not all(re.match(r"^[A-Z0-9.^=\-]{1,20}$", x) for x in out):
        raise _bad("BAD SYMBOL IN LIST")
    return out


async def _named_list(request: Request, spec: str) -> tuple[str, list[str]]:
    """`WL:<name>` (a stored watchlist) or `LIST:A,B,C` -> (canonical spec, symbols)."""
    up = spec.strip()
    if up.upper().startswith("WL:"):
        wl = await user(request).watchlist(up[3:])
        return f"WL:{wl['name']}", list(wl["symbols"])
    if up.upper().startswith("LIST:"):
        syms = _symbol_list(up[5:])
        return "LIST:" + ",".join(syms), syms
    raise _bad("LIST MUST BE WL:<NAME> OR LIST:A,B,C")


async def _top100(request: Request) -> list[str]:
    try:
        uni = (await svc(request).screener())["data"]
    except DataError as e:
        raise DataError(e.kind, f"TOP100 NEEDS THE SCREENER: {e}", getattr(e, "detail", None)) from None
    i = uni["columns"].index("mcap")
    rows = [r for r in uni["rows"] if r[i] and re.match(r"^[A-Z]{1,5}$", r[0])]
    return [r[0] for r in sorted(rows, key=lambda r: -r[i])[:TOP_N]]


def _horizons(body: dict) -> list[int]:
    raw = body.get("h")
    if raw in (None, ""):
        return [1, 5, 10, 20]
    parts = raw if isinstance(raw, list) else [raw] if isinstance(raw, int | float) else str(raw).split(",")
    try:
        hs = sorted({int(str(x).strip()) for x in parts})
    except ValueError:
        raise _bad("H MUST BE WHOLE NUMBERS LIKE 1,5,10,20") from None
    if not hs or len(hs) > 8 or hs[0] < 1 or hs[-1] > 60:
        raise _bad("H MUST BE 1 TO 8 HORIZONS OF 1-60 DAYS")
    return hs


async def build_alpha(request: Request, body: dict) -> dict:
    spec = str(body.get("universe") or "TOP100").strip()
    fam = str(body.get("family") or "").strip().lower() or "core"
    if fam == "all":
        fam = None
    elif fam not in ALPHA_FAMILIES:
        raise _bad(f"FAMILY MUST BE {', '.join(f.upper() for f in ALPHA_FAMILIES)} OR ALL")
    hs = _horizons(body)
    range_ = _range(body, "2Y")
    kind = spec.upper()
    synthetic = kind == "SYN"
    if kind == "TOP100":
        universe, syms = "TOP100", await _top100(request)
    elif synthetic:
        universe, syms = "SYN", [f"SYN{i:04d}" for i in range(100)]
    elif kind.startswith(("WL:", "LIST:")):
        universe, syms = await _named_list(request, spec)
    else:
        raise _bad("UNIVERSE MUST BE TOP100, SYN, WL:<NAME> OR LIST:A,B,C")
    if len(syms) < 5:
        raise _bad(f"A CROSS-SECTION NEEDS AT LEAST 5 NAMES, {universe} HAS {len(syms)}")
    if len(syms) > 150:
        raise _bad("AT MOST 150 NAMES")
    envs, bad = await _bars(request, syms, range_, tolerate=True)
    if len(envs) < 5:
        why = next(iter(bad.values()), None)
        return {"not_runnable": f"NOT RUNNABLE: ONLY {len(envs)} OF {len(syms)} NAMES HAVE BARS" + (f" ({why})" if why else "")}
    keep = ("t", "o", "h", "l", "c", "v")
    sha, path = await _stored(request, {"bars": {s: {k: e["data"].get(k) for k in keep} for s, e in envs.items()}})
    return {"universe": universe, "symbols": list(envs), "range": range_, "family": fam, "h": hs, "failed": sorted(bad), "synthetic": synthetic,
            "data_path": path, "data_sha": sha, "labels": _labels(request, envs)}


async def build_regime(request: Request, body: dict) -> dict:
    win = _num(body, "win", 2, 500, 60, integer=True)
    edge = _num(body, "edge", 0, 1, 0.5)
    range_ = _range(body, "2Y")
    lst = body.get("list")
    if lst not in (None, ""):
        if not isinstance(lst, str):
            raise _bad("LIST MUST BE WL:<NAME> OR LIST:A,B,C")
        _, syms = await _named_list(request, lst)
    else:
        raw = body.get("symbols")
        if isinstance(raw, str):
            raw = raw.split(",")
        if not isinstance(raw, list) or not all(isinstance(x, str) and x.strip() for x in raw):
            raise _bad("SYMBOLS MUST BE A LIST OF AT LEAST 2 SYMBOLS (OR USE list)")
        syms = list(dict.fromkeys(resolve(x.strip().upper()) for x in raw))
    if len(syms) < 2:
        raise _bad("A CORRELATION REGIME NEEDS AT LEAST 2 SYMBOLS")
    if len(syms) > MAX_REGIME:
        raise _bad(f"AT MOST {MAX_REGIME} SYMBOLS")
    envs, _ = await _bars(request, syms, range_)
    sha, path = await _stored(request, {"bars": {s: _slim(e) for s, e in envs.items()}})
    return {"symbols": syms, "win": win, "edge": edge, "range": range_, "data_path": path, "data_sha": sha, "labels": _labels(request, envs)}


BUILD = {"risk": ("risk.run", build_risk), "opt": ("opt.run", build_opt), "attr": ("attr.run", build_attr), "fact": ("fact.run", build_fact),
         "ql": ("ql.run", build_ql), "alpha": ("alpha.scan", build_alpha), "regime": ("corr.regime", build_regime)}


@router.post("/quant/{fn}")
async def quant_run(request: Request, fn: str):
    if fn not in BUILD:  # BUILD is the one list of quant functions that exist
        return error(DataError("not_found", f"NO QUANT FUNCTION {fn.upper()}"))
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
