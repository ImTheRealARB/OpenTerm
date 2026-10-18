"""Plain-vanilla interest-rate swap valuation on a single curve, and a par-yield bootstrap.

Written for OpenTerm; no third-party source.

Single-curve projection: the same discount curve discounts the cash flows and implies the floating-leg forwards, so the
floating leg is worth ``notional * (1 - DF(T))`` and the par rate is ``(1 - DF(T)) / annuity``. Accrual is ``1 / freq`` per period
(a 30/360-style regular schedule; no calendar, no stub). A curve object offers ``df(t)`` (discount factor at ``t`` years),
``zero(t)`` (continuously compounded zero rate) and ``shifted(bp)`` (a parallel shift of the zero rates by ``bp`` basis points).
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections.abc import Mapping
from itertools import pairwise

__all__ = ["DiscountCurve", "FlatCurve", "bootstrap_par_curve", "flat_curve", "value_swap"]


class FlatCurve:
    """Flat continuously compounded zero curve: ``df(t) = exp(-r t)``."""

    def __init__(self, rate: float):
        if not math.isfinite(rate):
            raise ValueError(f"rate must be finite, got {rate}")
        self.rate = float(rate)

    def df(self, t: float) -> float:
        return math.exp(-self.rate * t)

    def zero(self, t: float) -> float:
        return self.rate

    def shifted(self, bp: float) -> FlatCurve:
        return FlatCurve(self.rate + bp / 1e4)


class DiscountCurve:
    """Discount factors at nodes, log-linear in between (flat zero rate), flat zero rate beyond the last node, plus a parallel shift."""

    def __init__(self, times: list[float], dfs: list[float], shift: float = 0.0):
        if not times or len(times) != len(dfs):
            raise ValueError("times and dfs must be non-empty and the same length")
        if any(b <= a for a, b in pairwise(times)) or times[0] <= 0:
            raise ValueError("node times must be positive and strictly increasing")
        if any(d <= 0 or not math.isfinite(d) for d in dfs):
            raise ValueError("discount factors must be positive and finite")
        self.times = list(times)
        self.dfs = list(dfs)
        self._logdf = [math.log(d) for d in dfs]
        self.shift = shift  # continuously compounded, as a decimal

    def _base_logdf(self, t: float) -> float:
        times, logdf = self.times, self._logdf
        if t <= 0:
            return 0.0
        if t >= times[-1]:
            return logdf[-1] * t / times[-1]  # flat zero rate beyond the last node
        i = bisect_right(times, t)
        if i == 0:  # between today (df = 1) and the first node
            return logdf[0] * t / times[0]
        t0, t1 = times[i - 1], times[i]
        if t == t0:
            return logdf[i - 1]
        w = (t - t0) / (t1 - t0)
        return logdf[i - 1] + w * (logdf[i] - logdf[i - 1])

    def df(self, t: float) -> float:
        return math.exp(self._base_logdf(t) - self.shift * t)

    def zero(self, t: float) -> float:
        if t <= 0:
            t = self.times[0]
        return -self._base_logdf(t) / t + self.shift

    def shifted(self, bp: float) -> DiscountCurve:
        return DiscountCurve(self.times, self.dfs, self.shift + bp / 1e4)


def flat_curve(r: float) -> FlatCurve:
    """Flat curve at the continuously compounded zero rate ``r`` (a decimal)."""
    return FlatCurve(r)


def bootstrap_par_curve(par: Mapping[float, float], freq: int = 2) -> DiscountCurve:
    """Bootstrap discount factors from par yields.

    Args:
        par: Par yield (a decimal, paid ``freq`` times a year, quoted at par) by maturity in years. At least one point.
        freq: Coupons per year.

    The par yield at every coupon date ``n / freq`` up to the longest maturity is read from ``par`` by linear interpolation
    (flat before the first and after the last point). Then ``DF(n) = (1 - c_n / freq * sum(DF(1..n-1))) / (1 + c_n / freq)`` is
    solved date by date, so a bond with the quoted coupon at a quoted maturity on the schedule reprices to 100 exactly. Between
    nodes the curve is log-linear in the discount factor; beyond the last node the zero rate is flat.

    Raises:
        ValueError: On an empty or non-finite input, a non-positive maturity, a non-positive ``freq``, or a par curve so steep
            that a discount factor would be negative.
    """
    if not par:
        raise ValueError("par curve is empty")
    if freq <= 0 or not isinstance(freq, int):
        raise ValueError(f"freq must be a positive integer, got {freq!r}")
    points = sorted((float(t), float(y)) for t, y in par.items())
    if any(t <= 0 or not math.isfinite(t) or not math.isfinite(y) for t, y in points):
        raise ValueError("par maturities must be positive and finite, yields finite")
    mats = [t for t, _ in points]
    yields = [y for _, y in points]

    def par_at(t: float) -> float:
        if t <= mats[0]:
            return yields[0]
        if t >= mats[-1]:
            return yields[-1]
        i = bisect_right(mats, t)
        w = (t - mats[i - 1]) / (mats[i] - mats[i - 1])
        return yields[i - 1] + w * (yields[i] - yields[i - 1])

    n_max = max(1, round(mats[-1] * freq - 1e-9))
    if mats[-1] * freq > n_max + 1e-9:
        n_max += 1
    times: list[float] = []
    dfs: list[float] = []
    annuity = 0.0  # sum of DF over the earlier coupon dates
    for n in range(1, n_max + 1):
        t = n / freq
        c = par_at(t) / freq
        df = (1.0 - c * annuity) / (1.0 + c)
        if df <= 0:
            raise ValueError(f"par yields imply a non-positive discount factor at {t} years")
        times.append(t)
        dfs.append(df)
        annuity += df
    return DiscountCurve(times, dfs)


def value_swap(
    notional: float,
    fixed_rate: float,
    years: float,
    freq: int,
    curve: FlatCurve | DiscountCurve,
    pay_fixed: bool = True,
) -> dict:
    """Value a plain-vanilla fixed-for-floating swap on one curve.

    Args:
        notional: Notional amount.
        fixed_rate: Fixed coupon rate (a decimal).
        years: Swap tenor in years; ``years * freq`` must be a whole number of periods.
        freq: Payments per year (both legs).
        curve: A curve from :func:`flat_curve` or :func:`bootstrap_par_curve`.
        pay_fixed: True when the holder pays fixed and receives floating.

    Returns:
        ``{"par_rate", "pv_fixed_leg", "pv_float_leg", "mtm", "dv01", "cashflows"}``. The leg PVs are unsigned; ``mtm`` is the
        holder's value (float minus fixed when paying fixed, the reverse when receiving). ``dv01`` is the change in ``mtm`` for a
        +1 bp parallel shift of the zero curve. Each cash flow is ``{"n", "t", "df", "fixed", "float_estimate", "net", "pv"}``:
        the fixed coupon, the projected floating payment ``notional * (DF(t_prev) / DF(t) - 1)``, the holder's net amount and its
        present value (the ``pv`` values sum to ``mtm``).

    Raises:
        ValueError: On a non-positive notional, ``freq`` or tenor, or a tenor that is not a whole number of periods.
    """
    for name, value in (("notional", notional), ("fixed_rate", fixed_rate), ("years", years)):
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite, got {value}")
    if notional <= 0:
        raise ValueError("notional must be positive")
    if freq <= 0 or not isinstance(freq, int):
        raise ValueError(f"freq must be a positive integer, got {freq!r}")
    periods = round(years * freq)
    if periods < 1 or abs(years * freq - periods) > 1e-9:
        raise ValueError(f"years * freq must be a positive whole number, got {years} * {freq}")

    def legs(c: FlatCurve | DiscountCurve) -> tuple[float, float, float, float]:
        dfs = [c.df((i + 1) / freq) for i in range(periods)]
        annuity = math.fsum(dfs) / freq
        pv_fixed = notional * fixed_rate * annuity
        pv_float = notional * (1.0 - dfs[-1])
        return pv_fixed, pv_float, annuity, dfs[-1]

    def mtm_of(c: FlatCurve | DiscountCurve) -> float:
        pv_fixed, pv_float, _, _ = legs(c)
        return (pv_float - pv_fixed) if pay_fixed else (pv_fixed - pv_float)

    pv_fixed, pv_float, annuity, df_last = legs(curve)
    mtm = (pv_float - pv_fixed) if pay_fixed else (pv_fixed - pv_float)
    par_rate = (1.0 - df_last) / annuity
    dv01 = mtm_of(curve.shifted(1.0)) - mtm

    cashflows = []
    prev_df = 1.0
    sign = 1.0 if pay_fixed else -1.0
    for n in range(1, periods + 1):
        t = n / freq
        df = curve.df(t)
        fixed = notional * fixed_rate / freq
        floating = notional * (prev_df / df - 1.0)
        net = sign * (floating - fixed)
        cashflows.append({"n": n, "t": t, "df": df, "fixed": fixed, "float_estimate": floating, "net": net, "pv": net * df})
        prev_df = df
    return {
        "par_rate": par_rate,
        "pv_fixed_leg": pv_fixed,
        "pv_float_leg": pv_float,
        "mtm": mtm,
        "dv01": dv01,
        "cashflows": cashflows,
    }
