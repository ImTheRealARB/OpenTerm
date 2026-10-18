"""OV (pricer) and OSA (multi-leg payoff) table payloads (spec decisions G, J). Pure: the service gathers the market inputs and the
clock; nothing here does I/O. A missing input makes the model NOT RUNNABLE and the status lists every missing field; no opinion is
defaulted silently (the one convention that is, MULT=100 and COMM=0, is shown in the inputs table with its basis).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ..research.table import col, head, payload, section

TYPE_WORDS = {"C": "call", "CALL": "call", "P": "put", "PUT": "put"}
BARRIERS = {"UO": "up-and-out", "UI": "up-and-in", "DO": "down-and-out", "DI": "down-and-in"}
LEG = re.compile(r"^([+-]?)(\d+)([CP])(\d+(?:\.\d+)?)(?:@(\d+(?:\.\d+)?))?$", re.IGNORECASE)
GREEK_KEYS = ("delta", "gamma", "theta", "vega", "rho")


class ParamError(ValueError):
    """A typed argument is malformed (HTTP 400); the message is the usage line shown on screen."""


def num(params: dict, key: str, label: str | None = None) -> float | None:
    v = params.get(key)
    if v in (None, ""):
        return None
    try:
        x = float(str(v).strip())
    except ValueError:
        raise ParamError(f"{(label or key).upper()}={v}: NOT A NUMBER") from None
    if not math.isfinite(x):
        raise ParamError(f"{(label or key).upper()}={v}: NOT A FINITE NUMBER")
    return x


def pct(params: dict, key: str) -> float | None:
    x = num(params, key)
    return None if x is None else x / 100.0


def parse_expiry(params: dict) -> tuple[str | None, float | None]:
    """(EXP date text, typed T in years). EXP is YYYY-MM-DD; T is years."""
    exp = params.get("exp")
    if exp:
        try:
            datetime.strptime(str(exp).strip(), "%Y-%m-%d")
        except ValueError:
            raise ParamError("EXP: YYYY-MM-DD") from None
        exp = str(exp).strip()
    t = num(params, "t")
    if t is not None and t <= 0:
        raise ParamError("T MUST BE POSITIVE (YEARS)")
    return exp or None, t


def exp_epoch(exp: str) -> int:
    return int(datetime.strptime(exp, "%Y-%m-%d").replace(tzinfo=UTC).timestamp())


def parse_legs(text: str) -> list[dict]:
    """`+1C270@5.2,-1C290` -> [{qty, type, strike, premium|None}]. Anything else is a 400, never a guess."""
    legs = []
    for tok in [t.strip() for t in str(text).split(",") if t.strip()]:
        m = LEG.match(tok)
        if not m:
            raise ParamError(f"BAD LEG '{tok}'. USE [+-]QTY C|P STRIKE [@PREMIUM], E.G. +1C270@5.2,-1C290")
        sign, qty, kind, strike, prem = m.groups()
        q = int(qty) * (-1 if sign == "-" else 1)
        if q == 0 or float(strike) <= 0:
            raise ParamError(f"BAD LEG '{tok}': QTY AND STRIKE MUST BE NON-ZERO / POSITIVE")
        legs.append({"qty": q, "type": kind.upper(), "strike": float(strike), "premium": float(prem) if prem else None})
    if not legs:
        raise ParamError("LEGS: AT LEAST ONE LEG")
    return legs


def parse_strategy(text: str) -> list[dict]:
    """`BULLCALL,270,290` | `BEARPUT,l,u` | `STRADDLE,k` | `STRANGLE,put,call` | `CONDOR,pw,pb,cb,cw`."""
    parts = [p.strip() for p in str(text).split(",") if p.strip()]
    name, args = (parts[0].upper() if parts else ""), parts[1:]
    try:
        k = [float(a) for a in args]
    except ValueError:
        raise ParamError("STRAT: STRIKES MUST BE NUMBERS") from None
    shapes = {"BULLCALL": 2, "BEARPUT": 2, "STRADDLE": 1, "STRANGLE": 2, "CONDOR": 4}
    if name not in shapes or len(k) != shapes[name]:
        raise ParamError("STRAT: BULLCALL,LOW,HIGH | BEARPUT,LOW,HIGH | STRADDLE,K | STRANGLE,PUT,CALL | CONDOR,PUTWING,PUTBODY,CALLBODY,CALLWING")
    if name in ("BULLCALL", "BEARPUT") and not k[0] < k[1]:
        raise ParamError("STRAT: LOW STRIKE MUST BE BELOW HIGH STRIKE")
    if name == "CONDOR" and not k[0] < k[1] < k[2] < k[3]:
        raise ParamError("STRAT: CONDOR STRIKES MUST NEST: PUTWING < PUTBODY < CALLBODY < CALLWING")
    mk = lambda q, t, s: {"qty": q, "type": t, "strike": s, "premium": None}
    if name == "BULLCALL":
        return [mk(1, "C", k[0]), mk(-1, "C", k[1])]
    if name == "BEARPUT":
        return [mk(-1, "P", k[0]), mk(1, "P", k[1])]
    if name == "STRADDLE":
        return [mk(1, "C", k[0]), mk(1, "P", k[0])]
    if name == "STRANGLE":
        return [mk(1, "P", k[0]), mk(1, "C", k[1])]
    return [mk(1, "P", k[0]), mk(-1, "P", k[1]), mk(-1, "C", k[2]), mk(1, "C", k[3])]


# --- OV -----------------------------------------------------------------------------------------------------------------

@dataclass
class OvInputs:
    spot: float | None = None
    spot_basis: str = ""
    k: float | None = None
    kind: str | None = None          # call | put
    T: float | None = None
    t_basis: str = ""
    iv: float | None = None
    iv_basis: str = ""
    r: float | None = None
    r_basis: str = ""
    q: float | None = None
    q_basis: str = ""
    price: float | None = None
    steps: int = 400
    heston: dict = field(default_factory=dict)
    barrier: dict = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)


def pctxt(v: float | None, digits: int = 4) -> str:
    return "-" if v is None else f"{v * 100:.{digits}f}%"


def ov_models(i: OvInputs) -> tuple[list[dict], list[dict]]:
    """(price rows, IV-solve rows). Imported lazily so the server does not load the quant package until OV is used."""
    from ..quant import binomial as qb
    from ..quant import heston as qh
    from ..quant import options as qo

    S, K, T, r, sig, q, kind = i.spot, i.k, i.T, i.r, i.iv, i.q, i.kind
    rows = []
    g = qo.bs_greeks(S, K, T, r, sig, kind, q)
    rows.append({"model": "BS", "price": qo.bs_price(S, K, T, r, sig, kind, q), **g,
                 "note": "BLACK-SCHOLES-MERTON, EUROPEAN, CONTINUOUS DIVIDEND YIELD"})
    for label, american in (("BIN EU", False), ("BIN AM", True)):
        px = qb.binomial_price(S, K, T, r, sig, kind, american=american, steps=i.steps, q=q)
        gb = qb.binomial_greeks(S, K, T, r, sig, kind, american=american, steps=i.steps, q=q)
        rows.append({"model": label, "price": px, **gb,
                     "note": f"COX-ROSS-RUBINSTEIN, {i.steps} STEPS, " + ("AMERICAN EXERCISE" if american else "EUROPEAN")})
    if i.heston:
        h = i.heston
        px = qh.heston_price(S, K, T, r, h["v0"], h["kappa"], h["theta"], h["sigmav"], h["rho"], kind, q)
        fe = qh.heston_feller_condition(h["kappa"], h["theta"], h["sigmav"])
        rows.append({"model": "HESTON", "price": px, **dict.fromkeys(GREEK_KEYS), "note":
                     f"HESTON (LEWIS INTEGRAL), EUROPEAN; FELLER RATIO {fe['feller_ratio']:.2f} " + ("OK" if fe["is_satisfied"] else "VIOLATED")})
    if i.barrier:
        b = i.barrier
        px = qo.barrier_option_price(S, K, b["h"], T, r, sig, b["type"], kind, q, b["rebate"])
        gb = qo.barrier_greeks(S, K, b["h"], T, r, sig, b["type"], kind, q, b["rebate"])
        rows.append({"model": "BARRIER", "price": px, **gb, "note":
                     f"{b['type'].upper()} AT {b['h']:g}, REBATE {b['rebate']:g}, CONTINUOUS MONITORING (REINER-RUBINSTEIN); GREEKS BY FINITE DIFFERENCE"})
    solve = []
    if i.price is not None:
        try:
            iv = qo.implied_volatility(i.price, S, K, T, r, kind, q)
        except ValueError as e:
            solve.append({"price": i.price, "iv": None, "status": f"NO IMPLIED VOL: {e}"})
        else:
            if math.isnan(iv):
                solve.append({"price": i.price, "iv": None, "status": "NO IMPLIED VOL: THE PRICE DOES NOT PIN A VOLATILITY (VEGA TOO SMALL)"})
            else:
                solve.append({"price": i.price, "iv": iv, "status": "SOLVED"})
    return rows, solve


PRICE_COLUMNS = [
    col("model", "MODEL"), col("price", "PRICE", "num4"), col("delta", "DELTA", "num4"), col("gamma", "GAMMA", "num4"),
    col("theta", "THETA", "num4"), col("vega", "VEGA", "num4"), col("rho", "RHO", "num4"), col("note", "NOTE"),
]
INPUT_COLUMNS = [col("name", "INPUT"), col("value", "VALUE"), col("basis", "BASIS")]


def ov_payload(symbol: str, i: OvInputs, source: str) -> dict:
    ins = [
        {"name": "SPOT", "value": "-" if i.spot is None else f"{i.spot:,.2f}", "basis": i.spot_basis or "-"},
        {"name": "K", "value": "-" if i.k is None else f"{i.k:g}", "basis": "typed on the command line" if i.k is not None else "MISSING"},
        {"name": "TYPE", "value": (i.kind or "-").upper(), "basis": "typed on the command line" if i.kind else "MISSING"},
        {"name": "T (YEARS)", "value": "-" if i.T is None else f"{i.T:.4f}", "basis": i.t_basis or "MISSING"},
        {"name": "IV", "value": pctxt(i.iv, 2), "basis": i.iv_basis or "MISSING"},
        {"name": "R", "value": pctxt(i.r), "basis": i.r_basis or "MISSING", "rate": i.r},
        {"name": "Q", "value": pctxt(i.q), "basis": i.q_basis or "MISSING", "rate": i.q},
    ]
    status = "RUNNABLE" if not i.missing else "NOT RUNNABLE: " + ", ".join(i.missing)
    rows, solve = ov_models(i) if not i.missing else ([], [])
    sections = [
        section("inputs", "INPUTS", INPUT_COLUMNS, ins),
        section("price", "MODELS", PRICE_COLUMNS, rows),
    ]
    if i.price is not None:
        sections.append(section("ivsolve", "IMPLIED VOL FROM PRICE", [col("price", "PRICE", "price"), col("iv", "IV", "pct"),
                                                                        col("status", "STATUS")], solve))
    head_rows = [head("SPOT", "-" if i.spot is None else f"{i.spot:,.2f}", i.spot)]
    notes = ["EVERY INPUT SHOWS WHERE IT CAME FROM; IV IS AN OPINION AND IS NEVER DEFAULTED",
             "THETA PER CALENDAR DAY; VEGA AND RHO PER 1 POINT. HESTON AND BARRIER RUN ONLY WITH THEIR INPUTS (V0 KAPPA THETA SIGMAV RHO | H BARR)"]
    return payload(symbol, f"OV {symbol}", head_rows, sections, notes, source, status=status)


# --- OSA ----------------------------------------------------------------------------------------------------------------

def spot_grid(strikes: list[float], spot: float, points: int = 41) -> list[float]:
    lo = min([*strikes, spot]) * 0.8
    hi = max([*strikes, spot]) * 1.2
    return [lo + (hi - lo) * j / (points - 1) for j in range(points)]


def osa_payload(symbol: str, legs: list[dict], spot: float, spot_basis: str, T: float | None, iv: float | None, iv_basis: str,
                r: float | None, r_basis: str, mult: float, comm: float, source: str, missing: list[str]) -> dict:
    status = "RUNNABLE" if not missing else "NOT RUNNABLE: " + ", ".join(missing)
    inputs = [
        {"name": "SPOT", "value": f"{spot:,.2f}", "basis": spot_basis},
        {"name": "T (YEARS)", "value": "-" if T is None else f"{T:.4f}", "basis": "MISSING" if T is None else "from EXP/T"},
        {"name": "IV", "value": pctxt(iv, 2), "basis": iv_basis or "MISSING"},
        {"name": "R", "value": pctxt(r), "basis": r_basis or "MISSING", "rate": r},
        {"name": "MULT", "value": f"{mult:g}", "basis": "typed" if mult != 100 else "default: US equity contract size 100"},
        {"name": "COMM", "value": f"{comm * 100:g}%", "basis": "typed" if comm else "default: none (OSA ignores dividend yield, as the Vibe payoff does)"},
    ]
    leg_cols = [col("qty", "QTY", "int"), col("type", "TYPE"), col("strike", "STRIKE", "price"), col("premium", "PREMIUM", "price"),
                col("delta", "DELTA", "num4"), col("gamma", "GAMMA", "num4"), col("theta", "THETA", "num4"), col("vega", "VEGA", "num4"),
                col("rho", "RHO", "num4")]
    empty = [section("inputs", "INPUTS", INPUT_COLUMNS, inputs),
             section("legs", "LEGS", leg_cols, [{"qty": x["qty"], "type": x["type"], "strike": x["strike"], "premium": x["premium"]} for x in legs])]
    if missing:
        return payload(symbol, f"OSA {symbol}", [head("SPOT", f"{spot:,.2f}", spot)], empty, [], source, status=status)

    from ..quant import options as qo
    from ..quant import payoff as qp

    objs = [qp.OptionLeg("call" if x["type"] == "C" else "put", x["strike"], x["qty"], x["premium"]) for x in legs]
    grid = spot_grid([x["strike"] for x in legs], spot)
    rep = qp.expiry_payoff(objs, grid, entry_spot=spot, time_to_expiry=T, rate=r, iv=iv, multiplier=mult, commission_rate=comm)
    premiums = [x["premium"] if x["premium"] is not None else qo.bs_price(spot, x["strike"], T, r, iv, o.option_type)
                for x, o in zip(legs, objs, strict=True)]
    net_greeks = dict.fromkeys(GREEK_KEYS, 0.0)
    leg_rows = []
    for x, o, prem in zip(legs, objs, premiums, strict=True):
        g = qo.bs_greeks(spot, x["strike"], T, r, iv, o.option_type)
        leg_rows.append({"qty": x["qty"], "type": x["type"], "strike": x["strike"], "premium": prem, **g})
        for k in GREEK_KEYS:
            net_greeks[k] += x["qty"] * mult * g[k]
    iv_axis = [iv * f for f in (0.6, 0.8, 1.0, 1.2, 1.4)]
    spots = [spot * f for f in (0.8, 0.9, 0.95, 1.0, 1.05, 1.1, 1.2)]
    scen = qp.scenario_grid(objs, spots, iv_axis, entry_spot=spot, time_to_expiry=T, rate=r, entry_iv=iv, multiplier=mult,
                            commission_rate=comm)
    z = [list(row) for row in scen]   # Vibe: shape (len(iv_values), len(spot_grid))

    def money_head(label: str, v: float) -> dict:
        return head(label, "UNBOUNDED" if math.isinf(v) else f"{v:,.2f}", None if math.isinf(v) else v)

    debit = rep.net_premium >= 0
    be = rep.breakevens
    headline = [
        head("SPOT", f"{spot:,.2f}", spot),
        head("NET DEBIT" if debit else "NET CREDIT", f"{abs(rep.net_premium):,.2f}", rep.net_premium),
        money_head("MAX PROFIT", rep.max_profit), money_head("MAX LOSS", rep.max_loss),
        head("BREAKEVEN", ", ".join(f"{b:,.2f}" for b in be) if be else "NONE", be[0] if be else None),
        head("ENTRY COST", f"{rep.entry_cost:,.2f}", rep.entry_cost),
    ]
    sections = [
        section("legs", "LEGS", leg_cols, leg_rows),
        section("payoff", "PAYOFF AT EXPIRY", [col("spot", "SPOT", "price"), col("pnl", "P&L", "money")],
                [{"spot": s, "pnl": p} for s, p in zip(rep.spot_grid, rep.payoff, strict=True)]),
        section("net", "NET GREEKS (x QTY x MULT)", [col("name", "GREEK"), col("value", "VALUE", "num4")],
                [{"name": k.upper(), "value": v} for k, v in net_greeks.items()]),
        section("inputs", "INPUTS", INPUT_COLUMNS, inputs),
    ]
    chart = {"id": "payoff", "title": "P&L AT EXPIRY", "xlabel": "SPOT", "ylabel": "P&L",
             "series": [{"name": "P&L", "points": [[s, p] for s, p in zip(rep.spot_grid, rep.payoff, strict=True)]}],
             "marks": [{"x": spot, "label": "SPOT"}, *({"x": b, "label": "BE"} for b in be)]}
    heat = {"id": "scenario", "title": "MARK-TO-MARKET P&L: SPOT (ACROSS) x IV (DOWN), TIME UNCHANGED", "xlabel": "SPOT", "ylabel": "IV",
            "x": [round(s, 2) for s in spots], "y": [f"{v * 100:.1f}%" for v in iv_axis], "z": z, "unit": "money"}
    notes = ["PREMIUMS WITHOUT @PREMIUM ARE BLACK-SCHOLES AT THE ENTRY IV; PAYOFF IS AT EXPIRY, EUROPEAN, NO EXIT FEES",
             "HISTORICAL OR HYPOTHETICAL PAYOFF, NOT A FORECAST"]
    return payload(symbol, f"OSA {symbol}", headline, sections, notes, source, status=status, charts=[chart], heat=heat)
