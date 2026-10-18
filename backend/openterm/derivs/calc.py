"""YAS, SWPM, CDSW and FXFA: calculator math and table payloads (spec decisions K, L). Pure: the service gathers market inputs and the
clock. The quant package is imported inside functions so the server import stays light. A missing input makes the model NOT RUNNABLE and
the status lists every missing field; nothing is defaulted silently (a convention that is, FREQ and the day count, is shown with its basis).
"""

from __future__ import annotations

import calendar
import math
from dataclasses import dataclass, field
from datetime import date
from itertools import pairwise

from ..research.table import col, head, payload, section

INPUT_COLUMNS = [col("name", "INPUT"), col("value", "VALUE"), col("basis", "BASIS")]
SUMMARY_COLUMNS = [col("name", "MEASURE"), col("value", "VALUE", "num4"), col("unit", "UNIT")]


class CalcError(ValueError):
    """A typed argument is malformed or the model cannot price it (HTTP 400); the message is shown on screen."""


def num(params: dict, key: str, label: str | None = None) -> float | None:
    v = params.get(key)
    if v in (None, ""):
        return None
    try:
        x = float(str(v).strip())
    except ValueError:
        raise CalcError(f"{(label or key).upper()}={v}: NOT A NUMBER") from None
    if not math.isfinite(x):
        raise CalcError(f"{(label or key).upper()}={v}: NOT A FINITE NUMBER")
    return x


def parse_date(text: str | None, label: str) -> date | None:
    if not text:
        return None
    try:
        return date.fromisoformat(str(text).strip())
    except ValueError:
        raise CalcError(f"{label}: YYYY-MM-DD") from None


def not_runnable(missing: list[str]) -> str:
    return "NOT RUNNABLE: MISSING " + ", ".join(missing)


# --- YAS --------------------------------------------------------------------------------------------------------------

DAY_COUNTS = ("ACT/ACT", "30/360")
KEY_TENORS = (1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 20.0, 30.0)


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.year * 12 + d.month - 1 + n, 12)
    return date(y, m + 1, min(d.day, calendar.monthrange(y, m + 1)[1]))


def days_between(a: date, b: date, conv: str) -> float:
    if conv == "30/360":
        from ..quant.fixedincome import year_fraction

        return round(year_fraction(a, b, "30/360") * 360.0)
    return float((b - a).days)


@dataclass
class Bond:
    cpn: float          # decimal
    mat: date
    freq: int
    settle: date
    face: float
    conv: str
    last: date = field(init=False)
    nxt: date = field(init=False)
    dates: list[date] = field(init=False)   # remaining coupon dates, ascending
    w: float = field(init=False)            # periods from settlement to the next coupon
    accrued: float = field(init=False)

    def __post_init__(self) -> None:
        step = 12 // self.freq
        sched, k = [], 0
        while True:
            d = add_months(self.mat, -step * k)
            sched.append(d)
            if d <= self.settle:
                break
            k += 1
        self.last = sched[-1]
        self.dates = sorted(d for d in sched if d > self.settle)
        self.nxt = self.dates[0]
        period = days_between(self.last, self.nxt, self.conv)
        self.w = days_between(self.settle, self.nxt, self.conv) / period
        self.accrued = self.face * self.cpn / self.freq * days_between(self.last, self.settle, self.conv) / period

    def flows(self) -> list[float]:
        c = self.face * self.cpn / self.freq
        return [c + (self.face if i == len(self.dates) - 1 else 0.0) for i in range(len(self.dates))]

    def times(self) -> list[float]:
        """Years from settlement to each cash flow (periods / freq)."""
        return [(self.w + k) / self.freq for k in range(len(self.dates))]

    def dirty(self, y: float) -> float:
        base = 1.0 + y / self.freq
        return math.fsum(cf / base ** (self.w + k) for k, cf in enumerate(self.flows()))


