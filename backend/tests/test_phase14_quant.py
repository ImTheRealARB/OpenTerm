"""Phase 14 step 2: the quant library (`openterm.quant`), spec docs/specs/PHASE_14.md decisions G, K, J.

Two kinds of test, both written before the code:
  * textbook values (Hull) and identities (put-call parity, in-out parity, convergence), no dependency on Vibe;
  * the port against Vibe-Trading's OWN output: tests/fixtures/quant_vibe_expected.json, produced by running the original files
    (HKUDS/Vibe-Trading @ d0db2e3) with scripts/vibe_quant_crosscheck.py. Each case is {"fn": "<module>.<function>", "args", "result"
    | "raises"}; NaN is null, infinities are "inf" / "-inf". Closed forms must agree to 1e-9 relative; quadrature (Heston) to 1e-6; the
    curve fit is compared by the fitted curve (the simplex may end elsewhere in a flat valley), not by its parameters.
Was strict xfail until step 2 landed; the marker is gone (QUANT = lambda f: f).
"""

import dataclasses
import datetime as dt
import json
import math
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures"


def xf(group: str, step: int):
    return pytest.mark.xfail(strict=True, reason=f"Phase 14 step {step}: {group}")


QUANT = lambda f: f  # step 2 landed

CASES = json.loads((FIX / "quant_vibe_expected.json").read_bytes().decode("utf-8"))["cases"]
EXCEPTIONS = {"ValueError": ValueError}


def mod(name: str):
    import importlib

    return importlib.import_module(f"openterm.quant.{name}")


def revive(v):
    if isinstance(v, dict) and "$date" in v:
        return dt.date.fromisoformat(v["$date"])
    return v


def approx_tree(got, want, rel: float, path: str = ""):
    """Compares nested results: floats with a relative tolerance (and 1e-12 absolute floor), null as NaN, "inf" strings."""
    if isinstance(want, dict):
        got = dataclasses.asdict(got) if dataclasses.is_dataclass(got) else got
        assert isinstance(got, dict), path
        for k, w in want.items():
            assert k in got, f"{path}.{k} missing"
            approx_tree(got[k], w, rel, f"{path}.{k}")
    elif isinstance(want, list):
        got = list(got)
        assert len(got) == len(want), f"{path}: {len(got)} != {len(want)}"
        for i, (g, w) in enumerate(zip(got, want, strict=True)):
            approx_tree(g, w, rel, f"{path}[{i}]")
    elif want is None:
        assert got is None or (isinstance(got, float) and math.isnan(got)), f"{path}: {got!r} should be NaN"
    elif want in ("inf", "-inf"):
        assert got == float(want), path
    elif isinstance(want, (bool, str)):
        assert got == want, path
    else:
        assert got == pytest.approx(want, rel=rel, abs=1e-12), f"{path}: {got!r} != {want!r}"


def run_case(case: dict):
    modname, fname = case["fn"].split(".")
    m = mod(modname)
    args = {k: revive(v) for k, v in case["args"].items() if k != "_label"}
    if modname == "payoff":
        args = {k: ([m.OptionLeg(*leg) for leg in v["$legs"]] if isinstance(v, dict) and "$legs" in v else v) for k, v in args.items()}
        for key in ("legs",):
            if key in case["args"] and isinstance(case["args"][key], dict):
                args[key] = [m.OptionLeg(*leg) for leg in case["args"][key]["$legs"]]
    fn = getattr(m, fname)
    if "raises" in case:
        with pytest.raises(EXCEPTIONS[case["raises"]]):
            fn(**args)
        return None
    return fn(**args)


def tolerance(case: dict) -> float:
    if case["fn"].startswith("heston.heston_price"):
        return 1e-6
    if case["fn"].startswith("fixedincome.fit_yield_curve"):
        return 1e-3
    if case["fn"] == "options.implied_volatility":
        return 1e-6
    if case["fn"] == "options.barrier_greeks":
        return 1e-6   # gamma is a second finite difference (dS = 0.01): one ulp of price noise shows at about 1e-8 relative
    return 1e-9


