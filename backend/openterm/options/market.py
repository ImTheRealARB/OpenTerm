"""Market inputs for the derivative functions, derived from data we already have. Pure."""

from __future__ import annotations

import math


def interp(xs: list[float], ys: list[float], x: float) -> float:
    """Linear interpolation, flat beyond the ends. xs ascending."""
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for i in range(1, len(xs)):
        if x <= xs[i]:
            w = (x - xs[i - 1]) / (xs[i] - xs[i - 1])
            return ys[i - 1] * (1 - w) + ys[i] * w
    return ys[-1]


def par_to_continuous(par_percent: float) -> float:
    """A Treasury par yield (bond-equivalent, semi-annual) in percent -> a continuously compounded rate as a ratio."""
    return 2.0 * math.log1p(par_percent / 200.0)


def treasury_rate(curve: dict, years: float) -> tuple[float, float]:
    """(continuous rate as a ratio, the interpolated par yield in percent) of the Treasury curve payload at `years`."""
    pts = [(y, v) for y, v in zip(curve["years"], curve["yields"], strict=True) if v is not None]
    pts.sort()
    par = interp([p[0] for p in pts], [p[1] for p in pts], years)
    return par_to_continuous(par), par