def yas_measures(b: Bond, y: float) -> dict:
    """Durations, convexity and key-rate durations at yield `y` (decimal, periodic compounding) for a settlement between coupons."""
    base = 1.0 + y / b.freq
    cfs, ts = b.flows(), b.times()
    pvs = [cf / base ** (b.freq * t) for cf, t in zip(cfs, ts, strict=True)]
    dirty = math.fsum(pvs)
    mac = math.fsum(t * p for t, p in zip(ts, pvs, strict=True)) / dirty
    mod = mac / base
    conv = math.fsum(t * (t + 1.0 / b.freq) * p for t, p in zip(ts, pvs, strict=True)) / dirty / base**2
    krd = dict.fromkeys(KEY_TENORS, 0.0)
    for t, p in zip(ts, pvs, strict=True):
        contrib = t / base * p / dirty
        if t <= KEY_TENORS[0]:
            krd[KEY_TENORS[0]] += contrib
        elif t >= KEY_TENORS[-1]:
            krd[KEY_TENORS[-1]] += contrib
        else:
            hi = next(k for k in KEY_TENORS if k >= t)
            lo = KEY_TENORS[KEY_TENORS.index(hi) - 1]
            wr = (t - lo) / (hi - lo)
            krd[lo] += contrib * (1 - wr)
            krd[hi] += contrib * wr
    return {"mac": mac, "mod": mod, "convexity": conv, "krd": krd, "pvs": pvs, "dirty": dirty}


def solve_yield(b: Bond, dirty_target: float) -> float:
    from ..quant.numerics import brent

    try:
        return float(brent(lambda y: b.dirty(y) - dirty_target, -0.5, 5.0, xtol=1e-14))
    except ValueError as e:
        raise CalcError(f"NO YIELD REPRICES THIS BOND TO {dirty_target - b.accrued:.4f} (CLEAN)") from e


def yas_inputs_rows(cpn, mat, freq, settle, face, conv, px, yld, settle_basis) -> list[dict]:
    return [
        {"name": "CPN", "value": "-" if cpn is None else f"{cpn * 100:.4f}%", "basis": "typed" if cpn is not None else "MISSING"},
        {"name": "MAT", "value": str(mat) if mat else "-", "basis": "typed" if mat else "MISSING"},
        {"name": "FREQ", "value": str(freq), "basis": "typed" if freq != 2 else "default: 2 (US Treasury convention)"},
        {"name": "SETTLE", "value": str(settle), "basis": settle_basis},
        {"name": "DAYS", "value": conv, "basis": "typed" if conv != "ACT/ACT" else "default: ACT/ACT (US Treasury convention)"},
        {"name": "FACE", "value": f"{face:g}", "basis": "price is per this face" if face != 100 else "default: price per 100"},
        {"name": "PX (CLEAN)", "value": "-" if px is None else f"{px:.6f}", "basis": "typed" if px is not None else "-"},
        {"name": "YLD", "value": "-" if yld is None else f"{yld * 100:.6f}%", "basis": "typed" if yld is not None else "-"},
    ]


