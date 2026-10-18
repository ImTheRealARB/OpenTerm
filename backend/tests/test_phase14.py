"""Phase 14: options, rates, futures (spec: docs/specs/PHASE_14.md).

API-level contract tests written before the code, in fixture mode (no network; OPENTERM_FIXTURES pins the clock to 2026-10-18T00:00Z,
decision C). Each group is strict-xfail until its build step lands; that step deletes the marker (OPT = step 3, PRICER = step 4,
SURF = step 5, RATES = step 6, FUT = step 7). Expected numbers are read from the recorded answers in tests/fixtures (recorded
2026-10-18 by scripts/record_phase14.py) with independent code written here (math.erf Black-Scholes, plain CSV/JSON/HTML parsing),
so a test never calls the module it checks. The quant library has its own file: test_phase14_quant.py.
"""

import json
import math
import re
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 18, tzinfo=UTC)


def xf(group: str, step: int):
    return pytest.mark.xfail(strict=True, reason=f"Phase 14 step {step}: {group}")


OPT = lambda f: f  # step 3 landed
PRICER = lambda f: f  # step 4 landed
SURF = lambda f: f  # step 5 landed
RATES = xf("rates and calculators", 6)
FUT = xf("futures and policy", 7)


def fixture_body(name: str):
    rec = json.loads((FIX / f"{name}.json").read_bytes().decode("utf-8"))
    return rec["body"] if "body" in rec else rec["text"]


def data(client, path: str, **params):
    r = client.get(f"/api/{path}", params=params)
    assert r.status_code == 200, (path, params, r.status_code, r.text[:300])
    return r.json()


def section(d: dict, sid: str) -> dict:
    return next(s for s in d["data"]["sections"] if s["id"] == sid)


def headline(d: dict, label: str) -> dict:
    return next(h for h in d["data"]["headline"] if h["label"] == label)


KINDS = ("text", "int", "num", "num4", "pct", "bp", "money", "price", "date")


def assert_table_payload(d: dict):
    p = d["data"]
    assert set(p) >= {"symbol", "title", "headline", "sections", "notes"}
    assert d["source"] and "stale" in d and "fallback_from" in d
    for s in p["sections"]:
        assert set(s) >= {"id", "title", "columns", "rows"}
        keys = {c["key"] for c in s["columns"]}
        assert all(c["kind"] in KINDS for c in s["columns"])
        for row in s["rows"]:
            assert keys <= set(row), (s["id"], keys - set(row))


# --- independent Black-Scholes (math.erf), used to check the API without calling the code under test -------------------

def ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs(S, K, T, r, sig, kind, q=0.0):
    d1 = (math.log(S / K) + (r - q + sig * sig / 2) * T) / (sig * math.sqrt(T))
    d2 = d1 - sig * math.sqrt(T)
    if kind == "call":
        return S * math.exp(-q * T) * ncdf(d1) - K * math.exp(-r * T) * ncdf(d2)
    return K * math.exp(-r * T) * ncdf(-d2) - S * math.exp(-q * T) * ncdf(-d1)


def bs_delta(S, K, T, r, sig, kind, q=0.0):
    d1 = (math.log(S / K) + (r - q + sig * sig / 2) * T) / (sig * math.sqrt(T))
    return math.exp(-q * T) * (ncdf(d1) if kind == "call" else ncdf(d1) - 1.0)


# --- recorded option chains (AAPL, eight expiries; spot 343.46) ---------------------------------------------------------

EXPIRIES = [1792368000, 1792972800, 1795132800, 1797552000, 1799971200, 1807833600, 1813190400, 1821139200]
SPOT = 343.46


def chain(epoch: int) -> dict:
    return fixture_body(f"yahoo_options_aapl_{epoch}")["optionChain"]["result"][0]


