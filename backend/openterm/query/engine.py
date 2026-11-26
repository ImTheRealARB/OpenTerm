"""Runs a parsed QRY (query/lang.py) against the services the panels already use, and builds the table payload. The same function
answers the QRY panel (`/api/query`), the SDK and the Excel bridge (`/api/xl/...`), so all three always agree.

Snapshot order of work (cheapest first, so a big universe is narrowed before the slow per-symbol calls):
  1. resolve the universe (scanner words, a list, or US = the screener file);
  2. screener fields (one file for the whole US market) and the WHERE conditions on them;
  3. quote fields (one batched call) and their conditions;
  4. Yahoo key statistics (one call per symbol, at most PER_SYMBOL_CAP symbols) and their conditions;
  5. SORT, LIMIT.
A value a source did not give stays empty (a condition on it fails: never read as zero).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from typing import Any

from ..errors import DataError
from ..redact import redact
from ..research.table import col, head, payload, section
from ..router import AllFailed
from ..scanner import universe as U
from . import lang as L

MAX_SERIES_SYMBOLS = 20
MAX_QUOTE_SYMBOLS = 800
STATS_CONCURRENCY = 6


def _bad(e: Exception) -> DataError:
    return DataError("bad_request", str(e))


async def _symbols(app: Any, q: L.Query, screener: dict[str, dict] | None) -> tuple[list[str], str]:
    if q.universe == "US":
        if screener is None:
            raise DataError("bad_request", "FOR US NEEDS THE SCREENER FILE")
        return sorted(screener), "US LISTED (SCREENER FILE)"
    if q.universe.startswith("LIST:"):
        syms = [s for s in q.universe[5:].split(",") if s]
        return (syms if q.series else U.clean(syms)), "YOUR LIST"
    from ..scanner.routes import (
        resolve_universe,  # the scan routes own the async resolution (watchlists, N-PORT, NSE lists)
    )

    try:
        syms, _, where = await resolve_universe(app, q.universe, None)
    except U.UniverseError as e:
        raise _bad(e) from e
    return syms, where


async def _screener(svc: Any) -> dict[str, dict]:
    env = await svc.screener()
    d = env["data"]
    cols = d["columns"]
    # sector / industry / country arrive as indexes into the payload's lookup lists (it keeps the ~1 MB file small)
    lookups = {"sector": d.get("sectors") or [], "industry": d.get("industries") or [], "country": d.get("countries") or []}
    out = {}
    for r in d["rows"]:
        row = dict(zip(cols, r, strict=False)) if isinstance(r, list) else dict(r)
        for k, names in lookups.items():
            v = row.get(k)
            if isinstance(v, int) and 0 <= v < len(names):
                row[k] = names[v]
        if row.get("symbol"):
            out[str(row["symbol"]).upper()] = row
    return out


def _stat(raw: dict, path: tuple[str, ...]) -> float | None:
    mod, key = path
    v = (raw.get(mod) or {}).get(key)
    v = v.get("raw") if isinstance(v, dict) else v
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


async def snapshot(app: Any, q: L.Query) -> dict:
    svc = app.state.service
    groups = L.needed_groups(q)
    notes: list[str] = []
    screener = await _screener(svc) if "screener" in groups or q.universe == "US" else None
    syms, where = await _symbols(app, q, screener)
    total = len(syms)
    rows = {s: {"symbol": s} for s in syms}

    def keep(group: str) -> None:
        conds = [c for c in q.where if L.FIELDS[c.field].group == group]
        if conds:
            for s in [s for s, r in rows.items() if not L.passes(r, conds)]:
                del rows[s]

    if screener is not None:
        for s, r in rows.items():
            src = screener.get(s.upper()) or {}
            for f in ("name", "mcap", "sector", "industry", "country"):
                r[f] = src.get(f)
        if "screener" in groups and any(screener.get(s.upper()) is None for s in rows):
            notes.append("SYMBOLS OUTSIDE THE US SCREENER FILE HAVE NO NAME / MCAP / SECTOR (THEY FAIL A WHERE ON THOSE FIELDS)")
        keep("screener")
    if "quote" in groups:
        if len(rows) > MAX_QUOTE_SYMBOLS:
            raise DataError("bad_request", f"{len(rows)} SYMBOLS FOR QUOTE FIELDS (MAX {MAX_QUOTE_SYMBOLS}): NARROW FIRST WITH A SCREENER FIELD, E.G. WHERE mcap>1e10")
        got = await svc.quotes(list(rows))
        failed = 0
        for s, r in rows.items():
            qd = (got.get(s) or {}).get("data")
            qd = qd.model_dump() if hasattr(qd, "model_dump") else qd
            if not isinstance(qd, dict):
                failed += 1
                continue
            for f in ("last", "chg", "pct", "volume", "open", "high", "low", "prev"):
                r[f] = qd.get(L.FIELDS[f].path[0])
        if failed:
            notes.append(f"NO QUOTE FOR {failed} SYMBOL(S): THEIR QUOTE FIELDS ARE EMPTY")
        keep("quote")
    if "stats" in groups:
        if len(rows) > L.PER_SYMBOL_CAP:
            raise DataError("bad_request", f"{len(rows)} SYMBOLS FOR KEY-STATISTICS FIELDS (ONE CALL EACH, MAX {L.PER_SYMBOL_CAP}): "
                                           "NARROW FIRST WITH A SCREENER OR QUOTE FIELD, E.G. WHERE mcap>5e10")
        sem = asyncio.Semaphore(STATS_CONCURRENCY)

        async def one(s: str) -> tuple[str, dict | None]:
            async with sem:
                try:
                    raw, _ = await svc.router.call("keystats", lambda p: p.keystats(s), s)
                    return s, raw
                except AllFailed:
                    return s, None

        got = await asyncio.gather(*(one(s) for s in rows))
        missing = 0
        for s, raw in got:
            if raw is None:
                missing += 1
                continue
            for f in (f for f in L.FIELDS.values() if f.group == "stats"):
                rows[s][f.name] = _stat(raw, f.path)
        if missing:
            notes.append(f"NO KEY STATISTICS FOR {missing} SYMBOL(S)")
        keep("stats")
    out = L.sort_rows(list(rows.values()), q.sort, q.desc)
    matched = len(out)
    out = out[: q.limit]
    cols = [col("symbol", "SYMBOL")] + [col(f, L.FIELDS[f].label[:22], L.FIELDS[f].kind) for f in q.fields]
    srcs = sorted({L.FIELDS[f].source for f in q.fields})
    for r in out:
        r["go_fn"], r["go_sym"] = "DES", r["symbol"]
    data = payload("QRY", "QRY " + ", ".join(q.fields).upper(), [head("UNIVERSE", where), head("MATCHED", f"{matched} OF {total}", matched),
                                                                  head("SHOWN", str(len(out)), len(out))],
                   [section("result", "RESULT (ENTER OPENS DES)", cols, out)],
                   notes + [f"SOURCES: {'; '.join(srcs)}", "A MISSING VALUE FAILS ITS WHERE CONDITION (NEVER READ AS ZERO)"], "; ".join(srcs))
    return {"data": data, "source": "; ".join(srcs), "as_of": datetime.now(UTC).timestamp(), "age_s": 0.0, "stale": False, "fallback_from": []}


def _range_for(start: date, today: date) -> str:
    days = (today - start).days
    for r, n in (("1Y", 366), ("2Y", 731), ("5Y", 1827), ("10Y", 3653), ("20Y", 7306)):
        if days <= n:
            return r
    return "MAX"


async def series(app: Any, q: L.Query) -> dict:
    svc = app.state.service
    syms, _ = await _symbols(app, q, None)
    if len(syms) > MAX_SERIES_SYMBOLS:
        raise DataError("bad_request", f"DATES MODE TAKES AT MOST {MAX_SERIES_SYMBOLS} SYMBOLS")
    start, end = q.dates  # type: ignore[misc]
    today = date.today()
    rng = _range_for(start, today)
    notes: list[str] = []
    cols_data: dict[str, dict[str, float | None]] = {}
    srcs: set[str] = set()

    async def load(sym: str) -> tuple[str, dict | Exception]:
        try:
            if sym.startswith("FRED:"):
                return sym, (await svc.fred_series(sym[5:], rng if rng in ("1Y", "2Y", "5Y", "10Y", "20Y") else "MAX"))["data"]
            return sym, (await svc.history(sym, rng, "1d"))["data"]
        except DataError as e:
            return sym, e

    got = await asyncio.gather(*(load(s) for s in syms))
    for sym, d in got:
        if isinstance(d, Exception):
            notes.append(f"{sym}: {redact(str(d))[:70]}")
            continue
        d = d.model_dump() if hasattr(d, "model_dump") else d
        srcs.add(str(d.get("source")))
        ts = d["t"]
        for f in q.fields:
            fd = L.FIELDS[f]
            if sym.startswith("FRED:") != (fd.group == "fred"):
                notes.append(f"{sym} HAS NO {f.upper()} ({'FRED SERIES TAKE value' if sym.startswith('FRED:') else 'value IS FOR FRED:<ID>'})")
                continue
            vals = d.get(fd.path[0])
            if vals is None:
                notes.append(f"{sym} HAS NO {f.upper()} FROM ITS SOURCE")
                continue
            pts = [(datetime.fromtimestamp(t, UTC).date().isoformat(), v) for t, v in zip(ts, vals, strict=False)]
            pts = [(dd, v) for dd, v in pts if start.isoformat() <= dd <= end.isoformat()]
            pts = L.resample(pts, q.freq)
            if f == "ret":
                base = next((v for _, v in pts if v), None)
                pts = [(dd, (v / base - 1) if v is not None and base else None) for dd, v in pts]
            cols_data[f"{sym} {f.upper()}"] = dict(pts)
    if not cols_data:
        raise DataError("not_found", "NO SERIES ANSWERED: " + "; ".join(notes)[:200])
    dates = sorted({d for v in cols_data.values() for d in v})
    keys = list(cols_data)
    ids = {k: f"c{i}" for i, k in enumerate(keys)}
    rows = [{"date": d, **{ids[k]: cols_data[k].get(d) for k in keys}} for d in reversed(dates)]
    kind_of = {k: L.FIELDS[k.rsplit(" ", 1)[1].lower()].kind for k in keys}
    cols = [col("date", "DATE", "date")] + [col(ids[k], k[:24], kind_of[k]) for k in keys]

    def x(d: str) -> float:
        dd = date.fromisoformat(d)
        return dd.year + (dd.timetuple().tm_yday - 1) / 365.25

    charts = [{"id": "lines", "title": "QRY SERIES", "xlabel": "YEAR", "ylabel": "",
               "series": [{"name": k, "points": [[x(d), v] for d, v in sorted(cols_data[k].items())]} for k in keys[:8]]}]
    data = payload("QRY", "QRY " + ", ".join(q.fields).upper() + f" {start}..{end} {q.freq}",
                   [head("SERIES", str(len(keys))), head("ROWS", str(len(rows))), head("FREQ", {"D": "DAILY", "W": "WEEKLY (LAST)", "M": "MONTHLY (LAST)"}[q.freq])],
                   [section("series", "SERIES (NEWEST FIRST)", cols, rows)],
                   notes + [f"SOURCES: {'; '.join(sorted(srcs))}", "W AND M ROWS ARE THE LAST VALUE OF EACH WEEK / MONTH; A GAP STAYS EMPTY"],
                   "; ".join(sorted(srcs)), charts=charts)
    return {"data": data, "source": "; ".join(sorted(srcs)), "as_of": datetime.now(UTC).timestamp(), "age_s": 0.0, "stale": False, "fallback_from": []}


async def run(app: Any, text: str) -> dict:
    try:
        q = L.parse(text)
    except L.QueryError as e:
        raise _bad(e) from e
    return await (series(app, q) if q.series else snapshot(app, q))


def fields_payload(words: str) -> dict:
    found = L.search_fields(words)
    rows = [{"name": f.name, "label": f.label, "group": f.group.upper(), "source": f.source, "unit": f.unit, "freq": f.freq,
             "key": f.key or "NO KEY", "mode": "DATES" if f.group in L.SERIES_GROUPS else "SNAPSHOT"} for f in found]
    data = payload("FLD", "FLD FIELD CATALOG" + (f": {words.upper()}" if words else ""), [head("FIELDS", f"{len(rows)} OF {len(L.FIELDS)}")],
                   [section("fields", "FIELDS", [col("name", "FIELD"), col("label", "WHAT"), col("mode", "MODE"), col("group", "GROUP"),
                                                 col("source", "SOURCE"), col("unit", "UNIT"), col("freq", "UPDATES"), col("key", "KEY")], rows)],
                   ["USE IN QRY: QRY last, pe FOR SPX WHERE pe<15 SORT pe ASC | QRY close FOR AAPL,FRED:DGS10 DATES -2Y..0 FREQ M",
                    "SNAPSHOT FIELDS GO WITHOUT DATES; HISTORY FIELDS (close adj ret vol value) NEED DATES"], "catalog")
    return {"data": data, "source": "catalog", "as_of": datetime.now(UTC).timestamp(), "age_s": 0.0, "stale": False, "fallback_from": []}