def yas_payload(cpn, mat, freq, settle, face, conv, px, yld, settle_basis, missing: list[str]) -> dict:
    ins = section("inputs", "INPUTS", INPUT_COLUMNS, yas_inputs_rows(cpn, mat, freq, settle, face, conv, px, yld, settle_basis))
    title = "YAS BOND YIELD ANALYSIS"
    notes = ["NO BOND DATABASE IS FREE: THE BOND IS DESCRIBED BY ITS TERMS. SETTLE DEFAULTS TO TODAY (A FACT, NOT AN OPINION)",
             "YIELD IS A PERIODIC-COMPOUNDING (STREET) YIELD; FIRST COUPON DISCOUNTED FOR THE FRACTION OF A PERIOD TO SETTLEMENT",
             f"ACCRUED AND THE STUB USE {conv} DAYS WITHIN THE COUPON PERIOD. COMPUTED HERE, NOT A DEALER OR EXCHANGE YIELD",
             "KEY-RATE DURATIONS ALLOCATE EACH CASH FLOW'S MODIFIED DURATION TO THE NEAREST KEY TENORS (TRIANGULAR); THEY SUM TO MODIFIED DURATION"]
    if missing or (px is None and yld is None):
        miss = list(missing)
        if px is None and yld is None:
            miss.append("PX OR YLD")
        return payload("YAS", title, [], [ins], notes, "typed bond terms", status=not_runnable(miss))
    b = Bond(cpn, mat, freq, settle, face, conv)
    if yld is not None:
        y = yld
        m = yas_measures(b, y)
        dirty = m["dirty"]
        clean = dirty - b.accrued
    else:
        clean = px
        dirty = clean + b.accrued
        y = solve_yield(b, dirty)
        m = yas_measures(b, y)
    dv01_1m = m["mod"] * dirty / face * 1_000_000.0 * 1e-4
    cur_yield = cpn * face / clean * 100.0 if clean else None
    summary = [
        {"name": "YIELD", "value": y * 100.0, "unit": "% (PERIODIC, FREQ/YR)"},
        {"name": "CLEAN", "value": clean, "unit": f"PER {face:g}"},
        {"name": "ACCRUED", "value": b.accrued, "unit": f"PER {face:g}"},
        {"name": "DIRTY", "value": dirty, "unit": f"PER {face:g}"},
        {"name": "MAC DURATION", "value": m["mac"], "unit": "YEARS"},
        {"name": "MOD DURATION", "value": m["mod"], "unit": "YEARS"},
        {"name": "CONVEXITY", "value": m["convexity"], "unit": "YEARS^2"},
        {"name": "DV01 PER 1M", "value": dv01_1m, "unit": "CASH PER 1M PAR, 1 BP"},
        {"name": "CURRENT YIELD", "value": cur_yield, "unit": "% (COUPON / CLEAN)"},
        {"name": "DAYS ACCRUED", "value": days_between(b.last, settle, conv), "unit": conv},
    ]
    cfs = b.flows()
    flows = []
    for k, (d, cf, t, p) in enumerate(zip(b.dates, cfs, b.times(), m["pvs"], strict=True)):
        principal = face if k == len(b.dates) - 1 else 0.0
        flows.append({"n": k + 1, "date": d.isoformat(), "coupon": cf - principal, "principal": principal, "total": cf, "t": t,
                      "df": p / cf if cf else None, "pv": p})
    krd = [{"tenor": f"{t:g}Y", "krd": v, "dv01": v * dirty / face * 1_000_000.0 * 1e-4} for t, v in m["krd"].items()]
    sections = [
        ins,
        section("summary", "SUMMARY", SUMMARY_COLUMNS, summary, "YIELD IN PERCENT; DURATIONS IN YEARS; DV01 FOR 1,000,000 PAR"),
        section("krd", "KEY-RATE DURATIONS", [col("tenor", "TENOR"), col("krd", "KRD", "num4"), col("dv01", "DV01 PER 1M", "num")], krd),
        section("cashflows", "CASH FLOWS", [col("n", "#", "int"), col("date", "DATE", "date"), col("coupon", "COUPON", "num4"),
                                           col("principal", "PRINCIPAL", "num4"), col("total", "TOTAL", "num4"), col("t", "YEARS", "num4"),
                                           col("df", "DF", "num4"), col("pv", "PV", "num4")], flows),
    ]
    head_rows = [head("CPN", f"{cpn * 100:.3f}%", cpn), head("MAT", str(mat)), head("YIELD", f"{y * 100:.4f}%", y * 100.0),
                 head("CLEAN", f"{clean:.4f}", clean), head("SETTLE", str(settle))]
    chart = {"id": "pv", "title": "PRESENT VALUE OF EACH CASH FLOW", "xlabel": "YEARS", "ylabel": "PV",
             "series": [{"name": "PV", "points": [[round(f["t"], 4), f["pv"]] for f in flows]}]}
    return payload("YAS", title, head_rows, sections, notes, "typed bond terms", status="RUNNABLE", charts=[chart])


# --- SWPM -------------------------------------------------------------------------------------------------------------

