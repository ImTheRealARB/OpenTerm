"""Credit primitives: flat-hazard CDS valuation, hazard/survival conversion and expected loss.

Ported from HKUDS/Vibe-Trading @ d0db2e3, agent/src/quantlib/credit.py (MIT; see THIRD_PARTY.md).
Changes: only ``cds_price``, ``hazard_rate_to_survival_probability``, ``survival_probability_to_hazard_rate``, ``expected_loss``
and the ``_require_finite`` helper they use were ported (the Altman, Merton, KMV and spread-analytics parts were left out).
numpy and scipy removed: ``np.exp`` / ``np.log`` / ``np.ceil`` -> ``math``, the premium-date grid is a plain list.

All rates and ratios are decimals unless a name ends in ``_bp``.
"""

from __future__ import annotations

import math

__all__ = [
    "cds_price",
    "expected_loss",
    "hazard_rate_to_survival_probability",
    "survival_probability_to_hazard_rate",
]


def _require_finite(value: float, name: str) -> float:
    """Check a value is a finite number, refusing NaN and infinity.

    Args:
        value: The candidate value.
        name: Field name for the error message.

    Returns:
        ``value`` unchanged (its int/float type is preserved).

    Raises:
        ValueError: If the value is not a finite number. A non-finite input
            here would otherwise flow through the range guards (which are all
            false for NaN) and surface as a NaN score, probability or zone.
    """
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    return value


def hazard_rate_to_survival_probability(hazard_rate: float, tenor_years: float) -> float:
    """Convert a constant hazard rate lambda to cumulative survival probability Q(T) = exp(-lambda * T).

    Args:
        hazard_rate: Annualised default intensity / hazard rate lambda >= 0.
        tenor_years: Time horizon in years >= 0.

    Returns:
        Survival probability in [0.0, 1.0].

    Raises:
        ValueError: If hazard_rate or tenor_years is negative.
    """
    hazard_rate = _require_finite(hazard_rate, "hazard_rate")
    tenor_years = _require_finite(tenor_years, "tenor_years")
    if hazard_rate < 0.0 or tenor_years < 0.0:
        raise ValueError(f"hazard_rate and tenor_years must be non-negative, got {hazard_rate}, {tenor_years}")
    return float(math.exp(-hazard_rate * tenor_years))


def survival_probability_to_hazard_rate(survival_prob: float, tenor_years: float) -> float:
    """Convert a survival probability Q(T) to implied constant hazard rate lambda = -ln(Q(T)) / T.

    Args:
        survival_prob: Survival probability in (0.0, 1.0].
        tenor_years: Time horizon in years > 0.

    Returns:
        Annualised hazard rate lambda.

    Raises:
        ValueError: If survival_prob is not in (0.0, 1.0] or tenor_years <= 0.
    """
    survival_prob = _require_finite(survival_prob, "survival_prob")
    tenor_years = _require_finite(tenor_years, "tenor_years")
    if survival_prob <= 0.0 or survival_prob > 1.0:
        raise ValueError(f"survival_prob must be in (0.0, 1.0], got {survival_prob}")
    if tenor_years <= 0.0:
        raise ValueError(f"tenor_years must be strictly positive, got {tenor_years}")
    return float(-math.log(survival_prob) / tenor_years)


