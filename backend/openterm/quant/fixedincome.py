"""Fixed-income primitives: day count conventions, bond pricing, risk metrics, and yield curve fitting.

Ported from HKUDS/Vibe-Trading @ d0db2e3, agent/src/quantlib/fixedincome.py (MIT; see THIRD_PARTY.md).
Changes: numpy and scipy removed. Arrays became lists (``bond_cashflows`` returns two lists, ``nelson_siegel`` / ``svensson`` /
``CurveFit.__call__`` return a float for a scalar maturity and a list for a sequence), ``brentq`` -> ``numerics.brent``, the
simplex search -> ``numerics.nelder_mead`` and the OLS step -> ``numerics.lstsq`` (Householder QR). ``key_rate_duration`` returns
a ``TenorMap`` (a dict keyed by float tenor that also answers to the tenor's string, because the JSON form has string keys).
Added for OpenTerm, not in Vibe: ``price_mid_period`` and ``ytm_from_clean`` (settlement between coupons, stub-period
discounting). The fit starts from the same geometric grid, but the simplex may end elsewhere in a flat valley, so compare fitted
curves and rmse rather than parameters.

All rates are decimals, maturities/horizons are in years, and duration/convexity
metrics are in years or years squared.
"""

from __future__ import annotations

import datetime as _dt
import math
from bisect import bisect_left
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import pairwise

from openterm.quant.numerics import brent, lstsq, nelder_mead

__all__ = [
    "COMPOUNDING_CONVENTIONS",
    "DAY_COUNT_CONVENTIONS",
    "DEFAULT_COMPOUNDING",
    "DEFAULT_DAY_COUNT",
    "DEFAULT_KEY_RATE_TENORS",
    "CurveFit",
    "TenorMap",
    "accrued_interest",
    "bond_cashflows",
    "bond_price",
    "convexity",
    "dv01",
    "effective_duration",
    "fit_yield_curve",
    "key_rate_duration",
    "macaulay_duration",
    "modified_duration",
    "nelson_siegel",
    "price_mid_period",
    "svensson",
    "year_fraction",
    "ytm_from_clean",
    "ytm_solve",
]

#: Day-count conventions understood by :func:`year_fraction`.
DAY_COUNT_CONVENTIONS: tuple[str, ...] = (
    "ACT/365F",
    "ACT/360",
    "ACT/ACT",
    "30/360",
    "30E/360",
)

#: Convention assumed when the caller does not name one.
DEFAULT_DAY_COUNT: str = "ACT/365F"

#: Compounding conventions understood by the pricing functions.
COMPOUNDING_CONVENTIONS: tuple[str, ...] = ("discrete", "continuous")

#: Compounding assumed when the caller does not name one (the markdown's behaviour).
DEFAULT_COMPOUNDING: str = "discrete"

#: Standard benchmark tenors for Key Rate Duration decomposition.
DEFAULT_KEY_RATE_TENORS: tuple[float, ...] = (
    0.5, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 20.0, 30.0
)


class TenorMap(dict):
    """``{tenor_years: value}`` with float keys that also looks up by the tenor's string (``"0.5"``), as in the JSON form."""

    def _key(self, key):
        if isinstance(key, str):
            try:
                return float(key)
            except ValueError:
                return key
        return key

    def __contains__(self, key) -> bool:
        return super().__contains__(self._key(key))

    def __getitem__(self, key):
        return super().__getitem__(self._key(key))

    def get(self, key, default=None):
        return super().get(self._key(key), default)


def year_fraction(
    start: _dt.date,
    end: _dt.date,
    day_count: str = DEFAULT_DAY_COUNT,
) -> float:
    """Accrual factor between two dates under a named day-count convention.

    Args:
        start: Period start (accrual runs from this date, inclusive).
        end: Period end (accrual runs to this date, exclusive).
        day_count: One of :data:`DAY_COUNT_CONVENTIONS`. ``ACT/ACT`` is the
            ISDA variant: each calendar year contributes
            ``days_in_that_year / (365 or 366)``.

    Returns:
        Year fraction as a float. Negative if ``end`` precedes ``start``.

    Raises:
        ValueError: If ``day_count`` is not a recognised convention.
    """
    if day_count not in DAY_COUNT_CONVENTIONS:
        raise ValueError(
            f"unknown day_count {day_count!r}; expected one of {DAY_COUNT_CONVENTIONS}"
        )

    if end < start:
        return -year_fraction(end, start, day_count)

    if day_count == "ACT/365F":
        return (end - start).days / 365.0
    if day_count == "ACT/360":
        return (end - start).days / 360.0
    if day_count in ("30/360", "30E/360"):
        d1, d2 = start.day, end.day
        if day_count == "30/360":
            # US bond basis: clip D1 to 30, then clip D2 when adjusted D1 is 30.
            if d1 == 31:
                d1 = 30
            if d2 == 31 and d1 == 30:
                d2 = 30
        else:  # 30E/360 (Eurobond basis) clips both legs unconditionally.
            d1 = min(d1, 30)
            d2 = min(d2, 30)
        months = 12 * (end.year - start.year) + (end.month - start.month)
        return (30.0 * months + (d2 - d1)) / 360.0

    # ACT/ACT (ISDA): accumulate each calendar year against its own basis.
    total = 0.0
    cursor = start
    while cursor < end:
        year_end = _dt.date(cursor.year + 1, 1, 1)
        chunk_end = min(year_end, end)
        basis = 366.0 if _is_leap(cursor.year) else 365.0
        total += (chunk_end - cursor).days / basis
        cursor = chunk_end
    return total