def swpm_payload(n, fixed, tenor, freq, direction, curve_label, curve_basis, curve_note, res: dict | None, missing: list[str],
                 freq_basis: str, source: str) -> dict:
    ins = section("inputs", "INPUTS", INPUT_COLUMNS, [
        {"name": "N", "value": "-" if n is None else f"{n:,.0f}", "basis": "typed" if n is not None else "MISSING"},
        {"name": "FIXED", "value": "-" if fixed is None else f"{fixed * 100:.4f}%", "basis": "typed" if fixed is not None else "MISSING"},
        {"name": "TENOR", "value": "-" if tenor is None else f"{tenor:g}Y", "basis": "typed" if tenor is not None else "MISSING"},
        {"name": "FREQ", "value": str(freq), "basis": freq_basis},
        {"name": "DIR", "value": direction or "-", "basis": "typed (PAY = pay fixed, receive floating)" if direction else "MISSING"},
        {"name": "CURVE", "value": curve_label, "basis": curve_basis},
    ])
    notes = ["SINGLE-CURVE VALUATION: THE SAME CURVE DISCOUNTS AND PROJECTS THE FLOATING LEG (NO OIS/SOFR BASIS), PERIODS ARE 1/FREQ",
             "DV01 IS THE CHANGE IN MTM FOR A +1 BP PARALLEL SHIFT OF THE ZERO CURVE. COMPUTED HERE, NOT A DEALER QUOTE"]
    if curve_note:
        notes.insert(0, curve_note)
    if missing or res is None:
        return payload("SWPM", "SWPM VANILLA SWAP", [], [ins], notes, source, status=not_runnable(missing))
    summary = [
        {"name": "PAR RATE", "value": res["par_rate"] * 100.0, "unit": "% (FIXED RATE AT WHICH MTM = 0)"},
        {"name": "PV FIXED", "value": res["pv_fixed_leg"], "unit": "CASH (UNSIGNED)"},
        {"name": "PV FLOAT", "value": res["pv_float_leg"], "unit": "CASH (UNSIGNED)"},
        {"name": "MTM", "value": res["mtm"], "unit": "CASH, HOLDER'S VALUE (" + ("PAY FIXED" if direction == "PAY" else "RECEIVE FIXED") + ")"},
        {"name": "DV01", "value": res["dv01"], "unit": "CASH PER +1 BP"},
        {"name": "FIXED - PAR", "value": (fixed - res["par_rate"]) * 1e4, "unit": "BP"},
    ]
    flows = [{"n": c["n"], "t": c["t"], "df": c["df"], "fixed": c["fixed"], "float": c["float_estimate"], "net": c["net"], "pv": c["pv"]}
             for c in res["cashflows"]]
    sections = [
        ins,
        section("summary", "SUMMARY", SUMMARY_COLUMNS, summary),
        section("cashflows", "CASH FLOWS", [col("n", "#", "int"), col("t", "YEARS", "num4"), col("df", "DF", "num4"),
                                           col("fixed", "FIXED", "num"), col("float", "FLOAT (PROJECTED)", "num"),
                                           col("net", "NET (HOLDER)", "num"), col("pv", "PV", "num")], flows),
    ]
    head_rows = [head("NOTIONAL", f"{n:,.0f}", n), head("FIXED", f"{fixed * 100:.4f}%", fixed * 100.0),
                 head("PAR RATE", f"{res['par_rate'] * 100:.4f}%", res["par_rate"] * 100.0),
                 head("MTM", f"{res['mtm']:,.0f}", res["mtm"])]
    chart = {"id": "df", "title": "DISCOUNT FACTORS ON THE SWAP DATES", "xlabel": "YEARS", "ylabel": "DF",
             "series": [{"name": "DF", "points": [[c["t"], c["df"]] for c in flows]}]}
    return payload("SWPM", "SWPM VANILLA SWAP", head_rows, sections, notes, source, status="RUNNABLE", charts=[chart])


# --- CDSW -------------------------------------------------------------------------------------------------------------

