"""Phase 14 step 8: the options portfolio backtest engine (`openterm.bt.engines.options_portfolio`), spec decision N.

The port is replayed against Vibe-Trading's OWN output: tests/fixtures/btopt_vibe_expected.json, produced by running the original engine
(HKUDS/Vibe-Trading @ d0db2e3) with scripts/vibe_btopt_crosscheck.py on deterministic synthetic bars. Each case holds its bars, config and
trade instructions plus the original's trades, equity, Greeks and metrics; strings must be equal, numbers agree to 1e-9 relative.
Strict xfail until step 8 landed; that step deleted the marker (BTOPT = lambda f: f).
"""

import json
import math
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from openterm.bt.engines import options_portfolio as op

FIX = Path(__file__).parent / "fixtures"
DOC = json.loads((FIX / "btopt_vibe_expected.json").read_bytes().decode("utf-8"))
CASES = {c["name"]: c for c in DOC["cases"]}
BTOPT = lambda f: f  # step 8 landed
REL = 1e-9


def frames(case: dict) -> dict[str, pd.DataFrame]:
    out = {}
    for code, b in case["bars"].items():
        idx = pd.DatetimeIndex(pd.to_datetime(b["dates"]))
        cl = pd.Series(b["close"], index=idx, dtype=float)
        out[code] = pd.DataFrame({"open": cl, "high": cl, "low": cl, "close": cl, "volume": 1000.0})
    return out


def run(case: dict) -> op.OptionsRun:
    return op.run_options_backtest(case["config"], frames(case), case["signals"], bars_per_year=case["bars_per_year"])


def same(got, want, where: str) -> None:
    if isinstance(want, dict):
        assert isinstance(got, dict) and set(got) == set(want), f"{where}: keys {sorted(got)} != {sorted(want)}"
        for k in want:
            same(got[k], want[k], f"{where}.{k}")
    elif isinstance(want, list):
        assert len(got) == len(want), f"{where}: {len(got)} items != {len(want)}"
        for i, (g, w) in enumerate(zip(got, want, strict=True)):
            same(g, w, f"{where}[{i}]")
    elif isinstance(want, bool) or want is None or isinstance(want, str):
        assert got == want, f"{where}: {got!r} != {want!r}"
    else:
        assert got is not None and not isinstance(got, str), f"{where}: {got!r} != {want!r}"
        assert math.isclose(float(got), float(want), rel_tol=REL, abs_tol=1e-12), f"{where}: {got!r} != {want!r}"


OK_CASES = [n for n, c in CASES.items() if "result" in c]
ERR_CASES = [n for n, c in CASES.items() if "raises" in c]


@BTOPT
@pytest.mark.parametrize("name", OK_CASES)
def test_run_matches_vibe(name):
    case, want = CASES[name], CASES[name]["result"]
    got = run(case)
    same(got.trades, want["trades"], "trades")
    same(got.equity, want["equity"], "equity")
    same(got.greeks, want["greeks"], "greeks")
    if case["bars_per_year"] is not None:
        same(got.metrics, want["metrics"], "metrics")


@BTOPT
def test_cross_market_annualisation_is_span_derived():
    """The one deliberate difference from Vibe. With bars_per_year=None Vibe resolves the factor through `effective_bars_per_year` on
    an equity index of date STRINGS, whose difference has no `.days`, so it silently falls back to 252; its own comment says the factor is
    span-derived. The port indexes by timestamp, so it is. Everything not annualised is identical, and the annualised keys equal Vibe's
    when the same equity path is annualised at the factor Vibe actually used."""
    case = CASES["two_underlyings_none_bpy"]
    want, got = case["result"]["metrics"], run(case)
    for k in ("final_value", "total_return", "max_drawdown", "trade_count", "win_rate", "profit_loss_ratio", "warnings"):
        same(got.metrics[k], want[k], k)
    assert got.metrics["annual_return"] != want["annual_return"]   # 130 bars over ~0.49 years is not 252 a year
    at_252 = op._calc_options_metrics(got.equity_series, case["config"]["initial_cash"], got.trades, 252)
    same({**at_252, "options_margin_hold": got.metrics["options_margin_hold"],
          "options_rejected_opens": got.metrics["options_rejected_opens"]}, want, "metrics@252")


@BTOPT
@pytest.mark.parametrize("name", ERR_CASES)
def test_errors_match_vibe(name):
    case = CASES[name]
    assert case["raises"] == "ValueError"
    with pytest.raises(ValueError):
        run(case)


@BTOPT
@pytest.mark.parametrize("case", [f for f in DOC["fns"] if f["fn"] == "historical_volatility"], ids=lambda f: f["name"])
def test_historical_volatility(case):
    a = case["args"]
    close = pd.Series(a["close"], index=pd.DatetimeIndex(pd.to_datetime(a["dates"])), dtype=float)
    got = op.historical_volatility(close, window=a["window"], default_iv=a["default_iv"], bars_per_year=a["bars_per_year"])
    same([float(x) for x in got], case["result"], "hv")