def _require_finite(**values: float | Sequence[float]) -> None:
    """Raise when a named numeric input holds NaN or an infinity.

    Every range check in this module is a comparison (``face <= 0``) and a
    comparison with NaN is False, so a NaN walked past each of them and came
    out as a NaN price, duration or curve.

    Raises:
        ValueError: Naming the first non-finite input.
    """
    for name, value in values.items():
        items = value if isinstance(value, (list, tuple)) else (value,)
        if not all(math.isfinite(float(v)) for v in items):
            raise ValueError(f"{name} must be finite, got {value!r}")


def _is_leap(year: int) -> bool:
    """Report whether a Gregorian year is a leap year.

    Args:
        year: Four-digit calendar year.

    Returns:
        True when the year has 366 days.
    """
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def accrued_interest(
    face: float,
    coupon_rate: float,
    freq: int,
    last_coupon: _dt.date,
    settlement: _dt.date,
    next_coupon: _dt.date,
    day_count: str = DEFAULT_DAY_COUNT,
) -> float:
    """Interest earned by the seller between the last coupon and settlement.

    Dirty price = clean price + accrued interest. :func:`bond_price` returns the
    price on a coupon date, where accrued interest is zero by construction; use
    this function to move a mid-period settlement onto that basis.

    Args:
        face: Par amount the coupon is computed on.
        coupon_rate: Annual coupon rate as a decimal.
        freq: Coupon payments per year (1 = annual, 2 = semi-annual).
        last_coupon: Date of the most recent coupon payment.
        settlement: Settlement date of the trade.
        next_coupon: Date of the upcoming coupon payment.
        day_count: One of :data:`DAY_COUNT_CONVENTIONS`.

    Returns:
        Accrued interest in the same currency units as ``face``.

    Raises:
        ValueError: If any numeric input is non-finite, if ``freq`` is not
            positive, if the coupon dates are not ordered, if ``settlement``
            falls outside the coupon period, or if ``day_count`` is not a
            recognised convention.
    """
    # Before the endpoint shortcuts: settling exactly on a coupon date returns
    # a constant, which would otherwise launder a NaN face or rate into a
    # clean-looking 0.0.
    _require_finite(face=face, coupon_rate=coupon_rate, freq=freq)
    if freq <= 0:
        raise ValueError(f"freq must be positive, got {freq}")
    if not last_coupon < next_coupon:
        raise ValueError("last_coupon must precede next_coupon")
    if not last_coupon <= settlement <= next_coupon:
        raise ValueError("settlement must fall inside [last_coupon, next_coupon]")
    # Checked here as well as in year_fraction: the endpoint returns below never
    # reach year_fraction, so an unknown convention would otherwise pass there.
    if day_count not in DAY_COUNT_CONVENTIONS:
        raise ValueError(
            f"unknown day_count {day_count!r}; expected one of {DAY_COUNT_CONVENTIONS}"
        )

    # 30/360 and 30E/360 clip the day-of-month, so distinct calendar dates
    # (e.g. Jan 30 -> Jan 31) can still year_fraction to 0.0. last_coupon <
    # next_coupon is already guaranteed above, so that can never mean a
    # true zero-length period -- checking settlement's own position against
    # the coupon dates keeps the endpoints correct regardless.
    if settlement == last_coupon:
        return 0.0
    if settlement == next_coupon:
        return face * coupon_rate / freq

    period = year_fraction(last_coupon, next_coupon, day_count)
    if period == 0.0:
        return 0.0
    elapsed = year_fraction(last_coupon, settlement, day_count)
    return face * coupon_rate / freq * (elapsed / period)


