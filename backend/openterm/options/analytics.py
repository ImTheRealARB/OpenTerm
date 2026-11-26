"""Phase 28 options analytics: pure maths, no I/O, no numpy (the server process may import it).

Everything here is a MODEL number, and the panels say so:
  * probabilities are risk-neutral lognormal (Black-Scholes) numbers from the contract's own IV, labelled MODEL PROBABILITY;
  * probability of touch uses the reflection rule of thumb (about twice the probability of finishing past the strike);
  * expected move shows BOTH the ATM straddle price and the IV x sqrt(T) one-sigma range, since they differ;
  * max pain is the strike where option holders, in total, would be paid least at expiry (a statistic, not a forecast).
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from itertools import pairwise

PROB_LABEL = "MODEL PROBABILITY, LOGNORMAL (RISK-NEUTRAL, FROM EACH CONTRACT'S IV)"
TOUCH_LABEL = "TOUCH = REFLECTION APPROXIMATION (ABOUT 2 x PROBABILITY OF FINISHING PAST THE STRIKE)"


def ncdf(x: float) -> float:
    """Standard normal cumulative distribution."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def d2(S: float, K: float, T: float, r: float, q: float, iv: float) -> float:
    return (math.log(S / K) + (r - q - 0.5 * iv * iv) * T) / (iv * math.sqrt(T))


def prob_itm(S: float, K: float, T: float, r: float, q: float, iv: float | None, kind: str) -> float | None:
    """Risk-neutral probability the option finishes in the money: N(d2) for a call, N(-d2) for a put. None without an IV."""
    if iv is None or iv <= 0 or T <= 0 or S <= 0 or K <= 0:
        return None
    z = d2(S, K, T, r, q, iv)
    return ncdf(z) if kind == "call" else ncdf(-z)


def prob_touch(p_itm: float | None, itm_now: bool) -> float | None:
    """Probability the price touches the strike before expiry: 1 when already through it, else about 2 x P(ITM), at most 1."""
    if p_itm is None:
        return None
    return 1.0 if itm_now else min(1.0, 2.0 * p_itm)


def breakeven(kind: str, K: float, premium: float | None) -> float | None:
    """Underlying price at expiry where a long position breaks even."""
    if premium is None:
        return None
    return K + premium if kind == "call" else K - premium


def extrinsic(kind: str, S: float, K: float, premium: float | None) -> float | None:
    """Time value = premium minus intrinsic value (never below 0 shown as is: a negative value means a stale quote)."""
    if premium is None:
        return None
    intrinsic = max(0.0, S - K) if kind == "call" else max(0.0, K - S)
    return premium - intrinsic


def prob_columns(rows: list[dict], kind: str, S: float, T: float, r: float, q: float) -> None:
    """Adds p_itm, p_otm, p_touch, breakeven, extrinsic to OMON chain rows in place (rows carry strike, iv, bid/ask/last)."""
    for row in rows:
        K = row["strike"]
        prem = _premium(row)
        p = prob_itm(S, K, T, r, q, row.get("iv"), kind)
        itm_now = K < S if kind == "call" else K > S
        row["p_itm"] = p
        row["p_otm"] = None if p is None else 1.0 - p
        row["p_touch"] = prob_touch(p, itm_now)
        row["breakeven"] = breakeven(kind, K, prem)
        row["extrinsic"] = extrinsic(kind, S, K, prem)


def _premium(row: dict) -> float | None:
    bid, ask = row.get("bid"), row.get("ask")
    if bid is not None and ask is not None and bid > 0 and ask >= bid:
        return (bid + ask) / 2.0
    last = row.get("last")
    return last if last is not None and last > 0 else None


# --- expected move, max pain, walls ---------------------------------------------------------------------------------------

def atm_strike(strikes: Iterable[float], S: float) -> float | None:
    ks = list(strikes)
    return min(ks, key=lambda k: (abs(k - S), k)) if ks else None


def expected_move(S: float, T: float, calls: list[dict], puts: list[dict], atm_iv: float | None) -> dict:
    """Both ways of stating the market's expected move to this expiry:
    straddle = call mid + put mid at the strike nearest spot; sigma = S x IV x sqrt(T) (one standard deviation)."""
    cby = {r["strike"]: _premium(r) for r in calls}
    pby = {r["strike"]: _premium(r) for r in puts}
    k = atm_strike(set(cby) & set(pby), S)
    straddle = None
    if k is not None and cby[k] is not None and pby[k] is not None:
        straddle = cby[k] + pby[k]
    sigma = S * atm_iv * math.sqrt(T) if atm_iv and T > 0 else None
    return {"strike": k, "straddle": straddle, "straddle_pct": straddle / S if straddle else None,
            "sigma": sigma, "sigma_pct": sigma / S if sigma else None}


