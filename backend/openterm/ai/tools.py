"""The agent's tools: an allow-list of OpenTerm's own read routes, called in-process (ASGI), with results shaped small.

So a tool returns exactly what the panels show, with the same source, age and STALE label. There are no order tools and no Kite tool: a test
scans names and paths. `backtest_run` writes one BT run (the existing store) and nothing else; every other tool only reads.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from .context import RESULT_LIMIT, truncate_text

JOB_WAIT_S = 90.0
QUANT_FNS = ("risk", "fact", "ql", "alpha", "regime")
RESEARCH_FNS = ("ee", "eeo", "anr", "mgmt", "cn", "dvd", "splt", "cacs", "ipo", "si", "evts", "etf", "memb", "mgr")


@dataclass
class ToolResult:
    ok: bool
    text: str
    source: str | None = None
    age_s: float | None = None
    stale: bool = False
    error: str | None = None
    empty: bool = False


# --- shaping helpers --------------------------------------------------------------------------------------------------------------------
def slim(obj: Any, max_list: int = 12, max_str: int = 240, depth: int = 0) -> Any:
    """Cut a JSON value down: long lists keep their head, long numeric series become {n, first, last}, long strings are clipped."""
    if depth > 6:
        return "..."
    if isinstance(obj, dict):
        return {k: slim(v, max_list, max_str, depth + 1) for k, v in obj.items()}
    if isinstance(obj, list):
        if len(obj) > 30 and all(isinstance(x, (int, float)) or x is None for x in obj):
            nums = [x for x in obj if x is not None]
            return {"n": len(obj), "first": nums[0] if nums else None, "last": nums[-1] if nums else None}
        head = [slim(x, max_list, max_str, depth + 1) for x in obj[:max_list]]
        return head + [f"...{len(obj) - max_list} MORE"] if len(obj) > max_list else head
    if isinstance(obj, str) and len(obj) > max_str:
        return obj[:max_str] + "..."
    return obj


def table_shape(d: dict, max_rows: int = 12) -> dict:
    """A Phase 13/14/15 table payload -> {title, headline, sections: [{title, rows: [{COLUMN: value}], total_rows}], notes}."""
    out: dict[str, Any] = {"title": d.get("title"), "headline": {h["label"]: h["value"] for h in d.get("headline") or []}, "sections": []}
    for s in d.get("sections") or []:
        cols = [(c["key"], c["title"]) for c in s.get("columns") or []]
        rows = [{title: r.get(key) for key, title in cols if r.get(key) is not None} for r in (s.get("rows") or [])[:max_rows]]
        out["sections"].append({"title": s.get("title"), "rows": rows, "total_rows": len(s.get("rows") or []), **({"note": s["note"]} if s.get("note") else {})})
    if d.get("notes"):
        out["notes"] = d["notes"][:4]
    if d.get("key_required"):
        out["key_required"] = d["key_required"]
    if d.get("status"):
        out["status"] = d["status"]
    return out


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d")


def shape_history(env: dict, args: dict) -> dict:
    d = env["data"]
    t, c = d.get("t") or [], d.get("c") or []
    bars = [(ts, cl, h, lo, v) for ts, cl, h, lo, v in zip(t, c, d.get("h") or c, d.get("l") or c, d.get("v") or [0] * len(c), strict=False) if cl is not None]
    if not bars:
        return {"symbol": d.get("symbol"), "n_bars": 0}
    closes = [b[1] for b in bars]
    vols = [b[4] for b in bars if b[4] is not None]
    return {"symbol": d.get("symbol"), "range": d.get("range"), "interval": d.get("interval"), "currency": d.get("currency"), "n_bars": len(bars),
            "first": {"date": _iso(bars[0][0]), "close": bars[0][1]}, "last": {"date": _iso(bars[-1][0]), "close": bars[-1][1]},
            "period_return_pct": (closes[-1] / closes[0] - 1.0) * 100.0 if closes[0] else None,
            "high": max(b[2] for b in bars if b[2] is not None), "low": min(b[3] for b in bars if b[3] is not None),
            "avg_volume": sum(vols) / len(vols) if vols else None,
            "recent": [{"date": _iso(b[0]), "close": b[1]} for b in bars[-10:]]}


QUOTE_KEYS = ("symbol", "name", "currency", "price", "prev_close", "change", "change_pct", "open", "high", "low", "volume", "market_cap", "state", "market_state")


def shape_quote(resp: dict, args: dict) -> dict:
    out = {}
    for sym, env in (resp.get("results") or {}).items():
        if isinstance(env, dict) and "data" in env:
            row = {k: env["data"][k] for k in QUOTE_KEYS if env["data"].get(k) is not None}
            row.update(source=env.get("source"), age_s=env.get("age_s"), stale=bool(env.get("stale")))
            out[sym] = row
        else:
            out[sym] = {"error": (env or {}).get("error", "NO DATA") if isinstance(env, dict) else "NO DATA"}
    return out


def shape_news(env: dict, args: dict) -> dict:
    items = (env["data"].get("items") or [])[:8]
    return {"query": env["data"].get("query"), "items": [{k: i.get(k) for k in ("title", "publisher", "published", "summary", "url") if i.get(k)} for i in items]}


def shape_filings(env: dict, args: dict) -> dict:
    d = env["data"]
    fl = [f for f in d.get("filings") or [] if not args.get("form") or f.get("form") == args["form"].upper()][:15]
    return {"company": d.get("name"), "cik": d.get("cik"), "filings": [{k: f.get(k) for k in ("form", "filed", "report_date", "description", "url") if f.get(k)} for f in fl]}


def shape_screener(env: dict, args: dict) -> dict:
    d = env["data"]
    cols = d["columns"]
    ix = {c: i for i, c in enumerate(cols)}
    rows = d["rows"]
    if args.get("sector"):
        want = str(args["sector"]).lower()
        ids = {i for i, name in enumerate(d.get("sectors") or []) if want in name.lower()}
        rows = [r for r in rows if r[ix["sector"]] in ids]
    if args.get("min_mcap") is not None:
        rows = [r for r in rows if (r[ix["mcap"]] or 0) >= float(args["min_mcap"])]
    sort = {"mcap": "mcap", "pct": "pct", "volume": "volume"}.get(args.get("sort") or "mcap", "mcap")
    rows = sorted(rows, key=lambda r: r[ix[sort]] if r[ix[sort]] is not None else float("-inf"), reverse=args.get("order", "desc") != "asc")
    limit = max(1, min(int(args.get("limit") or 10), 25))
    sectors = d.get("sectors") or []
    return {"matches": len(rows), "universe": d.get("count"), "rows": [
        {"symbol": r[ix["symbol"]], "name": r[ix["name"]], "last": r[ix["last"]], "pct": r[ix["pct"]], "volume": r[ix["volume"]], "mcap": r[ix["mcap"]],
         "sector": sectors[r[ix["sector"]]] if r[ix["sector"]] < len(sectors) else None} for r in rows[:limit]]}


def shape_table_env(env: dict, args: dict) -> dict:
    return table_shape(env["data"])


def shape_slim(env: dict, args: dict) -> dict:
    return slim(env.get("data", env))


# --- the registry -----------------------------------------------------------------------------------------------------------------------
def obj(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": properties, "required": required or [], "additionalProperties": False}


S = {"type": "string"}


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict
    path: str
    method: str = "GET"
    build: Callable[[dict], dict] = field(default=lambda a: {"params": a})
    shape: Callable[[dict, dict], Any] = shape_slim
    job: bool = False  # POST returns a job: wait for it and shape its result
    local: Callable[[dict, dict], dict] | None = None  # answered in this process, no route (skill, strategy_check, doc_search); gets the runner's context
    doc_only: bool = False  # offered only to an AI DOC run, never in plain chat


def _bt_body(a: dict) -> dict:
    body: dict[str, Any] = {"symbols": a["symbols"], "range": a.get("range") or "5Y", "interval": a.get("interval") or "1D", "options": a.get("options") or {}}
    body["rule"] = a["rule"]
    return {"json": body}


def _rates(a: dict) -> dict:
    ccy = (a.get("ccy") or "USD").upper()
    return {"path": "/api/rates", "params": {}} if ccy == "USD" else {"path": "/api/rates/curve", "params": {"ccy": ccy}}


def _portfolio(a: dict) -> dict:
    return {"path": f"/api/portfolios/{a['name']}"} if a.get("name") else {"path": "/api/portfolios"}


def _skill(a: dict, ctx: dict) -> dict:
    from . import skills

    return {"name": a["name"], "playbook": skills.get(a["name"])}


def _strategy_check(a: dict, ctx: dict) -> dict:
    """Parse a BT rule with the engine's own parser. A rejected rule is information for the model, not a failed call."""
    from ..bt import rules

    try:
        node = rules.parse(a["rule"])
    except rules.RuleError as e:
        return {"valid": False, "error": str(e), "col": e.col, "grammar": "CLOSE|OPEN|HIGH|LOW|VOLUME|SMA<n>|EMA<n>|RSI<n>|HIGH<n>|LOW<n>|RET<n> or a number; > < >= <= CROSS> CROSS<; AND OR"}
    return {"valid": True, "rule": a["rule"], "warmup_bars": rules.max_period(node)}


