"""Phase 15: risk, quant library, alphas (spec: docs/specs/PHASE_15.md).

API-level contract tests written before the code, in fixture + synthetic mode (no network; OPENTERM_FIXTURES pins the clock). Every
function is a job (`POST /api/quant/{fn}`, decision B): the helper `run` submits it, waits for the job and returns the standard envelope
`{data, source, stale, age_s, fallback_from}` whose `data` is the table payload. Expected numbers are computed HERE with independent numpy
code from the very bars the API serves (`/api/history`), never by calling the module under test. Every group was strict-xfail until its
build step landed (RISK, OPT, ATTR = step 3; FACT, QL = step 4; ALPHA, REGIME = step 5); the markers are gone.
The ported library itself is tested against Vibe-Trading's own numbers in test_phase15_quant.py.
"""

import math
import os
import subprocess
import sys
import time
import zipfile
from datetime import date
from io import BytesIO
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest

FIX = Path(__file__).parent / "fixtures"


def xf(group: str, step: int):
    return pytest.mark.xfail(strict=True, reason=f"Phase 15 step {step}: {group}")


RISK = lambda f: f  # step 3 landed
OPT = lambda f: f  # step 3 landed
ATTR = lambda f: f  # step 3 landed
FACT = lambda f: f  # step 4 landed
QL = lambda f: f  # step 4 landed
ALPHA = lambda f: f  # step 5 landed
REGIME = lambda f: f  # step 5 landed
PLUMB = lambda f: f  # step 3 landed

SYN = ["SYN0001", "SYN0002", "SYN0003"]


# --- helpers ------------------------------------------------------------------------------------------------------------------------

def submit(client, fn: str, **body):
    return client.post(f"/api/quant/{fn}", json=body)


def run(client, fn: str, timeout: float = 90.0, **body) -> dict:
    """Submit, wait for the job, return the result envelope (asserting the job finished)."""
    r = submit(client, fn, **body)
    assert r.status_code == 200, (fn, body, r.status_code, r.text[:300])
    job = r.json()
    t0 = time.time()
    while job["state"] not in ("done", "error", "cancelled"):
        assert time.time() - t0 < timeout, f"{fn} job still {job['state']}"
        time.sleep(0.05)
        job = client.get(f"/api/jobs/{job['id']}").json()
    assert job["state"] == "done", (fn, body, job.get("error"))
    return job["result"]


def closes(client, symbol: str, range_: str = "1Y") -> dict[int, float]:
    h = client.get("/api/history", params={"symbol": symbol, "range": range_, "interval": "1d"}).json()["data"]
    return dict(zip(h["t"], h["c"], strict=True))


def epoch(d: date) -> int:
    return (d - date(1970, 1, 1)).days * 86400


def returns(prices: dict[int, float]) -> np.ndarray:
    p = np.array([prices[t] for t in sorted(prices)])
    return p[1:] / p[:-1] - 1


def put_portfolio(client, name: str, positions: list[tuple[str, float]]):
    r = client.put(f"/api/portfolios/{name}", json={"positions": [{"symbol": s, "qty": q, "cost": 100} for s, q in positions]})
    assert r.status_code == 200, r.text


def headline(d: dict, label: str) -> dict:
    return next(h for h in d["data"]["headline"] if h["label"] == label)


def section(d: dict, sid: str) -> dict:
    return next(s for s in d["data"]["sections"] if s["id"] == sid)


def rows(d: dict, sid: str) -> list[dict]:
    return section(d, sid)["rows"]


def last_close(client, symbol: str) -> float:
    p = closes(client, symbol)
    return p[max(p)]


# --- job plumbing and server guards -------------------------------------------------------------------------------------------------

@PLUMB
def test_quant_route_validates_function_and_body(client):
    assert submit(client, "nosuchfn").status_code == 404
    assert client.post("/api/quant/risk", content=b"[1, 2]", headers={"content-type": "application/json"}).status_code == 400
    r = submit(client, "risk", portfolio="MISSING")
    assert r.status_code == 404 and "MISSING" in r.json()["error"]


