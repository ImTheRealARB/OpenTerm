"""Table payloads for OVDV, SKEW and HIVG (spec decisions H, I). Pure: the service passes in fitted smiles and bars."""

from __future__ import annotations

import math

from ..research.table import col, head, payload, section
from . import hivg as hv
from . import surface as sf

FIT_LABEL = "FIT: QUADRATIC IN LOG-MONEYNESS, NOT SVI"
SMILE_POINTS = 21


def pctv(v: float | None, digits: int = 1) -> str:
    return "-" if v is None else f"{v * 100:.{digits}f}%"


def _head(symbol: str, sm: dict, n_fit: int) -> list[dict]:
    spot_label = "INDEX" if sm["kind"] == "crypto" else "SPOT"
    return [head(spot_label, f"{sm['spot']:,.2f}", sm["spot"]), head("FIT", FIT_LABEL),
            head("EXPIRIES", f"{n_fit} OF {sm['planned']}", n_fit)]


def ovdv_payload(symbol: str, sm: dict, rows: list[dict], notes: list[str], key_required: list[dict]) -> dict:
    fit_rows = [{"expiry": r["date"], "days": r["T"] * 365.0, "forward": r["F"], "atm_iv": r["fit"].a, "a": r["fit"].a, "b": r["fit"].b,
                 "c": r["fit"].c, "rmse": r["fit"].rmse, "n": r["fit"].n} for r in rows]
    sec = section("fit", "FITTED SMILE PER EXPIRY", [
        col("expiry", "EXPIRY", "date"), col("days", "DAYS", "num"), col("forward", "FORWARD", "price"), col("atm_iv", "ATM IV", "pct"),
        col("a", "A", "num4"), col("b", "B", "num4"), col("c", "C", "num4"), col("rmse", "RMSE", "pct"), col("n", "QUOTES", "int")],
        fit_rows, "IV(k) = A + B k + C k^2, k = ln(STRIKE / FORWARD); A IS THE ATM IV AT THE FORWARD")
    xs = [math.exp(-0.2 + 0.4 * j / (SMILE_POINTS - 1)) for j in range(SMILE_POINTS)]
    chart = {"id": "smile", "title": "FITTED SMILE BY EXPIRY (IV vs FORWARD MONEYNESS)", "xlabel": "K / FORWARD", "ylabel": "IV",
             "series": [{"name": r["date"], "points": [[round(m, 4), r["fit"].iv_in_range(math.log(m))] for m in xs]} for r in rows]}
    heat = {"id": "surface", "title": "IV SURFACE: EXPIRY (DOWN) x FORWARD MONEYNESS (ACROSS)", "xlabel": "K / FORWARD", "ylabel": "EXPIRY",
            "x": list(sf.MONEYNESS_GRID), "y": [r["date"] for r in rows], "z": [sf.grid_row(r["fit"]) for r in rows], "unit": "pct"}
    return payload(symbol, f"OVDV {symbol}", _head(symbol, sm, len(rows)), [sec], notes, sm["source"], key_required, charts=[chart], heat=heat)


def skew_payload(symbol: str, sm: dict, rows: list[dict], notes: list[str], key_required: list[dict]) -> dict:
    out = []
    for r in rows:
        m = sf.skew_metrics(r["fit"], r["T"])
        out.append({"expiry": r["date"], "days": r["T"] * 365.0, **m, "n": r["fit"].n})
    sec = section("skew", "SKEW BY EXPIRY", [
        col("expiry", "EXPIRY", "date"), col("days", "DAYS", "num"), col("atm_iv", "ATM IV", "pct"), col("iv_c25", "25D CALL IV", "pct"),
        col("iv_p25", "25D PUT IV", "pct"), col("rr25", "RR25", "pct"), col("bf25", "BF25", "pct"), col("slope", "SLOPE", "num4"),
        col("n", "QUOTES", "int")], out,
        "RR25 = 25-DELTA CALL IV - 25-DELTA PUT IV; BF25 = AVERAGE OF THE TWO - ATM IV; SLOPE = dIV/dk AT THE FORWARD; ALL FROM THE FITTED SMILE")
    chart = {"id": "term", "title": "ATM IV TERM STRUCTURE", "xlabel": "DAYS TO EXPIRY", "ylabel": "ATM IV",
             "series": [{"name": "ATM IV", "points": [[round(x["days"], 2), x["atm_iv"]] for x in out]}]}
    return payload(symbol, f"SKEW {symbol}", _head(symbol, sm, len(rows)), [sec], notes, sm["source"], key_required, charts=[chart])