def bond_cashflows(
    face: float,
    coupon_rate: float,
    n_periods: int,
    freq: int = 1,
) -> tuple[list[float], list[float]]:
    """Coupon schedule of a bullet bond, in periods and amounts.

    Args:
        face: Redemption amount paid with the final coupon.
        coupon_rate: Annual coupon rate as a decimal.
        n_periods: Number of remaining coupon periods.
        freq: Coupon payments per year.

    Returns:
        Tuple ``(periods, amounts)`` where ``periods`` is ``1..n_periods`` as
        floats and ``amounts`` is the cash paid at each. Time in years is
        ``periods / freq``.

    Raises:
        ValueError: If any numeric input is non-finite, if ``face`` is not
            positive, if ``n_periods`` is not a positive integer, or if
            ``freq`` is not positive.
    """
    # freq too: with an infinite frequency every coupon collapses to zero and
    # the schedule reprices to a plausible-looking par.
    _require_finite(face=face, coupon_rate=coupon_rate, freq=freq)
    if face <= 0:
        raise ValueError(f"face must be positive, got {face}")
    if isinstance(n_periods, bool) or not isinstance(n_periods, int) or n_periods <= 0:
        raise ValueError(f"n_periods must be a positive integer, got {n_periods!r}")
    if freq <= 0:
        raise ValueError(f"freq must be positive, got {freq}")

    periods = [float(k) for k in range(1, n_periods + 1)]
    coupon = face * coupon_rate / freq
    amounts = [coupon] * n_periods
    amounts[-1] += face
    return periods, amounts


def _discount_factors(
    ytm: float,
    periods: Sequence[float],
    freq: int,
    compounding: str,
) -> list[float]:
    """Compute discount factors for period indices under discrete or continuous compounding."""
    _require_finite(ytm=ytm)
    if compounding == "discrete":
        periodic = 1.0 + ytm / freq
        if periodic <= 0.0:
            raise ValueError(
                f"discrete compounding needs 1 + ytm/freq > 0, got {periodic}"
            )
        return [periodic ** (-k) for k in periods]
    if compounding == "continuous":
        return [math.exp(-ytm * k / freq) for k in periods]
    raise ValueError(
        f"unknown compounding {compounding!r}; expected one of {COMPOUNDING_CONVENTIONS}"
    )


def _pv_terms(
    face: float,
    coupon_rate: float,
    ytm: float,
    n_periods: int,
    freq: int,
    compounding: str,
) -> tuple[list[float], list[float]]:
    """``(periods, discounted cash flows)`` of the bullet schedule."""
    periods, amounts = bond_cashflows(face, coupon_rate, n_periods, freq)
    dfs = _discount_factors(ytm, periods, freq, compounding)
    return periods, [a * d for a, d in zip(amounts, dfs, strict=True)]


def bond_price(
    face: float,
    coupon_rate: float,
    ytm: float,
    n_periods: int,
    freq: int = 1,
    compounding: str = DEFAULT_COMPOUNDING,
) -> float:
    """Present value of a bullet bond settling on a coupon date.

    The result is a *clean* price: settlement is assumed to sit on a coupon date
    so no interest has accrued. Add :func:`accrued_interest` for a dirty price.

    Args:
        face: Par/redemption amount, conventionally 100.
        coupon_rate: Annual coupon rate as a decimal (0.05 == 5%).
        ytm: Annual yield to maturity as a decimal.
        n_periods: Number of remaining coupon periods.
        freq: Coupon payments per year (1 = annual, 2 = semi-annual).
        compounding: One of :data:`COMPOUNDING_CONVENTIONS`.

    Returns:
        Present value in the same units as ``face``.

    Raises:
        ValueError: If the schedule arguments or ``compounding`` are invalid.
    """
    return float(math.fsum(_pv_terms(face, coupon_rate, ytm, n_periods, freq, compounding)[1]))


