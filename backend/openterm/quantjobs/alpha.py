"""ALPHA (spec decision I): the alpha-zoo scan. IC per day (rank correlation of the factor at t with the forward return over h days),
then per factor IC mean / std, IR, t-stat, share of positive days, IC at each horizon (decay) and coverage; the label is Vibe's rule.

The factors are the ported Vibe code, untouched (`quantlib.alpha.compute_factor` on a wide OHLCV panel built from the stored bars). The
market return and size proxy the academic factors need come from the panel itself; a factor that cannot be computed or has no IC day is
skipped and listed in the notes with its reason, never faked. pandas / numpy load in the job worker only.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable

import numpy as np
import pandas as pd

from ..quantlib.alpha import ZOO, compute_factor
from ..quantlib.alpha.bench import categorise, t_stat
from ..research.table import col, head, payload, section
from . import common as cm

MIN_NAMES = 5  # a cross-section needs at least this many names on a day
MIN_BARS = 60
KEEP_SHARE = 0.7  # a symbol with fewer than this share of the longest history is dropped
DAY_SHARE = 0.5  # a day needs bars for at least this share of the names
FIELDS = (("open", "o"), ("high", "h"), ("low", "l"), ("close", "c"), ("volume", "v"))


def build_panel(bars: dict) -> tuple[dict[str, pd.DataFrame], list[str], list[str]]:
    """(wide panel, symbols kept, symbols dropped). One bar a day (the last), aligned on UTC day numbers."""
    cols: dict[str, dict[str, pd.Series]] = {k: {} for k, _ in FIELDS}
    for sym, b in bars.items():
        if not b or not b.get("t"):
            continue
        t = np.asarray(b["t"], dtype=np.int64) // 86400
        arr = {k: np.array([np.nan if x is None else x for x in (b.get(s) or [None] * len(t))], dtype=float) for k, s in FIELDS}
        ok = np.isfinite(arr["close"]) & (arr["close"] > 0)
        t = t[ok]
        if t.size == 0:
            continue
        last = np.append(t[1:] != t[:-1], True)
        for k, _ in FIELDS:
            cols[k][sym] = pd.Series(arr[k][ok][last], index=t[last])
    longest = max((s.size for s in cols["close"].values()), default=0)
    kept = [s for s, v in cols["close"].items() if v.size >= max(MIN_BARS, KEEP_SHARE * longest)]
    dropped = sorted(set(bars) - set(kept))
    if not kept:
        return {}, [], dropped
    frames = {k: pd.DataFrame({s: cols[k][s] for s in kept}).sort_index() for k, _ in FIELDS}
    full = frames["close"].notna().mean(axis=1) >= DAY_SHARE
    idx = pd.to_datetime(frames["close"].index[full].to_numpy() * 86400, unit="s")
    out = {}
    for k, f in frames.items():
        g = f[full.to_numpy()]
        g.index = idx
        out[k] = g
    return out, kept, dropped


def _rank_ic(rf: np.ndarray, rr: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Pearson correlation of two rank matrices over each day's valid entries (NaN where fewer than MIN_NAMES or no variance)."""
    n = valid.sum(axis=1).astype(float)
    a = np.where(valid, rf, 0.0)
    b = np.where(valid, rr, 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        ma, mb = a.sum(axis=1) / n, b.sum(axis=1) / n
        da = np.where(valid, a - ma[:, None], 0.0)
        db = np.where(valid, b - mb[:, None], 0.0)
        cov = (da * db).sum(axis=1)
        den = np.sqrt((da * da).sum(axis=1) * (db * db).sum(axis=1))
        ic = np.where((n >= MIN_NAMES) & (den > 0), cov / den, np.nan)
    return ic


def daily_ic(factor: pd.DataFrame, fwd: pd.DataFrame) -> np.ndarray:
    """Spearman IC per day between the factor at t and the forward return (average ranks on the pairwise-valid names)."""
    f = factor.reindex(index=fwd.index, columns=fwd.columns).replace([np.inf, -np.inf], np.nan)
    valid = (f.notna() & fwd.notna()).to_numpy()
    fm, rm = f.where(valid), fwd.where(valid)
    return _rank_ic(fm.rank(axis=1).to_numpy(), rm.rank(axis=1).to_numpy(), valid)


def _stats(ic: np.ndarray) -> dict | None:
    v = ic[np.isfinite(ic)]
    if v.size < 2:
        return None
    mean, std = float(v.mean()), float(v.std(ddof=1))
    return {"ic_mean": mean, "ic_std": std, "ic_count": int(v.size), "ic_positive_ratio": float((v > 0).mean())}


def scan(panel: dict[str, pd.DataFrame], family: str | None, horizons: list[int], progress: Callable[[float, str], None]):
    """(rows, skipped [(id, reason)]). The first horizon is the primary one the label and t-stat use."""
    close = panel["close"]
    fwd = {h: close.shift(-h) / close - 1.0 for h in horizons}
    zoo = [z for z in ZOO if family in (None, z["family"])]
    rows: list[dict] = []
    skipped: list[tuple[str, str]] = []
    for i, z in enumerate(zoo, 1):
        progress(0.1 + 0.88 * (i - 1) / max(len(zoo), 1), f"factor {i}/{len(zoo)}")
        try:
            with warnings.catch_warnings(), np.errstate(all="ignore"):
                warnings.simplefilter("ignore")
                fac = compute_factor(z["id"], panel)
                ics = {h: daily_ic(fac, fwd[h]) for h in horizons}
        except Exception as e:  # noqa: BLE001  a factor that cannot run is listed, not hidden
            skipped.append((z["id"], f"{type(e).__name__}: {str(e)[:60]}"))
            continue
        st = _stats(ics[horizons[0]])
        if st is None:
            skipped.append((z["id"], f"NO IC DAY (WARM-UP {z.get('min_warmup_bars')} BARS, PANEL HAS {len(close)})"))
            continue
        t = t_stat(st["ic_mean"], st["ic_std"], st["ic_count"])
        row = {"id": z["id"], "family": z["family"], "ic_mean": st["ic_mean"], "ic_std": st["ic_std"],
               "ir": st["ic_mean"] / st["ic_std"] if st["ic_std"] > 0 else None, "t": t, "pos_ratio": st["ic_positive_ratio"],
               "coverage": float(np.isfinite(fac.to_numpy(dtype=float)).mean()), "label": categorise(st)}
        for h in horizons:
            v = ics[h][np.isfinite(ics[h])]
            row[f"ic_h{h}"] = float(v.mean()) if v.size else None
        rows.append(row)
    return rows, skipped


def run(params: dict, progress: Callable[[float, str], None]) -> dict:
    labels = params.get("labels") or {}
    title = f"ALPHA {params.get('universe') or ''}".strip()
    if params.get("not_runnable"):
        return cm.not_runnable(title, params["not_runnable"], labels)
    progress(0.02, "loading bars")
    data = cm.load(params)
    horizons = list(params["h"])
    panel, kept, dropped = build_panel(data["bars"])
    failed = list(params.get("failed") or [])
    if len(kept) < MIN_NAMES:
        return cm.not_runnable(title, f"ONLY {len(kept)} NAMES HAVE ENOUGH BARS (NEED {MIN_NAMES}, AT LEAST {MIN_BARS} BARS EACH)", labels)
    progress(0.08, f"panel {len(panel['close'])} days x {len(kept)} names")
    rows, skipped = scan(panel, params.get("family"), horizons, progress)
    if not rows:
        return cm.not_runnable(title, "NO FACTOR HAD AN IC DAY ON THIS PANEL", labels)
    rows.sort(key=lambda r: (r["ir"] is None, -(r["ir"] or 0.0)))
    h0 = horizons[0]
    hcols = [col(f"ic_h{h}", f"IC H{h}", "num4") for h in horizons]
    cols = [col("id", "FACTOR"), col("family", "FAMILY"), col("ic_mean", "IC MEAN", "num4"), col("ic_std", "IC STD", "num4"), col("ir", "IR", "num"),
            col("t", "T", "num"), col("pos_ratio", "IC>0", "pct"), *hcols, col("coverage", "COVERAGE", "pct"), col("label", "LABEL")]
    counts = {k: sum(1 for r in rows if r["label"] == k) for k in ("alive", "reversed", "dead")}
    best = next((r for r in rows if r["ir"] is not None), rows[0])
    chart = {"id": "decay", "title": f"IC DECAY BY HORIZON: {best['id']} (BEST IR)", "xlabel": "HORIZON (DAYS)", "ylabel": "MEAN RANK IC",
             "series": [{"name": best["id"], "points": [[h, cm.fin(best[f"ic_h{h}"])] for h in horizons]}]}
    notes = []
    if params.get("synthetic"):
        notes.append("SYNTHETIC DATA, NOT A MARKET: THE ICS BELOW ARE NOISE AROUND ZERO BY CONSTRUCTION")
    notes += [
        f"IC = DAILY SPEARMAN RANK CORRELATION OF THE FACTOR AT T WITH THE RETURN FROM T TO T+H, ACROSS NAMES; LABEL, T, IR AND IC>0 USE H={h0}",
        "LABEL (VIBE RULE): ALIVE = IC MEAN > 0.02, IC>0 ON AT LEAST 55% OF DAYS AND |T| > 2; REVERSED = IC MEAN < -0.02 AND |T| > 2; DEAD OTHERWISE",
        "T TREATS DAYS AS INDEPENDENT: FOR H > 1 THE FORWARD RETURNS OVERLAP AND T IS INFLATED. A SCAN OVER MANY FACTORS FINDS CHANCE WINNERS",
        "PRICE AND VOLUME FACTORS ONLY, NO FUNDAMENTALS; NOT A TRADING SIGNAL",
    ]
    if dropped or failed:
        gone = sorted({*dropped, *failed})
        notes.append(f"{len(gone)} NAMES DROPPED (NO BARS OR TOO FEW): {', '.join(gone[:8])}{' ...' if len(gone) > 8 else ''}")
    if skipped:
        notes.append("SKIPPED FACTORS: " + "; ".join(f"{i} ({why})" for i, why in skipped))
    notes += [n for n in cm.data_notes(labels) if n not in notes]
    heads = [head("UNIVERSE", str(params.get("universe") or "")), head("NAMES", str(len(kept)), len(kept)),
             head("DAYS", str(len(panel["close"])), len(panel["close"])), head("FACTORS", str(len(rows)), len(rows)),
             head("ALIVE", str(counts["alive"]), counts["alive"]), head("REVERSED", str(counts["reversed"]), counts["reversed"]),
             head("DEAD", str(counts["dead"]), counts["dead"]), head("PRIMARY H", str(h0), h0)]
    if params.get("synthetic"):
        heads.insert(0, head("DATA", "SYNTHETIC DATA, NOT A MARKET"))
    out = payload(None, title, heads, [section("zoo", "ALPHA ZOO", cols, [{**r} for r in rows], f"IC AT H={h0} UNLESS THE COLUMN SAYS OTHERWISE")],
                  notes, status="RUNNABLE", charts=[chart])
    progress(1.0, "done")
    return cm.envelope(out, labels)