@PLUMB
def test_second_identical_run_is_a_cache_hit(client):
    put_portfolio(client, "T", [(s, 10) for s in SYN])
    first = run(client, "risk", portfolio="T", range="1y")
    again = submit(client, "risk", portfolio="T", range="1y").json()
    assert again["state"] == "done" and again["cached"] is True and again["result"]["data"]["title"] == first["data"]["title"]


def test_server_never_imports_the_heavy_math_libraries(tmp_path):
    """numpy/pandas/scipy/statsmodels/arch load in job workers only (decision A), even after a quant job was submitted."""
    code = (
        "import sys\n"
        "from fastapi.testclient import TestClient\n"
        "from openterm.main import app\n"
        "with TestClient(app) as c:\n"
        "    assert c.get('/api/health').status_code == 200\n"
        "    c.get('/api/keys'); c.get('/api/sources'); c.get('/api/jobs'); c.post('/api/quant/risk', json={'portfolio': 'NONE'})\n"
        "bad = [m for m in ('pandas', 'numpy', 'scipy', 'statsmodels', 'arch') if m in sys.modules]\n"
        "print('LOADED', bad)\n"
        "sys.exit(1 if bad else 0)\n"
    )
    env = {**os.environ, "OPENTERM_FIXTURES": "1", "OPENTERM_DB_PATH": str(tmp_path / "g.db"),
           "OPENTERM_KEYRING": "memory", "OPENTERM_DOTENV_PATH": str(tmp_path / "k.env")}
    r = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=120, check=False,
                       cwd=Path(__file__).parents[1])
    assert r.returncode == 0, r.stdout + r.stderr


@PLUMB
def test_history_accepts_a_twenty_year_range_with_daily_bars(client):
    h = client.get("/api/history", params={"symbol": "AAPL", "range": "20Y", "interval": "1d"}).json()["data"]
    assert len(h["t"]) > 4500 and h["t"][0] < epoch(date(2008, 1, 1))
    assert np.diff(h["t"]).max() < 8 * 86400  # daily, not the monthly bars range=max returns


# --- RISK ---------------------------------------------------------------------------------------------------------------------------

@RISK
def test_risk_summary_matches_independent_numbers(client):
    qty = {"SYN0001": 100, "SYN0002": 200, "SYN0003": 300}
    put_portfolio(client, "T", list(qty.items()))
    d = run(client, "risk", portfolio="T", range="1y")
    px = {s: closes(client, s) for s in SYN}
    last = {s: px[s][max(px[s])] for s in SYN}
    value = sum(qty[s] * last[s] for s in SYN)
    w = np.array([qty[s] * last[s] / value for s in SYN])
    r = np.column_stack([returns(px[s]) for s in SYN])
    port = r @ w  # today's weights held constant (decision D)
    assert headline(d, "VALUE")["raw"] == pytest.approx(value, rel=1e-6)
    assert headline(d, "VOL (ANN)")["raw"] == pytest.approx(port.std(ddof=1) * math.sqrt(252), rel=1e-3)
    assert headline(d, "HHI")["raw"] == pytest.approx(float((w**2).sum()), rel=1e-6)
    assert headline(d, "EFFECTIVE N")["raw"] == pytest.approx(1 / float((w**2).sum()), rel=1e-6)
    eq = np.cumprod(1 + port)
    assert headline(d, "MAX DD")["raw"] == pytest.approx(float((eq / np.maximum.accumulate(eq) - 1).min()), abs=1e-6)
    assert "SYNTHETIC" in str(d["data"]["headline"]) + str(d["data"]["notes"]) + d["source"].upper()