def cds_price(
    spread_bps: float,
    recovery_rate: float = 0.40,
    tenor_years: float = 5.0,
    risk_free_rate: float = 0.03,
    coupon_bps: float = 100.0,
    notional: float = 10_000_000.0,
    payment_frequency: int = 4,
) -> dict:
    """Flat-hazard single-name Credit Default Swap (CDS) valuation engine.

    Computes the implied hazard rate, survival probability curve, Risky Present Value
    of a Basis Point (RPV01), protection leg PV, premium leg PV, fair par spread,
    and mark-to-market (MTM) upfront cash payment.

    The hazard rate comes from the credit triangle (``lambda = s / (1 - R)``) rather
    than being bootstrapped by root-finding the way the ISDA Standard Model does, so
    ``par_spread_bps`` -- recomputed from the discretised legs -- lands near, not
    exactly on, the quoted ``spread_bps`` (~0.4% apart for a 5y investment-grade
    name). Value the contract against ``par_spread_bps``; read ``hazard_rate`` as the
    triangle approximation it is.

    Args:
        spread_bps: Market quoted par CDS spread in basis points (e.g. 150.0 for 150 bps).
        recovery_rate: Expected recovery rate on default in [0.0, 1.0) (standard senior unsecured = 0.40).
        tenor_years: Contract maturity in years > 0 (standard benchmark = 5.0 years).
        risk_free_rate: Continuously compounded annual risk-free discount rate.
        coupon_bps: Fixed running coupon in basis points (standard 100 bps IG, 500 bps HY).
        notional: Contract notional amount in currency units.
        payment_frequency: Premium coupon payment frequency per year (standard quarterly = 4).

    Returns:
        dict with keys:
            * ``hazard_rate`` (float): Implied constant hazard rate (default intensity).
            * ``survival_probability`` (float): Probability of survival to maturity Q(T).
            * ``default_probability`` (float): Cumulative probability of default 1 - Q(T).
            * ``rpv01`` (float): Risky annuity (present value of unit running spread per dollar notional).
            * ``protection_leg_pv`` (float): Present value of default protection per dollar notional.
            * ``premium_leg_pv`` (float): Present value of fixed running premium per dollar notional.
            * ``par_spread_bps`` (float): Model par spread in basis points.
            * ``upfront_pct`` (float): Upfront payment as decimal fraction of notional.
            * ``upfront_amount`` (float): Net upfront cash payment (positive = buyer pays seller).
            * ``buyer_mtm`` (float): Mark-to-market value for the protection buyer.

    Raises:
        ValueError: If spread_bps < 0, recovery_rate not in [0, 1), tenor_years <= 0, or notional <= 0.
    """
    spread_bps = _require_finite(spread_bps, "spread_bps")
    recovery_rate = _require_finite(recovery_rate, "recovery_rate")
    tenor_years = _require_finite(tenor_years, "tenor_years")
    risk_free_rate = _require_finite(risk_free_rate, "risk_free_rate")
    coupon_bps = _require_finite(coupon_bps, "coupon_bps")
    notional = _require_finite(notional, "notional")
    payment_frequency = _require_finite(payment_frequency, "payment_frequency")
    if spread_bps < 0.0:
        raise ValueError(f"spread_bps must be non-negative, got {spread_bps}")
    if not (0.0 <= recovery_rate < 1.0):
        raise ValueError(f"recovery_rate must be in [0.0, 1.0), got {recovery_rate}")
    if tenor_years <= 0.0:
        raise ValueError(f"tenor_years must be strictly positive, got {tenor_years}")
    if notional <= 0.0:
        raise ValueError(f"notional must be strictly positive, got {notional}")
    if payment_frequency <= 0:
        raise ValueError(f"payment_frequency must be positive, got {payment_frequency}")

    s_dec = spread_bps / 10_000.0
    c_dec = coupon_bps / 10_000.0
    lgd = 1.0 - recovery_rate

    # Implied hazard rate lambda ≈ s / LGD
    lambda_hazard = float(s_dec / lgd) if lgd > 0 else 0.0

    n_periods = max(1, math.ceil(tenor_years * payment_frequency))
    # Keep regular premium dates fixed at the requested frequency; only the
    # last period is a stub when maturity falls between coupon dates.
    t_grid = [k / payment_frequency for k in range(1, n_periods)] + [tenor_years]
    t_prev = [0.0] + t_grid[:-1]
    dts = [b - a for a, b in zip(t_prev, t_grid, strict=True)]
    t_mid = [0.5 * (a + b) for a, b in zip(t_prev, t_grid, strict=True)]

    # Survival probabilities Q(t) = exp(-lambda * t)
    q_grid = [math.exp(-lambda_hazard * t) for t in t_grid]
    q_prev = [1.0] + q_grid[:-1]

    # Discount factors D(t) = exp(-r * t)
    df_grid = [math.exp(-risk_free_rate * t) for t in t_grid]
    df_mid = [math.exp(-risk_free_rate * t) for t in t_mid]

    # Premium leg / RPV01: sum(dt_i * D(t_i) * Q(t_i)) + accrual on default
    premium_cashflow = math.fsum(dt * d * q for dt, d, q in zip(dts, df_grid, q_grid, strict=True))
    accrual_cashflow = math.fsum(
        0.5 * dt * d * (qp - q) for dt, d, qp, q in zip(dts, df_mid, q_prev, q_grid, strict=True)
    )
    rpv01 = float(premium_cashflow + accrual_cashflow)

    # Protection leg: sum( LGD * D(t_mid) * (Q(t_{i-1}) - Q(t_i)) )
    prot_leg_pv = float(lgd * math.fsum(d * (qp - q) for d, qp, q in zip(df_mid, q_prev, q_grid, strict=True)))

    # Par spread in bps
    par_spread = float((prot_leg_pv / rpv01) * 10_000.0) if rpv01 > 0 else spread_bps

    # Premium leg PV for running coupon c
    prem_leg_pv = float(c_dec * rpv01)

    # Upfront percentage and amount
    upfront_pct = float(prot_leg_pv - prem_leg_pv)
    upfront_amt = float(upfront_pct * notional)

    survival_T = float(math.exp(-lambda_hazard * tenor_years))
    default_prob_T = float(1.0 - survival_T)

    return {
        "hazard_rate": lambda_hazard,
        "survival_probability": survival_T,
        "default_probability": default_prob_T,
        "rpv01": rpv01,
        "protection_leg_pv": prot_leg_pv,
        "premium_leg_pv": prem_leg_pv,
        "par_spread_bps": par_spread,
        "upfront_pct": upfront_pct,
        "upfront_amount": upfront_amt,
        "buyer_mtm": upfront_amt,
    }


def expected_loss(ead: float, pd: float, lgd: float) -> float:
    """Compute regulatory Expected Loss (EL = EAD * PD * LGD).

    Args:
        ead: Exposure at Default in currency units >= 0.
        pd: Probability of Default in [0.0, 1.0].
        lgd: Loss Given Default in [0.0, 1.0].

    Returns:
        Expected loss amount in currency units.

    Raises:
        ValueError: If ead < 0, pd not in [0, 1], or lgd not in [0, 1].
    """
    ead = _require_finite(ead, "ead")
    pd = _require_finite(pd, "pd")
    lgd = _require_finite(lgd, "lgd")
    if ead < 0.0:
        raise ValueError(f"ead must be non-negative, got {ead}")
    if not (0.0 <= pd <= 1.0):
        raise ValueError(f"pd must be in [0.0, 1.0], got {pd}")
    if not (0.0 <= lgd <= 1.0):
        raise ValueError(f"lgd must be in [0.0, 1.0], got {lgd}")
    return float(ead * pd * lgd)