def cdsw_payload(spread, rec, tenor, rf, coupon, notional, freq, freq_basis, res: dict | None, missing: list[str]) -> dict:
    ins = section("inputs", "INPUTS", INPUT_COLUMNS, [
        {"name": "SPREAD", "value": "-" if spread is None else f"{spread:g} bp", "basis": "typed" if spread is not None else "MISSING"},
        {"name": "REC", "value": "-" if rec is None else f"{rec * 100:g}%", "basis": "typed" if rec is not None else "MISSING"},
        {"name": "TENOR", "value": "-" if tenor is None else f"{tenor:g}Y", "basis": "typed" if tenor is not None else "MISSING"},
        {"name": "RF", "value": "-" if rf is None else f"{rf * 100:g}%", "basis": "typed (continuous)" if rf is not None else "MISSING"},
        {"name": "COUPON", "value": "-" if coupon is None else f"{coupon:g} bp", "basis": "typed" if coupon is not None else "MISSING"},
        {"name": "N", "value": "-" if notional is None else f"{notional:,.0f}", "basis": "typed" if notional is not None else "MISSING"},
        {"name": "FREQ", "value": str(freq), "basis": freq_basis},
    ])
    notes = [("FLAT HAZARD, CREDIT TRIANGLE (HAZARD = SPREAD / (1 - RECOVERY)), NOT THE ISDA STANDARD MODEL: THE MODEL PAR SPREAD LANDS NEAR, "
              "NOT ON, THE QUOTE; VALUE AGAINST PAR SPREAD BPS"),
             "USER INPUTS ONLY: NO MARKET CDS QUOTES, NO CURVE. UPFRONT > 0 MEANS THE PROTECTION BUYER PAYS",
             "ENGINE: Vibe-Trading quantlib credit.cds_price (MIT), CROSS-CHECKED AGAINST ITS OWN NUMBERS"]
    if missing or res is None:
        return payload("CDSW", "CDSW CDS VALUATION", [], [ins], notes, "typed inputs", status=not_runnable(missing))
    summary = [
        {"name": "PAR SPREAD BPS", "value": res["par_spread_bps"], "unit": "BP (MODEL)"},
        {"name": "UPFRONT AMOUNT", "value": res["upfront_amount"], "unit": "CASH, BUYER PAYS IF > 0"},
        {"name": "UPFRONT PCT", "value": res["upfront_pct"] * 100.0, "unit": "% OF NOTIONAL"},
        {"name": "RPV01", "value": res["rpv01"], "unit": "PER UNIT NOTIONAL"},
        {"name": "HAZARD RATE", "value": res["hazard_rate"], "unit": "PER YEAR"},
        {"name": "SURVIVAL PROB", "value": res["survival_probability"], "unit": "TO MATURITY"},
        {"name": "DEFAULT PROB", "value": res["default_probability"], "unit": "TO MATURITY"},
        {"name": "PROTECTION LEG PV", "value": res["protection_leg_pv"], "unit": "PER UNIT NOTIONAL"},
        {"name": "PREMIUM LEG PV", "value": res["premium_leg_pv"], "unit": "PER UNIT NOTIONAL"},
        {"name": "BUYER MTM", "value": res["buyer_mtm"], "unit": "CASH"},
    ]
    sections = [ins, section("summary", "SUMMARY", SUMMARY_COLUMNS, summary)]
    head_rows = [head("PAR SPREAD", f"{res['par_spread_bps']:.2f} bp", res["par_spread_bps"]),
                 head("UPFRONT", f"{res['upfront_amount']:,.0f}", res["upfront_amount"]),
                 head("HAZARD", f"{res['hazard_rate'] * 100:.3f}%", res["hazard_rate"] * 100.0)]
    lam = res["hazard_rate"]
    steps = 20
    chart = {"id": "survival", "title": "SURVIVAL PROBABILITY (FLAT HAZARD)", "xlabel": "YEARS", "ylabel": "Q(t)",
             "series": [{"name": "Q", "points": [[round(tenor * i / steps, 4), math.exp(-lam * tenor * i / steps)]
                                                  for i in range(steps + 1)]}]}
    return payload("CDSW", "CDSW CDS VALUATION", head_rows, sections, notes, "typed inputs", status="RUNNABLE", charts=[chart])


# --- FXFA -------------------------------------------------------------------------------------------------------------

TENOR_DAYS = {"1W": 7, "2W": 14, "1M": 30, "2M": 61, "3M": 91, "6M": 182, "9M": 273, "1Y": 365}
DEFAULT_TENORS = ("1W", "1M", "3M", "6M", "1Y")


def interp_short(points: list[tuple[float, float]], years: float) -> tuple[float, bool]:
    """(rate percent, flat) at `years` from curve points, flat beyond the ends; `flat` is True when the tenor lies off the curve."""
    pts = sorted(points)
    if years <= pts[0][0]:
        return pts[0][1], years < pts[0][0] - 1e-9
    if years >= pts[-1][0]:
        return pts[-1][1], years > pts[-1][0] + 1e-9
    for (x0, y0), (x1, y1) in pairwise(pts):
        if x0 <= years <= x1:
            return y0 + (y1 - y0) * (years - x0) / (x1 - x0), False
    return pts[-1][1], True