def vibe_cases(*prefixes: str):
    """One parametrized test per recorded case; the id is the function and the case's position (stable across xdist workers)."""
    return [pytest.param(c, id=f"{c['fn']}-{i}") for i, c in enumerate(CASES) if c["fn"].startswith(prefixes)]


# --- the port against Vibe's own numbers ------------------------------------------------------------------------

@QUANT
@pytest.mark.parametrize("case", vibe_cases("options."))
def test_options_match_vibe(case):
    got = run_case(case)
    if "raises" in case:
        return
    if "true_sigma" in case:
        assert got == pytest.approx(case["result"], rel=1e-6) == pytest.approx(case["true_sigma"], rel=1e-6)
        return
    approx_tree(got, case["result"], tolerance(case))


@QUANT
@pytest.mark.parametrize("case", vibe_cases("heston."))
def test_heston_matches_vibe(case):
    got = run_case(case)
    if "raises" not in case:
        approx_tree(got, case["result"], tolerance(case))


@QUANT
@pytest.mark.parametrize("case", vibe_cases("fixedincome."))
def test_fixed_income_matches_vibe(case):
    got = run_case(case)
    if "raises" in case:
        return
    if case["fn"].endswith("fit_yield_curve"):
        m = mod("fixedincome")
        grid = [0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 20.0, 30.0]
        want = _vibe_curve(case, grid)
        assert [float(x) for x in got(grid)] == pytest.approx(want, abs=5e-5)  # within half a basis point everywhere
        assert got.rmse == pytest.approx(case["result"]["rmse"], abs=2e-5)
        assert got.model == case["result"]["model"] and m is not None
        return
    approx_tree(got, case["result"], tolerance(case))


def _vibe_curve(case: dict, grid: list[float]) -> list[float]:
    """Vibe's fitted curve evaluated from its recorded parameters (the closed forms, which the port also implements)."""
    p = case["result"]["params"]

    def ns(t, b0, b1, b2, lam):
        x = t / lam
        f = (1 - math.exp(-x)) / x
        return b0 + b1 * f + b2 * (f - math.exp(-x))

    def sv(t, b0, b1, b2, b3, l1, l2):
        x1, x2 = t / l1, t / l2
        f1, f2 = (1 - math.exp(-x1)) / x1, (1 - math.exp(-x2)) / x2
        return b0 + b1 * f1 + b2 * (f1 - math.exp(-x1)) + b3 * (f2 - math.exp(-x2))

    return [(ns if case["result"]["model"] == "nelson_siegel" else sv)(t, *p) for t in grid]


@QUANT
@pytest.mark.parametrize("case", vibe_cases("credit."))
def test_credit_matches_vibe(case):
    got = run_case(case)
    if "raises" not in case:
        approx_tree(got, case["result"], tolerance(case))


@QUANT
@pytest.mark.parametrize("case", vibe_cases("payoff."))
def test_payoff_matches_vibe(case):
    got = run_case(case)
    if "raises" in case:
        return
    if isinstance(got, list) and got and not isinstance(got[0], (int, float)):  # strategy builders return OptionLeg lists
        got = [dataclasses.asdict(x) for x in got]
    elif isinstance(got, tuple):
        got = list(got)
    approx_tree(got, case["result"], tolerance(case))


# --- textbook values and identities (no Vibe involved) ----------------------------------------------------------

@QUANT
def test_black_scholes_textbook():
    o = mod("options")
    assert o.bs_price(42, 40, 0.5, 0.10, 0.20, "call") == pytest.approx(4.76, abs=0.005)    # Hull, Example 15.6
    assert o.bs_price(42, 40, 0.5, 0.10, 0.20, "put") == pytest.approx(0.81, abs=0.005)
    assert o.bs_price(100, 100, 1.0, 0.05, 0.2, "call") == pytest.approx(10.4506, abs=1e-4)
    assert o.bs_price(100, 100, 1.0, 0.05, 0.2, "put") == pytest.approx(5.5735, abs=1e-4)