def price_mid_period(
    face: float,
    coupon_rate: float,
    ytm: float,
    freq: int,
    last_coupon: _dt.date,
    next_coupon: _dt.date,
    settlement: _dt.date,
    n_periods: int,
    day_count: str = DEFAULT_DAY_COUNT,
    compounding: str = DEFAULT_COMPOUNDING,
) -> dict[str, float]:
    """Price of a bullet bond settling between two coupon dates (written for OpenTerm; not in Vibe).

    The first remaining coupon is ``w`` periods away, where ``w`` is the day-count fraction from settlement to the next coupon
    over the fraction of the whole coupon period (the stub). Cash flow ``k`` (0-based) is discounted for ``w + k`` periods, so the
    dirty price is ``sum(cf_k / (1 + y/freq)**(w + k))`` (``exp(-y * (w + k) / freq)`` under continuous compounding). The accrued
    interest follows :func:`accrued_interest` (by the same day count) and the clean price is dirty minus accrued.

    Args:
        n_periods: Coupon payments remaining, counting the next one.
        Others as in :func:`accrued_interest` and :func:`bond_price`.

    Returns:
        ``{"clean", "dirty", "accrued", "w"}``.

    Raises:
        ValueError: As :func:`accrued_interest` and :func:`bond_price`.
    """
    accrued = accrued_interest(face, coupon_rate, freq, last_coupon, settlement, next_coupon, day_count)
    period = year_fraction(last_coupon, next_coupon, day_count)
    w = year_fraction(settlement, next_coupon, day_count) / period if period else 0.0
    periods, amounts = bond_cashflows(face, coupon_rate, n_periods, freq)
    _require_finite(ytm=ytm)
    if compounding == "discrete":
        periodic = 1.0 + ytm / freq
        if periodic <= 0.0:
            raise ValueError(f"discrete compounding needs 1 + ytm/freq > 0, got {periodic}")
        dfs = [periodic ** (-(w + k - 1.0)) for k in periods]
    elif compounding == "continuous":
        dfs = [math.exp(-ytm * (w + k - 1.0) / freq) for k in periods]
    else:
        raise ValueError(
            f"unknown compounding {compounding!r}; expected one of {COMPOUNDING_CONVENTIONS}"
        )
    dirty = float(math.fsum(a * d for a, d in zip(amounts, dfs, strict=True)))
    return {"clean": dirty - accrued, "dirty": dirty, "accrued": accrued, "w": w}


def ytm_solve(
    price: float,
    face: float,
    coupon_rate: float,
    n_periods: int,
    freq: int = 1,
    compounding: str = DEFAULT_COMPOUNDING,
    bracket: tuple[float, float] = (-0.5, 10.0),
) -> float:
    """Invert :func:`bond_price` for the yield that reproduces a market price.

    Args:
        price: Observed price, on the same clean basis as :func:`bond_price`.
        face: Par/redemption amount.
        coupon_rate: Annual coupon rate as a decimal.
        n_periods: Number of remaining coupon periods.
        freq: Coupon payments per year.
        compounding: One of :data:`COMPOUNDING_CONVENTIONS`.
        bracket: ``(low, high)`` annual yield search interval as decimals.

    Returns:
        Annual yield to maturity as a decimal.

    Raises:
        ValueError: If ``price`` or a bracket bound is non-finite, or if the
            price is not reachable inside ``bracket``.
    """
    low, high = bracket
    # NaN fails ``low >= high`` and every solver evaluation; name the input
    # instead of reporting a bracket that "cannot reprice" it.
    _require_finite(price=price, bracket_low=low, bracket_high=high)
    if low >= high:
        raise ValueError(f"bracket must be increasing, got {bracket}")

    def pv_diff(y: float) -> float:
        return bond_price(face, coupon_rate, y, n_periods, freq, compounding) - price

    try:
        return float(brent(pv_diff, low, high))
    except ValueError as exc:
        raise ValueError(
            f"no yield in {bracket} reprices this bond to {price}: {exc}"
        ) from exc


def ytm_from_clean(
    clean: float,
    face: float,
    coupon_rate: float,
    freq: int,
    last_coupon: _dt.date,
    next_coupon: _dt.date,
    settlement: _dt.date,
    n_periods: int,
    day_count: str = DEFAULT_DAY_COUNT,
    compounding: str = DEFAULT_COMPOUNDING,
    bracket: tuple[float, float] = (-0.5, 10.0),
) -> float:
    """Yield that reproduces a quoted clean price for a settlement between coupons (inverse of :func:`price_mid_period`).

    Raises:
        ValueError: If the inputs are invalid or no yield in ``bracket`` reprices the bond to ``clean``.
    """
    low, high = bracket
    _require_finite(clean=clean, bracket_low=low, bracket_high=high)
    if low >= high:
        raise ValueError(f"bracket must be increasing, got {bracket}")

    def diff(y: float) -> float:
        return price_mid_period(face, coupon_rate, y, freq, last_coupon, next_coupon, settlement,
                                n_periods, day_count, compounding)["clean"] - clean

    try:
        return float(brent(diff, low, high, xtol=1e-15))
    except ValueError as exc:
        raise ValueError(f"no yield in {bracket} reprices this bond to {clean}: {exc}") from exc


