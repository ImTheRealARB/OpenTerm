"""Expiry selection and the implied-vol surface fit (spec decision H). Pure: no I/O, no clock.

A *smile* is the list of out-of-the-money (k, iv) points of one expiry with k = ln(K / F), F the forward. The fit is a weighted-free
least squares of IV on k with a quadratic, `iv(k) = a + b k + c k^2` (labelled QUADRATIC IN LOG-MONEYNESS, NOT SVI); `a` is the ATM IV at
the forward. Nothing is extrapolated past the quotes' range without saying so: grid cells whose fitted IV is not positive are empty.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

#: Days after the nearest expiry that the other seven expiries are chosen closest to (spec decision H).
EXPIRY_OFFSETS_DAYS = (7, 30, 60, 90, 180, 270, 365)
MONEYNESS_GRID = (0.80, 0.85, 0.90, 0.95, 1.00, 1.05, 1.10, 1.15, 1.20)
MIN_POINTS = 6
MIN_IV = 0.01


def pick_expiries(dates: list[int]) -> list[int]:
    """The eight expiries every options function uses: the nearest, then the one closest to +7, +30, +60, +90, +180, +270 and +365
    days after it, each used once. Shared by PCR, OVDV, SKEW and HIVG so one set of chain fetches serves all four. The recorder
    (scripts/record_phase14.py) has the same rule; a test locks the two together."""
    if not dates:
        return []
    ordered = sorted(dates)
    first, picked = ordered[0], [ordered[0]]
    for days in EXPIRY_OFFSETS_DAYS:
        rest = [d for d in ordered if d not in picked]
        if rest:
            picked.append(min(rest, key=lambda d: abs(d - (first + days * 86400))))
    return sorted(picked)


@dataclass
class Fit:
    a: float
    b: float
    c: float
    rmse: float
    n: int
    k_min: float
    k_max: float

    def iv(self, k: float) -> float:
        return self.a + self.b * k + self.c * k * k

    def iv_in_range(self, k: float) -> float | None:
        """The fitted IV at k, or None when k lies outside the quotes the fit was made from (never extrapolated) or the fit is not a
        positive vol there."""
        if k < self.k_min - 1e-9 or k > self.k_max + 1e-9:
            return None
        v = self.iv(k)
        return v if v >= MIN_IV else None


def fit_smile(points: list[tuple[float, float]]) -> Fit | None:
    """Quadratic least squares of IV on k. None when there are too few points or they are all at one k."""
    from ..quant import numerics as nm

    pts = sorted(points)
    if len(pts) < MIN_POINTS or pts[0][0] == pts[-1][0]:
        return None
    ks = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    try:
        a, b, c = nm.lstsq([[1.0] * len(ks), ks, [k * k for k in ks]], ys)
    except (ValueError, ZeroDivisionError):
        return None
    fit = Fit(a, b, c, 0.0, len(pts), ks[0], ks[-1])
    fit.rmse = math.sqrt(sum((fit.iv(k) - y) ** 2 for k, y in pts) / len(pts))
    return fit


def grid_row(fit: Fit) -> list[float | None]:
    """Fitted IV at each forward moneyness of MONEYNESS_GRID; a cell is empty outside the range of quotes the fit used."""
    return [fit.iv_in_range(math.log(m)) for m in MONEYNESS_GRID]


def delta_strike(fit: Fit, T: float, call: bool) -> float | None:
    """The k where the forward delta is 25 (calls: N(d1) = 0.25; puts: N(-d1) = 0.25), solved on the fitted smile, or None when the
    fit has no such strike inside the range of quotes it was made from."""
    from ..quant import numerics as nm

    if T <= 0:
        return None

    def f(k: float) -> float:
        s = max(fit.iv(k), MIN_IV)
        d1 = (-k + 0.5 * s * s * T) / (s * math.sqrt(T))
        return (nm.norm_cdf(d1) - 0.25) if call else (nm.norm_cdf(d1) - 0.75)

    lo, hi = (0.0, 1.5) if call else (-1.5, 0.0)
    if f(lo) * f(hi) > 0:
        return None
    try:
        k = nm.brent(f, lo, hi, xtol=1e-10)
    except ValueError:
        return None
    return k if fit.k_min - 1e-9 <= k <= fit.k_max + 1e-9 else None   # a strike nobody quoted is not reported


def skew_metrics(fit: Fit, T: float) -> dict:
    """ATM IV, 25-delta call and put IV, risk reversal (call - put), butterfly (wing average - ATM) and the slope dIV/dk at the forward."""
    kc, kp = delta_strike(fit, T, True), delta_strike(fit, T, False)
    ivc = fit.iv(kc) if kc is not None else None
    ivp = fit.iv(kp) if kp is not None else None
    return {
        "atm_iv": fit.a, "iv_c25": ivc, "iv_p25": ivp,
        "rr25": None if ivc is None or ivp is None else ivc - ivp,
        "bf25": None if ivc is None or ivp is None else (ivc + ivp) / 2 - fit.a,
        "slope": fit.b,
    }


def interp_total_variance(points: list[tuple[float, float]], T: float) -> tuple[float, bool]:
    """ATM IV at time `T` from (T_i, atm_iv_i) pairs, linear in total variance sigma^2 T; (iv, True) when T is outside the range and
    the nearest expiry's IV is used flat."""
    pts = sorted(p for p in points if p[0] > 0)
    if not pts:
        raise ValueError("no expiries")
    if T <= pts[0][0]:
        return pts[0][1], T < pts[0][0]
    if T >= pts[-1][0]:
        return pts[-1][1], T > pts[-1][0]
    for (t0, v0), (t1, v1) in itertools.pairwise(pts):
        if t0 <= T <= t1:
            w0, w1 = v0 * v0 * t0, v1 * v1 * t1
            w = w0 + (w1 - w0) * (T - t0) / (t1 - t0)
            return math.sqrt(max(w, 0.0) / T), False
    raise ValueError("unreachable")