def rank_text(history: list[tuple[str, float]], iv30: float | None) -> str:
    n = len(history)
    if n < 20 or iv30 is None:
        first = history[0][0] if history else "-"
        return f"NOT AVAILABLE: {n} LOCAL SNAPSHOT{'' if n == 1 else 'S'} SINCE {first} (NEEDS 20)"
    rank, pct = hv.percentile_rank([v for _, v in history], iv30)
    return f"{rank * 100:.0f}% RANK · {pct * 100:.0f}% PERCENTILE · FROM {n} LOCAL SNAPSHOTS SINCE {history[0][0]}"


def hivg_payload(symbol: str, sm: dict, rows: list[dict], bars: dict | None, bars_error: str | None, iv30: float | None,
                 iv30_note: str | None, history: list[tuple[str, float]], notes: list[str], key_required: list[dict]) -> dict:
    rv_rows: list[dict] = []
    rets: list[float | None] = []
    rv30 = None
    td = hv.CRYPTO_TRADING_DAYS if sm.get("kind") == "crypto" else hv.TRADING_DAYS  # crypto trades 365 days a year
    if bars:
        rets = hv.log_returns(bars["c"])
        for n in hv.WINDOWS:
            rv_rows.append({"window": n, "cc_vol": hv.cc_vol(rets, n, td), "parkinson": hv.parkinson_vol(bars["h"], bars["l"], n, td)})
        rv30 = next((r["cc_vol"] for r in rv_rows if r["window"] == 30), None)
    iv_rows = [{"expiry": r["date"], "days": r["T"] * 365.0, "atm_iv": r["fit"].a} for r in rows]
    vrp = iv30 - rv30 if iv30 is not None and rv30 is not None else None
    headline = [
        head("IV30", pctv(iv30), iv30), head("RV30", pctv(rv30), rv30),
        head("VRP", "-" if vrp is None else f"{vrp * 100:+.1f} VOL PTS (IV30 - RV30)", vrp),
        head("IV RANK", rank_text(history, iv30)),
    ]
    sections = [
        section("rv", "REALIZED VOL", [col("window", "DAYS", "int"), col("cc_vol", "CLOSE-CLOSE", "pct"), col("parkinson", "PARKINSON", "pct")],
                rv_rows, bars_error and f"NO BARS: {bars_error}"),
        section("iv", "IMPLIED VOL (ATM, FITTED)", [col("expiry", "EXPIRY", "date"), col("days", "DAYS", "num"), col("atm_iv", "ATM IV", "pct")],
                iv_rows, iv30_note),
    ]
    charts = []
    if bars and rets:
        roll = hv.rolling_cc(rets, 20, td)[-252:]
        pts = [[float(i - len(roll) + 1), v] for i, v in enumerate(roll)]
        series = [{"name": "RV20", "points": pts}]
        if iv30 is not None:
            series.append({"name": "IV30 NOW", "points": [[pts[0][0], iv30], [0.0, iv30]], "dash": True})
        charts.append({"id": "rv", "title": "ROLLING 20-DAY REALIZED VOL vs IMPLIED VOL NOW", "xlabel": "TRADING DAYS AGO", "ylabel": "VOL",
                       "series": series})
    return payload(symbol, f"HIVG {symbol}", headline, sections, notes, sm["source"], key_required, charts=charts)