def macaulay_duration(
    face: float,
    coupon_rate: float,
    ytm: float,
    n_periods: int,
    freq: int = 1,
    compounding: str = DEFAULT_COMPOUNDING,
) -> float:
    """Present-value-weighted average time to the bond's cash flows.

    Args:
        face: Par/redemption amount.
        coupon_rate: Annual coupon rate as a decimal.
        ytm: Annual yield to maturity as a decimal.
        n_periods: Number of remaining coupon periods.
        freq: Coupon payments per year.
        compounding: One of :data:`COMPOUNDING_CONVENTIONS`.

    Returns:
        Macaulay duration in **years**.

    Raises:
        ValueError: If the schedule arguments or ``compounding`` are invalid.
    """
    periods, pv = _pv_terms(face, coupon_rate, ytm, n_periods, freq, compounding)
    return float(math.fsum(k / freq * p for k, p in zip(periods, pv, strict=True)) / math.fsum(pv))


def modified_duration(
    face: float,
    coupon_rate: float,
    ytm: float,
    n_periods: int,
    freq: int = 1,
    compounding: str = DEFAULT_COMPOUNDING,
) -> float:
    """Semi-elasticity of price to yield, ``-(dP/dy)/P``.

    Args:
        face: Par/redemption amount.
        coupon_rate: Annual coupon rate as a decimal.
        ytm: Annual yield to maturity as a decimal.
        n_periods: Number of remaining coupon periods.
        freq: Coupon payments per year.
        compounding: One of :data:`COMPOUNDING_CONVENTIONS`. Under continuous
            compounding modified duration equals Macaulay duration.

    Returns:
        Modified duration in years, positive for a conventional bond.

    Raises:
        ValueError: If the schedule arguments or ``compounding`` are invalid.
    """
    d_mac = macaulay_duration(face, coupon_rate, ytm, n_periods, freq, compounding)
    if compounding == "continuous":
        return d_mac
    return d_mac / (1.0 + ytm / freq)


def key_rate_duration(
    face: float,
    coupon_rate: float,
    ytm: float,
    n_periods: int,
    freq: int = 1,
    key_rates: Sequence[float] = DEFAULT_KEY_RATE_TENORS,
    compounding: str = DEFAULT_COMPOUNDING,
) -> TenorMap:
    """Decompose bond yield sensitivity into Key Rate Durations (KRD) across benchmark tenors.

    Distributes cash flow sensitivities to adjacent key rates with triangular kernels.
    Sum of key rate durations equals modified duration.
    Args:
        face: Par/redemption amount.
        coupon_rate: Annual coupon rate as a decimal.
        ytm: Annual yield to maturity as a decimal.
        n_periods: Number of remaining coupon periods.
        freq: Coupon payments per year.
        key_rates: Sequence of key rate tenors in years (strictly increasing).
        compounding: One of :data:`COMPOUNDING_CONVENTIONS`.

    Returns:
        Dict mapping each key rate tenor (float) to its Key Rate Duration (float in years).

    Raises:
        ValueError: If key_rates is empty, non-finite or not strictly
            increasing, or schedule/compounding invalid.
    """
    kr = [float(k) for k in key_rates]
    if len(kr) == 0:
        raise ValueError("key_rates must contain at least one tenor")
    # A NaN tenor is neither empty nor non-increasing, so it sailed past both
    # checks and came back as a NaN key in the result dict.
    _require_finite(key_rates=kr)
    if any(b - a <= 0.0 for a, b in pairwise(kr)):
        raise ValueError(f"key_rates must be strictly increasing, got {key_rates}")

    periods, pv_terms = _pv_terms(face, coupon_rate, ytm, n_periods, freq, compounding)
    price = float(math.fsum(pv_terms))
    if price <= 0.0:
        raise ValueError("bond price must be positive for key rate duration")

    cf_times = [k / freq for k in periods]
    # Modified discount factor weight per cash flow
    if compounding == "continuous":
        time_weights = cf_times
    else:
        time_weights = [t / (1.0 + ytm / freq) for t in cf_times]

    cf_durations = [w * p / price for w, p in zip(time_weights, pv_terms, strict=True)]  # Sums to modified duration

    krd_result = TenorMap((t, 0.0) for t in kr)

    for t_cf, dur_cf in zip(cf_times, cf_durations, strict=True):
        if t_cf <= kr[0]:
            krd_result[kr[0]] += dur_cf
        elif t_cf >= kr[-1]:
            krd_result[kr[-1]] += dur_cf
        else:
            # Find interval kr[k] <= t_cf <= kr[k+1]
            idx = bisect_left(kr, t_cf)
            t_left = kr[idx - 1]
            t_right = kr[idx]
            w_right = (t_cf - t_left) / (t_right - t_left)
            w_left = 1.0 - w_right
            krd_result[t_left] += dur_cf * w_left
            krd_result[t_right] += dur_cf * w_right

    return krd_result


