"""Produces backend/tests/fixtures/btopt_vibe_expected.json by running Vibe-Trading's OWN options portfolio engine.

Not part of the app and never imported by it. Needs numpy, pandas and scipy (scipy is NOT an OpenTerm dependency: run it through uv's
`--with`) and a directory with the original files from HKUDS/Vibe-Trading @ d0db2e3 laid out as in the repo (the `agent` folder):
  agent/backtest/engines/options_portfolio.py   agent/backtest/engines/base.py   agent/backtest/metrics.py   agent/backtest/models.py
  agent/src/quantlib/options.py
The files are never copied into this repo.

    cd backend
    uv run --with scipy python ../scripts/vibe_btopt_crosscheck.py <path to the agent folder>

A temp package is built from the original files. Two things are replaced, nothing else:
  * `backtest/engines/base.py` is reduced to its `evaluation_start_index` function (cut out of the original by `ast`, so it is the
    original text); the rest of that file imports loaders and constraint code the options engine never touches.
  * `backtest/run_card.py` is a no-op `write_run_card` (the engine calls it after the metrics are final; it only writes a report).
The engine is then run on deterministic synthetic bars (a closed-form sin/cos path, stored in the fixture so both sides read the identical
numbers) with the loader/engine/run_dir shape Vibe's own tests use. Each case is
{"name", "config", "bars": {code: {"dates", "close"}}, "signals", "bars_per_year", "result": {"metrics", "equity", "trades", "greeks"} | "raises"};
NaN is null. A "fns" section holds direct calls to historical_volatility, iv_smile_adjustment and leg_iv.
"""

import ast
import contextlib
import datetime as dt
import io
import json
import math
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

SRC = Path(sys.argv[1])
OUT = Path(__file__).resolve().parents[1] / "backend" / "tests" / "fixtures" / "btopt_vibe_expected.json"
COPY = ["backtest/engines/options_portfolio.py", "backtest/metrics.py", "backtest/models.py", "src/quantlib/options.py"]
N = 130
DATES = pd.bdate_range("2025-01-02", periods=N)


def build_package() -> Path:
    root = Path(tempfile.mkdtemp(prefix="vibe_btopt_"))
    for pkg in ("src", "src/quantlib", "backtest", "backtest/engines"):
        (root / pkg).mkdir(parents=True, exist_ok=True)
        (root / pkg / "__init__.py").write_text("", encoding="utf-8")
    for rel in COPY:
        shutil.copy(SRC / rel, root / rel)
    base = (SRC / "backtest/engines/base.py").read_text(encoding="utf-8")
    tree = ast.parse(base)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "evaluation_start_index")
    seg = ast.get_source_segment(base, fn)
    (root / "backtest/engines/base.py").write_text(
        "from __future__ import annotations\n\nfrom typing import Any, Dict\n\nimport numpy as np\nimport pandas as pd\n\n\n" + seg + "\n", encoding="utf-8")
    (root / "backtest/run_card.py").write_text("def write_run_card(*a, **k):\n    return None\n", encoding="utf-8")
    return root


def path(seed: float, drift: float, vol: float, jump_at: int | None = None, jump: float = 0.0) -> list[float]:
    s, out = 0.0, []
    for t in range(N):
        r = drift + vol * math.sin(0.37 * t + seed) + 0.5 * vol * math.cos(1.31 * t + 2 * seed)
        if jump_at is not None and t == jump_at:
            r += jump
        s += r
        out.append(round(100.0 * math.exp(s), 4))
    return out


def D(i: int) -> str:
    return str(DATES[i].date())


def plus(i: int, days: int) -> str:
    return str((DATES[i].to_pydatetime() + dt.timedelta(days=days)).date())


def bars(code_paths: dict[str, list[float]], drop: dict[str, list[int]] | None = None) -> dict:
    out = {}
    for code, closes in code_paths.items():
        keep = [i for i in range(N) if i not in set((drop or {}).get(code, []))]
        out[code] = {"dates": [D(i) for i in keep], "close": [closes[i] for i in keep]}
    return out


def leg(t, k, e, q=None):
    d = {"type": t, "strike": k, "expiry": e}
    if q is not None:
        d["qty"] = q
    return d


def sig(i, action, legs, underlying="AAA"):
    return {"date": D(i), "action": action, "underlying": underlying, "legs": legs}


def cfg(codes, **opt):
    o = {"risk_free_rate": 0.04, "contract_multiplier": 100.0}
    o.update(opt)
    return {"codes": codes, "start_date": D(0), "end_date": D(N - 1), "initial_cash": 100_000, "commission": 0.001,
            "options_config": o}