@RISK
def test_risk_var_rows_are_ordered_and_priced(client):
    put_portfolio(client, "T", [(s, 100) for s in SYN])
    d = run(client, "risk", portfolio="T", range="1y", hor=1)
    by = {(r["method"], r["conf"]): r for r in rows(d, "var")}
    assert {m for m, _ in by} == {"HIST", "NORMAL", "EVT"} and {c for _, c in by} == {95, 99}
    value = headline(d, "VALUE")["raw"]
    for r in by.values():
        assert r["var_money"] == pytest.approx(r["var_pct"] * value, rel=1e-6) and r["es_pct"] >= r["var_pct"] > 0
    for m in ("HIST", "NORMAL"):
        assert by[(m, 99)]["var_pct"] > by[(m, 95)]["var_pct"]
    # the 5th percentile of the portfolio's daily returns, within one order statistic of the stored VaR
    px = {s: closes(client, s) for s in SYN}
    w = np.full(3, 1 / 3)  # equal quantities at equal synthetic prices are about equal weights; compare loosely
    port = np.column_stack([returns(px[s]) for s in SYN]) @ w
    assert by[("HIST", 95)]["var_pct"] == pytest.approx(-np.percentile(port, 5), rel=0.25)


@RISK
def test_risk_stress_replays_use_each_holdings_own_history_and_report_coverage(client):
    put_portfolio(client, "S", [("AAPL", 10), ("SYN0001", 5)])
    d = run(client, "risk", portfolio="S", range="1y")
    st = {r["id"]: r for r in rows(d, "stress")}
    assert set(st) == {"2008", "2020", "2022"}
    assert (st["2008"]["start"], st["2008"]["end"]) == ("2008-09-12", "2009-03-09")
    assert (st["2020"]["start"], st["2020"]["end"]) == ("2020-02-19", "2020-03-23")
    assert (st["2022"]["start"], st["2022"]["end"]) == ("2022-01-03", "2022-10-12")
    aapl = closes(client, "AAPL", "20Y")

    def at(day: str) -> float:  # close of the last bar on or before that day
        return aapl[max(t for t in aapl if t < epoch(date.fromisoformat(day)) + 86400)]

    weight = headline(d, "VALUE")["raw"]
    w_aapl = 10 * last_close(client, "AAPL") / weight
    assert 0 < w_aapl < 1
    for key in ("2008", "2020", "2022"):
        r = st[key]
        assert r["coverage"] == pytest.approx(w_aapl, rel=1e-6)  # SYN0001 has no history in those windows
        own = at(r["end"]) / at(r["start"]) - 1
        assert r["ret"] == pytest.approx(own, rel=1e-6) and r["loss_money"] == pytest.approx(own * 10 * last_close(client, "AAPL"), rel=1e-6)
    assert "COVERAGE" in str(section(d, "stress")["note"]).upper() or any("COVERAGE" in n.upper() for n in d["data"]["notes"])


@RISK
def test_risk_backtest_section_has_the_three_tests(client):
    put_portfolio(client, "T", [(s, 100) for s in SYN])
    d = run(client, "risk", portfolio="T", range="1y")
    tests = {r["test"]: r for r in rows(d, "backtest")}
    assert set(tests) >= {"KUPIEC POF", "CHRISTOFFERSEN INDEPENDENCE", "BASEL TRAFFIC LIGHT"}
    assert 0 <= tests["KUPIEC POF"]["p"] <= 1 and tests["BASEL TRAFFIC LIGHT"]["result"] in ("GREEN", "YELLOW", "RED")


@RISK
def test_risk_not_runnable_without_a_portfolio_choice(client):
    put_portfolio(client, "A", [("SYN0001", 1)])
    put_portfolio(client, "B", [("SYN0002", 1)])
    d = run(client, "risk")
    assert d["data"]["status"].startswith("NOT RUNNABLE") and "A" in d["data"]["status"] and "B" in d["data"]["status"]
    only = run(client, "risk", portfolio="A", range="1y")
    assert only["data"].get("status", "RUNNABLE").startswith("RUNNABLE") or "status" not in only["data"]


@RISK
def test_risk_charts_are_equity_and_drawdown(client):
    put_portfolio(client, "T", [(s, 100) for s in SYN])
    d = run(client, "risk", portfolio="T", range="1y")
    ch = {c["id"]: c for c in d["data"]["charts"]}
    assert set(ch) >= {"equity", "drawdown"} and all(len(c["series"][0]["points"]) > 200 for c in ch.values())
    assert min(y for _, y in ch["drawdown"]["series"][0]["points"] if y is not None) <= 0


