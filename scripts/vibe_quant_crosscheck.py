"""Produces backend/tests/fixtures/quant_vibe_expected.json by running Vibe-Trading's OWN quantlib code.

Not part of the app and never imported by it. Needs numpy, pandas and scipy (scipy is NOT an OpenTerm dependency: run it through uv's
`--with`) and a directory with the original files from HKUDS/Vibe-Trading @ d0db2e3 laid out as in the repo (the `agent` folder):
  agent/src/quantlib/{options,volatility,fixedincome,credit}.py   agent/backtest/options_payoff.py
The files are never copied into this repo.

    cd backend
    uv run --with scipy python ../scripts/vibe_quant_crosscheck.py <path to the agent folder>

Each case is {"fn": "<module>.<function>", "args": {...}}; the output adds "result" or "raises" (the exception class name).
Argument encodings: {"$date": "2026-10-18"} is a datetime.date; lists are lists (turned into numpy arrays for the payoff module,
which the original expects); {"$legs": [...]} builds OptionLeg objects. NaN is written as null, infinities as "inf" / "-inf".
"""

import dataclasses
import datetime as dt
import importlib
import json
import math
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np

SRC = Path(sys.argv[1])
OUT = Path(__file__).resolve().parents[1] / "backend" / "tests" / "fixtures" / "quant_vibe_expected.json"
FILES = {
    "src/quantlib/options.py": "src/quantlib/options.py", "src/quantlib/volatility.py": "src/quantlib/volatility.py",
    "src/quantlib/fixedincome.py": "src/quantlib/fixedincome.py", "src/quantlib/credit.py": "src/quantlib/credit.py",
    "backtest/options_payoff.py": "backtest/options_payoff.py",
}
MODULES = {"options": "src.quantlib.options", "heston": "src.quantlib.volatility", "fixedincome": "src.quantlib.fixedincome",
           "credit": "src.quantlib.credit", "payoff": "backtest.options_payoff"}

SPEC = {"S": 100.0, "K": 100.0, "T": 1.0, "r": 0.05, "sigma": 0.2}


def build_package() -> Path:
    root = Path(tempfile.mkdtemp(prefix="vibe_quant_"))
    for pkg in ("src", "src/quantlib", "backtest"):
        (root / pkg).mkdir(parents=True, exist_ok=True)
        (root / pkg / "__init__.py").write_text("", encoding="utf-8")
    for dst, src in FILES.items():
        shutil.copy(SRC / src, root / dst)
    # options_payoff imports bs_price from the engine file, which pulls in the whole backtest package; the engine's bs_price IS
    # quantlib.options.bs_price (the engine imports it from there), so the import is pointed at its origin. Nothing else changes.
    p = root / "backtest" / "options_payoff.py"
    p.write_text(p.read_text(encoding="utf-8").replace("from backtest.engines.options_portfolio import bs_price",
                                                       "from src.quantlib.options import bs_price"), encoding="utf-8")
    return root


def case(fn: str, **args) -> dict:
    return {"fn": fn, "args": args}


def d(s: str) -> dict:
    return {"$date": s}