@QUANT
def test_put_call_parity_and_greek_signs():
    o = mod("options")
    for S, K, T, r, q, sig in [(100, 100, 1.0, 0.05, 0.0, 0.2), (80, 95, 0.4, 0.02, 0.03, 0.35), (500, 420, 2.0, 0.045, 0.01, 0.15)]:
        c, p = o.bs_price(S, K, T, r, sig, "call", q), o.bs_price(S, K, T, r, sig, "put", q)
        assert c - p == pytest.approx(S * math.exp(-q * T) - K * math.exp(-r * T), abs=1e-9)
        gc, gp = o.bs_greeks(S, K, T, r, sig, "call", q), o.bs_greeks(S, K, T, r, sig, "put", q)
        assert gc["delta"] - gp["delta"] == pytest.approx(math.exp(-q * T), abs=1e-12)
        assert gc["gamma"] == pytest.approx(gp["gamma"]) and gc["vega"] == pytest.approx(gp["vega"])
        assert gc["gamma"] > 0 and gc["vega"] > 0 and 0 < gc["delta"] < 1 and -1 < gp["delta"] < 0
    # delta against a finite difference of price: the Greeks and the pricer agree
    g = o.bs_greeks(100, 105, 0.75, 0.04, 0.3, "call", 0.01)
    h = 1e-4
    fd = (o.bs_price(100 + h, 105, 0.75, 0.04, 0.3, "call", 0.01) - o.bs_price(100 - h, 105, 0.75, 0.04, 0.3, "call", 0.01)) / (2 * h)
    assert g["delta"] == pytest.approx(fd, abs=1e-6)


@QUANT
def test_implied_volatility_round_trip_and_refusals():
    o = mod("options")
    for sig in (0.05, 0.2, 0.6, 1.5):
        px = o.bs_price(100, 90, 0.5, 0.03, sig, "put", 0.01)
        assert o.implied_volatility(px, 100, 90, 0.5, 0.03, "put", 0.01) == pytest.approx(sig, rel=1e-5)
    # a price that carries no volatility information is NaN, never a confident wrong number
    assert math.isnan(o.implied_volatility(50.0, 100, 50, 20 / 365, 0.0, "call"))
    with pytest.raises(ValueError):
        o.implied_volatility(120.0, 100, 100, 1.0, 0.05, "call")   # above the no-arbitrage ceiling


@QUANT
def test_barrier_in_out_parity():
    o = mod("options")
    S, K, T, r, sig, q = 100.0, 100.0, 1.0, 0.05, 0.25, 0.02
    van = o.bs_price(S, K, T, r, sig, "call", q)
    for out, inn, h in (("down-and-out", "down-and-in", 85.0), ("up-and-out", "up-and-in", 125.0)):
        a = o.barrier_option_price(S, K, h, T, r, sig, out, "call", q)
        b = o.barrier_option_price(S, K, h, T, r, sig, inn, "call", q)
        assert a + b == pytest.approx(van, abs=1e-9)


@QUANT
def test_binomial_matches_black_scholes_and_hull_american_put():
    b = mod("binomial")
    o = mod("options")
    # Hull: two-step American put, S=50 K=52 r=5% sigma=30% T=2 -> 7.4284 (European 6.2457)
    assert b.binomial_price(50, 52, 2.0, 0.05, 0.30, "put", american=True, steps=2) == pytest.approx(7.4284, abs=1e-4)
    assert b.binomial_price(50, 52, 2.0, 0.05, 0.30, "put", american=False, steps=2) == pytest.approx(6.2457, abs=1e-4)
    # European converges to Black-Scholes; American put carries an early-exercise premium; American call without dividends does not
    eu = b.binomial_price(100, 100, 1.0, 0.05, 0.2, "put", american=False, steps=1000)
    assert eu == pytest.approx(o.bs_price(100, 100, 1.0, 0.05, 0.2, "put"), abs=5e-3)
    am = b.binomial_price(100, 100, 1.0, 0.05, 0.2, "put", american=True, steps=1000)
    assert am == pytest.approx(6.09, abs=0.01) and am > eu
    c_am = b.binomial_price(100, 100, 1.0, 0.05, 0.2, "call", american=True, steps=500)
    assert c_am == pytest.approx(o.bs_price(100, 100, 1.0, 0.05, 0.2, "call"), abs=1e-2)
    # American call on a dividend payer can exercise early: premium over European is >= 0
    assert b.binomial_price(100, 90, 1.0, 0.03, 0.2, "call", american=True, steps=400, q=0.06) >= \
        b.binomial_price(100, 90, 1.0, 0.03, 0.2, "call", american=False, steps=400, q=0.06) - 1e-12