# --- PORT OPT -----------------------------------------------------------------------------------------------------------------------

def target(d: dict) -> dict[str, float]:
    return {r["symbol"]: r["w_target"] for r in rows(d, "trades")}


def lookback_returns(client, lookback: int) -> np.ndarray:
    px = {s: closes(client, s) for s in SYN}
    return np.column_stack([returns(px[s])[-lookback:] for s in SYN])


@OPT
@pytest.mark.parametrize("method", ["EQVOL", "RP", "MV", "MAXDIV", "HRP", "TURN"])
def test_every_optimizer_returns_a_long_only_full_investment_preview(client, method):
    put_portfolio(client, "T", [(s, 100) for s in SYN])
    d = run(client, "opt", portfolio="T", method=method, lookback=120)
    w = target(d)
    assert set(w) == set(SYN) and sum(w.values()) == pytest.approx(1.0, abs=1e-6) and min(w.values()) >= -1e-9
    now = sum(r["w_now"] for r in rows(d, "trades"))
    assert now == pytest.approx(1.0, abs=1e-6)
    assert any("NOT A FORECAST" in n.upper() for n in d["data"]["notes"]) or "NOT A FORECAST" in str(d["data"]["headline"]).upper()


@OPT
def test_equal_volatility_weights_are_inverse_volatility(client):
    put_portfolio(client, "T", [(s, 100) for s in SYN])
    d = run(client, "opt", portfolio="T", method="EQVOL", lookback=120)
    inv = 1 / lookback_returns(client, 120).std(axis=0, ddof=1)
    for s, want in zip(SYN, inv / inv.sum(), strict=True):
        assert target(d)[s] == pytest.approx(want, rel=1e-3)


@OPT
def test_risk_parity_equalises_risk_contributions(client):
    put_portfolio(client, "T", [(s, 100) for s in SYN])
    d = run(client, "opt", portfolio="T", method="RP", lookback=120)
    w = np.array([target(d)[s] for s in SYN])
    cov = np.cov(lookback_returns(client, 120), rowvar=False)
    rc = w * (cov @ w) / float(w @ cov @ w)
    assert rc == pytest.approx(np.full(3, 1 / 3), abs=0.02)


@OPT
def test_cap_bounds_every_weight_and_says_how(client):
    put_portfolio(client, "T", [(s, 100) for s in SYN])
    d = run(client, "opt", portfolio="T", method="EQVOL", cap=0.34, lookback=120)
    w = target(d)
    assert max(w.values()) <= 0.34 + 1e-9 and sum(w.values()) == pytest.approx(1.0, abs=1e-6)
    d2 = run(client, "opt", portfolio="T", method="MV", cap=0.4, lookback=120)
    assert max(target(d2).values()) <= 0.4 + 1e-6


@OPT
def test_trades_are_whole_shares_at_the_last_close(client):
    put_portfolio(client, "T", [("SYN0001", 100), ("SYN0002", 100), ("SYN0003", 100)])
    d = run(client, "opt", portfolio="T", method="RP", lookback=120)
    total = sum(100 * last_close(client, s) for s in SYN)
    for r in rows(d, "trades"):
        px = last_close(client, r["symbol"])
        assert r["shares"] == round(r["shares"]) and r["cash"] == pytest.approx(r["shares"] * px, rel=1e-6)
        assert r["w_delta"] == pytest.approx(r["w_target"] - r["w_now"], abs=1e-9)
        assert abs(r["shares"] * px / total - r["w_delta"]) < px / total  # rounded to the nearest share


@OPT
def test_high_turnover_cost_keeps_the_current_weights(client):
    put_portfolio(client, "T", [("SYN0001", 300), ("SYN0002", 100), ("SYN0003", 100)])
    free = run(client, "opt", portfolio="T", method="TURN", lookback=120, tc=0)
    costly = run(client, "opt", portfolio="T", method="TURN", lookback=120, tc=1.0)

    def turnover(d):
        return sum(abs(r["w_delta"]) for r in rows(d, "trades"))
    assert turnover(costly) < turnover(free) and turnover(costly) < 0.05