def max_pain(calls: list[dict], puts: list[dict]) -> float | None:
    """The strike at which the total intrinsic value paid to all open contracts is smallest. None without open interest."""
    coi = [(r["strike"], r.get("oi") or 0) for r in calls]
    poi = [(r["strike"], r.get("oi") or 0) for r in puts]
    if not any(o for _, o in coi) and not any(o for _, o in poi):
        return None
    strikes = sorted({k for k, _ in coi} | {k for k, _ in poi})
    best, best_pay = None, math.inf
    for x in strikes:
        pay = sum(max(0.0, x - k) * o for k, o in coi) + sum(max(0.0, k - x) * o for k, o in poi)
        if pay < best_pay:
            best, best_pay = x, pay
    return best


def walls(rows: list[dict]) -> float | None:
    """The strike with the most open interest on one side (a call wall or put wall)."""
    best = max(rows, key=lambda r: r.get("oi") or 0, default=None)
    return best["strike"] if best and (best.get("oi") or 0) > 0 else None


def strike_profile(calls: list[dict], puts: list[dict]) -> list[dict]:
    """OI and volume by strike, both sides, for the strike chart table."""
    by: dict[float, dict] = {}
    for side, rows in (("c", calls), ("p", puts)):
        for r in rows:
            e = by.setdefault(r["strike"], {"strike": r["strike"], "c_oi": None, "p_oi": None, "c_vol": None, "p_vol": None})
            e[f"{side}_oi"] = r.get("oi")
            e[f"{side}_vol"] = r.get("volume")
    return [by[k] for k in sorted(by)]


# --- OSA risk profile -----------------------------------------------------------------------------------------------------

def leg_value(S: float, leg: dict, T: float, r: float, iv: float) -> float:
    """One leg's model value per unit at time-to-expiry T (intrinsic at T <= 0)."""
    from ..quant import options as qo

    kind = "call" if leg["type"] == "C" else "put"
    if T <= 1e-9:
        return max(0.0, S - leg["strike"]) if kind == "call" else max(0.0, leg["strike"] - S)
    return qo.bs_price(S, leg["strike"], T, r, iv, kind)


def pl_curves(legs: list[dict], premiums: list[float], grid: list[float], T: float, r: float, iv: float, mult: float,
              days_forward: float, iv_shift: float) -> list[dict]:
    """P/L at each grid spot TODAY (T), at a chosen date (T - days_forward/365) and at EXPIRY, with the IV shifted by
    `iv_shift` (absolute vol points as a fraction, e.g. +0.05) for the two curves before expiry. Also the net delta and gamma
    along the today curve (finite differences)."""
    from ..quant import options as qo

    t_mid = max(0.0, T - days_forward / 365.0)
    v = max(0.01, iv + iv_shift)
    cost = sum(x["qty"] * p for x, p in zip(legs, premiums, strict=True))
    out = []
    for S in grid:
        def book(t: float, S=S) -> float:
            return sum(x["qty"] * leg_value(S, x, t, r, v if t > 0 else iv) for x in legs)
        delta = gamma = 0.0
        for x in legs:
            kind = "call" if x["type"] == "C" else "put"
            g = qo.bs_greeks(S, x["strike"], T, r, v, kind)
            delta += x["qty"] * mult * g["delta"]
            gamma += x["qty"] * mult * g["gamma"]
        out.append({"spot": S, "today": (book(T) - cost) * mult, "at_date": (book(t_mid) - cost) * mult,
                    "expiry": (book(0.0) - cost) * mult, "delta": delta, "gamma": gamma})
    return out


def prob_profit(curve: list[dict], S0: float, T: float, r: float, iv: float) -> float | None:
    """Probability the EXPIRY P/L is above zero, under the lognormal model: sums the probability mass of grid cells whose
    expiry P/L is positive (cells bounded at the midpoints between grid spots; the ends run to 0 and infinity)."""
    if T <= 0 or iv <= 0 or len(curve) < 2:
        return None
    s = iv * math.sqrt(T)
    mu = math.log(S0) + (r - 0.5 * iv * iv) * T

    def cdf(x: float) -> float:
        return 0.0 if x <= 0 else ncdf((math.log(x) - mu) / s)

    spots = [c["spot"] for c in curve]
    edges = [0.0] + [(a + b) / 2 for a, b in pairwise(spots)] + [math.inf]
    total = 0.0
    for c, lo, hi in zip(curve, edges, edges[1:], strict=False):
        if c["expiry"] > 0:
            total += (1.0 if math.isinf(hi) else cdf(hi)) - cdf(lo)
    return total


