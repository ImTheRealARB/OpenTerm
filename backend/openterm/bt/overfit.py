"""Overfitting guards, walk-forward optimisation and the efficient front for BT OPT (Phase 26 items 3, 4 and 7).

Worker side only (numpy; the multiple-testing module imports scipy). Everything works on the *returns matrix*: one column per
parameter set, one row per bar, each cell that run's bar return. Building it once from the full-history runs lets every check
here re-slice history without running another backtest.

- Probability of backtest overfitting (PBO), by combinatorially symmetric cross-validation (CSCV; Bailey, Borwein, Lopez de
  Prado and Zhu, "The Probability of Backtest Overfitting", 2015): cut the rows into S blocks; for every way of picking S/2
  blocks as "in sample" (the rest is "out of sample"), find the column with the best in-sample Sharpe and see where it ranks
  out of sample. PBO = the share of splits where that winner lands in the bottom half. Near 0: the winner keeps winning on
  data it never saw. Near or above 0.5: picking the best in sample is no better than picking at random.
- Deflated Sharpe ratio: the multiple-testing module's `deflated_sharpe_ratio` (probability that the winner's true Sharpe beats
  the best Sharpe that N strategies with NO edge would show by luck).
"""

from __future__ import annotations

import itertools
import math

import numpy as np

CSCV_BLOCKS = 10  # C(10, 5) = 252 splits: cheap even for 2,000 columns