@OPT
def test_compare_section_has_before_and_after(client):
    put_portfolio(client, "T", [(s, 100) for s in SYN])
    d = run(client, "opt", portfolio="T", method="RP", lookback=120)
    cmp_ = {r["metric"]: r for r in rows(d, "compare")}
    assert set(cmp_) >= {"VOL", "SHARPE", "MAX WEIGHT", "EFFECTIVE N", "TURNOVER"}
    assert cmp_["VOL"]["after"] <= cmp_["VOL"]["before"] * 1.0001 or cmp_["MAX WEIGHT"]["after"] <= cmp_["MAX WEIGHT"]["before"]
    bad = submit(client, "opt", portfolio="T", method="NOPE")
    assert bad.status_code == 400 and "METHOD" in bad.json()["error"].upper()
    assert client.get("/api/portfolios/T").json()["positions"][0]["qty"] == 100  # the preview never edits the portfolio


# --- PORT ATTR ----------------------------------------------------------------------------------------------------------------------

def xirr(flows: list[tuple[date, float]]) -> float:
    t0 = flows[0][0]
    f = lambda r: sum(a / (1 + r) ** ((d - t0).days / 365.0) for d, a in flows)
    lo, hi = -0.9, 10.0
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if f(mid) > 0 else (lo, mid)
    return (lo + hi) / 2


VALS = [{"date": "2025-01-01", "value": 10000, "flow": 0}, {"date": "2025-07-01", "value": 16000, "flow": 4000},
        {"date": "2025-12-31", "value": 17600, "flow": 0}]


@ATTR
def test_return_measures_from_stored_valuations(client):
    put_portfolio(client, "T", [("AAPL", 10)])
    assert client.put("/api/portfolios/T/vals", json={"rows": VALS}).status_code == 200
    assert [r["date"] for r in client.get("/api/portfolios/T/vals").json()["rows"]] == [v["date"] for v in VALS]
    d = run(client, "attr", portfolio="T", bench="SPY", range="1y")
    got = {r["measure"]: r["value"] for r in rows(d, "returns")}
    d0, d1, d2 = date(2025, 1, 1), date(2025, 7, 1), date(2025, 12, 31)
    twr = (16000 - 4000) / 10000 * (17600 / 16000) - 1  # sub-periods end at each valuation, flows are end-of-day
    assert got["TWR"] == pytest.approx(twr, abs=1e-9) and twr == pytest.approx(0.32, abs=1e-9)
    total_days = (d2 - d0).days
    dietz = (17600 - 10000 - 4000) / (10000 + 4000 * (d2 - d1).days / total_days)
    assert got["MODIFIED DIETZ"] == pytest.approx(dietz, abs=1e-9)
    assert got["MWR (XIRR)"] == pytest.approx(xirr([(d0, -10000), (d1, -4000), (d2, 17600)]), abs=1e-6)
    assert got["SIMPLE"] == pytest.approx((17600 - 10000 - 4000) / 10000, abs=1e-9)


@ATTR
def test_returns_need_two_valuations(client):
    put_portfolio(client, "T", [("AAPL", 10)])
    d = run(client, "attr", portfolio="T", bench="SPY", range="1y")
    assert any("NEEDS 2 VALUATIONS" in str(x).upper() for x in (section(d, "returns")["note"], d["data"]["notes"]))
    assert rows(d, "returns") == []
    assert client.put("/api/portfolios/T/vals", json={"rows": [{"date": "2025-13-01", "value": 1, "flow": 0}]}).status_code == 400