def _doc_search(a: dict, ctx: dict) -> dict:
    from . import doc

    d = ctx.get("doc")
    if d is None:
        raise ValueError("NO DOCUMENT LOADED: use AI DOC to load one")
    return doc.doc_search(d, a["query"], int(a.get("k") or 3))


def _skill_names() -> list[str]:
    from . import skills

    return skills.names()


REGISTRY: dict[str, Tool] = {t.name: t for t in [
    Tool("skill", "Load a finance playbook (steps and limits) before answering a valuation, earnings, options, risk or macro question.",
         obj({"name": {"type": "string", "enum": ["valuation", "earnings", "options", "risk", "macro"]}}, ["name"]), "local:skill", local=_skill),
    Tool("strategy_check", "Check a backtest rule with the engine's own parser, for example 'SMA20 CROSS> SMA50' or 'RSI14 < 30'. Returns valid or the error and its column.",
         obj({"rule": S}, ["rule"]), "local:strategy_check", local=_strategy_check),
    Tool("doc_search", "Search the loaded document for passages about a topic; returns the best chunks labelled C1, C2... Cite them.",
         obj({"query": S, "k": {"type": "integer"}}, ["query"]), "local:doc_search", local=_doc_search, doc_only=True),
    Tool("quote", "Latest quote for one or more tickers (comma separated, up to 10): price, change, volume, market cap.",
         obj({"symbols": S}, ["symbols"]), "/api/quote", shape=shape_quote),
    Tool("history", "Daily price history summary for one ticker: first and last close, period return, high, low, average volume, last 10 closes.",
         obj({"symbol": S, "range": {"type": "string", "description": "1M 3M 6M 1Y 2Y 5Y 10Y"}}, ["symbol"]), "/api/history", shape=shape_history),
    Tool("profile", "Company profile: sector, industry, country, employees, business description.", obj({"symbol": S}, ["symbol"]), "/api/profile", shape=shape_slim),
    Tool("fa", "Financial statements (income statement, balance sheet, cash flow) from SEC filings. period A = annual, Q = quarterly.",
         obj({"symbol": S, "period": {"type": "string", "enum": ["A", "Q"]}}, ["symbol"]), "/api/fa", shape=shape_slim),
    Tool("filings", "Recent SEC filings for a ticker (optionally one form type such as 10-K, 10-Q, 8-K).",
         obj({"symbol": S, "form": S}, ["symbol"]), "/api/filings", shape=shape_filings),
    Tool("news", "Recent news headlines for a ticker or a text query.", obj({"symbol": S, "q": S}), "/api/news", shape=shape_news),
    Tool("screener", "Screen the US universe: optional sector name, minimum market cap (US$), sort by mcap, pct or volume, limit up to 25.",
         obj({"sector": S, "min_mcap": {"type": "number"}, "sort": {"type": "string", "enum": ["mcap", "pct", "volume"]},
              "order": {"type": "string", "enum": ["asc", "desc"]}, "limit": {"type": "integer"}}), "/api/screener", shape=shape_screener),
    Tool("research", "A research table for a ticker: ee (earnings estimates), eeo, anr (analyst ratings), mgmt, cn (company news), dvd (dividends), "
         "splt, cacs, ipo, si (short interest), evts, etf, memb, mgr.",
         obj({"fn": {"type": "string", "enum": list(RESEARCH_FNS)}, "symbol": S}, ["fn"]), "/api/research/{fn}",
         build=lambda a: {"path": f"/api/research/{a['fn']}", "params": {k: v for k, v in a.items() if k != "fn"}}, shape=shape_table_env),
    Tool("options_chain", "Option chain monitor for a ticker (optional expiry date YYYY-MM-DD): strikes, bid/ask, implied vol, open interest.",
         obj({"symbol": S, "date": S}, ["symbol"]), "/api/deriv/omon", shape=shape_table_env),
    Tool("rates", "Government yield curve (default USD; also EUR, GBP, CAD, JPY) with 2s10s spread.", obj({"ccy": S}), "/api/rates", build=_rates, shape=shape_slim),
    Tool("macro", "Search macro series (FRED-style catalog) by text, for example 'cpi' or 'unemployment'.", obj({"q": S}), "/api/macro", shape=shape_slim),
    Tool("portfolio", "The user's portfolios: with no name, the list; with a name, its positions (symbol, quantity, cost).", obj({"name": S}), "/api/portfolios",
         build=_portfolio, shape=shape_slim),
    Tool("backtest_run", "Run a historical backtest of a rule such as 'SMA20>SMA50' on 1-10 symbols. A historical simulation, not a forecast. Returns the run id and metrics.",
         obj({"symbols": {"type": "array", "items": S}, "rule": S, "range": S, "interval": S, "options": {"type": "object"}}, ["symbols", "rule"]),
         "/api/bt/run", method="POST", build=_bt_body, shape=shape_slim, job=True),
    Tool("backtest_get", "Metrics of a stored backtest run by run id.", obj({"run_id": S}, ["run_id"]), "/api/bt/runs/{run_id}",
         build=lambda a: {"path": f"/api/bt/runs/{a['run_id']}"}, shape=shape_slim),
    Tool("quant", "Quant analytics job: risk (portfolio VaR and drawdown, args {portfolio}), fact (factor regression, args {symbol}), ql (calculators, args {calc, symbol}), "
         "alpha (alpha zoo scan, args {universe}), regime (correlation regime, args {list}).",
         obj({"fn": {"type": "string", "enum": list(QUANT_FNS)}, "args": {"type": "object"}}, ["fn"]), "/api/quant/{fn}", method="POST",
         build=lambda a: {"path": f"/api/quant/{a['fn']}", "json": a.get("args") or {}}, shape=shape_table_env, job=True),
]}


