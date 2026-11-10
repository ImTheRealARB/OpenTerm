"""The client. Every method is a read (HTTP GET) of an endpoint OpenTerm already serves; nothing here writes or trades.

Honesty rules, which the tests check:
  * `source=` pins one data source for the call. OpenTerm then asks ONLY that source: if it cannot answer you get an
    exception whose text starts `SRC=NAME:`, never data from another source.
  * every market-data DataFrame carries `source`, `as_of` (epoch seconds when OpenTerm fetched it), `as_of_iso`, `age_s`,
    `stale` and `fallback_from` in `df.attrs`. A stale answer is returned flagged (or raised, see `raise_on_stale`).
  * a missing value stays NaN/None. The SDK never fills, interpolates or invents.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx
import pandas as pd
from typing_extensions import Self

from .errors import BackendDown, BadRequest, OpenTermError, StaleData, from_reply

_SOURCE_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}\Z")
DEFAULT_URL = "http://127.0.0.1:8000"


def _iso(epoch: float | None) -> str | None:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat() if epoch is not None else None


@dataclass
class BacktestRun:
    """A stored backtest result, read-only. `metrics` are OpenTerm's own numbers, untouched."""

    id: str
    metrics: dict[str, Any]
    equity: pd.DataFrame
    trades: pd.DataFrame
    config: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)