def cases() -> list[dict]:
    out: list[dict] = []
    # --- Black-Scholes price and Greeks (closed form: tolerance 1e-10 in the tests)
    bs = [
        dict(S=100, K=100, T=1.0, r=0.05, sigma=0.2, option_type="call", q=0.0),
        dict(S=100, K=110, T=0.5, r=0.03, sigma=0.25, option_type="put", q=0.02),
        dict(S=50, K=45, T=0.25, r=0.01, sigma=0.4, option_type="call", q=0.03),
        dict(S=250, K=300, T=2.0, r=0.045, sigma=0.35, option_type="P", q=0.0),
        dict(S=100, K=90, T=0.0, r=0.05, sigma=0.2, option_type="call"),   # expired, in the money
        dict(S=100, K=100, T=0.0, r=0.05, sigma=0.2, option_type="put"),    # expired, at the money
        dict(S=100, K=100, T=1.0, r=0.05, sigma=0.0, option_type="call", q=0.01),   # zero volatility
        dict(S=0, K=100, T=1.0, r=0.05, sigma=0.2, option_type="put"),      # non-positive spot
        dict(S=100, K=100, T=1.0, r=0.05, sigma=0.2, option_type="kall"),   # unknown type: raises
    ]
    for a in bs:
        out.append(case("options.bs_price", **a))
        out.append(case("options.bs_greeks", **a))
    # --- implied volatility: the prices are Vibe's own bs_price at a known sigma, written by the runner (see "from_bs")
    iv = [
        dict(sigma=0.2, S=100, K=100, T=1.0, r=0.05, option_type="call", q=0.0),
        dict(sigma=0.35, S=100, K=120, T=0.5, r=0.03, option_type="call", q=0.01),
        dict(sigma=0.5, S=100, K=80, T=0.25, r=0.02, option_type="put", q=0.0),
        dict(sigma=0.9, S=100, K=100, T=2.0, r=0.05, option_type="put", q=0.02),
    ]
    for a in iv:
        out.append({"fn": "options.implied_volatility", "from_bs": a, "args": {}})
    out.append(case("options.implied_volatility", market_price=50.0, S=100, K=50, T=20 / 365, r=0.0, option_type="call"))   # price carries no vol: nan
    out.append(case("options.implied_volatility", market_price=1.0, S=100, K=100, T=0.0, r=0.05, option_type="call"))      # raises
    out.append(case("options.implied_volatility", market_price=120.0, S=100, K=100, T=1.0, r=0.05, option_type="call"))   # raises
    # --- barrier options, all four types, call and put, with and without rebate
    for bt, h in (("down-and-out", 85.0), ("down-and-in", 85.0), ("up-and-out", 120.0), ("up-and-in", 120.0)):
        for ot in ("call", "put"):
            for k, rebate in ((100.0, 0.0), (95.0, 3.0)):
                out.append(case("options.barrier_option_price", S=100.0, K=k, H=h, T=1.0, r=0.05, sigma=0.25, barrier_type=bt,
                                option_type=ot, q=0.02, rebate=rebate))
    out.append(case("options.barrier_option_price", S=100.0, K=100.0, H=90.0, T=0.0, r=0.05, sigma=0.25, barrier_type="doc"))
    out.append(case("options.barrier_option_price", S=100.0, K=100.0, H=-1.0, T=1.0, r=0.05, sigma=0.25, barrier_type="doc"))
    out.append(case("options.barrier_greeks", S=100.0, K=100.0, H=85.0, T=1.0, r=0.05, sigma=0.25, barrier_type="down-and-out",
                    option_type="call", q=0.02))
    out.append(case("options.barrier_greeks", S=100.0, K=105.0, H=120.0, T=0.75, r=0.04, sigma=0.3, barrier_type="up-and-in",
                    option_type="put", q=0.0))
    # --- Heston (quadrature: tolerance 1e-6 in the tests)
    hp = dict(S0=100.0, T=1.0, r=0.05, v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7, q=0.01)
    for k in (80.0, 100.0, 120.0):
        for ot in ("call", "put"):
            out.append(case("heston.heston_price", K=k, option_type=ot, **hp))
    out.append(case("heston.heston_price", S0=100.0, K=100.0, T=0.25, r=0.02, v0=0.09, kappa=1.5, theta=0.06, sigma_v=0.5, rho=0.3,
                    option_type="call"))
    out.append(case("heston.heston_price", S0=100.0, K=100.0, T=0.0, r=0.02, v0=0.09, kappa=1.5, theta=0.06, sigma_v=0.5, rho=0.3))
    out.append(case("heston.heston_price", S0=100.0, K=100.0, T=1.0, r=0.02, v0=0.09, kappa=1.5, theta=0.06, sigma_v=0.5, rho=1.5))
    out.append(case("heston.heston_feller_condition", kappa=2.0, theta=0.04, sigma_v=0.3))
    out.append(case("heston.heston_feller_condition", kappa=1.0, theta=0.04, sigma_v=0.6))
    # --- fixed income
    for dc in ("ACT/365F", "ACT/360", "ACT/ACT", "30/360", "30E/360"):
        out.append(case("fixedincome.year_fraction", start=d("2026-01-31"), end=d("2026-10-18"), day_count=dc))
        out.append(case("fixedincome.year_fraction", start=d("2024-02-29"), end=d("2028-02-29"), day_count=dc))
    out.append(case("fixedincome.accrued_interest", face=100.0, coupon_rate=0.045, freq=2, last_coupon=d("2026-05-15"),
                    settlement=d("2026-10-18"), next_coupon=d("2026-11-15"), day_count="ACT/ACT"))
    out.append(case("fixedincome.accrued_interest", face=100.0, coupon_rate=0.045, freq=2, last_coupon=d("2026-05-15"),
                    settlement=d("2026-10-18"), next_coupon=d("2026-11-15"), day_count="30/360"))
    out.append(case("fixedincome.accrued_interest", face=100.0, coupon_rate=0.045, freq=2, last_coupon=d("2026-05-15"),
                    settlement=d("2026-12-01"), next_coupon=d("2026-11-15")))   # raises: outside the period
    bonds = [
        dict(face=100.0, coupon_rate=0.05, ytm=0.06, n_periods=20, freq=2),
        dict(face=100.0, coupon_rate=0.04, ytm=0.04, n_periods=20, freq=1),
        dict(face=1000.0, coupon_rate=0.0, ytm=0.035, n_periods=10, freq=1),
        dict(face=100.0, coupon_rate=0.0725, ytm=0.051, n_periods=60, freq=2, compounding="continuous"),
    ]
    for b in bonds:
        out.append(case("fixedincome.bond_cashflows", face=b["face"], coupon_rate=b["coupon_rate"], n_periods=b["n_periods"],
                        freq=b["freq"]))
        for fn in ("bond_price", "macaulay_duration", "modified_duration", "convexity", "dv01"):
            out.append(case(f"fixedincome.{fn}", **b))
    out.append(case("fixedincome.key_rate_duration", face=100.0, coupon_rate=0.05, ytm=0.06, n_periods=20, freq=2))
    out.append(case("fixedincome.key_rate_duration", face=100.0, coupon_rate=0.0725, ytm=0.051, n_periods=60, freq=2,
                    key_rates=[1.0, 5.0, 10.0, 30.0]))
    for price, b in ((94.6, bonds[0]), (88.0, bonds[3])):
        out.append(case("fixedincome.ytm_solve", price=price, face=b["face"], coupon_rate=b["coupon_rate"],
                        n_periods=b["n_periods"], freq=b["freq"], compounding=b.get("compounding", "discrete")))
    out.append(case("fixedincome.ytm_solve", price=-5.0, face=100.0, coupon_rate=0.05, n_periods=10))   # raises
    out.append(case("fixedincome.nelson_siegel", tau=[0.25, 1.0, 5.0, 10.0, 30.0], beta0=0.045, beta1=-0.02, beta2=0.01, lambda1=1.8))
    out.append(case("fixedincome.svensson", tau=[0.25, 1.0, 5.0, 10.0, 30.0], beta0=0.045, beta1=-0.02, beta2=0.01, beta3=-0.005,
                    lambda1=1.8, lambda2=9.0))
    mats = [0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 20.0, 30.0]
    ylds = [0.0412, 0.0408, 0.0399, 0.0391, 0.0394, 0.0402, 0.0416, 0.0431, 0.0462, 0.0451]
    out.append(case("fixedincome.fit_yield_curve", maturities=mats, yields=ylds, model="nelson_siegel"))
    out.append(case("fixedincome.fit_yield_curve", maturities=mats, yields=ylds, model="svensson"))
    out.append(case("fixedincome.fit_yield_curve", maturities=mats[:3], yields=ylds[:3], model="svensson"))   # raises
    # --- credit
    for s, rec, ten, rf, cpn in ((150.0, 0.40, 5.0, 0.03, 100.0), (450.0, 0.25, 3.0, 0.045, 500.0), (60.0, 0.40, 1.0, 0.02, 100.0)):
        out.append(case("credit.cds_price", spread_bps=s, recovery_rate=rec, tenor_years=ten, risk_free_rate=rf, coupon_bps=cpn,
                        notional=10_000_000.0))
    out.append(case("credit.cds_price", spread_bps=150.0, recovery_rate=1.0, tenor_years=5.0))   # raises
    out.append(case("credit.hazard_rate_to_survival_probability", hazard_rate=0.025, tenor_years=5.0))
    out.append(case("credit.survival_probability_to_hazard_rate", survival_prob=0.88, tenor_years=5.0))
    out.append(case("credit.expected_loss", ead=1_000_000.0, pd=0.02, lgd=0.6))
    # --- payoff
    legs = {"$legs": [("call", 100.0, 1, None), ("call", 110.0, -1, None)]}
    cond = {"$legs": [("put", 80.0, 1, 0.6), ("put", 90.0, -1, 1.5), ("call", 110.0, -1, 1.4), ("call", 120.0, 1, 0.5)]}
    strad = {"$legs": [("call", 100.0, 1, None), ("put", 100.0, 1, None)]}
    naked = {"$legs": [("call", 105.0, -2, 2.5)]}
    grid = list(np.linspace(60.0, 140.0, 17))
    for name, lg in (("spread", legs), ("condor", cond), ("straddle", strad), ("naked", naked)):
        out.append(case("payoff.expiry_payoff", legs=lg, spot_grid=grid, entry_spot=100.0, time_to_expiry=0.25, rate=0.04, iv=0.3,
                        multiplier=100.0, commission_rate=0.001, _label=name))
    out.append(case("payoff.default_spot_grid", center=100.0, half_width_pct=0.3, points=7))
    out.append(case("payoff.scenario_grid", legs=legs, spot_grid=[80.0, 100.0, 120.0], iv_values=[0.2, 0.3, 0.4], entry_spot=100.0,
                    time_to_expiry=0.25, rate=0.04, entry_iv=0.3, multiplier=100.0, commission_rate=0.001))
    out.append(case("payoff.bull_call_spread", lower_strike=95.0, upper_strike=105.0, qty=2))
    out.append(case("payoff.long_straddle", strike=100.0, qty=1))
    out.append(case("payoff.iron_condor", put_wing=80.0, put_body=90.0, call_body=110.0, call_wing=120.0, qty=1))
    return out