@QUANT
def test_heston_reduces_to_black_scholes_and_keeps_parity():
    h = mod("heston")
    o = mod("options")
    # vol of vol -> 0 with v0 = theta: the variance is constant, so Heston is Black-Scholes at sigma = sqrt(v0)
    px = h.heston_price(100, 100, 1.0, 0.05, 0.04, 2.0, 0.04, 1e-4, 0.0, "call")
    assert px == pytest.approx(o.bs_price(100, 100, 1.0, 0.05, 0.2, "call"), abs=1e-3)
    c = h.heston_price(100, 110, 0.5, 0.03, 0.05, 1.5, 0.06, 0.4, -0.6, "call", 0.01)
    p = h.heston_price(100, 110, 0.5, 0.03, 0.05, 1.5, 0.06, 0.4, -0.6, "put", 0.01)
    assert c - p == pytest.approx(100 * math.exp(-0.01 * 0.5) - 110 * math.exp(-0.03 * 0.5), abs=1e-6)
    # negative correlation: the skew is downward (out-of-the-money puts are richer than calls of the same distance)
    lo = h.heston_price(100, 85, 1.0, 0.03, 0.04, 2.0, 0.04, 0.5, -0.8, "put")
    hi = h.heston_price(100, 118, 1.0, 0.03, 0.04, 2.0, 0.04, 0.5, -0.8, "call")
    sig_lo = o.implied_volatility(lo, 100, 85, 1.0, 0.03, "put")
    sig_hi = o.implied_volatility(hi, 100, 118, 1.0, 0.03, "call")
    assert sig_lo > sig_hi


@QUANT
def test_numerics_are_scipy_free():
    import sys

    n = mod("numerics")
    assert n.norm_cdf(0.0) == 0.5 and n.norm_cdf(1.96) == pytest.approx(0.9750021048517795, abs=1e-12)
    assert n.norm_pdf(0.0) == pytest.approx(1 / math.sqrt(2 * math.pi))
    assert n.brent(lambda x: x * x - 2, 0.0, 2.0) == pytest.approx(math.sqrt(2), abs=1e-12)
    assert n.integrate(lambda x: math.sin(x), 0.0, math.pi) == pytest.approx(2.0, abs=1e-10)
    # In a fresh interpreter: another test on the same xdist worker may already have imported scipy (the Phase 15 quantlib tests do).
    import subprocess

    code = ("import sys; import openterm.quant.options, openterm.quant.heston, openterm.quant.fixedincome, openterm.quant.credit; "
            "sys.exit(1 if 'scipy' in sys.modules else 0)")
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0, "openterm.quant must not import scipy"


@QUANT
def test_bond_textbook_and_mid_period_settlement():
    f = mod("fixedincome")
    # 5% coupon, 10 years, semi-annual, yield 6%: 92.56126 (the textbook 92.56; also Vibe's own fixture)
    assert f.bond_price(100, 0.05, 0.06, 20, 2) == pytest.approx(92.56126, abs=1e-5)   # sum of 20 half-year flows at 3%
    assert f.bond_price(100, 0.04, 0.04, 20, 1) == pytest.approx(100.0, abs=1e-9)      # coupon = yield -> par
    # settle between coupons: accrued by actual days; the dirty price discounts the first coupon by the stub fraction
    q = f.price_mid_period(face=100.0, coupon_rate=0.045, ytm=0.047, freq=2, last_coupon=dt.date(2026, 5, 15),
                           next_coupon=dt.date(2026, 11, 15), settlement=dt.date(2026, 10, 18), n_periods=16, day_count="ACT/ACT")
    assert q["accrued"] == pytest.approx(2.25 * 156 / 184, abs=1e-9)
    assert q["dirty"] == pytest.approx(q["clean"] + q["accrued"], abs=1e-12)
    w = 28 / 184  # days to the next coupon over days in the period
    pv = sum((2.25 + (100 if k == 15 else 0)) / (1 + 0.047 / 2) ** (w + k) for k in range(16))
    assert q["dirty"] == pytest.approx(pv, abs=1e-9)
    # the yield solved from that clean price is the yield used
    assert f.ytm_from_clean(q["clean"], face=100.0, coupon_rate=0.045, freq=2, last_coupon=dt.date(2026, 5, 15),
                            next_coupon=dt.date(2026, 11, 15), settlement=dt.date(2026, 10, 18), n_periods=16,
                            day_count="ACT/ACT") == pytest.approx(0.047, abs=1e-10)