def cases() -> list[dict]:
    a = path(0.3, 0.0004, 0.011, jump_at=60, jump=-0.05)
    b = path(1.1, 0.0002, 0.016)
    c = []

    def add(name, config, closes, signals, bpy=252, drop=None, **extra):
        c.append({"name": name, "config": config, "bars": bars(closes, drop), "signals": signals,
                  "bars_per_year": bpy, **extra})

    # A long straddle held to expiry: one leg exercises, the other expires; the expiry is a weekend day.
    e = plus(35, 42)
    add("long_straddle", cfg(["AAA"]), {"AAA": a},
        [sig(35, "open", [leg("call", 100.0, e, 2), leg("put", 100.0, e, 2)])])
    # A bull call spread on a smile, American, closed early by a close signal.
    e = plus(32, 60)
    add("bull_call_spread", cfg(["AAA"], iv_skew=-0.15, iv_curvature=0.05, exercise_style="american"), {"AAA": a},
        [sig(32, "open", [leg("call", 100.0, e, 5), leg("call", 108.0, e, -5)]),
         sig(70, "close", [leg("call", 100.0, e), leg("call", 108.0, e)])])
    # Deep in-the-money American put: early exercise fires.
    e = plus(10, 90)
    add("american_early_exercise", cfg(["AAA"], risk_free_rate=0.08, exercise_style="american"), {"AAA": a},
        [sig(10, "open", [leg("put", 140.0, e, 3)])])
    # A short strangle with margin; a second, oversized sale is rejected; one more fits.
    e = plus(25, 40)
    add("short_strangle_margin", cfg(["AAA"]), {"AAA": a},
        [sig(25, "open", [leg("put", 95.0, e, -5), leg("call", 105.0, e, -5)]),
         sig(40, "open", [leg("call", 98.0, plus(40, 30), -50)]),
         sig(45, "open", [leg("call", 130.0, plus(45, 30), -1)])])
    # Rolling: short call, closed, rolled to the next expiry, left to expire; the last open outlives the data.
    e1, e2 = plus(30, 28), plus(55, 28)
    add("rolling", cfg(["AAA"]), {"AAA": a},
        [sig(30, "open", [leg("call", 102.0, e1, -3)]),
         sig(55, "close", [leg("call", 102.0, e1)]),
         sig(55, "open", [leg("call", 104.0, e2, -3)]),
         sig(60, "close", [leg("put", 90.0, e2)]),          # nothing matches: no-op
         sig(100, "open", [leg("call", 120.0, plus(100, 90), 2)])])
    # Partial closes: a long lot (4, then an oversized 100 clamps to the remaining 6) and a short lot (3 of 8).
    e = plus(40, 80)
    add("partial_close", cfg(["AAA"]), {"AAA": a},
        [sig(40, "open", [leg("call", 100.0, e, 10), leg("put", 95.0, e, -8)]),
         sig(50, "close", [leg("call", 100.0, e, 4), leg("put", 95.0, e, 3)]),
         sig(60, "close", [leg("call", 100.0, e, 100)]),
         sig(70, "close", [leg("put", 95.0, e)])])
    # Two underlyings, one with missing bars (last-available price), cross-market annualisation (bars_per_year None).
    e = plus(30, 50)
    add("two_underlyings_none_bpy", cfg(["AAA", "BBB"]), {"AAA": a, "BBB": b},
        [sig(30, "open", [leg("call", 100.0, e, 2)], "AAA"), sig(30, "open", [leg("put", 100.0, e, -2)], "BBB"),
         sig(60, "close", [leg("call", 100.0, e)], "AAA")],
        bpy=None, drop={"BBB": [29, 30, 31, 45, 46, 47, 48]})
    # same_day_fill, margin off, warm-up bars, own default vol, mixed-case option types, no commission.
    e = plus(25, 60)
    cf = cfg(["AAA"], same_day_fill=True, margin_enabled=False, default_iv=0.25)
    cf["commission"] = 0.0
    cf["warmup_bars"] = 20
    add("same_day_nomargin_warmup", cf, {"AAA": a},
        [sig(10, "open", [leg("Call", 100.0, plus(10, 60), 1)]),           # inside the warm-up: never fills
         sig(25, "open", [leg("Put", 100.0, e, -40), leg("CALL", 110.0, e, -40)]),
         sig(80, "close", [leg("put", 100.0, e)])])
    # Errors.
    add("bad_default_iv", cfg(["AAA"], default_iv=-1.0), {"AAA": a}, [], raises_expected=True)
    add("bad_option_type", cfg(["AAA"]), {"AAA": a},
        [sig(20, "open", [leg("straddle", 100.0, plus(20, 30), 1)])], raises_expected=True)
    return c


