"""SCORE (Phase 29): textbook formula scores from SEC filings. Pure maths, no I/O, unit-tested.

Every function takes plain numbers (dollars, shares) and returns a dict:
    {"score": float | None, "zone": str | None, "formula": str, "inputs": [(label, value)], "missing": [names]}
`score` is None when an input the formula needs is missing; `missing` then says which, so the panel can print
"NOT COMPUTABLE: <names>" instead of guessing. These are FORMULA SCORES, NOT RATINGS (the panel says so).

`cur` is the latest fiscal year, `prev` the year before; both are dicts keyed like the FA rows (sec_parse.ROWS keys plus
sec_parse.EXTRA_ROWS keys), e.g. {"revenue": 3.9e11, "total_assets": 3.6e11, ...}.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from statistics import NormalDist

_N = NormalDist()  # standard normal: cdf for Merton


def _need(d: dict, keys: Iterable[str], tag: str = "") -> list[str]:
    """Names of the keys that are missing (None or absent) in d, suffixed with `tag` (" (PRIOR YEAR)")."""
    return [f"{k}{tag}" for k in keys if d.get(k) is None]


def _out(score, zone, formula, inputs, missing) -> dict:
    return {"score": None if missing else score, "zone": None if missing else zone, "formula": formula,
            "inputs": inputs, "missing": missing}


ZERO_DENOMINATOR = "A DENOMINATOR IS ZERO (REVENUE, ASSETS, LIABILITIES ...)"


def _zero_safe(formula: str, calc):
    """Run `calc()` (the formula's arithmetic, returns the `_out` dict). A company with a zero in a denominator (a
    pre-revenue biotech has no revenue or gross profit; a shell has no assets) has NO score: the result says why instead of
    the ZeroDivisionError becoming an HTTP 500 on the panel."""
    try:
        return calc()
    except ZeroDivisionError:
        return _out(None, None, formula, [], [ZERO_DENOMINATOR])


# --- Altman Z (1968, public manufacturers) and Z'' (1995, non-manufacturers) -------------------------------------
def altman_z(cur: dict, market_cap: float | None) -> dict:
    """Z = 1.2 X1 + 1.4 X2 + 3.3 X3 + 0.6 X4 + 1.0 X5. Safe > 2.99, distress < 1.81."""
    formula = "1.2 WC/TA + 1.4 RE/TA + 3.3 EBIT/TA + 0.6 MVE/TL + 1.0 SALES/TA"
    missing = _need(cur, ("current_assets", "current_liabilities", "retained_earnings", "operating_income", "total_assets",
                          "total_liabilities", "revenue"))
    if market_cap is None:
        missing.append("market_cap")
    if missing:
        return _out(None, None, formula, [], missing)
    ta, tl = cur["total_assets"], cur["total_liabilities"]

    def calc() -> dict:
        x1 = (cur["current_assets"] - cur["current_liabilities"]) / ta
        x2 = cur["retained_earnings"] / ta
        x3 = cur["operating_income"] / ta  # EBIT ~ operating income (the filing's own line)
        x4 = market_cap / tl
        x5 = cur["revenue"] / ta
        z = 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * x4 + 1.0 * x5
        zone = "SAFE" if z > 2.99 else "GREY" if z >= 1.81 else "DISTRESS"
        return _out(z, zone, formula, [("X1 WC/TA", x1), ("X2 RE/TA", x2), ("X3 EBIT/TA", x3), ("X4 MVE/TL", x4),
                                       ("X5 SALES/TA", x5)], [])

    return _zero_safe(formula, calc)


def altman_z2(cur: dict) -> dict:
    """Z'' = 6.56 X1 + 3.26 X2 + 6.72 X3 + 1.05 X4 (book equity, no sales term). Safe > 2.6, distress < 1.1."""
    formula = "6.56 WC/TA + 3.26 RE/TA + 6.72 EBIT/TA + 1.05 BOOK EQUITY/TL"
    missing = _need(cur, ("current_assets", "current_liabilities", "retained_earnings", "operating_income", "total_assets",
                          "total_liabilities", "equity"))
    if missing:
        return _out(None, None, formula, [], missing)
    ta, tl = cur["total_assets"], cur["total_liabilities"]

    def calc() -> dict:
        x1 = (cur["current_assets"] - cur["current_liabilities"]) / ta
        x2 = cur["retained_earnings"] / ta
        x3 = cur["operating_income"] / ta
        x4 = cur["equity"] / tl
        z = 6.56 * x1 + 3.26 * x2 + 6.72 * x3 + 1.05 * x4
        zone = "SAFE" if z > 2.6 else "GREY" if z >= 1.1 else "DISTRESS"
        return _out(z, zone, formula, [("X1 WC/TA", x1), ("X2 RE/TA", x2), ("X3 EBIT/TA", x3), ("X4 BE/TL", x4)], [])

    return _zero_safe(formula, calc)


# --- Piotroski F (2000): nine pass/fail tests, current year vs prior year ----------------------------------------
def piotroski_f(cur: dict, prev: dict) -> dict:
    formula = "ONE POINT EACH: ROA>0, CFO>0, ROA UP, CFO>NI, LEVERAGE DOWN, CURRENT RATIO UP, NO NEW SHARES, GROSS MARGIN UP, ASSET TURNOVER UP"
    keys = ("net_income", "total_assets", "operating_cf", "long_term_debt", "current_assets", "current_liabilities",
            "shares_diluted", "gross_profit", "revenue")
    missing = _need(cur, keys) + _need(prev, keys, " (PRIOR YEAR)")
    if missing:
        return _out(None, None, formula, [], missing)

    def roa(d):
        return d["net_income"] / d["total_assets"]

    def calc() -> dict:
        tests = [
            ("ROA > 0", roa(cur) > 0),
            ("OPERATING CASH FLOW > 0", cur["operating_cf"] > 0),
            ("ROA HIGHER THAN LAST YEAR", roa(cur) > roa(prev)),
            ("CASH FLOW > NET INCOME (LOW ACCRUALS)", cur["operating_cf"] > cur["net_income"]),
            ("LONG-TERM DEBT / ASSETS LOWER", cur["long_term_debt"] / cur["total_assets"] < prev["long_term_debt"] / prev["total_assets"]),
            ("CURRENT RATIO HIGHER", cur["current_assets"] / cur["current_liabilities"] > prev["current_assets"] / prev["current_liabilities"]),
            ("NO NEW SHARES (DILUTED COUNT NOT UP)", cur["shares_diluted"] <= prev["shares_diluted"]),
            ("GROSS MARGIN HIGHER", cur["gross_profit"] / cur["revenue"] > prev["gross_profit"] / prev["revenue"]),
            ("ASSET TURNOVER HIGHER", cur["revenue"] / cur["total_assets"] > prev["revenue"] / prev["total_assets"]),
        ]
        f = sum(1 for _, ok in tests if ok)
        zone = "STRONG" if f >= 8 else "WEAK" if f <= 2 else "MIDDLE"
        return _out(float(f), zone, formula, [(name, 1.0 if ok else 0.0) for name, ok in tests], [])

    return _zero_safe(formula, calc)


# --- Beneish M (1999, eight variables) ---------------------------------------------------------------------------
def beneish_m(cur: dict, prev: dict) -> dict:
    """M > -1.78 = the profile of an earnings manipulator in Beneish's sample (a flag, not a finding)."""
    formula = ("-4.84 + 0.920 DSRI + 0.528 GMI + 0.404 AQI + 0.892 SGI + 0.115 DEPI - 0.172 SGAI + 4.679 TATA - 0.327 LVGI")
    keys = ("receivables", "revenue", "gross_profit", "current_assets", "ppe", "total_assets", "da", "sga",
            "current_liabilities", "long_term_debt")
    missing = _need(cur, (*keys, "net_income", "operating_cf")) + _need(prev, keys, " (PRIOR YEAR)")
    if missing:
        return _out(None, None, formula, [], missing)
    c, p = cur, prev
    sec_c, sec_p = c.get("lt_investments") or 0.0, p.get("lt_investments") or 0.0  # securities: 0 when not tagged

    def calc() -> dict:
        dsri = (c["receivables"] / c["revenue"]) / (p["receivables"] / p["revenue"])
        gmi = (p["gross_profit"] / p["revenue"]) / (c["gross_profit"] / c["revenue"])
        aqi = (1 - (c["current_assets"] + c["ppe"] + sec_c) / c["total_assets"]) / (1 - (p["current_assets"] + p["ppe"] + sec_p) / p["total_assets"])
        sgi = c["revenue"] / p["revenue"]
        depi = (p["da"] / (p["da"] + p["ppe"])) / (c["da"] / (c["da"] + c["ppe"]))
        sgai = (c["sga"] / c["revenue"]) / (p["sga"] / p["revenue"])
        lvgi = ((c["current_liabilities"] + c["long_term_debt"]) / c["total_assets"]) / ((p["current_liabilities"] + p["long_term_debt"]) / p["total_assets"])
        tata = (c["net_income"] - c["operating_cf"]) / c["total_assets"]
        m = -4.84 + 0.920 * dsri + 0.528 * gmi + 0.404 * aqi + 0.892 * sgi + 0.115 * depi - 0.172 * sgai + 4.679 * tata - 0.327 * lvgi
        zone = "FLAG (ABOVE -1.78)" if m > -1.78 else "NO FLAG"
        return _out(m, zone, formula, [("DSRI", dsri), ("GMI", gmi), ("AQI", aqi), ("SGI", sgi), ("DEPI", depi),
                                       ("SGAI", sgai), ("TATA", tata), ("LVGI", lvgi)], [])

    return _zero_safe(formula, calc)