def exp_date(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%d")


def years_to(epoch: int) -> float:
    """Spec C: expiry date 16:00 New York (20:00 UTC in October) minus the pinned clock, over 365 days."""
    return (epoch + 20 * 3600 - NOW.timestamp()) / 86400 / 365


def test_recorded_expiries_are_the_ones_pick_expiries_chooses():
    dates = chain(EXPIRIES[0])["expirationDates"]
    first, picked = dates[0], [dates[0]]
    for days in (7, 30, 60, 90, 180, 270, 365):
        rest = [x for x in dates if x not in picked]
        picked.append(min(rest, key=lambda x: abs(x - (first + days * 86400))))
    assert sorted(picked) == EXPIRIES  # the recorder and openterm.options.surface.pick_expiries must agree (tested in step 5)


# --- OPT: OMON, PCR ---------------------------------------------------------------------------------------------------

@OPT
def test_omon_nearest_expiry_rows_match_the_recorded_chain(client):
    d = data(client, "deriv/omon", symbol="AAPL")
    assert_table_payload(d)
    assert headline(d, "SPOT")["raw"] == SPOT and headline(d, "EXPIRY")["value"] == exp_date(EXPIRIES[0])
    assert headline(d, "EXPIRIES")["raw"] == len(chain(EXPIRIES[0])["expirationDates"])
    assert "COMPUTED HERE" in headline(d, "GREEKS")["value"] and "NOT VENDOR" in headline(d, "GREEKS")["value"]
    calls = section(d, "calls")["rows"]
    want = chain(EXPIRIES[0])["options"][0]["calls"]
    assert len(calls) == len(want) and [r["strike"] for r in calls] == sorted(r["strike"] for r in calls)
    by_strike = {r["strike"]: r for r in want}
    for r in calls:
        w = by_strike[r["strike"]]
        assert r["oi"] == w.get("openInterest", 0) and (r["volume"] or 0) == w.get("volume", 0)
        assert (r["bid"], r["ask"]) == (w.get("bid"), w.get("ask"))
    assert len(section(d, "puts")["rows"]) == len(chain(EXPIRIES[0])["options"][0]["puts"])
    assert {r["strike"] for r in section(d, "strads")["rows"]} >= {r["strike"] for r in calls[:3]}


@OPT
def test_omon_selected_expiry_and_unknown_expiry(client):
    d = data(client, "deriv/omon", symbol="AAPL", date=exp_date(EXPIRIES[3]))
    assert headline(d, "EXPIRY")["value"] == exp_date(EXPIRIES[3])
    assert headline(d, "T (YEARS)")["raw"] == pytest.approx(years_to(EXPIRIES[3]), abs=1e-9)
    r = client.get("/api/deriv/omon", params={"symbol": "AAPL", "date": "2026-10-20"})
    assert r.status_code == 400 and "EXPIR" in r.json()["error"].upper()
    assert client.get("/api/deriv/omon", params={"symbol": "ZZZZNOPE"}).status_code == 404


@OPT
def test_omon_iv_and_greeks_are_black_scholes_from_the_mid(client):
    ep = EXPIRIES[3]
    d = data(client, "deriv/omon", symbol="AAPL", date=exp_date(ep))
    T, r, q = headline(d, "T (YEARS)")["raw"], headline(d, "RATE")["raw"], headline(d, "DIV YIELD")["raw"]
    assert q == pytest.approx(0.0030701754)   # recorded trailingAnnualDividendYield
    assert 0.0 < r < 0.12
    calls = [x for x in section(d, "calls")["rows"] if x["iv_src"] == "MID"]
    row = min(calls, key=lambda x: abs(x["strike"] - SPOT))
    mid = (row["bid"] + row["ask"]) / 2
    assert bs(SPOT, row["strike"], T, r, row["iv"], "call", q) == pytest.approx(mid, abs=2e-4)   # the IV reprices the mid
    assert row["delta"] == pytest.approx(bs_delta(SPOT, row["strike"], T, r, row["iv"], "call", q), abs=1e-6)
    assert 0.0 < row["delta"] < 1.0 and row["gamma"] > 0 and row["vega"] > 0 and row["theta"] < 0
    put = min([x for x in section(d, "puts")["rows"] if x["iv_src"] == "MID"], key=lambda x: abs(x["strike"] - SPOT))
    assert -1.0 < put["delta"] < 0.0


@OPT
def test_omon_moneyness_filter(client):
    d = data(client, "deriv/omon", symbol="AAPL", moneyness="OTM")
    assert all(r["strike"] > SPOT for r in section(d, "calls")["rows"])
    assert all(r["strike"] < SPOT for r in section(d, "puts")["rows"])


@OPT
def test_omon_vendor_greeks_need_a_key_and_say_so(client):
    d = data(client, "deriv/omon", symbol="AAPL")
    assert d["data"]["key_required"] == [{"key": "TRADIER_TOKEN", "what": "VENDOR GREEKS AND IV"}]
    row = {p["name"]: p for p in client.get("/api/sources").json()["providers"]}
    assert "option_chain" in row["yahoo_options"]["capabilities"] and "option_chain" in row["tradier"]["capabilities"]
    assert row["tradier"]["calls"] == 0   # inert while keyless


@OPT
def test_pcr_totals_match_the_recorded_chains(client):
    d = data(client, "deriv/pcr", symbol="AAPL")
    assert_table_payload(d)
    rows = section(d, "expiry")["rows"]
    assert [r["expiry"] for r in rows] == [exp_date(e) for e in EXPIRIES]
    for r, ep in zip(rows, EXPIRIES, strict=True):
        o = chain(ep)["options"][0]
        cv, pv = sum(c.get("volume", 0) for c in o["calls"]), sum(c.get("volume", 0) for c in o["puts"])
        co, po = sum(c.get("openInterest", 0) for c in o["calls"]), sum(c.get("openInterest", 0) for c in o["puts"])
        assert (r["call_vol"], r["put_vol"], r["call_oi"], r["put_oi"]) == (cv, pv, co, po)
        assert r["pcr_oi"] == pytest.approx(po / co) and (r["pcr_vol"] is None or r["pcr_vol"] == pytest.approx(pv / cv))
    tot_c = sum(r["call_oi"] for r in rows)
    tot_p = sum(r["put_oi"] for r in rows)
    assert headline(d, "PCR OI")["raw"] == pytest.approx(tot_p / tot_c)


# --- PRICER: OV, OSA --------------------------------------------------------------------------------------------------

OV_ARGS = {"symbol": "AAPL", "K": "350", "EXP": exp_date(EXPIRIES[3]), "TYPE": "C", "IV": "27"}   # IV, R, Q are typed in percent


@PRICER
def test_ov_prices_with_black_scholes_binomial_and_sources_every_input(client):
    d = data(client, "deriv/ov", **OV_ARGS)
    assert_table_payload(d)
    assert d["data"]["status"] == "RUNNABLE"
    T = years_to(EXPIRIES[3])
    inputs = {r["name"]: r for r in section(d, "inputs")["rows"]}
    assert inputs["SPOT"]["value"].startswith("343.46") and inputs["IV"]["basis"].startswith("typed")
    r = float(inputs["R"]["value"].rstrip("%")) / 100
    q = float(inputs["Q"]["value"].rstrip("%")) / 100
    assert "Treasury" in inputs["R"]["basis"] and "Yahoo" in inputs["Q"]["basis"]
    models = {m["model"]: m for m in section(d, "price")["rows"]}
    want = bs(SPOT, 350.0, T, r, 0.27, "call", q)
    assert models["BS"]["price"] == pytest.approx(want, rel=2e-4)
    assert models["BIN EU"]["price"] == pytest.approx(want, abs=0.05)
    assert models["BIN AM"]["price"] >= models["BIN EU"]["price"] - 1e-9
    assert models["BS"]["delta"] == pytest.approx(bs_delta(SPOT, 350.0, T, r, 0.27, "call", q), abs=1e-4)
    assert "HESTON" not in models and "BARRIER" not in models   # their inputs were not typed


@PRICER
def test_ov_not_runnable_lists_every_missing_input(client):
    d = data(client, "deriv/ov", symbol="AAPL")
    st = d["data"]["status"]
    assert st.startswith("NOT RUNNABLE")
    for field in ("K", "EXP", "TYPE", "IV"):
        assert field in st
    assert all(m["price"] is None for m in section(d, "price")["rows"]) or section(d, "price")["rows"] == []


@PRICER
def test_ov_uses_the_chain_atm_iv_when_none_is_typed_and_says_so(client):
    args = {k: v for k, v in OV_ARGS.items() if k != "IV"}
    d = data(client, "deriv/ov", **args)
    iv = {r["name"]: r for r in section(d, "inputs")["rows"]}["IV"]
    assert iv["basis"].startswith("ATM IV FROM CHAIN, EXP " + exp_date(EXPIRIES[3]))
    assert 0.1 < float(iv["value"].rstrip("%")) / 100 < 0.8


@PRICER
def test_ov_solves_implied_vol_and_refuses_a_price_outside_the_bounds(client):
    T = years_to(EXPIRIES[3])
    r0 = data(client, "deriv/ov", **OV_ARGS)
    inputs = {r["name"]: r for r in section(r0, "inputs")["rows"]}
    r = float(inputs["R"]["value"].rstrip("%")) / 100
    q = float(inputs["Q"]["value"].rstrip("%")) / 100
    px = bs(SPOT, 350.0, T, r, 0.31, "call", q)
    d = data(client, "deriv/ov", **{**OV_ARGS, "PRICE": f"{px:.6f}"})
    solved = section(d, "ivsolve")["rows"][0]
    assert solved["iv"] == pytest.approx(0.31, abs=2e-4) and solved["status"] == "SOLVED"
    d = data(client, "deriv/ov", **{**OV_ARGS, "PRICE": "400"})   # above spot: no volatility prices that
    assert section(d, "ivsolve")["rows"][0]["status"].startswith("NO IMPLIED VOL")


@PRICER
def test_ov_heston_and_barrier_run_only_with_their_inputs(client):
    d = data(client, "deriv/ov", **OV_ARGS, V0="0.0729", KAPPA="2", THETA="0.0729", SIGMAV="0.4", RHO="-0.7",
             H="400", BARR="UO")
    models = {m["model"]: m for m in section(d, "price")["rows"]}
    assert {"HESTON", "BARRIER"} <= set(models)
    assert 0 < models["BARRIER"]["price"] < models["BS"]["price"]   # an up-and-out call is worth less than the vanilla
    assert models["HESTON"]["price"] == pytest.approx(models["BS"]["price"], rel=0.15)


OSA_SPREAD = {"symbol": "AAPL", "LEGS": "+1C270@5,-1C290@2", "EXP": exp_date(EXPIRIES[3]), "IV": "25", "MULT": "100"}


@PRICER
def test_osa_bull_call_spread_with_explicit_premiums(client):
    d = data(client, "deriv/osa", **OSA_SPREAD)
    assert_table_payload(d)
    assert headline(d, "NET DEBIT")["raw"] == pytest.approx(300.0)
    assert headline(d, "MAX PROFIT")["raw"] == pytest.approx(1700.0) and headline(d, "MAX LOSS")["raw"] == pytest.approx(-300.0)
    assert headline(d, "BREAKEVEN")["raw"] == pytest.approx(273.0)
    pay = {r["spot"]: r["pnl"] for r in section(d, "payoff")["rows"]}
    assert min(pay.values()) == pytest.approx(-300.0) and max(pay.values()) == pytest.approx(1700.0)
    assert d["data"]["charts"][0]["id"] == "payoff" and d["data"]["heat"]["id"] == "scenario"
    legs = section(d, "legs")["rows"]
    assert [(r["qty"], r["type"], r["strike"], r["premium"]) for r in legs] == [(1, "C", 270.0, 5.0), (-1, "C", 290.0, 2.0)]


@PRICER
def test_osa_strategy_shortcut_prices_legs_with_black_scholes(client):
    d = data(client, "deriv/osa", symbol="AAPL", STRAT="BULLCALL,270,290", EXP=exp_date(EXPIRIES[3]), IV="25", MULT="100")
    legs = section(d, "legs")["rows"]
    inputs = {r["name"]: r for r in section(d, "inputs")["rows"]}
    T = years_to(EXPIRIES[3])
    r = float(inputs["R"]["value"].rstrip("%")) / 100
    want = bs(SPOT, 270.0, T, r, 0.25, "call", 0.0) - bs(SPOT, 290.0, T, r, 0.25, "call", 0.0)
    assert legs[0]["premium"] - legs[1]["premium"] == pytest.approx(want, rel=2e-3)
    assert abs(headline(d, "NET DEBIT")["raw"] - want * 100) < 0.5 + 0.003 * want * 100


@PRICER
def test_osa_missing_inputs_are_not_runnable(client):
    d = data(client, "deriv/osa", symbol="AAPL", LEGS="+1C270")
    assert d["data"]["status"].startswith("NOT RUNNABLE") and "EXP" in d["data"]["status"] and "IV" in d["data"]["status"]
    bad = client.get("/api/deriv/osa", params={"symbol": "AAPL", "LEGS": "+1X270", "EXP": "2026-12-18", "IV": "20"})
    assert bad.status_code == 400 and "LEG" in bad.json()["error"].upper()


# --- SURF: OVDV, SKEW, HIVG -------------------------------------------------------------------------------------------

MONEYNESS = [0.80, 0.85, 0.90, 0.95, 1.00, 1.05, 1.10, 1.15, 1.20]


@SURF
def test_ovdv_surface_from_the_recorded_chains(client):
    d = data(client, "deriv/ovdv", symbol="AAPL")
    assert_table_payload(d)
    heat = d["data"]["heat"]
    assert heat["x"] == pytest.approx(MONEYNESS) and heat["y"] == [exp_date(e) for e in EXPIRIES]
    assert len(heat["z"]) == 8 and all(len(row) == 9 for row in heat["z"])
    # a cell outside the strikes the fit was made from is EMPTY (never extrapolated); every filled cell is a sane vol
    assert all(0.05 < v < 1.5 for row in heat["z"] for v in row if v is not None)
    assert all(row[4] is not None for row in heat["z"])   # the forward is always inside the quotes
    assert sum(v is not None for row in heat["z"] for v in row) >= 0.6 * 72
    assert heat["z"][0][0] is None and heat["z"][-1][0] is not None   # the 1-day expiry has quotes only near the money
    assert "QUADRATIC" in headline(d, "FIT")["value"] and "NOT SVI" in headline(d, "FIT")["value"]
    fit = section(d, "fit")["rows"]
    assert len(fit) == 8 and all(r["rmse"] < 0.03 and r["n"] >= 8 for r in fit)
    for i, r in enumerate(fit):   # the grid at forward moneyness 1.00 is the fitted ATM IV
        assert heat["z"][i][4] == pytest.approx(r["atm_iv"], abs=1e-9)
    assert len(d["data"]["charts"]) >= 1 and d["data"]["charts"][0]["series"]


@SURF
def test_ovdv_equity_skew_is_downward_in_most_expiries(client):
    z = data(client, "deriv/ovdv", symbol="AAPL")["data"]["heat"]["z"]
    pairs = [(row[0], row[4]) for row in z if row[0] is not None]
    assert len(pairs) >= 6 and sum(w > a for w, a in pairs) >= len(pairs) - 1   # 80% moneyness IV above ATM IV: the usual put skew


@SURF
def test_ovdv_crypto_comes_from_deribit(client):
    d = data(client, "deriv/ovdv", symbol="BTC")
    assert d["source"].startswith("deribit")
    assert headline(d, "INDEX")["raw"] == pytest.approx(81483.01)   # recorded deribit_index_btc
    assert len(d["data"]["heat"]["y"]) == 4 and all(0.2 < row[4] < 1.5 for row in d["data"]["heat"]["z"])


@SURF
def test_skew_table_relations(client):
    d = data(client, "deriv/skew", symbol="AAPL")
    assert_table_payload(d)
    rows = section(d, "skew")["rows"]
    assert len(rows) == 8
    shown = [r for r in rows if r["rr25"] is not None]   # a 25-delta strike outside the quoted range is not reported
    assert len(shown) >= 6
    for r in shown:
        assert r["rr25"] == pytest.approx(r["iv_c25"] - r["iv_p25"], abs=1e-9)
        assert r["bf25"] == pytest.approx((r["iv_c25"] + r["iv_p25"]) / 2 - r["atm_iv"], abs=1e-9)
    assert sum(r["rr25"] < 0 for r in shown) >= len(shown) - 1
    assert d["data"]["charts"][0]["id"] == "term"


def _log_returns(n: int) -> list[float]:
    res = fixture_body("yahoo_chart_aapl_1y_1d")["chart"]["result"][0]
    closes = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
    rets = [math.log(b / a) for a, b in pairwise(closes)]
    return rets[-n:]


@SURF
def test_hivg_realized_vol_matches_an_independent_calculation(client):
    d = data(client, "deriv/hivg", symbol="AAPL")
    assert_table_payload(d)
    rv = {r["window"]: r for r in section(d, "rv")["rows"]}
    assert set(rv) >= {10, 20, 30, 60, 90, 252}
    for n in (20, 60):
        x = _log_returns(n)
        mean = sum(x) / n
        sd = math.sqrt(sum((v - mean) ** 2 for v in x) / (n - 1))
        assert rv[n]["cc_vol"] == pytest.approx(sd * math.sqrt(252), rel=1e-9)
    assert headline(d, "RV30")["raw"] == pytest.approx(rv[30]["cc_vol"])
    iv30 = headline(d, "IV30")["raw"]
    assert 0.1 < iv30 < 0.9 and headline(d, "VRP")["raw"] == pytest.approx(iv30 - rv[30]["cc_vol"])
    assert len(section(d, "iv")["rows"]) == 8
    assert d["data"]["charts"][0]["id"] == "rv"


@SURF
def test_hivg_iv_rank_waits_for_twenty_local_snapshots(client):
    d = data(client, "deriv/hivg", symbol="AAPL")
    assert headline(d, "IV RANK")["value"].startswith("NOT AVAILABLE") and "1 LOCAL SNAPSHOT" in headline(d, "IV RANK")["value"]
    assert "20" in headline(d, "IV RANK")["value"]
    d = data(client, "deriv/hivg", symbol="AAPL")   # the same day again does not add a second point
    assert "1 LOCAL SNAPSHOT" in headline(d, "IV RANK")["value"]


# --- RATES: YAS, SWPM, CDSW, FXFA, RATES views ------------------------------------------------------------------------

YAS = {"CPN": "4.5", "MAT": "2034-05-15", "FREQ": "2", "SETTLE": "2026-10-18"}


def pv_yield(y: float, cpn=0.045, freq=2) -> float:
    """Dirty price per 100 of the YAS bond at settlement 2026-10-18: 16 coupons, first in 28 days of a 184-day period."""
    w = 28 / 184
    return sum((100 * cpn / freq + (100 if k == 15 else 0)) / (1 + y / freq) ** (w + k) for k in range(16))


@RATES
def test_yas_from_yield_and_from_price_agree(client):
    d = data(client, "deriv/yas", **YAS, YLD="4.7")
    assert_table_payload(d)
    s = {r["name"]: r["value"] for r in section(d, "summary")["rows"]}
    assert s["ACCRUED"] == pytest.approx(2.25 * 156 / 184, abs=1e-6)
    assert s["DIRTY"] == pytest.approx(pv_yield(0.047), abs=1e-6) and s["CLEAN"] == pytest.approx(s["DIRTY"] - s["ACCRUED"], abs=1e-6)
    assert 5.0 < s["MOD DURATION"] < 7.0 and s["CONVEXITY"] > 0
    assert s["DV01 PER 1M"] == pytest.approx(s["MOD DURATION"] * s["DIRTY"] / 100 * 1_000_000 * 1e-4, rel=0.02)
    d2 = data(client, "deriv/yas", **YAS, PX=f"{s['CLEAN']:.8f}")
    s2 = {r["name"]: r["value"] for r in section(d2, "summary")["rows"]}
    assert s2["YIELD"] == pytest.approx(4.7, abs=1e-5)
    krd = section(d, "krd")["rows"]
    assert sum(r["krd"] for r in krd) == pytest.approx(s["MOD DURATION"], rel=0.03)
    cfs = section(d, "cashflows")["rows"]
    assert len(cfs) == 16 and cfs[0]["date"] == "2026-11-15" and cfs[-1]["date"] == "2034-05-15"
    assert cfs[-1]["principal"] == 100.0 and cfs[0]["coupon"] == pytest.approx(2.25)


@RATES
def test_yas_needs_a_price_or_a_yield(client):
    d = data(client, "deriv/yas", **YAS)
    assert d["data"]["status"].startswith("NOT RUNNABLE") and "PX" in d["data"]["status"] and "YLD" in d["data"]["status"]
    assert client.get("/api/deriv/yas", params={**YAS, "YLD": "4.7", "MAT": "2026-01-01"}).status_code == 400


@RATES
def test_swpm_flat_curve_is_internally_consistent(client):
    d = data(client, "deriv/swpm", N="10000000", FIXED="4.0", TENOR="5", FREQ="2", DIR="PAY", CURVE="FLAT:4.0")
    assert_table_payload(d)
    r, freq = 0.04, 2
    dfs = [math.exp(-r * (i + 1) / freq) for i in range(10)]
    par = (1 - dfs[-1]) / (sum(dfs) / freq)
    s = {x["name"]: x["value"] for x in section(d, "summary")["rows"]}
    assert s["PAR RATE"] == pytest.approx(par * 100, abs=1e-9)
    assert s["PV FIXED"] == pytest.approx(1e7 * 0.04 * sum(dfs) / freq, rel=1e-9)
    assert s["MTM"] == pytest.approx(s["PV FLOAT"] - s["PV FIXED"], rel=1e-9) and s["DV01"] > 0
    assert len(section(d, "cashflows")["rows"]) == 10
    assert "DISCOUNT PROXY" not in " ".join(d["data"]["notes"])   # a typed flat curve is not the Treasury proxy
    t = data(client, "deriv/swpm", N="10000000", FIXED="4.0", TENOR="5", FREQ="2", DIR="REC", CURVE="TSY")
    assert any("TREASURY PAR CURVE AS A DISCOUNT PROXY" in n for n in t["data"]["notes"])
    assert any("NOT SOFR" in n for n in t["data"]["notes"])


@RATES
def test_swpm_missing_terms_are_not_runnable(client):
    d = data(client, "deriv/swpm", N="10000000")
    assert d["data"]["status"].startswith("NOT RUNNABLE") and "FIXED" in d["data"]["status"] and "TENOR" in d["data"]["status"]


@RATES
def test_cdsw_matches_vibe_cds_price(client):
    case = next(c for c in json.loads((FIX / "quant_vibe_expected.json").read_bytes().decode("utf-8"))["cases"]
                if c["fn"] == "credit.cds_price" and c["args"]["spread_bps"] == 150.0 and "result" in c)
    d = data(client, "deriv/cdsw", SPREAD="150", REC="40", TENOR="5", RF="3", COUPON="100", N="10000000")
    assert_table_payload(d)
    s = {x["name"]: x["value"] for x in section(d, "summary")["rows"]}
    want = case["result"]
    assert s["PAR SPREAD BPS"] == pytest.approx(want["par_spread_bps"], rel=1e-9)
    assert s["UPFRONT AMOUNT"] == pytest.approx(want["upfront_amount"], rel=1e-9)
    assert s["RPV01"] == pytest.approx(want["rpv01"], rel=1e-9) and s["HAZARD RATE"] == pytest.approx(want["hazard_rate"], rel=1e-9)
    assert any("FLAT HAZARD" in n and "NOT THE ISDA STANDARD MODEL" in n for n in d["data"]["notes"])
    assert client.get("/api/deriv/cdsw", params={"SPREAD": "150", "REC": "100", "TENOR": "5", "RF": "3", "COUPON": "100",
                                                  "N": "1000000"}).status_code == 400


@RATES
def test_fxfa_typed_rates_follow_covered_interest_parity(client):
    d = data(client, "deriv/fxfa", pair="EURUSD", R1="2.0", R2="4.0")
    assert_table_payload(d)
    spot = headline(d, "SPOT")["raw"]
    assert spot == pytest.approx(1.1244)   # recorded EURUSD=X
    days = {"1W": 7, "1M": 30, "3M": 91, "6M": 182, "1Y": 365}
    rows = {r["tenor"]: r for r in section(d, "forwards")["rows"]}
    for tenor, n in days.items():
        want = spot * (1 + 0.04 * n / 360) / (1 + 0.02 * n / 360)
        assert rows[tenor]["forward"] == pytest.approx(want, rel=1e-9)
        assert rows[tenor]["points"] == pytest.approx((want - spot) * 10000, rel=1e-6)
    assert any("COVERED INTEREST PARITY ESTIMATE, NOT A DEALER QUOTE" in n for n in d["data"]["notes"])


@RATES
def test_fxfa_rates_from_data_and_not_runnable_without_them(client):
    d = data(client, "deriv/fxfa", pair="EURUSD")
    inputs = {r["name"]: r for r in section(d, "inputs")["rows"]}
    assert "ECB" in inputs["EUR RATE"]["basis"] and "Treasury" in inputs["USD RATE"]["basis"]
    one_year = {r["tenor"]: r for r in section(d, "forwards")["rows"]}["1Y"]
    assert (one_year["forward"] > headline(d, "SPOT")["raw"]) == (inputs["USD RATE"]["rate"] > inputs["EUR RATE"]["rate"])
    n = data(client, "deriv/fxfa", pair="GBPUSD")
    assert n["data"]["status"].startswith("NOT RUNNABLE") and "GBP" in n["data"]["status"]


def ecb_latest() -> dict[str, tuple[float, float]]:
    b = fixture_body("ecb_yc_spot")
    tenors = [v["id"] for v in b["structure"]["dimensions"]["series"][6]["values"]]
    out = {}
    for key, ser in b["dataSets"][0]["series"].items():
        obs = ser["observations"]
        last = max(obs, key=int)
        prev = sorted(obs, key=int)[-2]
        out[tenors[int(key.split(":")[6])].removeprefix("SR_")] = (obs[last][0], obs[prev][0])
    return out


@RATES
def test_rates_curve_eur_matches_the_ecb_recording(client):
    d = data(client, "rates/curve", ccy="EUR")
    assert_table_payload(d)
    assert d["source"].startswith("ecb")
    rows = {r["tenor"]: r for r in section(d, "curve")["rows"]}
    want = ecb_latest()
    assert set(rows) == set(want) == {"3M", "6M", "1Y", "2Y", "5Y", "10Y", "20Y", "30Y"}
    for tenor, (now, prev) in want.items():
        assert rows[tenor]["yield"] == pytest.approx(now) and rows[tenor]["d1"] == pytest.approx((now - prev) * 100, abs=1e-6)


@RATES
def test_rates_curve_other_currencies(client):
    boe = data(client, "rates/curve", ccy="GBP")
    assert {r["tenor"]: r["yield"] for r in section(boe, "curve")["rows"]} == pytest.approx({"5Y": 4.9692, "10Y": 5.383, "20Y": 5.7225})
    boc = data(client, "rates/curve", ccy="CAD")
    assert {r["tenor"]: r["yield"] for r in section(boc, "curve")["rows"]}["10Y"] == pytest.approx(3.94)
    jp = data(client, "rates/curve", ccy="JPY")
    rows = {r["tenor"]: r for r in section(jp, "curve")["rows"]}
    last = fixture_body("mof_jgb").strip().splitlines()[-1].split(",")
    assert rows["10Y"]["yield"] == pytest.approx(float(last[10])) and rows["1Y"]["yield"] == pytest.approx(float(last[1]))
    assert client.get("/api/rates/curve", params={"ccy": "XXX"}).status_code == 400


@RATES
def test_rates_nelson_siegel_fit_of_a_shown_curve(client):
    d = data(client, "rates/curve", ccy="EUR", fit="NS")
    fit = {r["name"]: r["value"] for r in section(d, "fit")["rows"]}
    assert set(fit) >= {"BETA0", "BETA1", "BETA2", "LAMBDA", "RMSE BP"}
    assert fit["RMSE BP"] < 30
    fitted = section(d, "curve")["rows"]
    assert all(r["fitted"] is not None for r in fitted)
    assert any("NELSON-SIEGEL" in n for n in d["data"]["notes"])


@RATES
def test_rates_credit_spreads_from_fred_oas(client):
    d = data(client, "rates/spreads")
    assert_table_payload(d)
    rows = {r["series"]: r for r in section(d, "oas")["rows"]}
    assert set(rows) == {"BAMLC0A0CM", "BAMLH0A0HYM2", "BAMLC0A4CBBB", "BAMLH0A1HYBB", "BAMLH0A3HYC"}
    last = [ln.split(",") for ln in fixture_body("fred_csv_BAMLC0A0CM").strip().splitlines() if not ln.startswith("observation")]
    last = [x for x in last if x[1] not in ("", ".")][-1]
    assert rows["BAMLC0A0CM"]["bp"] == pytest.approx(float(last[1]) * 100) and rows["BAMLC0A0CM"]["date"] == last[0]
    assert rows["BAMLH0A0HYM2"]["bp"] > rows["BAMLC0A0CM"]["bp"]   # high yield pays more than investment grade


@RATES
def test_rates_auctions_results_and_upcoming(client):
    d = data(client, "rates/auctions")
    assert_table_payload(d)
    res, up = section(d, "results")["rows"], section(d, "upcoming")["rows"]
    want = fixture_body("treasurydirect_auctioned")
    assert len(res) == len(want) == 35 and res[0]["cusip"] == want[0]["cusip"]
    assert res[0]["bid_to_cover"] == pytest.approx(float(want[0]["bidToCoverRatio"]))
    assert len(up) == len(fixture_body("treasurydirect_upcoming"))
    assert [r["auction_date"] for r in res] == sorted((r["auction_date"] for r in res), reverse=True)


# --- FUT: CT, WIRP, COT -----------------------------------------------------------------------------------------------

MONTH = {"F": "JAN", "G": "FEB", "H": "MAR", "J": "APR", "K": "MAY", "M": "JUN", "N": "JUL", "Q": "AUG", "U": "SEP", "V": "OCT",
         "X": "NOV", "Z": "DEC"}


def fut_price(symbol: str) -> float:
    return fixture_body("yahoo_chart_fut_" + symbol.replace(".", "_"))["chart"]["result"][0]["meta"]["regularMarketPrice"]


CL = [f"CL{m}{y}.NYM" for y, ms in (("26", "XZ"), ("27", "FGHJKMNQUVXZ"), ("28", "F")) for m in ms]


@FUT
def test_ct_crude_term_structure(client):
    d = data(client, "deriv/ct", root="CL")
    assert_table_payload(d)
    rows = section(d, "contracts")["rows"]
    assert [r["symbol"] for r in rows] == CL and len(rows) == 15
    assert rows[0]["contract"] == "NOV 2026" and rows[-1]["contract"] == "JAN 2028"
    prices = [fut_price(s) for s in CL]
    assert [r["price"] for r in rows] == pytest.approx(prices)
    diffs = [b - a for a, b in pairwise(prices)]
    shape = "CONTANGO" if all(x >= 0 for x in diffs) else "BACKWARDATION" if all(x <= 0 for x in diffs) else "MIXED"
    assert headline(d, "SHAPE")["value"] == shape
    r1 = rows[1]   # Nov -> Dec: a one-month gap; roll yield = (front - next) / next annualised by month spacing
    assert r1["roll_yield"] == pytest.approx((prices[0] - prices[1]) / prices[1] * 12 / 1)
    assert rows[-1]["spread"] == pytest.approx(prices[-1] - prices[0])
    assert any("MONTH SPACING, NOT EXPIRY DATES" in n for n in d["data"]["notes"])
    assert d["data"]["charts"][0]["id"] == "curve"


@FUT
def test_ct_other_roots_and_unknown_root(client):
    zn = section(data(client, "deriv/ct", root="ZN"), "contracts")["rows"]
    assert [r["symbol"] for r in zn] == ["ZNZ26.CBT", "ZNH27.CBT"]   # ZNM27 is not on Yahoo: skipped, not invented
    es = section(data(client, "deriv/ct", root="ES"), "contracts")["rows"]
    assert [r["contract"] for r in es] == ["DEC 2026", "MAR 2027", "JUN 2027", "SEP 2027"]
    r = client.get("/api/deriv/ct", params={"root": "QQQQ"})
    assert r.status_code == 400 and "CL" in r.json()["error"]


def fomc_dates() -> list[str]:
    html = fixture_body("fomc_calendar")
    out = []
    marks = [(m.start(), m.group(1)) for m in re.finditer(r"(\d{4})\s*FOMC\s*Meetings", html)]
    for i, (pos, year) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(html)
        for m in re.finditer(r"fomc-meeting__month[^>]*><strong>(\w+)</strong>.*?fomc-meeting__date[^>]*>([\d]+)-(\d+)", html[pos:end], re.DOTALL):
            out.append(f"{year}-{datetime.strptime(m.group(1), '%B').month:02d}-{int(m.group(3)):02d}")
    return out


@FUT
def test_wirp_path_across_fomc_meetings(client):
    d = data(client, "deriv/wirp")
    assert_table_payload(d)
    meetings = [m for m in fomc_dates() if m > "2026-10-18"]
    assert meetings[0] == "2026-10-28"
    path = section(d, "path")["rows"]
    assert [r["meeting"] for r in path][: len(meetings)] == meetings[: len(path)] and len(path) >= 4
    effr = [ln.split(",") for ln in fixture_body("fred_csv_DFF").strip().splitlines()[1:] if ln.split(",")[1] not in ("", ".")][-1]
    assert headline(d, "EFFR")["raw"] == pytest.approx(float(effr[1])) and headline(d, "EFFR")["value"].endswith(effr[0])
    months = {r["contract"]: r for r in section(d, "months")["rows"]}
    px = fut_price("ZQX26.CBT")
    assert months["ZQX26"]["implied"] == pytest.approx(100 - px, abs=1e-9)
    assert path[0]["rate_before"] == pytest.approx(float(effr[1]))
    assert path[0]["change_bp"] == pytest.approx((path[0]["rate_after"] - path[0]["rate_before"]) * 100, abs=1e-9)
    assert path[1]["rate_before"] == pytest.approx(path[0]["rate_after"])
    assert any("NOT A PROBABILITY FORECAST" in n for n in d["data"]["notes"])


@FUT
def test_cot_positions_history_and_percentile(client):
    d = data(client, "deriv/cot", market="ES")
    assert_table_payload(d)
    rows = fixture_body("cftc_legacy_es")
    top = rows[0]
    assert headline(d, "REPORT DATE")["value"] == top["report_date_as_yyyy_mm_dd"][:10] == "2026-10-13"
    assert headline(d, "OPEN INTEREST")["raw"] == int(top["open_interest_all"])
    pos = {r["group"]: r for r in section(d, "positions")["rows"]}
    nc = pos["NON-COMMERCIAL"]
    assert (nc["long"], nc["short"]) == (int(top["noncomm_positions_long_all"]), int(top["noncomm_positions_short_all"]))
    assert nc["net"] == nc["long"] - nc["short"]
    assert nc["chg_net"] == int(top["change_in_noncomm_long_all"]) - int(top["change_in_noncomm_short_all"])
    nets = [int(r["noncomm_positions_long_all"]) - int(r["noncomm_positions_short_all"]) for r in rows]
    assert headline(d, "NON-COMM NET PERCENTILE")["raw"] == pytest.approx(sum(n <= nets[0] for n in nets) / len(nets))
    hist = section(d, "history")["rows"]
    assert len(hist) == 160 and hist[0]["date"] == "2026-10-13" and hist[0]["noncomm_net"] == nets[0]
    assert d["data"]["charts"][0]["id"] == "net"


@FUT
def test_cot_market_resolution(client):
    assert headline(data(client, "deriv/cot", market="CRUDE"), "MARKET")["value"].startswith("WTI-PHYSICAL")
    assert headline(data(client, "deriv/cot", market="GOLD"), "MARKET")["value"].startswith("GOLD")
    r = client.get("/api/deriv/cot", params={"market": "ZZZZ"})
    assert r.status_code == 404 and r.json()["kind"] == "not_found"
    assert client.get("/api/deriv/cot").status_code == 400


@OPT
def test_unknown_function_is_not_found(client):
    r = client.get("/api/deriv/zzz")
    assert r.status_code == 404 and r.json()["kind"] == "not_found"