def openai_tools(names: list[str] | None = None) -> list[dict]:
    return [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
            for t in REGISTRY.values() if (t.name in names if names is not None else not t.doc_only)]


# Arguments that are put into a route path: nothing may leave the route (httpx resolves `..`, so "../../keys" would reach /api/keys).
PATH_ARGS = {"name": re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,31}\Z"), "run_id": re.compile(r"^[A-Za-z0-9_\-]{1,64}\Z")}
TYPES: dict[str, tuple[type, ...]] = {"string": (str,), "integer": (int, str), "number": (int, float, str), "array": (list,), "object": (dict,)}


def _wrong_type(spec: dict, v: Any) -> bool:
    want = TYPES.get(spec.get("type", ""))
    if want is None:
        return False
    if isinstance(v, bool):
        return True
    if isinstance(v, float) and spec["type"] == "integer":  # JSON clients often send 10.0 for 10
        return not v.is_integer()
    if not isinstance(v, want):
        return True
    if isinstance(v, str) and spec["type"] in ("integer", "number"):  # a model often sends "5" for 5
        try:
            float(v)
        except ValueError:
            return True
    return False


def validate(name: str, args: Any) -> str | None:
    """An error message for the model, or None if the call is well formed."""
    t = REGISTRY.get(name)
    if t is None:
        return f"UNKNOWN TOOL {name}: use one of {', '.join(REGISTRY)}"
    if not isinstance(args, dict):
        return "ARGUMENTS MUST BE A JSON OBJECT"
    props = t.parameters["properties"]
    for k in args:
        if k not in props:
            return f"UNKNOWN ARGUMENT {k} for {name}: allowed {', '.join(props)}"
    for k in t.parameters["required"]:
        if args.get(k) in (None, "", []):
            return f"MISSING ARGUMENT {k} for {name}"
    for k, v in args.items():
        if _wrong_type(props[k], v):
            return f"ARGUMENT {k} MUST BE OF TYPE {props[k]['type'].upper()}"
        enum = props[k].get("enum")
        if enum and v not in enum:
            return f"ARGUMENT {k} MUST BE ONE OF {', '.join(map(str, enum))}"
        if k in PATH_ARGS and name in ("backtest_get", "portfolio") and not PATH_ARGS[k].match(v):
            return f"ARGUMENT {k} IS NOT A VALID {k.upper()}"
    return None