@QUANT
def test_swap_valuation_flat_curve():
    s = mod("swap")
    r, n, freq, years = 0.04, 10_000_000.0, 2, 5
    sw = s.value_swap(notional=n, fixed_rate=0.04, years=years, freq=freq, curve=s.flat_curve(r), pay_fixed=True)
    dfs = [math.exp(-r * (i + 1) / freq) for i in range(years * freq)]
    par = (1 - dfs[-1]) / (sum(dfs) / freq)
    assert sw["par_rate"] == pytest.approx(par, abs=1e-12)
    assert sw["pv_fixed_leg"] == pytest.approx(n * 0.04 * sum(dfs) / freq, rel=1e-12)
    assert sw["pv_float_leg"] == pytest.approx(n * (1 - dfs[-1]), rel=1e-12)
    assert sw["mtm"] == pytest.approx(sw["pv_float_leg"] - sw["pv_fixed_leg"], rel=1e-12)
    at_par = s.value_swap(notional=n, fixed_rate=par, years=years, freq=freq, curve=s.flat_curve(r), pay_fixed=True)
    assert abs(at_par["mtm"]) < 1e-6 * n
    up = s.value_swap(notional=n, fixed_rate=0.04, years=years, freq=freq, curve=s.flat_curve(r + 1e-4), pay_fixed=True)
    assert sw["dv01"] == pytest.approx(up["mtm"] - sw["mtm"], rel=0.01) and sw["dv01"] > 0   # pay-fixed gains when rates rise
    rec = s.value_swap(notional=n, fixed_rate=0.04, years=years, freq=freq, curve=s.flat_curve(r), pay_fixed=False)
    assert rec["mtm"] == pytest.approx(-sw["mtm"], rel=1e-12)


@QUANT
def test_bootstrap_zero_curve_reprices_par_instruments():
    s = mod("swap")
    par = {0.5: 0.040, 1.0: 0.041, 2.0: 0.043, 3.0: 0.044, 5.0: 0.046, 10.0: 0.048}
    curve = s.bootstrap_par_curve(par, freq=2)
    for t, c in par.items():
        n = round(t * 2)
        dfs = [curve.df(i / 2) for i in range(1, n + 1)]
        assert sum(c / 2 * d for d in dfs) + dfs[-1] == pytest.approx(1.0, abs=1e-9)   # a par bond at its own coupon prices to 100


@QUANT
def test_payoff_strategies_by_hand():
    p = mod("payoff")
    legs = [p.OptionLeg("call", 270.0, 1, 5.0), p.OptionLeg("call", 290.0, -1, 2.0)]
    rep = p.expiry_payoff(legs, [250.0, 270.0, 273.0, 290.0, 310.0], entry_spot=275.0, time_to_expiry=0.2, rate=0.04, iv=0.25,
                          multiplier=100.0, commission_rate=0.0)
    assert list(rep.payoff) == pytest.approx([-300.0, -300.0, 0.0, 1700.0, 1700.0])
    assert rep.net_premium == pytest.approx(300.0)
    assert rep.max_profit == pytest.approx(1700.0) and rep.max_loss == pytest.approx(-300.0)
    assert rep.breakevens == pytest.approx([273.0])
    assert not rep.profit_unbounded and not rep.loss_unbounded
    naked = p.expiry_payoff([p.OptionLeg("call", 105.0, -1, 2.0)], [90.0, 120.0], entry_spot=100.0, time_to_expiry=0.2, rate=0.04,
                            iv=0.3, multiplier=1.0, commission_rate=0.0)
    assert naked.loss_unbounded and naked.max_loss == -math.inf and naked.max_profit == pytest.approx(2.0)