def plain(o):
    if dataclasses.is_dataclass(o) and not isinstance(o, type):
        return {f.name: plain(getattr(o, f.name)) for f in dataclasses.fields(o)}
    if isinstance(o, dict):
        return {str(k): plain(v) for k, v in o.items()}
    if isinstance(o, np.ndarray):
        return [plain(x) for x in o.tolist()]
    if isinstance(o, (list, tuple)):
        return [plain(x) for x in o]
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return None if math.isnan(f) else ("inf" if f == math.inf else "-inf" if f == -math.inf else f)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if callable(o):
        return "<callable>"
    return o


def revive(mod, name: str, v):
    if isinstance(v, dict) and "$date" in v:
        return dt.date.fromisoformat(v["$date"])
    if isinstance(v, dict) and "$legs" in v:
        return [mod.OptionLeg(*leg) for leg in v["$legs"]]
    return v


def main() -> int:
    root = build_package()
    sys.path.insert(0, str(root))
    mods = {k: importlib.import_module(v) for k, v in MODULES.items()}
    result = []
    for c in cases():
        modname, fname = c["fn"].split(".")
        mod = mods[modname]
        args = {k: revive(mods.get("payoff"), k, v) for k, v in c["args"].items() if k != "_label"}
        if modname == "payoff":
            for k in ("spot_grid", "iv_values"):
                if k in args:
                    args[k] = np.asarray(args[k], dtype=float)
        if "from_bs" in c:
            a = dict(c["from_bs"])
            price = mods["options"].bs_price(a["S"], a["K"], a["T"], a["r"], a["sigma"], a["option_type"], a.get("q", 0.0))
            args = {"market_price": price, "S": a["S"], "K": a["K"], "T": a["T"], "r": a["r"], "option_type": a["option_type"],
                    "q": a.get("q", 0.0)}
            c = {**c, "args": args, "true_sigma": a["sigma"]}
        entry = dict(c)
        try:
            entry["result"] = plain(getattr(mod, fname)(**args))
        except Exception as e:  # recorded: the port must refuse the same inputs
            entry["raises"] = type(e).__name__
        result.append(entry)
    OUT.write_bytes(json.dumps({"source": "HKUDS/Vibe-Trading d0db2e3, run 2026-10-18", "cases": result}, indent=1).encode("utf-8"))
    print(f"wrote {len(result)} cases to {OUT}; raised: {sum('raises' in r for r in result)}")
    shutil.rmtree(root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