def convexity(
    face: float,
    coupon_rate: float,
    ytm: float,
    n_periods: int,
    freq: int = 1,
    compounding: str = DEFAULT_COMPOUNDING,
) -> float:
    """Second-order price sensitivity to yield, ``(d2P/dy2)/P``.

    Args:
        face: Par/redemption amount.
        coupon_rate: Annual coupon rate as a decimal.
        ytm: Annual yield to maturity as a decimal.
        n_periods: Number of remaining coupon periods.
        freq: Coupon payments per year.
        compounding: One of :data:`COMPOUNDING_CONVENTIONS`.

    Returns:
        Convexity in years squared. Positive for any bond without embedded
        short optionality.

    Raises:
        ValueError: If the schedule arguments or ``compounding`` are invalid.
    """
    periods, pv = _pv_terms(face, coupon_rate, ytm, n_periods, freq, compounding)
    price = math.fsum(pv)
    if compounding == "continuous":
        return float(math.fsum((k / freq) ** 2 * p for k, p in zip(periods, pv, strict=True)) / price)
    weighted = math.fsum(k * (k + 1.0) / (freq**2) * p for k, p in zip(periods, pv, strict=True))
    return float(weighted / price / (1.0 + ytm / freq) ** 2)


def dv01(
    face: float,
    coupon_rate: float,
    ytm: float,
    n_periods: int,
    freq: int = 1,
    par_amount: float = 1_000_000.0,
    compounding: str = DEFAULT_COMPOUNDING,
) -> float:
    """Cash value of one basis point on a stated par position.

    Args:
        face: Par/redemption amount the quoted price is per, conventionally 100.
        coupon_rate: Annual coupon rate as a decimal.
        ytm: Annual yield to maturity as a decimal.
        n_periods: Number of remaining coupon periods.
        freq: Coupon payments per year.
        par_amount: Par value held. The market value hedged is
            ``par_amount * price / face``.
        compounding: One of :data:`COMPOUNDING_CONVENTIONS`.

    Returns:
        Price change, in currency units, for a 1bp rise in yield, reported as a
        positive number.

    Raises:
        ValueError: If ``face`` is zero, if ``par_amount`` is non-finite, or
            the schedule/compounding is invalid.
    """
    if face == 0:
        raise ValueError("face must be non-zero")
    # face itself is admitted by the schedule checks downstream; par_amount
    # never reaches them, so a NaN position size would scale into a NaN hedge.
    _require_finite(par_amount=par_amount)
    d_mod = modified_duration(face, coupon_rate, ytm, n_periods, freq, compounding)
    price = bond_price(face, coupon_rate, ytm, n_periods, freq, compounding)
    return d_mod * (price / face) * 1e-4 * par_amount


def effective_duration(
    reprice: Callable[[float], float],
    yield_level: float,
    bump: float = 1e-4,
) -> float:
    """Duration by symmetric repricing, valid for bonds with embedded options.

    Re-evaluates a custom pricing model at perturbed yields to compute duration.
    Args:
        reprice: Callable mapping a yield level to a price. It must contain the
            option/prepayment logic; nothing here inspects it.
        yield_level: Base yield to bump around.
        bump: Half-width of the symmetric shock, as a decimal (1e-4 = 1bp).

    Returns:
        Effective duration in years, ``(P_down - P_up) / (2 * P_0 * bump)``.

    Raises:
        ValueError: If ``bump`` is not positive or the base price is zero.
    """
    _require_finite(yield_level=yield_level, bump=bump)
    if bump <= 0:
        raise ValueError(f"bump must be positive, got {bump}")
    base = reprice(yield_level)
    if base == 0:
        raise ValueError("base price is zero; effective duration is undefined")
    down = reprice(yield_level - bump)
    up = reprice(yield_level + bump)
    return (down - up) / (2.0 * base * bump)


def _decay_factors(tau: Sequence[float], lam: float) -> tuple[list[float], list[float]]:
    """Compute Nelson-Siegel slope and curvature loadings for decay parameter lam."""
    _require_finite(decay=lam)
    if lam <= 0:
        raise ValueError(f"decay parameter must be positive, got {lam}")
    slope: list[float] = []
    curve: list[float] = []
    for t in tau:
        x = t / lam
        if x > 0:
            e = math.exp(-x)
            s = (1.0 - e) / x
            slope.append(s)
            curve.append(s - e)
        else:
            slope.append(1.0)
            curve.append(1.0 - math.exp(-x))
    return slope, curve


def _as_tau(tau: float | Sequence[float]) -> tuple[list[float], bool]:
    """Normalise scalar or sequence maturity argument to a list of floats."""
    was_scalar = isinstance(tau, (int, float))
    arr = [float(tau)] if was_scalar else [float(t) for t in tau]  # type: ignore[arg-type]
    _require_finite(maturities=arr)
    if any(t < 0 for t in arr):
        raise ValueError("maturities must be non-negative")
    return arr, was_scalar