# --- Ohlson O (1980) ---------------------------------------------------------------------------------------------
PRICE_INDEX_1968 = 628.0
"""US GDP price index rebased to 1968 = 100 (about 2024: deflator 125 on 2017 = 100 over 19.9 for 1968). Ohlson scales
total assets by it. A fixed input, shown on screen; it moves a few percent a year, which shifts O by about 0.01."""


def ohlson_o(cur: dict, prev: dict) -> dict:
    """O-score and its probability of failure within two years, P = e^O / (1 + e^O)."""
    formula = ("-1.32 - 0.407 LOG(TA/PRICE INDEX) + 6.03 TL/TA - 1.43 WC/TA + 0.0757 CL/CA - 1.72 X - 2.37 NI/TA"
               " - 1.83 FFO/TL + 0.285 Y - 0.521 CHIN")
    keys = ("total_assets", "total_liabilities", "current_assets", "current_liabilities", "net_income", "operating_cf")
    missing = _need(cur, keys) + _need(prev, ("net_income",), " (PRIOR YEAR)")
    if missing:
        return _out(None, None, formula, [], missing)
    c = cur
    if c["total_assets"] <= 0:  # the size term is a logarithm of assets
        return _out(None, None, formula, [], ["total_assets must be positive"])

    def calc() -> dict:
        ta_m = c["total_assets"] / 1e6
        size = math.log(ta_m / PRICE_INDEX_1968)
        tlta = c["total_liabilities"] / c["total_assets"]
        wcta = (c["current_assets"] - c["current_liabilities"]) / c["total_assets"]
        clca = c["current_liabilities"] / c["current_assets"]
        x = 1.0 if c["total_liabilities"] > c["total_assets"] else 0.0
        nita = c["net_income"] / c["total_assets"]
        futl = c["operating_cf"] / c["total_liabilities"]  # funds from operations ~ operating cash flow
        y = 1.0 if c["net_income"] < 0 and prev["net_income"] < 0 else 0.0
        den = abs(c["net_income"]) + abs(prev["net_income"])
        chin = (c["net_income"] - prev["net_income"]) / den if den else 0.0
        o = (-1.32 - 0.407 * size + 6.03 * tlta - 1.43 * wcta + 0.0757 * clca - 1.72 * x - 2.37 * nita - 1.83 * futl
             + 0.285 * y - 0.521 * chin)
        # logistic written so that exp() only ever sees a non-positive number (exp(-O) overflows for O below about -709)
        prob = 1 / (1 + math.exp(-o)) if o >= 0 else math.exp(o) / (1 + math.exp(o))
        zone = f"FAILURE PROBABILITY {prob * 100:.1f}%"
        return _out(o, zone, formula, [("SIZE LOG(TA $M / INDEX)", size), ("PRICE INDEX (1968=100, FIXED)", PRICE_INDEX_1968),
                                       ("TL/TA", tlta), ("WC/TA", wcta), ("CL/CA", clca), ("X (TL>TA)", x), ("NI/TA", nita),
                                       ("FFO/TL (FFO = OPERATING CF)", futl), ("Y (TWO LOSS YEARS)", y), ("CHIN", chin),
                                       ("PROBABILITY", prob)], [])

    return _zero_safe(formula, calc)