@ATTR
def test_brinson_effects_sum_to_the_active_return(client):
    put_portfolio(client, "T", [("AAPL", 10), ("SYN0001", 5)])
    d = run(client, "attr", portfolio="T", bench="SPY", range="1y")
    b = rows(d, "brinson")
    sectors = {r["sector"] for r in b}
    assert "Technology" in sectors and "Unclassified" in sectors  # AAPL from the screener, a SYN name has none
    eff = sum(r["allocation"] + r["selection"] + r["interaction"] for r in b if r["sector"] != "TOTAL")
    total = next(r for r in b if r["sector"] == "TOTAL")
    assert total["total"] == pytest.approx(eff, abs=1e-9)
    assert total["total"] == pytest.approx(headline(d, "PORTFOLIO RETURN")["raw"] - headline(d, "BENCH RETURN")["raw"], abs=1e-9)
    assert sum(r["wp"] for r in b if r["sector"] != "TOTAL") == pytest.approx(1.0, abs=1e-9)
    assert sum(r["wb"] for r in b if r["sector"] != "TOTAL") == pytest.approx(1.0, abs=1e-6)
    notes = " ".join(d["data"]["notes"]).upper()
    assert "HELD CONSTANT" in notes and "SPDR" in notes


# --- FACT ---------------------------------------------------------------------------------------------------------------------------

def french_factors() -> dict[str, dict[str, float]]:
    """Daily factor returns (percent) from the recorded Ken French zips, parsed here: {yyyymmdd: {factor: value}}."""
    import base64
    import json

    out: dict[str, dict[str, float]] = {}
    for name, cols in (("kenfrench_ff5_daily", ["MKT-RF", "SMB", "HML", "RMW", "CMA", "RF"]), ("kenfrench_mom_daily", ["MOM"])):
        rec = json.loads((FIX / f"{name}.json").read_bytes().decode("utf-8"))
        z = zipfile.ZipFile(BytesIO(base64.b64decode(rec["b64"])))
        for line in z.read(z.namelist()[0]).decode("latin-1").splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) == len(cols) + 1 and parts[0].isdigit() and len(parts[0]) == 8:
                out.setdefault(parts[0], {}).update(dict(zip(cols, map(float, parts[1:]), strict=True)))
    return out


@FACT
def test_fact_betas_match_an_independent_regression_on_the_french_files(client):
    d = run(client, "fact", symbol="AAPL", range="1y")
    fac = french_factors()
    px = closes(client, "AAPL", "1Y")
    ts = sorted(px)
    ret = {time.strftime("%Y%m%d", time.gmtime(t)): px[t] / px[p] - 1 for p, t in pairwise(ts)}
    days = sorted(day for day in ret if day in fac and all(k in fac[day] for k in ("MKT-RF", "SMB", "HML", "RMW", "CMA", "MOM", "RF")))
    assert len(days) > 150
    names = ["MKT-RF", "SMB", "HML", "RMW", "CMA", "MOM"]
    x = np.column_stack([np.ones(len(days))] + [[fac[day][n] / 100 for day in days] for n in names])
    y = np.array([ret[day] - fac[day]["RF"] / 100 for day in days])
    beta = np.linalg.lstsq(x, y, rcond=None)[0]
    got = {r["factor"]: r for r in rows(d, "loadings")}
    for i, n in enumerate(names, start=1):
        assert got[n]["beta"] == pytest.approx(beta[i], abs=1e-6)
    assert headline(d, "ALPHA (ANN)")["raw"] == pytest.approx(beta[0] * 252, abs=1e-5)
    res = y - x @ beta
    assert headline(d, "R2")["raw"] == pytest.approx(1 - res.var() / y.var(), abs=1e-6)
    assert headline(d, "FACTOR DATA ENDS")["value"] == "2026-08-31"
    assert all("t" in got[n] and got[n]["t"] is not None for n in names)


@FACT
def test_fact_non_us_symbols_say_so_and_unknown_symbols_fail_clearly(client):
    d = run(client, "fact", symbol="RELIANCE.NS", range="1y")
    assert "NON-US" in str(d["data"]["notes"]).upper()
    r = submit(client, "fact", symbol="NOSUCHSYMBOLXYZ", range="1y")
    assert r.status_code in (400, 404) or r.json().get("state") == "error"


# --- QL -----------------------------------------------------------------------------------------------------------------------------