def _sharpe_cols(r: np.ndarray) -> np.ndarray:
    """Per-observation Sharpe of every column (mean / std of bar returns). A flat column (no trades) gives NaN."""
    sd = r.std(axis=0, ddof=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(sd > 0, r.mean(axis=0) / sd, np.nan)


def pbo_cscv(returns: np.ndarray, blocks: int = CSCV_BLOCKS) -> dict | None:
    """CSCV probability of backtest overfitting over a T x N returns matrix, or None when it cannot be computed
    (fewer than 2 columns, or fewer than 2 rows per block)."""
    t, n = returns.shape
    if n < 2 or t < 2 * blocks:
        return None
    edges = np.linspace(0, t, blocks + 1).astype(int)
    parts = [returns[edges[k]:edges[k + 1]] for k in range(blocks)]
    logits = []
    for chosen in itertools.combinations(range(blocks), blocks // 2):
        rest = [k for k in range(blocks) if k not in chosen]
        is_sr = _sharpe_cols(np.vstack([parts[k] for k in chosen]))
        oos_sr = _sharpe_cols(np.vstack([parts[k] for k in rest]))
        if np.all(np.isnan(is_sr)):
            continue
        best = int(np.nanargmax(is_sr))
        oos = np.where(np.isnan(oos_sr), -np.inf, oos_sr)
        # Relative rank of the in-sample winner out of sample, in (0, 1): 1 = it was the best there too.
        rank = (oos < oos[best]).sum() + 0.5 * ((oos == oos[best]).sum() - 1) + 1
        w = rank / (n + 1)
        logits.append(math.log(w / (1 - w)))
    if not logits:
        return None
    lg = np.asarray(logits)
    return {"pbo": float((lg <= 0).mean()), "splits": len(lg), "blocks": blocks,
            "median_logit": float(np.median(lg))}


def deflated(best_returns: np.ndarray, sharpes: np.ndarray, n_trials: int) -> dict | None:
    """Deflated Sharpe of the winner, given every trial's per-observation Sharpe. None under 3 trials or 30 bars."""
    from ..quantlib.multipletesting import deflated_sharpe_ratio  # scipy: worker only

    sr = sharpes[np.isfinite(sharpes)]
    r = best_returns[np.isfinite(best_returns)]
    if n_trials < 3 or len(sr) < 3 or len(r) < 30 or r.std(ddof=1) == 0:
        return None
    sd = r.std(ddof=0)
    z = (r - r.mean()) / sd
    observed = float(r.mean() / r.std(ddof=1))
    res = deflated_sharpe_ratio(observed, n_trials=n_trials, n_observations=len(r), trial_sharpe_std=float(sr.std(ddof=1)),
                                skew=float((z**3).mean()), kurtosis=float((z**4).mean()))
    return {"dsr": float(res.deflated_sharpe_ratio), "expected_max_sharpe": float(res.expected_maximum_sharpe),
            "observed_sharpe": observed, "trials": n_trials}


def efficient(points: list[tuple[float | None, float | None]]) -> set[int]:
    """Indices of the efficient front of (return, max drawdown) points: no other point has a higher return AND a shallower
    drawdown. Drawdowns may be given negative (-0.25) or positive (0.25): the depth used is abs(). Points with a missing
    value are never on the front."""
    ok = [(i, r, abs(d)) for i, (r, d) in enumerate(points)
          if r is not None and d is not None and math.isfinite(r) and math.isfinite(d)]
    ok.sort(key=lambda x: (x[2], -x[1]))  # shallowest drawdown first; on a tie the higher return first
    front, best = set(), -math.inf
    for i, r, _ in ok:
        if r > best:
            front.add(i)
            best = r
    return front


_NAMED_FITS = ("SHARPE", "SORTINO", "CALMAR", "PF", "NET", "RETURN")


def slice_fitness(r: np.ndarray, fit: str, bars_per_year: int, cash: float = 100_000.0) -> float:
    """A fitness number for a slice of bar returns (walk-forward picks its in-sample winner with it). Higher is better;
    NaN when the slice cannot say (no movement). PF here is the profit factor of BAR returns (trades are not sliced).
    `fit` is one of the six words or a `fitexpr` formula over them (SHARPE-2*DD): each name is read from the slice's own
    returns (WIN and TRADES are not, the route refuses them with WF)."""
    if len(r) < 2:
        return math.nan
    if fit not in _NAMED_FITS:
        from . import fitexpr

        f = fitexpr.parse(fit)
        eq = np.cumprod(1 + r)
        dd = float((eq / np.maximum.accumulate(eq) - 1).min())
        values = {name: slice_fitness(r, name, bars_per_year) for name in f.names & set(_NAMED_FITS)}
        values["NET"] = cash * float(eq[-1])
        values["DD"] = abs(dd)
        values["ANNUAL"] = _annual(r, bars_per_year) if "ANNUAL" in f.names else math.nan
        return f.run(values)
    if fit in ("NET", "RETURN"):
        return float(np.prod(1 + r) - 1)
    if fit == "PF":
        loss = -r[r < 0].sum()
        return float(r[r > 0].sum() / loss) if loss > 0 else math.nan
    if fit == "CALMAR":
        eq = np.cumprod(1 + r)
        dd = float((eq / np.maximum.accumulate(eq) - 1).min())
        years = len(r) / bars_per_year
        cagr = float(eq[-1] ** (1 / years) - 1) if eq[-1] > 0 and years > 0 else math.nan
        return cagr / abs(dd) if dd < 0 else math.nan
    if fit == "SORTINO":
        down = r[r < 0]
        dsd = math.sqrt(float((down**2).sum()) / len(r)) if len(down) else 0.0
        return float(r.mean() / dsd * math.sqrt(bars_per_year)) if dsd > 0 else math.nan
    sd = r.std(ddof=1)
    return float(r.mean() / sd * math.sqrt(bars_per_year)) if sd > 0 else math.nan


def _annual(r: np.ndarray, bars_per_year: int) -> float | None:
    if not len(r):
        return None
    growth = float(np.prod(1 + r))
    return growth ** (bars_per_year / len(r)) - 1 if growth > 0 else -1.0


def walk_forward(returns: np.ndarray, times: list[int], n_windows: int, anchored: bool, fit: str, bars_per_year: int,
                 cash: float) -> dict | None:
    """Walk-forward optimisation over the returns matrix: the rows are cut into n_windows + 1 equal parts; window k picks the
    column with the best in-sample fitness on part k-1 (rolling) or parts 0..k-1 (anchored) and is tested on part k.
    Returns the windows, the stitched out-of-sample equity and the walk-forward efficiency (out-of-sample annual return /
    average in-sample annual return of the chosen columns). None when there are fewer than 4 rows per part."""
    t, _ = returns.shape
    edges = np.linspace(0, t, n_windows + 2).astype(int)
    if np.min(np.diff(edges)) < 4:
        return None
    windows, oos_parts, oos_times, is_annuals = [], [], [], []
    for k in range(1, n_windows + 1):
        i0 = 0 if anchored else edges[k - 1]
        i1, o1 = edges[k], edges[k + 1]
        scores = [slice_fitness(returns[i0:i1, j], fit, bars_per_year, cash) for j in range(returns.shape[1])]
        if not any(math.isfinite(s) for s in scores):
            continue  # nothing to choose from (every set was flat in sample): np.argmax would silently take column 0
        keys = [s if math.isfinite(s) else -math.inf for s in scores]
        best = int(np.argmax(keys))
        is_r, oos_r = returns[i0:i1, best], returns[i1:o1, best]
        is_a, oos_a = _annual(is_r, bars_per_year), _annual(oos_r, bars_per_year)
        if is_a is not None:
            is_annuals.append(is_a)
        oos_parts.append(oos_r)
        oos_times.extend(times[i1:o1])
        windows.append({"window": k, "is_start": times[i0], "is_end": times[i1 - 1], "oos_start": times[i1],
                        "oos_end": times[o1 - 1], "best": best, "is_fitness": None if not math.isfinite(scores[best]) else scores[best],
                        "is_annual": is_a, "oos_annual": oos_a, "oos_return": float(np.prod(1 + oos_r) - 1)})
    if not oos_parts:
        return None
    oos = np.concatenate(oos_parts)
    eq = cash * np.cumprod(1 + oos)
    oos_annual = _annual(oos, bars_per_year)
    mean_is = float(np.mean(is_annuals)) if is_annuals else None
    # A ratio of two losses is a positive number (-18% out of / -10% in = 1.9 "efficiency"): only a positive in-sample
    # return gives a meaningful one.
    wfe = oos_annual / mean_is if oos_annual is not None and mean_is is not None and mean_is > 0 else None
    return {"windows": windows, "equity": [[int(a), round(float(b), 4)] for a, b in zip(oos_times, eq, strict=True)],
            "oos_annual": oos_annual, "is_annual_mean": mean_is, "wfe": wfe, "anchored": anchored, "n_windows": n_windows}
