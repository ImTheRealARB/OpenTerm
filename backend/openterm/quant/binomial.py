"""Cox-Ross-Rubinstein binomial lattice for European and American options (calls and puts, continuous dividend yield).

Written for OpenTerm; no third-party source (the method is Cox, Ross and Rubinstein 1979, and the numbers in the tests are Hull's).

Conventions match :mod:`openterm.quant.options`: ``T`` in years, ``r`` and ``q`` continuously compounded, ``theta`` per calendar
day, ``vega`` and ``rho`` per 1 percentage point. The lattice has ``u = exp(sigma * sqrt(dt))``, ``d = 1 / u`` and risk-neutral
up-probability ``p = (exp((r - q) dt) - d) / (u - d)``; an American option is compared with its exercise value at every node.
"""

from __future__ import annotations

import math

from openterm.quant.options import normalise_option_type

__all__ = ["binomial_greeks", "binomial_price"]


def _lattice(
    S: float, K: float, T: float, r: float, sigma: float, is_call: bool, american: bool, steps: int, q: float
) -> tuple[float, list[float], list[float], float]:
    """Backward induction. Returns ``(price, values at step 1, values at step 2, dt)`` (the last two are empty below 2 steps)."""
    dt = T / steps
    u = math.exp(sigma * math.sqrt(dt))
    d = 1.0 / u
    growth = math.exp((r - q) * dt)
    p = (growth - d) / (u - d)
    if not 0.0 <= p <= 1.0:
        raise ValueError(
            f"{steps} steps is too few for sigma={sigma}, r={r}, q={q}, T={T}: the risk-neutral probability is {p:.4f}"
        )
    disc = math.exp(-r * dt)
    pu, pd = disc * p, disc * (1.0 - p)
    phi = 1.0 if is_call else -1.0
    # spot at step i, node j (j ups): S * u**(2j - i); a power table keeps the induction free of repeated exponentiation
    pw = [u**k for k in range(-steps, steps + 1)]

    def spot(i: int, j: int) -> float:
        return S * pw[2 * j - i + steps]

    vals = [max(phi * (spot(steps, j) - K), 0.0) for j in range(steps + 1)]
    v1: list[float] = []
    v2: list[float] = []
    for i in range(steps - 1, -1, -1):
        nxt = [pu * vals[j + 1] + pd * vals[j] for j in range(i + 1)]
        if american:
            nxt = [max(v, phi * (spot(i, j) - K)) for j, v in enumerate(nxt)]
        vals = nxt
        if i == 2:
            v2 = vals
        elif i == 1:
            v1 = vals
    return vals[0], v1, v2, dt


def _validate(S: float, K: float, T: float, sigma: float, steps: int) -> None:
    for name, value in (("S", S), ("K", K), ("T", T), ("sigma", sigma)):
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite, got {value}")
    if isinstance(steps, bool) or not isinstance(steps, int) or steps < 1:
        raise ValueError(f"steps must be a positive integer, got {steps!r}")


def binomial_price(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: str = "call",
    american: bool = False,
    steps: int = 400,
    q: float = 0.0,
) -> float:
    """Price a European or American option on a Cox-Ross-Rubinstein lattice.

    Args:
        S: Underlying spot price.
        K: Strike price.
        T: Time to expiry in years.
        r: Risk-free rate, continuously compounded.
        sigma: Annualised volatility.
        option_type: ``"call"`` or ``"put"`` (the aliases of :func:`openterm.quant.options.normalise_option_type`).
        american: Allow exercise at every node.
        steps: Number of time steps (the European price converges to Black-Scholes at order ``1 / steps``).
        q: Continuous dividend yield.

    Returns:
        The option price. At or past expiry (or a non-positive spot or strike) the immediate intrinsic value.

    Raises:
        ValueError: If the option type is unknown, ``steps`` is not a positive integer, ``sigma`` is not positive for a live
            option, or the lattice is too coarse for the inputs (risk-neutral probability outside [0, 1]).
    """
    kind = normalise_option_type(option_type)
    _validate(S, K, T, sigma, steps)
    is_call = kind == "call"
    if T <= 0 or S <= 0 or K <= 0:
        return float(max(S - K, 0.0) if is_call else max(K - S, 0.0))
    if sigma <= 0:
        raise ValueError(f"sigma must be positive for a lattice price, got {sigma}")
    return float(_lattice(S, K, T, r, sigma, is_call, american, steps, q)[0])


def binomial_greeks(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: str = "call",
    american: bool = False,
    steps: int = 400,
    q: float = 0.0,
) -> dict[str, float]:
    """Delta, gamma, theta, vega and rho from the lattice and by repricing.

    Delta and gamma come from the nodes at steps 1 and 2, theta from the centre node at step 2 against the root
    (``(f(2,1) - f(0,0)) / (2 dt)``, then per calendar day), all of the same tree. Vega and rho reprice with a central bump
    (volatility bumped by 1 point, the rate by 1 basis point) and are scaled to 1 percentage point, like
    :func:`openterm.quant.options.bs_greeks`.

    Raises:
        ValueError: As :func:`binomial_price`, and if ``steps`` is below 2.
    """
    kind = normalise_option_type(option_type)
    _validate(S, K, T, sigma, steps)
    if steps < 2:
        raise ValueError("steps must be at least 2 to read delta and gamma from the lattice")
    is_call = kind == "call"
    if T <= 0 or S <= 0 or K <= 0:
        if S == K:
            delta = 0.5 if is_call else -0.5
        elif is_call:
            delta = 1.0 if S > K else 0.0
        else:
            delta = -1.0 if S < K else 0.0
        return {"delta": delta, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}
    if sigma <= 0:
        raise ValueError(f"sigma must be positive for a lattice price, got {sigma}")

    price, v1, v2, dt = _lattice(S, K, T, r, sigma, is_call, american, steps, q)
    u = math.exp(sigma * math.sqrt(dt))
    s_up, s_dn = S * u, S / u
    delta = (v1[1] - v1[0]) / (s_up - s_dn)
    s_uu, s_dd = S * u * u, S / (u * u)
    h = 0.5 * (s_uu - s_dd)
    gamma = ((v2[2] - v2[1]) / (s_uu - S) - (v2[1] - v2[0]) / (S - s_dd)) / h
    theta = (v2[1] - price) / (2.0 * dt) / 365.0

    dvol = min(0.01, sigma / 2.0)
    up = _lattice(S, K, T, r, sigma + dvol, is_call, american, steps, q)[0]
    down = _lattice(S, K, T, r, sigma - dvol, is_call, american, steps, q)[0]
    vega = (up - down) / (2.0 * dvol) * 0.01
    dr = 1e-4
    r_up = _lattice(S, K, T, r + dr, sigma, is_call, american, steps, q)[0]
    r_dn = _lattice(S, K, T, r - dr, sigma, is_call, american, steps, q)[0]
    rho = (r_up - r_dn) / (2.0 * dr) * 0.01
    return {"delta": float(delta), "gamma": float(gamma), "theta": float(theta), "vega": float(vega), "rho": float(rho)}