@QL
def test_ql_deflated_sharpe_is_a_closed_form_probability(client):
    d = run(client, "ql", calc="DSR", sr=0.1, n=100, t=1000, skew=0.0, kurt=3.0, trial_sr_std=0.05)
    p = headline(d, "DSR")["raw"]
    assert 0.0 <= p <= 1.0
    more = run(client, "ql", calc="DSR", sr=0.1, n=1000, t=1000, skew=0.0, kurt=3.0, trial_sr_std=0.05)
    assert headline(more, "DSR")["raw"] < p  # more trials, more deflation
    sr0 = headline(d, "EXPECTED MAX SR")["raw"]
    z = (0.1 - sr0) * math.sqrt(999) / math.sqrt(1 - 0.0 * 0.1 + (3.0 - 1) / 4 * 0.1**2)
    assert p == pytest.approx(0.5 * (1 + math.erf(z / math.sqrt(2))), abs=1e-9)


@QL
def test_ql_missing_inputs_are_not_runnable(client):
    d = run(client, "ql", calc="DSR", sr=0.1)
    assert d["data"]["status"].startswith("NOT RUNNABLE") and "N" in d["data"]["status"] and "T" in d["data"]["status"]
    e = run(client, "ql", calc="EVENT", symbols=["AAPL"])
    assert e["data"]["status"].startswith("NOT RUNNABLE") and "DATE" in e["data"]["status"]
    assert submit(client, "ql", calc="NOPE").status_code == 400


@QL
@pytest.mark.parametrize(("calc", "symbols", "keys"), [
    ("GARCH", ["SYN0001"], {"OMEGA", "ALPHA", "BETA", "PERSISTENCE"}),
    ("OU", ["SYN0001"], {"KAPPA", "HALF LIFE"}),
    ("COINT", ["SYN0001", "SYN0002"], {"P-VALUE", "HEDGE RATIO"}),
    ("COPULA", ["SYN0001", "SYN0002"], {"KENDALL TAU"}),
    ("ROLL", ["SYN0001"], {"ROLL SPREAD"}),
    ("AMIHUD", ["SYN0001"], {"AMIHUD"}),
    ("ADF", ["SYN0001"], {"ADF STAT", "P-VALUE"}),
])
def test_ql_calculators_run_on_bars_and_label_daily_data(client, calc, symbols, keys):
    d = run(client, "ql", calc=calc, symbols=symbols, range="1y")
    labels = {h["label"] for h in d["data"]["headline"]} | {r.get("metric") for s in d["data"]["sections"] for r in s["rows"]}
    assert keys <= labels, (calc, keys - labels)
    assert d["data"]["title"].upper().startswith(calc) and d["source"]
    if calc in ("ROLL", "AMIHUD"):
        assert "DAILY BARS" in str(d["data"]["notes"]).upper()


@QL
def test_ql_ou_and_garch_numbers_are_finite_and_sensible(client):
    ou = run(client, "ql", calc="OU", symbols=["SYN0001"], range="1y")
    hl = headline(ou, "HALF LIFE")["raw"]
    assert hl is None or hl > 0
    g = run(client, "ql", calc="GARCH", symbols=["SYN0001"], range="1y", h=5)
    assert 0 <= headline(g, "PERSISTENCE")["raw"] < 1.0001
    fc = rows(g, "forecast")
    assert len(fc) == 5 and all(r["vol"] > 0 for r in fc)


# --- ALPHA --------------------------------------------------------------------------------------------------------------------------

@ALPHA
def test_alpha_zoo_scan_labels_follow_vibes_rule(client):
    d = run(client, "alpha", timeout=180, universe="SYN", range="1y", h=[1, 5])
    zoo = rows(d, "zoo")
    assert 24 <= len(zoo) <= 30 and len({r["id"] for r in zoo}) == len(zoo)
    assert "SYNTHETIC" in str(d["data"]["headline"]).upper() + str(d["data"]["notes"]).upper()
    for r in zoo:
        if r["ic_std"]:
            assert r["ir"] == pytest.approx(r["ic_mean"] / r["ic_std"], rel=1e-9)
        t = r["t"]
        alive = r["ic_mean"] > 0.02 and r["pos_ratio"] >= 0.55 and abs(t) > 2
        reversed_ = r["ic_mean"] < -0.02 and abs(t) > 2
        assert r["label"] == ("alive" if alive else "reversed" if reversed_ else "dead"), r["id"]
        assert r["family"] in ("alpha101", "qlib158", "academic") and "ic_h1" in r and "ic_h5" in r
    assert {r["label"] for r in zoo} <= {"alive", "reversed", "dead"}
    assert [c["id"] for c in d["data"]["charts"]] == ["decay"]


