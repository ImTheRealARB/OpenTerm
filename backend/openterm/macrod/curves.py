"""Pure rates maths for Phase 30: FWCV (bootstrap a zero curve from the Treasury par curve, then forward rates) and WIRP odds
(hike / hold / cut probabilities per FOMC meeting from the futures-implied path). No network, no numpy.

FWCV, step by step (what "bootstrapping" means):
  1. The Treasury publishes PAR yields: the coupon at which a bond of that maturity would trade at 100. They are semiannual
     bond-equivalent rates, quoted at 1M..30Y. We interpolate them linearly onto a half-year grid (0.5, 1.0, ... 30 years).
  2. Up to 1 year the bills pay no coupon, so the discount factor is D(t) = 1 / (1 + y/2)^(2t).
  3. Beyond 1 year, a par bond with coupon c (per year, paid every half year) is worth exactly 1:
        1 = c/2 * (D(0.5) + D(1.0) + ... + D(t)) + D(t)
     Every D before t is already known, so D(t) = (1 - c/2 * sum of earlier D) / (1 + c/2). That is the bootstrap.
  4. A zero rate is the yield of D(t) alone: z = 2 * (D^(-1/(2t)) - 1). A forward rate from a to b is the rate locked in today
     for borrowing between a and b: f = 2 * ((D(a) / D(b))^(1/(2(b-a))) - 1). "5y5y" = the 5-year rate starting in 5 years.
  Linear interpolation of par yields is the simplest honest choice; it makes the forward curve look kinked at the quoted tenors.

WIRP odds, the standard futures method:
  The implied path gives the expected policy rate after each meeting. The change at one meeting, D bp, is read as a mix of
  whole 25 bp moves: n = floor(|D| / 25) moves for sure plus one more with probability (|D| - 25n) / 25. Example: -10 bp means a
  40% chance of a 25 bp cut and a 60% chance of no change. Chaining the meetings gives a probability for each target level.
  This assumes moves come in 25 bp steps and ignores term premium: it is market-implied, NOT a forecast.
"""

from __future__ import annotations

import math

STEP_BP = 25.0
FORWARDS = (("1y1y", 1, 2), ("1y2y", 1, 3), ("2y1y", 2, 3), ("2y3y", 2, 5), ("3y2y", 3, 5), ("5y5y", 5, 10), ("10y10y", 10, 20), ("20y10y", 20, 30))


def _interp(xs: list[float], ys: list[float], x: float) -> float:
    if x <= xs[0]:
        return ys[0]
    for i in range(1, len(xs)):
        if x <= xs[i]:
            w = (x - xs[i - 1]) / (xs[i] - xs[i - 1])
            return ys[i - 1] + w * (ys[i] - ys[i - 1])
    return ys[-1]


def bootstrap(years: list[float], par_pct: list[float | None]) -> list[dict]:
    """Half-year grid out to the longest quoted tenor: [{t, par, df, zero}] with rates in percent. Missing tenors are skipped."""
    pts = sorted((t, y) for t, y in zip(years, par_pct, strict=True) if y is not None)
    if len(pts) < 3:
        raise ValueError("NEED AT LEAST THREE PAR YIELDS TO BOOTSTRAP")
    xs, ys = [p[0] for p in pts], [p[1] / 100.0 for p in pts]
    grid = [0.5 * k for k in range(1, int(xs[-1] * 2 + 1e-9) + 1)]
    out: list[dict] = []
    dfs: list[float] = []
    for t in grid:
        c = _interp(xs, ys, t)
        if t <= 1.0:
            df = (1 + c / 2) ** (-2 * t)
        else:
            df = (1 - c / 2 * sum(dfs)) / (1 + c / 2)
        if df <= 0:
            raise ValueError(f"BOOTSTRAP BROKE AT {t:g}Y (DISCOUNT FACTOR <= 0)")
        dfs.append(df)
        out.append({"t": t, "par": c * 100, "df": df, "zero": 2 * (df ** (-1 / (2 * t)) - 1) * 100})
    return out


def forward(zero_curve: list[dict], a: float, b: float) -> float | None:
    """Forward rate in percent (semiannual compounding) between years a and b; a = 0 means spot. None if b is off the curve."""
    by_t = {round(p["t"], 2): p["df"] for p in zero_curve}
    da = 1.0 if a == 0 else by_t.get(round(a, 2))
    db = by_t.get(round(b, 2))
    if da is None or db is None:
        return None
    return 2 * ((da / db) ** (1 / (2 * (b - a))) - 1) * 100


def forward_table(zero_curve: list[dict]) -> list[dict]:
    return [{"name": n, "start": a, "end": b, "rate": forward(zero_curve, a, b), "spot_end": forward(zero_curve, 0, b)} for n, a, b in FORWARDS]


def one_year_forwards(zero_curve: list[dict]) -> list[tuple[float, float | None]]:
    """The 1-year rate starting at each whole year: (start, f(start, start+1))."""
    last = zero_curve[-1]["t"]
    return [(float(s), forward(zero_curve, s, s + 1)) for s in range(int(last)) if s + 1 <= last]


# --- WIRP odds ----------------------------------------------------------------------------------------------------------------


def meeting_odds(change_bp: float) -> dict[int, float]:
    """One meeting's expected change (bp) as a mix of whole 25 bp steps: {steps: probability}; steps < 0 are cuts."""
    sign = -1 if change_bp < 0 else 1
    a = abs(change_bp) / STEP_BP
    n = math.floor(a + 1e-9)
    frac = a - n
    if frac < 1e-9:
        return {sign * n: 1.0}
    return {sign * n: 1.0 - frac, sign * (n + 1): frac}


def odds_table(path: list[dict]) -> list[dict]:
    """Per meeting: P(cut), P(hold), P(hike) at that meeting, the most likely target change since today (in steps of 25 bp) and its
    probability. `path` rows carry `meeting` and `change_bp` (from derivs.fut_tables.wirp_path)."""
    dist: dict[int, float] = {0: 1.0}  # cumulative steps since today -> probability
    rows = []
    for r in path:
        step = meeting_odds(r["change_bp"])
        nxt: dict[int, float] = {}
        for level, p in dist.items():
            for s, q in step.items():
                nxt[level + s] = nxt.get(level + s, 0.0) + p * q
        dist = nxt
        cut = sum(q for s, q in step.items() if s < 0)
        hike = sum(q for s, q in step.items() if s > 0)
        mode = max(dist.items(), key=lambda kv: (kv[1], -abs(kv[0])))
        rows.append({"meeting": r["meeting"], "p_cut": cut, "p_hold": 1.0 - cut - hike, "p_hike": hike,
                     "big_move": sum(q for s, q in step.items() if abs(s) >= 2),
                     "mode_bp": mode[0] * STEP_BP, "mode_p": mode[1], "cum_bp": r.get("cum_bp")})
    return rows
