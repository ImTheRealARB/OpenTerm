"""Produces backend/tests/fixtures/alpha_vibe_expected.json by running Vibe-Trading's OWN factor code (the whole ported Alpha Zoo).

Not part of the app and never imported by it. Needs numpy and pandas only (no scipy / statsmodels / arch) and a directory with the
original files from HKUDS/Vibe-Trading (the checkout's `agent` folder): `agent/src/factors/{base,_backend}.py` and
`agent/src/factors/zoo/<family>/*.py`. The files are never copied into this repo.

    cd backend
    uv run python ../scripts/vibe_alpha_crosscheck.py <path to the agent folder>

Which factors run: exactly the ones in `backend/openterm/quantlib/alpha/zoo_index.json` (what `scripts/port_vibe_alphas.py` ported), by
module file name. The panel is a seeded 300-bar x 8-name OHLCV panel; `vwap` (typical price) and `amount` (volume x vwap) are built HERE,
with Vibe's own non-China `vwap` rule, so the replay also checks OpenTerm's `extend_panel`. Per factor the fixture keeps the whole
matrix's finite count and sums (NaN positions are pinned by the count and the sampled rows) and the values on `ROWS`.
Output: {"source", "versions", "panel", "rows", "factors": {id: {"finite", "sum", "abs_sum", "values"}}}. NaN is written as null.
The factor modules' bottleneck fast path is switched off (pure numpy), the path an OpenTerm port has.
"""

from __future__ import annotations

import importlib
import json
import shutil
import subprocess
import sys
import tempfile
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

SRC = Path(sys.argv[1])
BACKEND = Path(__file__).resolve().parents[1] / "backend"
INDEX = BACKEND / "openterm" / "quantlib" / "alpha" / "zoo_index.json"
OUT = BACKEND / "tests" / "fixtures" / "alpha_vibe_expected.json"
ROWS = [90, 150, 230, 290, 296, 297, 298, 299]  # warm-ups run to 252 bars on a few academic factors; the last rows see every window full


def seeded_panel(n: int = 300, k: int = 8) -> tuple[pd.DatetimeIndex, list[str], dict[str, np.ndarray]]:
    rng = np.random.default_rng(1515)
    idx = pd.bdate_range("2024-01-02", periods=n)
    cols = ["AAPL", "MSFT", "NVDA", "AMZN", "JPM", "XOM", "JNJ", "KO"][:k]
    p0 = np.round(rng.uniform(25, 320, k), 2)
    mkt = rng.normal(0.0004, 0.008, n)
    beta = rng.uniform(0.6, 1.5, k)
    idio = rng.uniform(0.008, 0.022, k)
    close = np.zeros((n, k))
    open_ = np.zeros((n, k))
    prev = p0.copy()
    for t in range(n):
        open_[t] = prev * (1 + rng.normal(0, 0.004, k))
        close[t] = open_[t] * (1 + beta * mkt[t] + rng.normal(0, 1, k) * idio)
        prev = close[t]
    hi = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.005, (n, k))))
    lo = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.005, (n, k))))
    vol = np.round(np.exp(rng.normal(14.0, 0.35, (n, k))) * (1 + 15 * np.abs(close / open_ - 1)))
    return idx, cols, {"open": np.round(open_, 4), "high": np.round(hi, 4), "low": np.round(lo, 4), "close": np.round(close, 4),
                       "volume": vol}


def build_package(files: list[tuple[str, str]]) -> Path:
    root = Path(tempfile.mkdtemp(prefix="vibe_alpha_"))
    for pkg in ["src", "src/factors", "src/factors/zoo", *{f"src/factors/zoo/{fam}" for fam, _ in files}]:
        (root / pkg).mkdir(parents=True, exist_ok=True)
        (root / pkg / "__init__.py").write_text("", encoding="utf-8")
    for rel in ("base.py", "_backend.py"):
        shutil.copy(SRC / "src" / "factors" / rel, root / "src" / "factors" / rel)
    for fam, name in files:
        shutil.copy(SRC / "src" / "factors" / "zoo" / fam / f"{name}.py", root / "src" / "factors" / "zoo" / fam / f"{name}.py")
    # _backend reads a config flag through the app's settings; the flag is replaced by its "disabled" value. Nothing else changes.
    p = root / "src/factors/_backend.py"
    s = p.read_text(encoding="utf-8")
    needle = "    from src.config.accessor import get_env_config\n"
    assert needle in s
    s = s.replace(needle, "").replace("    if get_env_config().agent_tuning.vibe_trading_disable_bottleneck:\n        return\n", "    return\n")
    assert "get_env_config()" not in s and "src.config" not in s
    p.write_text(s, encoding="utf-8")
    return root


def cell(x: float):
    return None if not np.isfinite(x) else float(x)


def main() -> int:
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    files = [(z["family"], Path(z["file"]).stem) for z in index]
    root = build_package(files)
    sys.path.insert(0, str(root))
    idx, cols, arrays = seeded_panel()
    panel = {k: pd.DataFrame(v, index=idx, columns=cols) for k, v in arrays.items()}
    # Vibe's vwap rule for a non-China market (`base.vwap`): (O + H + L + C) / 4; `amount` is volume x vwap
    panel["vwap"] = (panel["open"] + panel["high"] + panel["low"] + panel["close"]) / 4.0
    panel["amount"] = panel["volume"] * panel["vwap"]
    factors, problems = {}, []
    for z, (fam, name) in zip(index, files, strict=True):
        mod = importlib.import_module(f"src.factors.zoo.{fam}.{name}")
        assert mod.__alpha_meta__["id"] == z["id"], (z["id"], mod.__alpha_meta__["id"])
        try:
            with np.errstate(all="ignore"), warnings.catch_warnings():
                warnings.simplefilter("ignore")
                out = mod.compute({k: v.copy() for k, v in panel.items()})
            out = out.reindex(index=idx, columns=cols)
        except Exception as e:  # noqa: BLE001
            problems.append(f"{z['id']}: {type(e).__name__}: {e}")
            continue
        a = out.to_numpy(dtype=float)
        fin = np.isfinite(a)
        factors[z["id"]] = {"finite": int(fin.sum()), "sum": float(a[fin].sum()), "abs_sum": float(np.abs(a[fin]).sum()),
                            "values": [[cell(x) for x in row] for row in a[ROWS]]}
    pnl = {"index": [d.strftime("%Y-%m-%d") for d in idx], "columns": cols}
    pnl.update({k: v.tolist() for k, v in arrays.items()})
    sha = subprocess.run(["git", "-C", str(SRC), "rev-parse", "--short=7", "HEAD"], capture_output=True, text=True).stdout.strip() or "unknown"
    data = {"source": f"HKUDS/Vibe-Trading@{sha}",
            "versions": {"python": sys.version.split()[0], "numpy": np.__version__, "pandas": pd.__version__},
            "panel": pnl, "rows": ROWS, "factors": factors}
    blob = json.dumps(data, separators=(",", ":"), allow_nan=False).encode("utf-8")
    OUT.write_bytes(blob)
    print(f"wrote {len(factors)} factors to {OUT} ({len(blob) / 1e6:.2f} MB)")
    for line in problems:
        print("PROBLEM", line)
    shutil.rmtree(root, ignore_errors=True)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
