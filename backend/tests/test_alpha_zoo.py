"""The full Alpha Zoo (every Vibe-Trading price/volume factor OpenTerm can feed): registry, skipped list, Vibe's own numbers, lookahead ban.

`alpha_vibe_expected.json` is written by `scripts/vibe_alpha_crosscheck.py`, which runs Vibe's OWN factor code on a seeded panel.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from openterm.quantlib.alpha import FAMILIES, ZOO, compute_factor, extend_panel
from openterm.quantlib.alpha import base as ops

HERE = Path(__file__).resolve().parent
ALPHA_DIR = HERE.parent / "openterm" / "quantlib" / "alpha"
FIX = json.loads((HERE / "fixtures" / "alpha_vibe_expected.json").read_text(encoding="utf-8"))
SKIPPED_MD = HERE.parents[1] / "docs" / "ALPHA_SKIPPED.md"
VIBE_TOTAL = 478  # alpha101 101 + qlib158 154 + academic 12 + gtja191 191 + fundamental 20 in Vibe's zoo at the ported commit
CORE = {f"alpha101_{n:03d}" for n in (1, 2, 3, 4, 6, 9, 12, 13, 16, 21, 33, 34, 101)} | {
    f"qlib158_{n}" for n in ("roc10", "std20", "ma20", "beta10", "resi10", "rsqr20", "rank20", "corr10", "rsv10", "wvma20")} | {
    f"academic_{n}" for n in ("strev", "illiq", "retskew", "mkt_rf", "rmw", "smb")}


MASKED = {"gtja191_143", "gtja191_010", "gtja191_108", "gtja191_121", "gtja191_131"}  # `PATCHES` in scripts/port_vibe_alphas.py


def panel_from(p: dict) -> dict[str, pd.DataFrame]:
    idx = pd.DatetimeIndex(pd.to_datetime(p["index"]))
    return {k: pd.DataFrame(p[k], index=idx, columns=p["columns"], dtype=float) for k in ("open", "high", "low", "close", "volume")}


# --- registry ---------------------------------------------------------------------------------------------------------------------

def test_registry_counts_and_files():
    ids = [z["id"] for z in ZOO]
    assert len(ids) == len(set(ids))
    n_ported, n_skipped = (int(x) for x in (ALPHA_DIR / "SOURCE").read_text().split()[1:3])
    assert len(ZOO) == n_ported == 435
    assert n_ported + n_skipped == VIBE_TOTAL
    assert dict(Counter(z["family"] for z in ZOO)) == {"alpha101": 82, "qlib158": 154, "academic": 12, "gtja191": 187}
    assert set(Counter(z["family"] for z in ZOO)) == set(FAMILIES)
    assert {z["id"] for z in ZOO if z["core"]} == CORE and len(CORE) == 29
    for z in ZOO:
        assert (ALPHA_DIR.parents[2] / z["file"]).is_file(), z["id"]
        assert set(z["columns_required"]) <= {"open", "high", "low", "close", "volume", "vwap", "amount"}, z["id"]
    on_disk = {(fam, p.name) for fam in FAMILIES for p in (ALPHA_DIR / "zoo" / fam).glob("*.py") if p.name != "__init__.py"}
    assert len(on_disk) == len(ZOO), "a factor module without a zoo entry (or the reverse)"


def test_skipped_list_is_consistent_with_the_zoo():
    text = SKIPPED_MD.read_text(encoding="utf-8")
    table = text.split("| Factor | Family | Reason |", 1)[1]
    skipped = re.findall(r"^\| `([a-z0-9_]+)` \| (\w+) \| (.+) \|$", table, flags=re.MULTILINE)
    ids = [s[0] for s in skipped]
    assert len(ids) == len(set(ids)) == VIBE_TOTAL - len(ZOO) == 43
    assert not set(ids) & {z["id"] for z in ZOO}
    assert all(reason.strip() for _, _, reason in skipped)
    assert Counter(f for _, f, _ in skipped) == {"fundamental": 20, "alpha101": 19, "gtja191": 4}
    summary = dict(re.findall(r"^\| (.+) \| (\d+) \|$", text.split("| Factor |", 1)[0], flags=re.MULTILINE))
    assert sum(int(v) for k, v in summary.items() if k != "Count") == len(ids)
    for fam, name in ((f, i.split("_", 1)[1]) for i, f, _ in skipped if f != "fundamental"):
        assert not (ALPHA_DIR / "zoo" / fam / (f"alpha_{name}.py" if "_" not in name else f"{name}.py")).exists()


# --- Vibe's own numbers -----------------------------------------------------------------------------------------------------------

def test_fixture_is_from_the_ported_commit():
    assert FIX["source"].endswith((ALPHA_DIR / "SOURCE").read_text().split()[0])
    assert set(FIX["factors"]) == {z["id"] for z in ZOO}


@pytest.fixture(scope="module")
def panel() -> dict[str, pd.DataFrame]:
    return panel_from(FIX["panel"])


@pytest.mark.parametrize("fid", [z["id"] for z in ZOO])
def test_every_factor_matches_vibes_values(fid, panel):
    want = FIX["factors"][fid]
    with np.errstate(all="ignore"):
        got = compute_factor(fid, panel).to_numpy(float)
    fin = np.isfinite(got)
    if fid in MASKED:
        # OpenTerm masks a bar Vibe fills (1 ** NaN = 1, NaN read as False): ours is NaN where Vibe's is a number, and equal wherever
        # ours has a value. The fixture is Vibe's own output and cannot be re-recorded offline.
        rows = np.array([[np.nan if x is None else x for x in r] for r in want["values"]], dtype=float)
        ours = got[FIX["rows"]]
        assert not (np.isfinite(ours) & ~np.isfinite(rows)).any(), fid
        both = np.isfinite(ours) & np.isfinite(rows)
        assert both.any() and np.allclose(ours[both], rows[both], rtol=1e-8, atol=1e-10), fid
        assert int(fin.sum()) <= want["finite"]
        return
    assert int(fin.sum()) == want["finite"], f"{fid}: NaN pattern differs"
    assert not np.isinf(got).any()
    assert got[fin].sum() == pytest.approx(want["sum"], rel=1e-7, abs=1e-7 * max(1.0, want["abs_sum"]))
    rows = np.array([[np.nan if x is None else x for x in r] for r in want["values"]], dtype=float)
    assert np.array_equal(np.isnan(got[FIX["rows"]]), np.isnan(rows))
    assert np.allclose(got[FIX["rows"]], rows, rtol=1e-8, atol=1e-10, equal_nan=True), fid


# --- per-family sample values, hand computed --------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def tiny() -> dict[str, pd.DataFrame]:
    idx = pd.bdate_range("2025-01-02", periods=70)
    rng = np.random.default_rng(5)
    c = pd.DataFrame(50 * np.exp(np.cumsum(rng.normal(0, 0.01, (70, 3)), axis=0)), index=idx, columns=["A", "B", "C"])
    o = c.shift(1).bfill() * 1.001
    return {"open": o, "close": c, "high": np.maximum(o, c) * 1.01, "low": np.minimum(o, c) * 0.99,
            "volume": pd.DataFrame(rng.integers(1000, 5000, c.shape).astype(float), index=idx, columns=c.columns)}


def test_qlib158_samples(tiny):
    c, o, h, _lo, v = (tiny[k] for k in ("close", "open", "high", "low", "volume"))
    assert np.allclose(compute_factor("qlib158_roc10", tiny).iloc[-1], (c.shift(10) / c).iloc[-1])
    assert np.allclose(compute_factor("qlib158_ma5", tiny).iloc[-1], c.iloc[-5:].mean() / c.iloc[-1])
    assert np.allclose(compute_factor("qlib158_kmid", tiny), (c - o) / o)
    assert np.allclose(compute_factor("qlib158_max20", tiny).iloc[-1], h.iloc[-20:].max() / c.iloc[-1])
    assert np.allclose(compute_factor("qlib158_vma5", tiny).iloc[-1], v.iloc[-5:].mean() / (v.iloc[-1] + 1e-12))


def test_alpha101_samples(tiny):
    c, o, v = tiny["close"], tiny["open"], tiny["volume"]
    # #12: sign(delta(volume, 1)) * -delta(close, 1)
    assert np.allclose(compute_factor("alpha101_012", tiny).iloc[1:], (np.sign(v.diff()) * -c.diff()).iloc[1:])
    # #101: (close - open) / ((high - low) + .001)
    assert np.allclose(compute_factor("alpha101_101", tiny), (c - o) / (tiny["high"] - tiny["low"] + 0.001))


def test_gtja191_samples(tiny):
    c, v = tiny["close"], tiny["volume"]
    ex = extend_panel(tiny)
    # #1: -1 * CORR(RANK(DELTA(LOG(VOLUME), 1)), RANK((CLOSE - OPEN) / OPEN), 6)
    x = np.log(v).diff().rank(axis=1)
    y = ((c - tiny["open"]) / tiny["open"]).rank(axis=1)
    assert np.allclose(compute_factor("gtja191_001", tiny).iloc[-1], -x.iloc[-6:].corrwith(y.iloc[-6:]).to_numpy())
    # #70: 6-day std of amount (turnover) on the volume * typical price proxy
    assert np.allclose(compute_factor("gtja191_070", tiny).iloc[-1], ex["amount"].iloc[-6:].std(ddof=1))


def test_academic_samples(tiny):
    c = tiny["close"]
    got = compute_factor("academic_strev", tiny)
    assert got.shape == c.shape and np.isfinite(got.iloc[-1]).all()
    assert np.allclose(compute_factor("academic_mkt_rf", tiny).iloc[-1].mean(), 0.0, atol=1e-9)  # a cross-sectional z-score


# --- operators ---------------------------------------------------------------------------------------------------------------------

def test_decay_linear_weights_put_the_most_weight_on_today():
    s = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0]})
    assert ops.decay_linear(s, 3).iloc[-1, 0] == pytest.approx((2 * 1 + 3 * 2 + 4 * 3) / 6)  # weights 1, 2, 3 oldest to newest


def test_ts_slope_and_resi_on_a_line():
    s = pd.DataFrame({"x": np.arange(10, dtype=float) * 2 + 1})
    assert ops.ts_slope(s, 5).iloc[-1, 0] == pytest.approx(2.0)
    assert ops.ts_resi(s, 5).iloc[-1, 0] == pytest.approx(0.0, abs=1e-12)


def test_delta_refuses_a_lookahead_shift():
    with pytest.raises(ValueError):
        ops.delta(pd.DataFrame({"x": [1.0, 2.0, 3.0]}), 0)
    with pytest.raises(ValueError):
        ops.delta(pd.DataFrame({"x": [1.0, 2.0, 3.0]}), -1)


def test_extend_panel_builds_vwap_and_amount_from_the_same_bar(tiny):
    ex = extend_panel(tiny)
    assert np.allclose(ex["vwap"], (tiny["open"] + tiny["high"] + tiny["low"] + tiny["close"]) / 4)
    assert np.allclose(ex["amount"], tiny["volume"] * ex["vwap"])
    assert "vwap" not in tiny and extend_panel(ex) is ex
    own = {**tiny, "vwap": tiny["close"], "amount": tiny["volume"]}
    assert extend_panel(own) is own


# --- the lookahead ban, every factor ---------------------------------------------------------------------------------------------

def _random_panel(days: int, names: int, seed: int) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2023-01-02", periods=days)
    close = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, 0.012, (days, names)), axis=0)), index=idx,
                         columns=[f"S{i:02d}" for i in range(names)])
    open_ = close.shift(1).bfill() * (1 + rng.normal(0, 0.002, close.shape))
    return {"close": close, "open": open_, "high": np.maximum(open_, close) * (1 + abs(rng.normal(0, 0.005, close.shape))),
            "low": np.minimum(open_, close) * (1 - abs(rng.normal(0, 0.005, close.shape))),
            "volume": pd.DataFrame(rng.integers(1e5, 1e6, close.shape).astype(float), index=idx, columns=close.columns)}


# Conditional factors (`cond ? expr : constant`, a running product) are legitimately defined before the declared warm-up of their
# longest branch: the value is the first bar index at which every input the BRANCH TAKEN needs exists. Rows before it must be NaN.
EARLY = {"alpha101_007": 19, "gtja191_010": 5, "gtja191_143": 1}
CUTS = (40, 120, 200, 270, 330)  # bar indices t: short (inside most warm-ups) through nearly the whole panel


def test_no_factor_reads_the_future():
    """Truncate-and-compare, several cut points, on random data: a factor's values at bars 0..t computed on the panel TRUNCATED at t
    (no later bar exists) must equal the values computed on the full panel, NaN pattern included. A second panel whose whole future
    is replaced by different random data must give the same values up to t as well."""
    days, names = 360, 10
    full = _random_panel(days, names, 11)
    other = {k: v.copy() for k, v in full.items()}
    rng = np.random.default_rng(12)
    for k, v in other.items():
        fut = v.iloc[CUTS[0] + 1:]
        other[k].iloc[CUTS[0] + 1:] = fut.to_numpy() * rng.uniform(0.5, 2.0, fut.shape)  # includes high < low mixes
    checked = 0
    for z in ZOO:
        with np.errstate(all="ignore"):
            whole = compute_factor(z["id"], full).to_numpy(float)
            alt = compute_factor(z["id"], other).to_numpy(float)
            head = slice(0, CUTS[0] + 1)
            assert np.array_equal(np.isnan(whole[head]), np.isnan(alt[head])), f"{z['id']}: NaN pattern up to t changed with the future"
            assert np.allclose(whole[head], alt[head], equal_nan=True, rtol=1e-9, atol=1e-12), f"{z['id']}: values up to t changed with the future"
            for t in CUTS:
                cut = compute_factor(z["id"], {k: v.iloc[: t + 1] for k, v in full.items()}).to_numpy(float)
                assert cut.shape == (t + 1, names), z["id"]
                assert np.array_equal(np.isnan(cut), np.isnan(whole[: t + 1])), f"{z['id']}: NaN pattern up to {t} depends on later bars"
                assert np.allclose(cut, whole[: t + 1], equal_nan=True, rtol=1e-9, atol=1e-12), f"{z['id']}: values up to {t} depend on later bars"
        checked += int(np.isfinite(whole[-1]).any())
    assert checked >= 0.95 * len(ZOO), "too many factors are all-NaN on the test panel: the check would pass vacuously"


def test_warmup_is_nan_not_a_fake_value():
    """Before a factor's declared warm-up (min_warmup_bars) is full its output is NaN, never 0 or another filler, and never inf;
    a name with no data at all stays NaN."""
    full = _random_panel(300, 10, 21)
    dark = {k: v.copy() for k, v in full.items()}
    for v in dark.values():
        v.iloc[:, 0] = np.nan
    bad_warm, bad_dark = [], []
    for z in ZOO:
        with np.errstate(all="ignore"):
            got = compute_factor(z["id"], full).to_numpy(float)
            gd = compute_factor(z["id"], dark).to_numpy(float)
        w = EARLY.get(z["id"], int(z.get("min_warmup_bars") or 1) - 1) + 1
        assert not np.isinf(got).any(), z["id"]
        if w > 1 and not np.isnan(got[: w - 1]).all():
            bad_warm.append((z["id"], w))
        if not np.isnan(gd[:, 0]).all():
            bad_dark.append(z["id"])
    assert not bad_warm, f"values before the declared warm-up: {bad_warm}"
    assert not bad_dark, f"a name with no bars got values: {bad_dark}"


def test_scan_family_selection():
    from openterm.quantjobs.alpha import scan

    rng = np.random.default_rng(2)
    idx = pd.bdate_range("2024-01-02", periods=120)
    c = pd.DataFrame(50 * np.exp(np.cumsum(rng.normal(0, 0.01, (120, 8)), axis=0)), index=idx, columns=[f"S{i}" for i in range(8)])
    o = c.shift(1).bfill()
    panel = {"close": c, "open": o, "high": np.maximum(o, c) * 1.01, "low": np.minimum(o, c) * 0.99,
             "volume": pd.DataFrame(rng.integers(1000, 5000, c.shape).astype(float), index=idx, columns=c.columns)}
    core, _ = scan(panel, "core", [1], lambda *a: None)
    qlib, _ = scan(panel, "qlib158", [1], lambda *a: None)
    assert {r["id"] for r in core} <= CORE and len(core) >= 20
    assert {r["family"] for r in qlib} == {"qlib158"} and len(qlib) > 100
