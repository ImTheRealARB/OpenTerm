"""Realized volatility for HIVG (spec decision I). Pure: lists in, numbers out. Annualised with sqrt(252), sample standard deviation."""

from __future__ import annotations

import itertools
import math

WINDOWS = (10, 20, 30, 60, 90, 252)
TRADING_DAYS = 252.0


def log_returns(closes: list[float | None]) -> list[float | None]:
    out: list[float | None] = []
    for a, b in itertools.pairwise(closes):
        out.append(math.log(b / a) if a and b and a > 0 and b > 0 else None)
    return out


def cc_vol(rets: list[float | None], n: int) -> float | None:
    """Close-to-close vol of the last n returns; None unless all n are present."""
    x = rets[-n:]
    if len(x) < n or any(v is None for v in x) or n < 2:
        return None
    mean = sum(x) / n
    return math.sqrt(sum((v - mean) ** 2 for v in x) / (n - 1)) * math.sqrt(TRADING_DAYS)


def parkinson_vol(highs: list[float | None], lows: list[float | None], n: int) -> float | None:
    """Parkinson (high-low) vol of the last n bars: sqrt(mean(ln(H/L)^2) / (4 ln 2)) annualised."""
    h, l_ = highs[-n:], lows[-n:]
    if len(h) < n or any(v is None or v <= 0 for v in h) or any(v is None or v <= 0 for v in l_):
        return None
    return math.sqrt(sum(math.log(a / b) ** 2 for a, b in zip(h, l_, strict=True)) / (4 * math.log(2) * n)) * math.sqrt(TRADING_DAYS)


def rolling_cc(rets: list[float | None], n: int) -> list[float | None]:
    """cc_vol over a sliding window, aligned to the last return of each window (None where the window is incomplete)."""
    # hand cc_vol just the window: slicing rets[: i + 1] copied the whole prefix at every step (quadratic)
    return [cc_vol(rets[i + 1 - n: i + 1], n) if i + 1 >= n else None for i in range(len(rets))]


def percentile_rank(history: list[float], now: float) -> tuple[float, float]:
    """(IV rank = (now - min) / (max - min), percentile = share of history at or below now)."""
    lo, hi = min(history), max(history)
    rank = 0.5 if hi == lo else (now - lo) / (hi - lo)
    return rank, sum(v <= now for v in history) / len(history)