@BTOPT
@pytest.mark.parametrize("case", [f for f in DOC["fns"] if f["fn"] in ("iv_smile_adjustment", "leg_iv")])
def test_smile(case):
    a = case["args"]
    fn = getattr(op, case["fn"])
    got = fn(a["S"], a["K"], a["base_iv"], a["skew"], a["curvature"])
    assert math.isclose(got, case["result"], rel_tol=REL)


# --- behaviours the recorded cases are meant to cover (a fixture that stopped covering one would silently weaken the replay)


def sides(name: str) -> list[str]:
    return [t["side"] for t in CASES[name]["result"]["trades"]]


@BTOPT
def test_fixture_covers_each_behaviour():
    assert {"buy", "expire", "exercise"} <= set(sides("long_straddle"))
    assert "early_exercise" in sides("american_early_exercise")
    assert "reject" in sides("short_strangle_margin")
    assert sides("rolling").count("sell") == 2 and sides("rolling").count("expire") == 2
    pc = [t for t in CASES["partial_close"]["result"]["trades"] if t["side"] == "close"]
    assert [t["qty"] for t in pc] == [4, -3, 6, -5]   # partial, partial, oversized request clamped, whole remainder
    assert CASES["two_underlyings_none_bpy"]["bars_per_year"] is None


# --- Vibe's own behaviour tests (agent/tests/test_options_*.py), restated on this port


def test_label_and_result_shape():
    r = run(CASES["long_straddle"])
    assert r.label == "MODEL-PRICED OPTIONS (BLACK-SCHOLES ON HISTORICAL VOL), NOT MARKET QUOTES" == op.MODEL_LABEL
    s = r.equity_series
    assert isinstance(s.index, pd.DatetimeIndex) and len(s) == len(r.equity) and s.iloc[-1] == r.equity[-1]["equity"]


def test_rejected_open_is_not_a_trade_and_holds_no_margin():
    case = CASES["short_strangle_margin"]
    got = run(case)
    assert got.metrics["options_rejected_opens"] == 1
    assert got.metrics["trade_count"] == sum(1 for t in got.trades if t["side"] != "reject")
    rej = next(t for t in got.trades if t["side"] == "reject")
    assert rej["reason"] == "insufficient buying power"


def test_margin_off_has_no_margin_keys():
    got = run(CASES["same_day_nomargin_warmup"])
    assert "options_margin_hold" not in got.metrics and all(r["margin_hold"] == 0.0 for r in got.equity)


def test_signal_fills_on_the_next_bar_not_its_own():
    case = CASES["long_straddle"]
    sig_date = case["signals"][0]["date"]
    got = run(case)
    first = got.trades[0]
    assert first["side"] == "buy" and first["timestamp"] > sig_date


def test_warmup_bars_are_not_graded():
    got = run(CASES["same_day_nomargin_warmup"])
    assert len(got.equity) == 130 - 20 and all(t["entry_date"] >= got.equity[0]["timestamp"] for t in got.trades)


def test_smile_open_and_mark_use_one_vol():
    # Vibe #1293: opening on the smile and marking flat books profit the instant the leg exists. With one shared leg_iv the first mark is
    # the entry price: a long OTM call bought and marked on the same bar changes equity only by the commission.
    case = json.loads(json.dumps(CASES["bull_call_spread"]))
    case["signals"] = [case["signals"][0]]
    case["config"]["options_config"]["iv_skew"] = -0.15
    got = run(case)
    fill = next(i for i, g in enumerate(got.greeks) if g["num_positions"])
    before, after = got.equity[fill - 1]["equity"], got.equity[fill]["equity"]
    assert abs(after - before) < 0.002 * 100_000 * 0.1   # only the 0.1% commission on the premium (a few hundred at most)


def test_option_type_is_folded_to_lower_case():
    p = op.OptionPosition("CALL", 100.0, "2026-01-16", 1, 1.0, "2025-01-02", "X")
    assert p.option_type == "call" and p.intrinsic_value(110.0) == 10.0
    with pytest.raises(ValueError):
        op.OptionPosition("straddle", 100.0, "2026-01-16", 1, 1.0, "2025-01-02", "X")


def test_hv_default_vol_before_a_full_window_and_no_backfill():
    close = pd.Series([100 + i * 0.5 for i in range(40)], index=pd.bdate_range("2025-01-02", periods=40))
    hv = op.historical_volatility(close, window=30, default_iv=0.3)
    assert (hv.iloc[:30] == 0.3).all() and hv.iloc[30] != 0.3


def test_no_data_and_bad_vol_raise_value_error():
    with pytest.raises(ValueError):
        op.run_options_backtest({"codes": ["A"]}, {}, [])


def test_module_does_not_import_scipy():
    code = "import sys, openterm.bt.engines.options_portfolio; sys.exit(1 if 'scipy' in sys.modules else 0)"
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0