def _meta(resp: dict) -> tuple[str | None, float | None, bool]:
    env = next(iter((resp.get("results") or {}).values()), None) if "results" in resp and "data" not in resp else resp
    if isinstance(env, dict):
        return env.get("source"), env.get("age_s"), bool(env.get("stale"))
    return None, None, False


def _is_empty(shaped: Any) -> bool:
    if shaped in (None, {}, []):
        return True
    if isinstance(shaped, dict):
        if shaped.get("n_bars") == 0:
            return True
        secs = shaped.get("sections")
        if secs is not None and not any(s.get("total_rows") for s in secs):
            return True
        for k in ("rows", "items", "filings", "matches"):
            if k in shaped and shaped[k] == []:
                return True
    return False


class ToolRunner:
    """Calls the allow-listed routes of the running app in-process, as the local user."""

    def __init__(self, app, client=("127.0.0.1", 50000), tools: list[str] | None = None, context: dict | None = None):
        self.ctx = context or {}
        self.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=client), base_url="http://openterm.local", timeout=120.0)
        self.allowed = set(tools) if tools is not None else None

    async def aclose(self) -> None:
        await self.http.aclose()

    async def __call__(self, name: str, args: dict) -> ToolResult:
        return await self.call(name, args)

    async def call(self, name: str, args: dict) -> ToolResult:
        if (err := validate(name, args)) or (self.allowed is not None and name not in self.allowed):
            return ToolResult(ok=False, text=err or f"TOOL {name} IS NOT AVAILABLE HERE", error=err or "NOT AVAILABLE")
        t = REGISTRY[name]
        if t.local is not None:
            try:
                data = t.local(args, self.ctx)
            except (OSError, ValueError, KeyError) as e:
                msg = f"TOOL ERROR {type(e).__name__}: {str(e)[:120]}"
                return ToolResult(ok=False, text=msg, error=msg)
            return ToolResult(ok=True, text=truncate_text(json.dumps(data, separators=(",", ":")), RESULT_LIMIT), source=data.get("source", "openterm"), age_s=0.0, empty=_is_empty(data))
        spec = {"path": t.path, **t.build(args)}
        try:
            r = await self.http.request(t.method, spec["path"], params=spec.get("params"), json=spec.get("json"))
            body = r.json()
            if r.status_code >= 400:
                msg = f"HTTP {r.status_code}: {body.get('error', 'ERROR') if isinstance(body, dict) else 'ERROR'}"
                return ToolResult(ok=False, text=msg, error=msg)
            if t.job:
                run_id = body.get("run_id") if isinstance(body, dict) else None
                body = await self._wait(body)
                if isinstance(body, str):
                    return ToolResult(ok=False, text=body, error=body)
                if run_id and name == "backtest_run":  # the job result is a summary: the stored run has the metrics
                    got = await self.http.get(f"/api/bt/runs/{run_id}")
                    body = {**got.json(), "run_id": run_id} if got.status_code == 200 else body
            shaped = t.shape(body if isinstance(body, dict) else {"data": body}, args)
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError, IndexError, ArithmeticError) as e:  # a shaper hit an odd payload
            msg = f"TOOL ERROR {type(e).__name__}: {str(e)[:120]}"
            return ToolResult(ok=False, text=msg, error=msg)
        source, age, stale = _meta(body if isinstance(body, dict) else {})
        text = truncate_text(json.dumps(shaped, default=str, separators=(",", ":")), RESULT_LIMIT)
        return ToolResult(ok=True, text=text, source=source, age_s=age, stale=stale, empty=_is_empty(shaped))

    async def _wait(self, job: dict) -> dict | str:
        """Poll a job until it is done: its result envelope, or an error string."""
        end = time.monotonic() + JOB_WAIT_S
        while True:
            if job.get("state") == "done":
                if job.get("run"):
                    return job["run"]
                res = job.get("result")
                return res if isinstance(res, dict) else {"data": res}
            if job.get("state") in ("failed", "cancelled", "error") or "id" not in job:
                return f"JOB {job.get('state', 'FAILED').upper()}: {str(job.get('error') or job.get('msg') or '')[:120]}"
            if time.monotonic() > end:
                return "JOB DID NOT FINISH IN TIME"
            await asyncio.sleep(0.25)
            job = (await self.http.get(f"/api/jobs/{job['id']}")).json()