def records(df: pd.DataFrame) -> list[dict]:
    df = df.astype(object).where(df.notna(), None)
    return json.loads(df.to_json(orient="records"))


def run_case(root: Path, case: dict) -> dict:
    from backtest.engines.options_portfolio import run_options_backtest

    data = {}
    for code, b in case["bars"].items():
        idx = pd.DatetimeIndex(pd.to_datetime(b["dates"]))
        cl = np.array(b["close"], dtype=float)
        data[code] = pd.DataFrame({"open": cl, "high": cl, "low": cl, "close": cl, "volume": 1000.0}, index=idx)

    class Loader:
        name = "synthetic"

        def fetch(self, codes, start, end):
            return {k: v.copy() for k, v in data.items()}

    class Engine:
        def generate(self, data_map):
            return case["signals"]

    run_dir = Path(tempfile.mkdtemp(prefix="vibe_btopt_run_"))
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            metrics = run_options_backtest(case["config"], Loader(), Engine(), run_dir, bars_per_year=case["bars_per_year"])
    except Exception as exc:  # noqa: BLE001 - recorded, not hidden
        return {"raises": type(exc).__name__}
    art = run_dir / "artifacts"
    rd = {k: records(pd.read_csv(art / f"{k}.csv", float_precision="round_trip")) for k in ("equity", "trades", "greeks")}
    shutil.rmtree(run_dir, ignore_errors=True)
    for t in rd["trades"]:  # trades.csv has a `reason` column for every row; only rejects carry one in the engine's records
        if t.get("reason") is None:
            t.pop("reason", None)
    return {"result": {"metrics": json.loads(json.dumps(metrics, allow_nan=False)), **rd}}


def fns(root: Path) -> list[dict]:
    from backtest.engines.options_portfolio import historical_volatility, iv_smile_adjustment, leg_iv

    out = []
    idx = DATES
    close = pd.Series(path(0.3, 0.0004, 0.011), index=idx)
    gapped = close.drop(close.index[[10, 11, 12, 40]])
    for name, ser, kw in [("hv_252", close, {"window": 30, "default_iv": 0.3, "bars_per_year": 252}),
                          ("hv_w10", close, {"window": 10, "default_iv": 0.2, "bars_per_year": 365}),
                          ("hv_none", gapped, {"window": 20, "default_iv": 0.3, "bars_per_year": None})]:
        hv = historical_volatility(ser, **kw)
        out.append({"fn": "historical_volatility", "name": name,
                    "args": {"dates": [str(x.date()) for x in ser.index], "close": [float(x) for x in ser], **kw},
                    "result": [float(x) for x in hv]})
    for args in [dict(S=100, K=100, base_iv=0.3, skew=-0.15, curvature=0.05), dict(S=100, K=80, base_iv=0.3, skew=-0.15, curvature=0.05),
                 dict(S=100, K=130, base_iv=0.2, skew=0.3, curvature=0.0), dict(S=100, K=60, base_iv=0.05, skew=-0.5, curvature=-0.2),
                 dict(S=0, K=100, base_iv=0.3, skew=-0.15, curvature=0.05), dict(S=100, K=-1, base_iv=0.0, skew=-0.15, curvature=0.05)]:
        out.append({"fn": "iv_smile_adjustment", "args": args, "result": iv_smile_adjustment(**args)})
        out.append({"fn": "leg_iv", "args": args, "result": leg_iv(args["S"], args["K"], args["base_iv"], args["skew"], args["curvature"])})
    flat = dict(S=100, K=80, base_iv=0.3, skew=0, curvature=0)
    out.append({"fn": "leg_iv", "args": flat, "result": leg_iv(flat["S"], flat["K"], flat["base_iv"], flat["skew"], flat["curvature"])})
    return out


def main() -> None:
    root = build_package()
    sys.path.insert(0, str(root))
    results = []
    for case in cases():
        expect_raise = case.pop("raises_expected", False)
        res = run_case(root, case)
        if expect_raise != ("raises" in res):
            raise SystemExit(f"case {case['name']}: raises={expect_raise} expected, got {list(res)}")
        results.append({**case, **res})
        print(case["name"], res.get("raises") or f"{len(res['result']['trades'])} trade records", file=sys.stderr)
    doc = {"source": "HKUDS/Vibe-Trading @ d0db2e3 agent/backtest/engines/options_portfolio.py (run by scripts/vibe_btopt_crosscheck.py)",
           "cases": results, "fns": fns(root)}
    OUT.write_bytes((json.dumps(doc, indent=1, allow_nan=False) + "\n").encode("utf-8"))
    print("wrote", OUT, file=sys.stderr)
    shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