def nelson_siegel(
    tau: float | Sequence[float],
    beta0: float,
    beta1: float,
    beta2: float,
    lambda1: float,
) -> float | list[float]:
    """Compute Nelson-Siegel zero rates for given maturities and parameters."""
    _require_finite(beta0=beta0, beta1=beta1, beta2=beta2)
    arr, was_scalar = _as_tau(tau)
    slope, curve = _decay_factors(arr, lambda1)
    out = [beta0 + beta1 * s + beta2 * c for s, c in zip(slope, curve, strict=True)]
    return out[0] if was_scalar else out


def svensson(
    tau: float | Sequence[float],
    beta0: float,
    beta1: float,
    beta2: float,
    beta3: float,
    lambda1: float,
    lambda2: float,
) -> float | list[float]:
    """Compute Svensson zero rates for given maturities and parameters."""
    _require_finite(beta0=beta0, beta1=beta1, beta2=beta2, beta3=beta3)
    arr, was_scalar = _as_tau(tau)
    slope, curve1 = _decay_factors(arr, lambda1)
    _, curve2 = _decay_factors(arr, lambda2)
    out = [
        beta0 + beta1 * s + beta2 * c1 + beta3 * c2
        for s, c1, c2 in zip(slope, curve1, curve2, strict=True)
    ]
    return out[0] if was_scalar else out


#: Search range, in years, for the Nelson-Siegel/Svensson decay parameters.
CURVE_DECAY_BOUNDS: tuple[float, float] = (0.05, 30.0)

#: Number of grid points per decay parameter used to seed the curve fit.
CURVE_DECAY_GRID: int = 48


@dataclass(frozen=True)
class CurveFit:
    """Result of :func:`fit_yield_curve`; call it to evaluate the fitted curve.

    Attributes:
        model: ``"nelson_siegel"`` or ``"svensson"``.
        params: Fitted parameters. Nelson-Siegel is
            ``(beta0, beta1, beta2, lambda1)``; Svensson is
            ``(beta0, beta1, beta2, beta3, lambda1, lambda2)``.
        rmse: Root-mean-square fitting error against input yields.
    """

    model: str
    params: tuple[float, ...]
    rmse: float = math.nan

    def __call__(self, tau: float | Sequence[float]) -> float | list[float]:
        """Evaluate the fitted curve at one or more maturities.

        Args:
            tau: Maturity or maturities in years.

        Returns:
            Zero rate(s) as decimals.

        Raises:
            ValueError: If the stored model name is not recognised.
        """
        if self.model == "nelson_siegel":
            return nelson_siegel(tau, *self.params)
        if self.model == "svensson":
            return svensson(tau, *self.params)
        raise ValueError(f"unknown curve model {self.model!r}")


def _curve_design(tau: Sequence[float], lambdas: Sequence[float]) -> list[list[float]]:
    """Linear design columns for a curve model with fixed decay parameters.

    Args:
        tau: Maturities in years.
        lambdas: One decay parameter for Nelson-Siegel, two for Svensson.

    Returns:
        Columns holding the level, slope and curvature loadings.

    Raises:
        ValueError: If a decay parameter is not positive.
    """
    slope, curve1 = _decay_factors(tau, lambdas[0])
    columns = [[1.0] * len(tau), slope, curve1]
    for lam in lambdas[1:]:
        columns.append(_decay_factors(tau, lam)[1])
    return columns


def _profiled_ssr(
    lambdas: Sequence[float], tau: Sequence[float], yields: Sequence[float]
) -> tuple[float, list[float]]:
    """Best achievable squared error for fixed decay parameters.

    Beta coefficients are solved via OLS; decay parameters are searched non-linearly.
    Args:
        lambdas: Decay parameters to condition on.
        tau: Maturities in years.
        yields: Observed zero rates aligned with ``tau``.

    Returns:
        Tuple ``(sum_of_squared_residuals, betas)``. The SSR is ``inf`` when the
        decay parameters are outside the admissible range.
    """
    if any(lam <= 0 for lam in lambdas):
        return float("inf"), [0.0] * (len(lambdas) + 2)
    columns = _curve_design(tau, lambdas)
    betas = lstsq(columns, yields)
    ssr = 0.0
    for i, y in enumerate(yields):
        fit = sum(b * col[i] for b, col in zip(betas, columns, strict=True))
        ssr += (fit - y) ** 2
    return float(ssr), betas