class OpenTerm:
    """`OpenTerm(base_url="http://127.0.0.1:8000")`. Pass `transport=httpx.MockTransport(...)` in tests.

    source: default pin for every call (a per-call `source=` overrides it).
    raise_on_stale: raise `StaleData` instead of returning an answer OpenTerm served from its stale cache.
    """

    def __init__(self, base_url: str = DEFAULT_URL, *, source: str | None = None, timeout: float = 30.0,
                 raise_on_stale: bool = False, transport: httpx.BaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self.source = self._clean_source(source)
        self.raise_on_stale = raise_on_stale
        self._http = httpx.Client(base_url=self.base_url, timeout=timeout, transport=transport)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- transport ---------------------------------------------------------------------------------
    @staticmethod
    def _clean_source(source: str | None) -> str | None:
        if source is None or not str(source).strip():
            return None
        name = str(source).strip().lower()
        if not _SOURCE_RE.match(name):
            raise BadRequest(f"SRC={str(source).strip().upper()[:40]}: NOT A SOURCE NAME", kind="bad_request")
        return name

    def _get(self, path: str, params: dict[str, Any] | None = None, *, source: str | None = None, pin: bool = True) -> Any:
        q = {k: v for k, v in (params or {}).items() if v is not None}
        if pin:
            pinned = self._clean_source(source) or self.source
            if pinned:
                q["source"] = pinned
        try:
            r = self._http.get(path, params=q)
        except httpx.TransportError as e:
            raise BackendDown(f"NO OPENTERM AT {self.base_url}: START IT FIRST", kind="unavailable",
                              detail=type(e).__name__) from e
        try:
            body = r.json()
        except ValueError:
            body = None
        if r.status_code >= 400:
            raise from_reply(r.status_code, body)
        return body

    def _meta(self, env: dict[str, Any]) -> dict[str, Any]:
        stale = bool(env.get("stale"))
        if stale and self.raise_on_stale:
            raise StaleData(f"STALE: {env.get('source')} ANSWER IS {env.get('age_s')} S OLD", kind="stale",
                            source=env.get("source"))
        as_of = env.get("as_of")
        return {"source": env.get("source"), "as_of": as_of, "as_of_iso": _iso(as_of), "age_s": env.get("age_s"),
                "stale": stale, "fallback_from": list(env.get("fallback_from") or []),
                **({"fallback_notes": env["fallback_notes"]} if env.get("fallback_notes") else {})}

    # --- market data ---------------------------------------------------------------------------------
    def quote(self, symbols: str | list[str], *, source: str | None = None) -> pd.DataFrame:
        """One row per symbol, indexed by symbol, with that row's own `source`, `as_of`, `age_s`, `stale` columns.

        A single symbol that cannot be quoted raises. With several, the ones that failed are left out and named in
        `df.attrs["errors"]` ({symbol: message}); if none succeeded it raises. `df.attrs` summarises: `source` is the one
        source or "mixed", `as_of` the oldest, `stale` true if any row is.
        """
        wanted = [symbols] if isinstance(symbols, str) else list(symbols)
        if not wanted:
            raise BadRequest("NO SYMBOLS", kind="bad_request")
        results = self._get("/api/quote", {"symbols": ",".join(wanted)}, source=source)["results"]
        rows, errors, envs = [], {}, []
        for sym in wanted:
            env = results.get(sym)
            if not isinstance(env, dict) or "error" in env or "data" not in env:
                errors[sym] = env.get("error", "NO ANSWER") if isinstance(env, dict) else "NO ANSWER"
                if isinstance(env, dict) and len(wanted) == 1:
                    raise from_reply(400, env)
                continue
            envs.append(env)
            rows.append({**env["data"], "source": env["source"], "as_of": env["as_of"], "age_s": env["age_s"],
                         "stale": bool(env["stale"]), "fallback_from": list(env.get("fallback_from") or [])})
        if not rows:
            first = next((v for v in results.values() if isinstance(v, dict)), None)
            raise from_reply(400, first) if first else OpenTermError("NO ANSWER")
        stale = any(e["stale"] for e in envs)
        if stale and self.raise_on_stale:
            raise StaleData("STALE: SOME QUOTES CAME FROM OPENTERM'S STALE CACHE", kind="stale")
        df = pd.DataFrame(rows).set_index("symbol")
        sources = {e["source"] for e in envs}
        oldest = min(envs, key=lambda e: e["as_of"])
        df.attrs.update(source=sources.pop() if len(sources) == 1 else "mixed", as_of=oldest["as_of"],
                        as_of_iso=_iso(oldest["as_of"]), age_s=max(e["age_s"] for e in envs), stale=stale,
                        fallback_from=sorted({n for e in envs for n in e.get("fallback_from") or []}), errors=errors)
        return df

    def history(self, symbol: str, range: str | None = None, interval: str | None = None, *,
                source: str | None = None) -> pd.DataFrame:
        """OHLCV bars indexed by UTC time (`open high low close volume`, plus `adj` / `fund` / `oi` when the source has them)."""
        env = self._get("/api/history", {"symbol": symbol, "range": range, "interval": interval}, source=source)
        d = env["data"]
        cols = {"open": d["o"], "high": d["h"], "low": d["l"], "close": d["c"], "volume": d["v"]}
        for k in ("adj", "fund", "oi"):
            if d.get(k) is not None:
                cols[k] = d[k]
        df = pd.DataFrame(cols, index=pd.to_datetime(d["t"], unit="s", utc=True).rename("time"))
        df.attrs.update(self._meta(env), symbol=d.get("symbol", symbol), range=d.get("range"), interval=d.get("interval"),
                        currency=d.get("currency"), exchange=d.get("exchange"), tz=d.get("tz"))
        return df

    bars = history

    def profile(self, symbol: str, *, source: str | None = None) -> dict[str, Any]:
        """The instrument description as a dict; the envelope fields (`source`, `as_of`, `stale` ...) are under `"_meta"`."""
        env = self._get("/api/profile", {"symbol": symbol}, source=source)
        return {**env["data"], "_meta": self._meta(env)}

    def search(self, query: str, *, source: str | None = None) -> pd.DataFrame:
        env = self._get("/api/search", {"q": query}, source=source)
        df = pd.DataFrame(env["data"])
        df.attrs.update(self._meta(env))
        return df

    def news(self, symbol: str | None = None, *, query: str | None = None, region: str | None = None,
             sector: str | None = None, commodity: str | None = None, section: str | None = None,
             limit: int | None = None, source: str | None = None) -> pd.DataFrame:
        """Headlines (title, url, publisher, published, summary, source, sentiment). OpenTerm never stores article bodies.
        `published` is a UTC datetime; items without one keep NaT."""
        env = self._get("/api/news", {"symbol": symbol, "q": query, "region": region, "sector": sector,
                                      "commodity": commodity, "section": section, "limit": limit}, source=source)
        df = pd.DataFrame(env["data"]["items"])
        df.attrs.update(self._meta(env), kind=env["data"].get("kind"), failed_feeds=env["data"].get("failed"))
        if "published" in df:
            df["published"] = pd.to_datetime(df["published"], unit="s", utc=True)
        return df

    def fundamentals(self, symbol: str, period: str = "A", statement: str = "IS") -> pd.DataFrame:
        """SEC company-facts statements (US filers only; no `source=`, SEC is the only source). `statement` is IS, BS or
        CF; `period` is A or Q. Rows are line items, columns are period ends; a value the filing lacks stays NaN."""
        statement = statement.upper()
        if statement not in ("IS", "BS", "CF"):
            raise BadRequest("STATEMENT: IS, BS OR CF", kind="bad_request")
        env = self._get("/api/fa", {"symbol": symbol, "period": period}, pin=False)
        d = env["data"]
        rows = d["statements"][statement]
        df = pd.DataFrame([r["values"] for r in rows], index=pd.Index([r["key"] for r in rows], name="item"),
                          columns=[p["end"] for p in d["periods"]])
        df.attrs.update(self._meta(env), symbol=d.get("symbol", symbol), period=d.get("period", period),
                        statement=statement, currency=d.get("currency"), labels={r["key"]: r["label"] for r in rows},
                        units={r["key"]: r["unit"] for r in rows}, derived={p["end"]: p["derived"] for p in d["periods"]})
        return df

    financials = fundamentals

    def sources(self) -> dict[str, Any]:
        """OpenTerm's `/api/sources`: which providers exist (the valid `source=` names), their health, which keys are set."""
        return self._get("/api/sources", pin=False)

    # --- the user's own data, read only ------------------------------------------------------------------
    def portfolios(self) -> pd.DataFrame:
        return pd.DataFrame(self._get("/api/portfolios", pin=False)["portfolios"])

    def portfolio(self, name: str) -> pd.DataFrame:
        """The saved positions as stored (no prices added). `attrs`: name, base currency, updated_at. Local data: no source."""
        d = self._get(f"/api/portfolios/{name}", pin=False)
        df = pd.DataFrame(d["positions"])
        df.attrs.update(name=d["name"], base=d["base"], updated_at=d["updated_at"], updated_at_iso=_iso(d["updated_at"]))
        return df

    def backtests(self) -> pd.DataFrame:
        """Stored backtest runs (id, strategy, symbols, interval, range, metrics ...). Runs are made in OpenTerm (BT), not here."""
        df = pd.DataFrame(self._get("/api/bt/runs", pin=False)["runs"])
        if "created_at" in df:
            df["created_at"] = pd.to_datetime(df["created_at"], unit="s", utc=True)
        return df

    def backtest(self, run_id: str) -> BacktestRun:
        d = self._get(f"/api/bt/runs/{run_id}", pin=False)

        def curve(points: list[list[float]] | None) -> pd.Series:
            pts = points or []
            return pd.Series([p[1] for p in pts], index=pd.to_datetime([p[0] for p in pts], unit="s", utc=True).rename("time"))

        equity = pd.DataFrame({"equity": curve(d.get("equity"))})
        if d.get("benchmark"):
            equity["benchmark"] = curve(d["benchmark"])
        trades = pd.DataFrame(d.get("trades") or [])
        meta = {k: d.get(k) for k in ("rule", "strategy", "symbols", "interval", "range", "engine", "labels", "created_at")}
        equity.attrs.update(run_id=d["id"], engine=d.get("engine"))
        trades.attrs.update(run_id=d["id"])
        return BacktestRun(id=d["id"], metrics=d.get("metrics") or {}, equity=equity, trades=trades,
                           config=d.get("config") or {}, meta=meta)
