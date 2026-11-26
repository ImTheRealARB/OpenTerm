"""The `scan.run` job (worker side, pandas): evaluate one BT rule on every symbol's daily bars, on the newest bar.

Each row says whether the rule holds on that symbol's latest bar and the value of every term the rule uses there (so the
panel can show WHY a symbol matched). A symbol without enough bars for the rule is `valid: false`, never a silent match or miss.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path

import msgpack

KEYS = {"data_path", "data_sha", "rule", "failed", "labels", "alert_id"}  # alert_id: the same evaluator checks indicator alerts


def validate(params: dict) -> dict:
    from ..jobs.kinds import BadParams

    if not isinstance(params, dict) or set(params) - KEYS or not {"data_path", "data_sha", "rule"} <= set(params):
        raise BadParams("SCAN.RUN PARAMS ARE BUILT BY /api/scan")
    return params


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def run(params: dict, progress: Callable[[float, str], None]) -> dict:
    from ..bt import frames, rules

    payload = msgpack.unpackb(Path(params["data_path"]).read_bytes(), raw=False)
    node = rules.parse(params["rule"])
    terms = {t.label: t for t in rules.terms(node) if t.kind != "NUM"}
    rows = []
    bars = payload["bars"]
    for k, (sym, b) in enumerate(bars.items()):
        df = frames.from_bars(b)
        if len(df) < 2:
            rows.append({"symbol": sym, "matched": False, "valid": False, "date": None, "close": None, "values": {},
                         "note": "NO BARS"})
            continue
        cache: dict = {}
        cond, valid = rules._eval(node, df, cache)
        values = {label: _num(rules._series(t, df, cache).iloc[-1]) for label, t in terms.items()}
        ok = bool(valid.iloc[-1])
        rows.append({"symbol": sym, "matched": ok and bool(cond.iloc[-1]), "valid": ok, "date": str(df.index[-1].date()),
                     "close": _num(df["close"].iloc[-1]), "values": values,
                     "note": "" if ok else f"NOT ENOUGH BARS ({len(df)}) FOR {rules.max_period(node)}-BAR TERMS"})
        if k % 25 == 0:
            progress(0.1 + 0.85 * k / max(1, len(bars)), f"{k} OF {len(bars)}")
    failed = params.get("failed") or {}
    rows += [{"symbol": s, "matched": False, "valid": False, "date": None, "close": None, "values": {}, "note": f"NO DATA: {e}"}
             for s, e in failed.items()]
    rows.sort(key=lambda r: (not r["matched"], not r["valid"], r["symbol"]))
    return {"rule": params["rule"], "terms": list(terms), "rows": rows, "matched": sum(r["matched"] for r in rows),
            "checked": sum(r["valid"] for r in rows), "failed": len(failed), "labels": params.get("labels") or {}}


# --- indicator columns (WL / Q `COLS=`): the newest bar's value of each column, per symbol ------------------------------

COLS_KEYS = {"data_path", "data_sha", "cols", "failed", "labels"}


def validate_cols(params: dict) -> dict:
    from ..jobs.kinds import BadParams
    from . import cols as C

    if not isinstance(params, dict) or set(params) - COLS_KEYS or not {"data_path", "data_sha", "cols"} <= set(params):
        raise BadParams("SCAN.COLS PARAMS ARE BUILT BY /api/scan/cols")
    try:
        C.parse(params["cols"])  # the route already checked it; a direct submit with bad columns is refused the same way
    except ValueError as e:
        raise BadParams(str(e)) from None
    return params


def _col_series(c, df, cache: dict):
    from ..bt import rules

    if c.kind in ("PCT_SMA", "PCT_EMA"):
        avg = rules._series(rules.Term(c.kind[4:], c.n), df, cache)
        return (df["close"] / avg - 1) * 100
    if c.kind == "REL_VOL":
        vol = df["volume"].astype(float)
        base = vol.shift(1).rolling(c.n, min_periods=c.n).mean()
        return vol / base.where(base > 0)  # no volume in the window (an index, FX) = no value, never a divide by zero
    return rules._series(rules.Term(c.kind, c.n, 0, c.name), df, cache)


def cols_run(params: dict, progress: Callable[[float, str], None]) -> dict:
    from ..bt import frames
    from . import cols as C

    payload = msgpack.unpackb(Path(params["data_path"]).read_bytes(), raw=False)
    spec = C.parse(params["cols"])
    rows: dict[str, dict] = {}
    bars = payload["bars"]
    for k, (sym, b) in enumerate(bars.items()):
        df = frames.from_bars(b)
        if not len(df):
            rows[sym] = {"date": None, "values": {}, "note": "NO BARS"}
            continue
        cache: dict = {}
        rows[sym] = {"date": str(df.index[-1].date()),
                     "values": {c.label: _num(_col_series(c, df, cache).iloc[-1]) for c in spec}, "note": ""}
        if k % 25 == 0:
            progress(0.1 + 0.85 * k / max(1, len(bars)), f"{k} OF {len(bars)}")
    for s, e in (params.get("failed") or {}).items():
        rows[s] = {"date": None, "values": {}, "note": f"NO DATA: {e}"}
    return {"cols": [c.public() for c in spec], "rows": rows, "labels": params.get("labels") or {}}