# --- Merton distance to default (1974; KMV default point) ---------------------------------------------------------
def merton_dd(equity: float | None, sigma_e: float | None, current_liabilities: float | None,
              long_term_debt: float | None, r: float | None, t: float = 1.0) -> dict:
    """Solve E = V N(d1) - D e^(-rT) N(d2) and sigma_E E = N(d1) sigma_V V for (V, sigma_V), then
    DD = (ln(V/D) + (r - sigma_V^2 / 2) T) / (sigma_V sqrt(T)), default point D = current liabilities + 0.5 long-term debt."""
    formula = "DD = (LN(V/D) + (R - SV^2/2) T) / (SV SQRT T); D = CURRENT LIABILITIES + 0.5 LONG-TERM DEBT; V, SV SOLVED FROM EQUITY"
    missing = [n for n, v in (("market_cap", equity), ("equity_vol", sigma_e), ("current_liabilities", current_liabilities),
                              ("risk_free_rate", r)) if v is None]
    if missing:
        return _out(None, None, formula, [], missing)
    d = current_liabilities + 0.5 * (long_term_debt or 0.0)
    if d <= 0 or equity <= 0 or sigma_e <= 0:
        return _out(None, None, formula, [], ["positive equity, volatility and default point"])
    # Fixed-point iteration from the usual start (V = E + D, sigma_V = sigma_E E / V); converges in a few dozen steps.
    v, sv = equity + d, sigma_e * equity / (equity + d)
    for _ in range(200):
        d1 = (math.log(v / d) + (r + sv * sv / 2) * t) / (sv * math.sqrt(t))
        d2 = d1 - sv * math.sqrt(t)
        n1 = _N.cdf(d1)
        if n1 <= 0.0:  # N(d1) underflowed: a near-default firm the iteration cannot solve (it would divide by zero)
            return _out(None, None, formula, [], ["the asset value and volatility could not be solved (N(d1) is zero)"])
        v_new = (equity + d * math.exp(-r * t) * _N.cdf(d2)) / n1
        sv_new = sigma_e * equity / (n1 * v_new)
        done = abs(v_new - v) < 1e-6 * v and abs(sv_new - sv) < 1e-8
        v, sv = v_new, sv_new
        if done:
            break
    else:
        # 200 steps and still moving: the numbers below would be a half-solved guess shown as a result
        return _out(None, None, formula, [], ["the asset value and volatility did not converge in 200 steps"])
    dd = (math.log(v / d) + (r - sv * sv / 2) * t) / (sv * math.sqrt(t))
    pd = _N.cdf(-dd)
    zone = f"MODEL DEFAULT PROBABILITY {pd * 100:.2f}% (1Y)"
    return _out(dd, zone, formula, [("EQUITY (MARKET CAP)", equity), ("EQUITY VOL (1Y DAILY, ANNUAL)", sigma_e),
                                    ("DEFAULT POINT D", d), ("RISK-FREE RATE", r), ("ASSET VALUE V (SOLVED)", v),
                                    ("ASSET VOL (SOLVED)", sv), ("PROBABILITY N(-DD)", pd)], [])