@ALPHA
def test_alpha_is_a_job_with_progress_and_a_cache(client):
    r = submit(client, "alpha", universe="SYN", range="1y", h=[1]).json()
    assert r["kind"] == "alpha.scan"
    seen = {r["progress"]}
    t0 = time.time()
    while r["state"] not in ("done", "error"):
        assert time.time() - t0 < 180
        time.sleep(0.05)
        r = client.get(f"/api/jobs/{r['id']}").json()
        seen.add(r["progress"])
    assert r["state"] == "done" and r["progress"] == 1.0
    assert submit(client, "alpha", universe="SYN", range="1y", h=[1]).json()["cached"] is True


@ALPHA
def test_alpha_universe_validation(client):
    assert submit(client, "alpha", universe="NOPE").status_code == 400
    assert submit(client, "alpha", universe="LIST:AAPL").status_code == 400  # a cross-section needs at least 5 names


def test_every_zoo_factor_passes_the_lookahead_sentinel():
    """A factor computed on bars cut at day t must equal the same factor on the full series at day t."""
    import numpy as np_
    import pandas as pd

    from openterm.quantlib.alpha import ZOO, compute_factor

    rng = np_.random.default_rng(7)
    days, names = 90, 14
    idx = pd.bdate_range("2025-01-02", periods=days)
    close = pd.DataFrame(100 * np_.exp(np_.cumsum(rng.normal(0, 0.012, (days, names)), axis=0)), index=idx,
                         columns=[f"S{i:02d}" for i in range(names)])
    panel = {"close": close, "open": close.shift(1).bfill() * (1 + rng.normal(0, 0.002, close.shape)),
             "high": close * 1.01, "low": close * 0.99, "volume": pd.DataFrame(rng.integers(1e5, 1e6, close.shape), index=idx, columns=close.columns)}
    for f in ZOO:
        full = compute_factor(f["id"], panel)
        for t in (60, 75, 89):
            cut = compute_factor(f["id"], {k: v.iloc[: t + 1] for k, v in panel.items()})
            a, b = cut.iloc[-1].to_numpy(float), full.iloc[t].to_numpy(float)
            assert np_.allclose(a, b, equal_nan=True, rtol=1e-9, atol=1e-12), (f["id"], t)


# --- CORR REGIME --------------------------------------------------------------------------------------------------------------------

@REGIME
def test_corr_regime_edge_density_matches_independent_numbers(client):
    syms = [f"SYN00{i:02d}" for i in range(1, 7)]
    d = run(client, "regime", symbols=syms, win=30, edge=0.2, range="1y")
    px = {s: closes(client, s) for s in syms}
    r = np.column_stack([returns(px[s]) for s in syms])
    c = np.corrcoef(r[-30:], rowvar=False)
    iu = np.triu_indices(len(syms), k=1)
    assert headline(d, "EDGE DENSITY")["raw"] == pytest.approx(float((np.abs(c[iu]) >= 0.2).sum() / len(iu[0])), abs=1e-12)
    assert headline(d, "STATE")["value"] in ("FUSED", "DIFFUSE")
    ep = rows(d, "episodes")
    assert ep and ep[-1]["state"] == headline(d, "STATE")["value"] and all(e["bars"] > 0 for e in ep)
    assert [c_["id"] for c_ in d["data"]["charts"]] == ["density"]


@REGIME
def test_corr_regime_needs_a_basket_and_valid_parameters(client):
    assert submit(client, "regime", symbols=["SYN0001"]).status_code == 400
    assert submit(client, "regime", symbols=["SYN0001", "SYN0002", "SYN0003"], win=1).status_code == 400
    assert submit(client, "regime", symbols=["SYN0001", "SYN0002", "SYN0003"], edge=1.5).status_code == 400