def fxfa_payload(pair: str, base: str, quote: str, spot: float | None, spot_basis: str, tenors: list[str],
                 r_base: dict, r_quote: dict, missing: list[str], source: str) -> dict:
    """`r_base` / `r_quote`: {"points": [(years, percent)] | None, "typed": percent | None, "basis": str, "date": str | None}."""
    def rate_at(r: dict, years: float) -> tuple[float, bool]:
        if r.get("typed") is not None:
            return r["typed"], False
        return interp_short(r["points"], years)

    def one_year(r: dict) -> float | None:
        if r.get("typed") is not None:
            return r["typed"]
        return interp_short(r["points"], 1.0)[0] if r.get("points") else None

    inputs = [
        {"name": f"{base} RATE", "rate": one_year(r_base), "basis": r_base["basis"]},
        {"name": f"{quote} RATE", "rate": one_year(r_quote), "basis": r_quote["basis"]},
        {"name": "SPOT", "rate": spot, "basis": spot_basis},
    ]
    notes = ["COVERED INTEREST PARITY ESTIMATE, NOT A DEALER QUOTE: FORWARD = SPOT x (1 + R_QUOTE x D/360) / (1 + R_BASE x D/360)",
             ("RATES ARE GOVERNMENT YIELDS OR TYPED, NOT INTERBANK DEPOSIT RATES; ACT/360 SIMPLE INTEREST FOR BOTH CURRENCIES; "
              "R_BASE = FIRST CURRENCY, R_QUOTE = SECOND (R1, R2 WHEN TYPED, IN PERCENT)"),
             "RATE SHOWN IN THE INPUTS IS THE 1Y POINT; EACH TENOR USES ITS OWN INTERPOLATED RATE"]
    ins = section("inputs", "INPUTS", [col("name", "INPUT"), col("rate", "VALUE (% / SPOT)", "num4"), col("basis", "BASIS")], inputs)
    if missing or spot is None:
        return payload(pair, f"FXFA {pair}", [], [ins], notes, source, status=not_runnable(missing or ["SPOT"]))
    pip = 100.0 if quote == "JPY" else 10000.0
    rows, flat_notes = [], []
    for t in tenors:
        d = TENOR_DAYS[t]
        rb, fb = rate_at(r_base, d / 365.0)
        rq, fq = rate_at(r_quote, d / 365.0)
        fwd = spot * (1 + rq / 100.0 * d / 360.0) / (1 + rb / 100.0 * d / 360.0)
        rows.append({"tenor": t, "days": d, "r_base": rb, "r_quote": rq, "forward": fwd, "points": (fwd - spot) * pip,
                     "annual": (fwd / spot - 1.0) * 365.0 / d})
        if fb or fq:
            flat_notes.append(t)
    if flat_notes:
        notes.append("TENORS BELOW THE SHORTEST CURVE POINT USE THAT POINT FLAT: " + " ".join(flat_notes))
    sections = [ins, section("forwards", "FORWARDS", [
        col("tenor", "TENOR"), col("days", "DAYS", "int"), col("r_base", f"{base} RATE %", "num4"), col("r_quote", f"{quote} RATE %", "num4"),
        col("forward", "FORWARD", "num4"), col("points", "POINTS", "num"), col("annual", "ANN. PREMIUM", "pct")], rows,
        f"POINTS IN {'100THS' if quote == 'JPY' else 'PIPS (1E-4)'} OF {quote}")]
    head_rows = [head("PAIR", f"{base}/{quote}"), head("SPOT", f"{spot:.4f}", spot)]
    chart = {"id": "fwd", "title": f"{pair} FORWARD POINTS", "xlabel": "DAYS", "ylabel": "POINTS",
             "series": [{"name": "POINTS", "points": [[r["days"], r["points"]] for r in rows]}]}
    return payload(pair, f"FXFA {pair}", head_rows, sections, notes, source, status="RUNNABLE", charts=[chart])


def tenors_of(text: str | None) -> list[str]:
    if not text:
        return list(DEFAULT_TENORS)
    out = [t.strip().upper() for t in text.replace(" ", ",").split(",") if t.strip()]
    bad = [t for t in out if t not in TENOR_DAYS]
    if bad or not out:
        raise CalcError("TENORS: " + " ".join(TENOR_DAYS))
    return sorted(dict.fromkeys(out), key=lambda t: TENOR_DAYS[t])


def split_pair(raw: str) -> tuple[str, str]:
    s = "".join(ch for ch in raw.upper() if ch.isalpha())
    if s.endswith("X") and len(s) == 7:   # EURUSD=X
        s = s[:6]
    if len(s) != 6:
        raise CalcError("PAIR: SIX LETTERS, E.G. EURUSD")
    return s[:3], s[3:]