def fit_yield_curve(
    maturities: Sequence[float],
    yields: Sequence[float],
    model: str = "svensson",
    decay_bounds: tuple[float, float] = CURVE_DECAY_BOUNDS,
    grid_points: int = CURVE_DECAY_GRID,
) -> CurveFit:
    """Fit a Nelson-Siegel or Svensson curve to observed zero rates.

    Beta coefficients are solved via OLS; decay parameters are searched over
    a geometric grid followed by Nelder-Mead simplex refinement.
    Args:
        maturities: Maturities in years, strictly positive.
        yields: Zero rates as decimals, aligned with ``maturities``.
        model: ``"nelson_siegel"`` or ``"svensson"``.
        decay_bounds: ``(low, high)`` search range in years for each decay
            parameter.
        grid_points: Grid resolution per decay parameter for the coarse pass.

    Returns:
        A :class:`CurveFit`, callable at arbitrary maturities.

    Raises:
        ValueError: If ``model`` is unknown, the inputs disagree in length, or
            there are fewer observations than free parameters.
    """
    if model not in ("nelson_siegel", "svensson"):
        raise ValueError(
            f"unknown model {model!r}; expected 'nelson_siegel' or 'svensson'"
        )
    tau = [float(t) for t in maturities]
    obs = [float(y) for y in yields]
    if len(tau) != len(obs):
        raise ValueError("maturities and yields must be 1-D and the same length")
    if not all(math.isfinite(t) for t in tau) or not all(math.isfinite(y) for y in obs):
        raise ValueError("maturities and yields must contain only finite values")
    if any(t <= 0 for t in tau):
        raise ValueError("maturities must be strictly positive")

    n_decay = 1 if model == "nelson_siegel" else 2
    n_params = n_decay + 2 + n_decay  # betas + decay parameters
    if len(tau) < n_params:
        raise ValueError(
            f"{model} has {n_params} parameters but only {len(tau)} observations"
        )

    low, high = decay_bounds
    if not math.isfinite(low) or not math.isfinite(high):
        raise ValueError("decay_bounds must contain only finite values")
    if not 0 < low < high:
        raise ValueError(f"decay_bounds must satisfy 0 < low < high, got {decay_bounds}")
    if grid_points < 2:
        raise ValueError("grid_points must be at least 2")
    ratio = high / low
    grid = [low * ratio ** (i / (grid_points - 1)) for i in range(grid_points)]
    grid[-1] = high

    # Each decay parameter's loadings are reused across the whole grid, so compute them once.
    loadings = {lam: _decay_factors(tau, lam) for lam in grid}
    ones = [1.0] * len(tau)

    def grid_ssr(lambdas: tuple[float, ...]) -> float:
        slope, curve1 = loadings[lambdas[0]]
        columns = [ones, slope, curve1]
        for lam in lambdas[1:]:
            columns.append(loadings[lam][1])
        betas = lstsq(columns, obs)
        total = 0.0
        for i, y in enumerate(obs):
            fit = sum(b * col[i] for b, col in zip(betas, columns, strict=True))
            total += (fit - y) ** 2
        return total

    best_ssr = float("inf")
    best_lambdas: tuple[float, ...] = (grid[0],) * n_decay
    if n_decay == 1:
        candidates = [(lam,) for lam in grid]
    else:
        # lambda1 == lambda2 makes the two curvature columns identical, so the
        # second hump carries no information; keep the pairs separated.
        candidates = [
            (short, long) for short in grid for long in grid if long > short * 1.05
        ]
    for lambdas in candidates:
        ssr = grid_ssr(lambdas)
        if ssr < best_ssr:
            best_ssr, best_lambdas = ssr, lambdas

    log_low, log_high = math.log(low), math.log(high)
    x_best, _ = nelder_mead(
        lambda p: _profiled_ssr([math.exp(v) for v in p], tau, obs)[0],
        [math.log(v) for v in best_lambdas],
        bounds=[(log_low, log_high)] * n_decay,
        xatol=1e-10,
        fatol=1e-18,
        maxiter=4000,
    )
    refined_lambdas = tuple(float(math.exp(v)) for v in x_best)
    refined_ssr, refined_betas = _profiled_ssr(refined_lambdas, tau, obs)
    if refined_ssr < best_ssr:
        best_ssr, best_lambdas = refined_ssr, refined_lambdas
        betas = refined_betas
    else:
        _, betas = _profiled_ssr(best_lambdas, tau, obs)

    params = tuple(float(b) for b in betas) + tuple(float(x) for x in best_lambdas)
    return CurveFit(
        model=model,
        params=params,
        rmse=float(math.sqrt(max(best_ssr, 0.0) / len(tau))),
    )