# --- GP cone --------------------------------------------------------------------------------------------------------------

def cone(S: float, points: list[tuple[float, float, float]]) -> list[dict]:
    """[(expiry epoch, T years, ATM IV)] -> 1 and 2 standard-deviation lognormal price ranges per expiry (driftless)."""
    out = []
    for epoch, T, iv in sorted(points):
        if T <= 0 or iv is None or iv <= 0:
            continue
        s = iv * math.sqrt(T)
        out.append({"time": epoch, "t": T, "iv": iv, "lo1": S * math.exp(-s), "hi1": S * math.exp(s),
                    "lo2": S * math.exp(-2 * s), "hi2": S * math.exp(2 * s)})
    return out


# --- earnings move --------------------------------------------------------------------------------------------------------

def report_moves(dates: list[str], t: list[float], c: list[float]) -> list[dict]:
    """Report dates (YYYY-MM-DD, the day the earnings 8-K was FILED) + daily bars -> the absolute close-to-close move from the
    close before the filing day to the close of the next session after it (covers both before-open and after-close reports)."""
    from datetime import UTC, datetime

    days = [datetime.fromtimestamp(x, UTC).strftime("%Y-%m-%d") for x in t]
    out = []
    for d in dates:
        i = next((j for j, x in enumerate(days) if x >= d), None)
        if i is None or i == 0 or i + 1 >= len(c):
            continue
        before, after = c[i - 1], c[i + 1]
        out.append({"date": d, "before": before, "after": after, "move": after / before - 1.0})
    return out


# --- India OI buildup -----------------------------------------------------------------------------------------------------

def buildup(price_chg: float | None, oi_chg: float | None) -> str | None:
    """The standard F&O reading of one interval: price up + OI up = LONG BUILDUP, price down + OI up = SHORT BUILDUP,
    price up + OI down = SHORT COVERING, price down + OI down = LONG UNWINDING. Flat price or OI = None (no reading)."""
    if price_chg is None or oi_chg is None or price_chg == 0 or oi_chg == 0:
        return None
    if oi_chg > 0:
        return "LONG BUILDUP" if price_chg > 0 else "SHORT BUILDUP"
    return "SHORT COVERING" if price_chg > 0 else "LONG UNWINDING"


def oi_rows(t: list[float], c: list[float], oi: list[float | None]) -> list[dict]:
    """Candles with OI -> one row per interval with the change in price and OI and the buildup reading."""
    out = []
    for i in range(1, len(c)):
        dp = c[i] - c[i - 1]
        do = None if oi[i] is None or oi[i - 1] is None else oi[i] - oi[i - 1]
        out.append({"time": t[i], "close": c[i], "chg": dp, "oi": oi[i], "oi_chg": do, "reading": buildup(dp, do)})
    return out


# --- IV rank from recorded snapshots ----------------------------------------------------------------------------------------

def iv_rank(history: list[float], now: float | None) -> tuple[float | None, float | None]:
    """(IV rank, IV percentile) of `now` against recorded values: rank = (now - min) / (max - min); percentile = share of days
    below now. None with fewer than 2 recorded values."""
    vals = [v for v in history if v is not None]
    if now is None or len(vals) < 2:
        return None, None
    lo, hi = min(vals), max(vals)
    rank = (now - lo) / (hi - lo) if hi > lo else None
    pct = sum(1 for v in vals if v < now) / len(vals)
    return rank, pct


# --- portfolio Greeks -----------------------------------------------------------------------------------------------------

def beta_weighted_delta(delta_shares: float, spot: float, beta: float | None, index_level: float) -> float | None:
    """A position's delta in shares of the underlying -> equivalent shares of the index: delta x spot x beta / index level."""
    if beta is None or index_level <= 0:
        return None
    return delta_shares * spot * beta / index_level


def parse_occ(sym: str) -> dict | None:
    """OCC option symbol `AAPL260116C00200000` (root, YYMMDD, C/P, strike x 1000, 8 digits) -> parts, else None."""
    import re

    m = re.fullmatch(r"([A-Z.]{1,6})(\d{6})([CP])(\d{8})", sym.replace(" ", "").upper())
    if not m:
        return None
    root, ymd, cp, k = m.groups()
    return {"root": root, "expiry": f"20{ymd[:2]}-{ymd[2:4]}-{ymd[4:]}", "type": cp, "strike": int(k) / 1000.0}
