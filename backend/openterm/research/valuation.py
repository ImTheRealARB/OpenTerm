"""DCF, WACC and RV on top of the ported Vibe engine (openterm/valuation). Pure functions: the service fetches the data.

The rule that shapes everything here comes from the engine: **a missing input makes the model NOT RUNNABLE; nothing is
defaulted.** Inputs that are facts come from data and are listed with their source (`found`); inputs that are opinions
(equity risk premium, terminal growth, exit multiple, forecast growth, capital-structure basis, discounting convention,
terminal method) must be typed and are echoed back with their basis (`assumptions`). Percent arguments are typed as
percent (ERP=5.5 is 5.5%).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import asdict
from datetime import date
from typing import Any

from ..valuation import comps as vc
from ..valuation import dcf as vd
from ..valuation.contracts import Assumption, MissingInputError, ValuationError
from .table import col, head, payload, section

TYPED = "typed on the command line"
PERCENT_KEYS = {"erp", "g", "growth", "rf", "tax", "kd", "ew"}
NUMBER_KEYS = {"exitx", "beta", "minority", "preferred", "assoc"}
CHOICE_KEYS = {"basis": {"current": "current", "target": "target"}, "conv": {"mid": "mid_year", "end": "year_end"},
               "tv": {"perp": "perpetuity_growth", "exit": "exit_multiple"}}
KNOWN_KEYS = PERCENT_KEYS | NUMBER_KEYS | set(CHOICE_KEYS) | {"years", "other", "peers", "policy"}
DCF_TEMPLATE = "ERP=5.5 G=2.5 EXITX=14 GROWTH=5 BASIS=CURRENT CONV=MID TV=PERP OTHER=0"
MAX_YEARS = 15
SENSITIVITY_STEP = 0.005


class ParamError(ValueError):
    pass


def parse_params(q: Mapping[str, str]) -> dict[str, Any]:
    """Query/command arguments -> typed values. Percent keys become ratios. Raises ParamError with a usage message."""
    out: dict[str, Any] = {}
    for raw_key, raw in q.items():
        k = raw_key.lower()
        if k in ("symbol",):
            continue
        if k not in KNOWN_KEYS:
            raise ParamError(f"UNKNOWN ARGUMENT {raw_key.upper()}. USE {' '.join(sorted(x.upper() for x in KNOWN_KEYS))}")
        v = str(raw).strip()
        if v == "":
            continue
        if k in PERCENT_KEYS | NUMBER_KEYS:
            try:
                n = float(v)
            except ValueError:
                raise ParamError(f"{k.upper()}={v}: NOT A NUMBER") from None
            if not math.isfinite(n):
                raise ParamError(f"{k.upper()}={v}: NOT A FINITE NUMBER")
            out[k] = n / 100.0 if k in PERCENT_KEYS else n
        elif k in CHOICE_KEYS:
            if v.lower() not in CHOICE_KEYS[k]:
                raise ParamError(f"{k.upper()}={v}: USE {' OR '.join(x.upper() for x in CHOICE_KEYS[k])}")
            out[k] = CHOICE_KEYS[k][v.lower()]
        elif k == "years":
            if not v.isdigit() or not 1 <= int(v) <= MAX_YEARS:
                raise ParamError(f"YEARS: 1 TO {MAX_YEARS}")
            out[k] = int(v)
        elif k == "other":
            if v != "0":
                raise ParamError("OTHER=0 ONLY: IT STATES THAT MINORITY INTEREST, PREFERRED EQUITY AND ASSOCIATE INVESTMENTS ARE ZERO")
            out[k] = 0.0
        elif k == "peers":
            out[k] = [s.strip().upper() for s in v.split(",") if s.strip()][:12]
        elif k == "policy":
            if v.lower() != "ltm":
                raise ParamError("POLICY=LTM ONLY: THE CALENDAR-YEAR POLICY NEEDS NEXT-FISCAL-YEAR FORECASTS THIS APP DOES NOT HOLD")
            out[k] = "ltm"
    return out


# ---------------------------------------------------------------------------------------------- filed figures


class Fin:
    """Read access to an FA payload (`fundamentals()["data"]`): values by row key and period index (0 = newest)."""

    def __init__(self, fa: dict):
        self.periods = fa.get("periods") or []
        self.rows = {r["key"]: r for stmt in (fa.get("statements") or {}).values() for r in stmt}
        self.currency = fa.get("currency")

    def v(self, key: str, i: int = 0) -> float | None:
        row = self.rows.get(key)
        if not row or i >= len(row["values"]):
            return None
        return row["values"][i]

    def end(self, i: int = 0) -> str | None:
        return self.periods[i]["end"] if i < len(self.periods) else None

    def label(self, i: int = 0) -> str:
        return self.periods[i]["label"] if i < len(self.periods) else "?"


def _debt(f: Fin, i: int = 0) -> tuple[float | None, str | None]:
    ltd, cur = f.v("long_term_debt", i), f.v("current_debt", i)
    if ltd is None:
        return None, "long-term debt is not tagged in the filing"
    return ltd + (cur or 0.0), (None if cur is not None else "current debt not tagged: counted as 0")


def _nwc(f: Fin, i: int) -> float | None:
    ca, cash, cl, cd = f.v("current_assets", i), f.v("cash", i), f.v("current_liabilities", i), f.v("current_debt", i)
    if None in (ca, cash, cl):
        return None
    return (ca - cash) - (cl - (cd or 0.0))


def _pct(v: float | None) -> str:
    return f"{v * 100:.2f}%" if v is not None else "-"


def _big(v: float | None) -> str:
    if v is None:
        return "-"
    a = abs(v)
    for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= div:
            return f"{v / div:.2f}{suf}"
    return f"{v:.2f}"


# ---------------------------------------------------------------------------------------------- DCF / WACC inputs


def gather(fin: Fin | None, fin_error: str | None, beta: tuple[float | None, str], rf: tuple[float | None, str],
           market_cap: tuple[float | None, str], p: Mapping[str, Any]) -> dict:
    """Facts from data (with their source) plus typed overrides. Returns {values, found, problems}."""
    values: dict[str, Any] = {}
    found: list[dict] = []
    problems: dict[str, str] = {}

    def put(name: str, value: float | None, source: str, reason: str | None = None) -> None:
        if value is None or (isinstance(value, float) and not math.isfinite(value)):
            problems[name] = reason or f"not available from {source}"
            return
        values[name] = value
        found.append({"input": name, "value": value, "source": source})

    def typed(name: str, key: str) -> bool:
        if key in p:
            put(name, p[key], TYPED)
            return True
        return False

    if not typed("risk_free_rate", "rf"):
        put("risk_free_rate", rf[0], rf[1])
    if not typed("beta", "beta"):
        put("beta", beta[0], beta[1])

    src = f"SEC filings {fin.label(0)} (FY ended {fin.end(0)})" if fin else "SEC filings"
    miss = fin_error or "no SEC filing data (US filers only)"
    if fin is None:
        for name in ("tax_rate", "pretax_cost_of_debt", "ebit", "depreciation_amortization", "capex", "delta_nwc",
                     "total_debt", "cash_and_equivalents", "diluted_shares"):
            if not (name == "tax_rate" and typed(name, "tax")) and not (name == "pretax_cost_of_debt" and typed(name, "kd")):
                problems[name] = miss
    else:
        pretax, tax = fin.v("pretax_income"), fin.v("income_tax")
        eff = tax / pretax if pretax and tax is not None else None
        if not typed("tax_rate", "tax"):
            if eff is not None and 0.0 <= eff <= 1.0:
                put("tax_rate", eff, f"{src}: income tax / pretax income")
            else:
                problems["tax_rate"] = (f"effective rate {_pct(eff)} is outside 0-100%: type TAX=" if eff is not None
                                        else "income tax or pretax income not tagged: type TAX=")
        debt, debt_note = _debt(fin)
        interest = fin.v("interest_expense")
        if not typed("pretax_cost_of_debt", "kd"):
            if interest is not None and debt:
                put("pretax_cost_of_debt", abs(interest) / debt, f"{src}: interest expense / total debt")
            else:
                problems["pretax_cost_of_debt"] = "interest expense or debt not tagged: type KD="
        put("ebit", fin.v("operating_income"), f"{src}: operating income")
        put("depreciation_amortization", fin.v("da"), f"{src}: depreciation and amortization (cash flow statement)")
        put("capex", fin.v("capex"), f"{src}: purchases of property, plant and equipment")
        nwc0, nwc1 = _nwc(fin, 0), _nwc(fin, 1)
        put("delta_nwc", nwc0 - nwc1 if nwc0 is not None and nwc1 is not None else None,
            f"{src}: change in operating NWC = (current assets - cash) - (current liabilities - current debt), two years",
            "needs two fiscal years of current assets, cash and current liabilities")
        put("total_debt", debt, f"{src}: current + long-term debt" + (f" ({debt_note})" if debt_note else ""), debt_note)
        put("cash_and_equivalents", fin.v("cash"), f"{src}: cash and equivalents")
        put("diluted_shares", fin.v("shares_diluted"), f"{src}: weighted average diluted shares")
    if p.get("basis") == "current":
        put("market_value_of_equity", market_cap[0], market_cap[1])
        if "total_debt" in values:
            values["market_value_of_debt"] = values["total_debt"]
            found.append({"input": "market_value_of_debt", "value": values["total_debt"],
                          "source": "book value of debt used for market value (no traded-debt data)"})
        else:
            problems["market_value_of_debt"] = "needs total debt"
    for name, key in (("minority_interest", "minority"), ("preferred_equity", "preferred"), ("associate_investments", "assoc")):
        if key in p:
            put(name, p[key], TYPED)
        elif "other" in p:
            put(name, 0.0, f"{TYPED}: OTHER=0")
        else:
            problems[name] = "not in the filings data: type OTHER=0 to state all three are zero, or MINORITY= PREFERRED= ASSOC="
    return {"values": values, "found": found, "problems": problems}


def _opinions(p: Mapping[str, Any], need: list[tuple[str, str, str]]) -> tuple[list[dict], list[str]]:
    """need: (engine name, param key, hint). Returns (assumptions, missing engine names)."""
    ass, missing = [], []
    for name, key, _hint in need:
        if key in p:
            v = p[key]
            ass.append({"name": name, "value": v, "basis": f"{TYPED} ({key.upper()}=...)"})
        else:
            missing.append(name)
    return ass, missing


WACC_OPINIONS = [("equity_risk_premium", "erp", "ERP=5.5"), ("capital_structure_basis", "basis", "BASIS=CURRENT|TARGET")]
DCF_OPINIONS = [("equity_risk_premium", "erp", "ERP=5.5"), ("terminal_growth", "g", "G=2.5"), ("exit_multiple", "exitx", "EXITX=14"),
                ("growth", "growth", "GROWTH=5"), ("capital_structure_basis", "basis", "BASIS=CURRENT|TARGET"),
                ("discounting_convention", "conv", "CONV=MID|END"), ("terminal_value_method", "tv", "TV=PERP|EXIT")]

INPUT_LABEL = {
    "risk_free_rate": "RISK-FREE RATE", "beta": "BETA", "tax_rate": "TAX RATE", "pretax_cost_of_debt": "PRETAX COST OF DEBT",
    "ebit": "EBIT (BASE YEAR)", "depreciation_amortization": "D&A (BASE YEAR)", "capex": "CAPEX (BASE YEAR)",
    "delta_nwc": "CHANGE IN NWC (BASE YEAR)", "total_debt": "TOTAL DEBT", "cash_and_equivalents": "CASH",
    "diluted_shares": "DILUTED SHARES", "market_value_of_equity": "MARKET CAP", "market_value_of_debt": "DEBT (BOOK)",
    "minority_interest": "MINORITY INTEREST", "preferred_equity": "PREFERRED EQUITY", "associate_investments": "ASSOCIATE INVESTMENTS",
    "equity_risk_premium": "EQUITY RISK PREMIUM", "terminal_growth": "TERMINAL GROWTH", "exit_multiple": "EXIT EV/EBITDA",
    "growth": "FORECAST GROWTH", "capital_structure_basis": "CAPITAL STRUCTURE", "discounting_convention": "DISCOUNTING",
    "terminal_value_method": "TERMINAL VALUE", "target_equity_weight": "TARGET EQUITY WEIGHT",
}
PCT_NAMES = {"risk_free_rate", "tax_rate", "pretax_cost_of_debt", "equity_risk_premium", "terminal_growth", "growth",
             "target_equity_weight"}


def _show(name: str, v: Any) -> str:
    if isinstance(v, str):
        return v.upper().replace("_", " ")
    if name in PCT_NAMES:
        return _pct(v)
    if name == "beta" or name == "exit_multiple":
        return f"{v:.2f}"
    return _big(v)


def _input_rows(found: list[dict], assumptions: list[dict], problems: dict[str, str], missing_opinions: list[str],
                hints: dict[str, str]) -> list[dict]:
    rows = [{"input": INPUT_LABEL.get(f["input"], f["input"]), "value": _show(f["input"], f["value"]), "source": f["source"]}
            for f in found]
    rows += [{"input": INPUT_LABEL.get(a["name"], a["name"]), "value": _show(a["name"], a["value"]), "source": "ASSUMPTION: " + a["basis"]}
             for a in assumptions]
    rows += [{"input": INPUT_LABEL.get(n, n), "value": "MISSING", "source": why} for n, why in problems.items()]
    rows += [{"input": INPUT_LABEL.get(n, n), "value": "MISSING", "source": f"YOUR CALL: type {hints[n]}"} for n in missing_opinions]
    return rows


INPUT_COLUMNS = [col("input", "INPUT", "text", 26), col("value", "VALUE", "text", 12), col("source", "WHERE IT COMES FROM", "text", 70)]


def _not_runnable(symbol: str, title: str, missing: list[str], rows: list[dict], found: list[dict], assumptions: list[dict],
                  template: str, extra_notes: list[str], source: str, reason: str | None = None) -> dict:
    status = f"NOT RUNNABLE: {len(missing)} INPUT(S) MISSING" if missing else f"NOT RUNNABLE: {reason}"
    notes = [f"TO RUN: {template}", "NOTHING HERE IS DEFAULTED: A MISSING INPUT STOPS THE MODEL", *extra_notes]
    out = payload(symbol, title, [head("STATUS", status)],
                  [section("inputs", "INPUTS", INPUT_COLUMNS, rows)], notes, source)
    out.update(runnable=False, status=status, missing=missing, found=found, assumptions=assumptions, result=None, warnings=[])
    return out


# ---------------------------------------------------------------------------------------------- WACC


def build_wacc(symbol: str, g: dict, p: Mapping[str, Any], source: str) -> dict:
    ass, miss_op = _opinions(p, WACC_OPINIONS)
    need_ew = p.get("basis") == "target"
    if need_ew:
        if "ew" in p:
            ass.append({"name": "target_equity_weight", "value": p["ew"], "basis": f"{TYPED} (EW=...)"})
        else:
            miss_op.append("target_equity_weight")
    needed = ["risk_free_rate", "beta", "pretax_cost_of_debt", "tax_rate"] + (
        ["market_value_of_equity", "market_value_of_debt"] if p.get("basis") == "current" else [])
    problems = {k: v for k, v in g["problems"].items() if k in needed}
    missing = [*problems, *miss_op]
    hints = {"equity_risk_premium": "ERP=5.5", "capital_structure_basis": "BASIS=CURRENT|TARGET", "target_equity_weight": "EW=90"}
    title = f"WACC {symbol} · COST OF CAPITAL"
    tmpl = f"WACC {symbol} ERP=5.5 BASIS=CURRENT"
    found = [f for f in g["found"] if f["input"] in needed]
    rows = _input_rows(found, ass, problems, miss_op, hints)
    if missing:
        return _not_runnable(symbol, title, missing, rows, found, ass, tmpl, [], source)
    v = g["values"]
    try:
        kw: dict[str, Any] = {"risk_free_rate": v["risk_free_rate"], "beta": v["beta"], "equity_risk_premium": p["erp"],
                              "pretax_cost_of_debt": v["pretax_cost_of_debt"], "tax_rate": v["tax_rate"],
                              "capital_structure_basis": p["basis"]}
        if p["basis"] == "current":
            kw.update(market_value_of_equity=v["market_value_of_equity"], market_value_of_debt=v["market_value_of_debt"])
        else:
            kw.update(target_equity_weight=p["ew"], target_debt_weight=1.0 - p["ew"])
        w = vd.wacc(**kw)
    except (ValuationError, MissingInputError) as e:
        return _not_runnable(symbol, title, [], rows, found, ass, tmpl, [], source, reason=str(e))
    result = asdict(w)
    lines = [
        ("RISK-FREE RATE", _pct(w.risk_free_rate)), ("BETA", f"{w.beta:.3f}"), ("EQUITY RISK PREMIUM", _pct(w.equity_risk_premium)),
        ("COST OF EQUITY", _pct(w.cost_of_equity)), ("PRETAX COST OF DEBT", _pct(w.pretax_cost_of_debt)),
        ("TAX RATE", _pct(w.tax_rate)), ("AFTER-TAX COST OF DEBT", _pct(w.cost_of_debt_after_tax)),
        ("EQUITY WEIGHT", _pct(w.equity_weight)), ("DEBT WEIGHT", _pct(w.debt_weight)), ("WACC", _pct(w.wacc)),
    ]
    out = payload(symbol, title, [head("WACC", _pct(w.wacc), w.wacc), head("BASIS", p["basis"].upper())],
                  [section("wacc", "BUILD", [col("item", "ITEM", "text", 26), col("value", "VALUE", "text", 12)],
                           [{"item": a, "value": b} for a, b in lines]),
                   section("inputs", "INPUTS", INPUT_COLUMNS, rows)],
                  ["COST OF EQUITY = RISK-FREE + BETA x ERP. WACC = E/(D+E) x COST OF EQUITY + D/(D+E) x COST OF DEBT x (1 - TAX)"],
                  source)
    out.update(runnable=True, status="RUNNABLE", missing=[], found=found, assumptions=ass, result=result, warnings=[])
    return out


# ---------------------------------------------------------------------------------------------- DCF


def _forecast(v: Mapping[str, Any], growth: float, years: int) -> dict[str, list[float]]:
    return {k: [v[k] * (1.0 + growth) ** t for t in range(1, years + 1)]
            for k in ("ebit", "depreciation_amortization", "capex", "delta_nwc")}


def build_dcf(symbol: str, g: dict, p: Mapping[str, Any], price: float | None, source: str) -> dict:
    ass, miss_op = _opinions(p, DCF_OPINIONS)
    if p.get("basis") == "target":
        if "ew" in p:
            ass.append({"name": "target_equity_weight", "value": p["ew"], "basis": f"{TYPED} (EW=...)"})
        else:
            miss_op.append("target_equity_weight")
    years = p.get("years", 5)
    ass.append({"name": "forecast_years", "value": years, "basis": "5 unless YEARS= is typed (structural horizon)" if "years" not in p else f"{TYPED} (YEARS=...)"})
    problems = dict(g["problems"])
    hints = {n: h for n, _k, h in DCF_OPINIONS} | {"target_equity_weight": "EW=90"}
    title = f"DCF {symbol} · DISCOUNTED CASH FLOW"
    missing = [*problems, *miss_op]
    rows = _input_rows(g["found"], ass, problems, miss_op, hints)
    notes_extra = ["THE FORECAST IS YOUR ASSUMPTIONS APPLIED TO FILED FIGURES: A SCENARIO, NOT A PREDICTION"]
    tmpl = f"DCF {symbol} {DCF_TEMPLATE}"
    if missing:
        return _not_runnable(symbol, title, missing, rows, g["found"], ass, tmpl, notes_extra, source)
    v = g["values"]
    inputs = {**v, **_forecast(v, p["growth"], years),
              "equity_risk_premium": p["erp"],
              "terminal_growth": Assumption("terminal_growth", p["g"], f"{TYPED} (G={p['g'] * 100:g})"),
              "exit_multiple": Assumption("exit_multiple", p["exitx"], f"{TYPED} (EXITX={p['exitx']:g})")}
    if p["basis"] == "target":
        inputs.update(target_equity_weight=p["ew"], target_debt_weight=1.0 - p["ew"])
    try:
        r = vd.run_dcf(inputs, capital_structure_basis=p["basis"], discounting_convention=p["conv"],
                       terminal_value_method=p["tv"])
    except (ValuationError, MissingInputError) as e:
        return _not_runnable(symbol, title, [], rows, g["found"], ass, tmpl, notes_extra, source, reason=str(e))
    tv, nb, wb = r.terminal_value, r.net_debt_bridge, r.wacc_build
    upside = r.value_per_share / price - 1 if price else None
    warnings = []
    if tv.growth_exceeds_gdp_ceiling:
        warnings.append(f"TERMINAL GROWTH {_pct(p['g'])} IS ABOVE THE {_pct(tv.gdp_growth_ceiling)} LONG-RUN GDP REFERENCE")
    if price is None:
        warnings.append("NO CURRENT PRICE: UPSIDE NOT SHOWN")
    result = {
        "wacc": wb.wacc, "cost_of_equity": wb.cost_of_equity, "enterprise_value": r.enterprise_value,
        "pv_explicit": r.pv_of_explicit_fcff, "pv_terminal": r.pv_of_terminal_value, "equity_value": r.equity_value,
        "value_per_share": r.value_per_share, "diluted_shares": nb.diluted_shares, "price": price, "upside": upside,
        "terminal_cross_check": {"implied_exit_multiple": tv.implied_ev_ebitda_multiple,
                                 "implied_perpetuity_growth": tv.implied_perpetuity_growth,
                                 "perpetuity_terminal_value": tv.perpetuity_terminal_value,
                                 "exit_terminal_value": tv.exit_terminal_value},
        "terminal_value_method": r.terminal_value_method, "discounting_convention": r.discounting_convention,
        "wacc_build": asdict(wb), "fcff": [asdict(y) for y in r.fcff_bridge], "discounted": [asdict(d) for d in r.discounted_fcff],
    }
    fcff_rows = [{"year": y.year, "ebit": y.ebit, "nopat": y.nopat, "da": y.depreciation_amortization, "capex": y.capex,
                  "dnwc": y.delta_nwc, "fcff": y.fcff, "factor": d.discount_factor, "pv": d.present_value}
                 for y, d in zip(r.fcff_bridge, r.discounted_fcff)]
    bridge = [
        ("PV OF EXPLICIT FCFF", _big(r.pv_of_explicit_fcff)),
        (f"PV OF TERMINAL VALUE ({'PERPETUITY' if r.terminal_value_method == 'perpetuity_growth' else 'EXIT MULTIPLE'})", _big(r.pv_of_terminal_value)),
        ("ENTERPRISE VALUE", _big(r.enterprise_value)), ("- TOTAL DEBT", _big(nb.total_debt)), ("+ CASH", _big(nb.cash_and_equivalents)),
        ("- MINORITY INTEREST", _big(nb.minority_interest)), ("- PREFERRED EQUITY", _big(nb.preferred_equity)),
        ("+ ASSOCIATE INVESTMENTS", _big(nb.associate_investments)), ("EQUITY VALUE", _big(r.equity_value)),
        ("DILUTED SHARES", _big(nb.diluted_shares)), ("VALUE PER SHARE", f"{r.value_per_share:.2f}"),
        ("CURRENT PRICE", f"{price:.2f}" if price else "-"), ("UPSIDE", _pct(upside) if upside is not None else "-"),
        ("PERPETUITY TV IMPLIES EXIT MULTIPLE", f"{tv.implied_ev_ebitda_multiple:.1f}x"),
        ("EXIT MULTIPLE IMPLIES PERPETUITY GROWTH", _pct(tv.implied_perpetuity_growth)),
    ]
    sens_rows, sens_cols = _sensitivity(r, p, v)
    sections = [
        section("value", "VALUE BRIDGE", [col("item", "ITEM", "text", 42), col("value", "VALUE", "text", 14)],
                [{"item": a, "value": b} for a, b in bridge]),
        section("fcff", "FREE CASH FLOW TO THE FIRM",
                [col("year", "YEAR", "int"), col("ebit", "EBIT", "money"), col("nopat", "NOPAT", "money"), col("da", "D&A", "money"),
                 col("capex", "CAPEX", "money"), col("dnwc", "D NWC", "money"), col("fcff", "FCFF", "money"),
                 col("factor", "DISC FACTOR", "num"), col("pv", "PV", "money")], fcff_rows),
        section("sensitivity", "VALUE PER SHARE: WACC (ROWS) x TERMINAL GROWTH (COLUMNS), PERPETUITY METHOD", sens_cols, sens_rows,
                "BLANK = TERMINAL GROWTH AT OR ABOVE WACC (UNDEFINED)"),
        section("inputs", "INPUTS", INPUT_COLUMNS, rows),
    ]
    out = payload(symbol, title,
                  [head("VALUE PER SHARE", f"{r.value_per_share:.2f}", r.value_per_share), head("PRICE", f"{price:.2f}" if price else None, price),
                   head("UPSIDE", _pct(upside) if upside is not None else None, upside), head("WACC", _pct(wb.wacc), wb.wacc)],
                  sections, [*warnings, *notes_extra, "SCENARIO OUTPUT, NOT A PRICE TARGET OR ADVICE"], source)
    out.update(runnable=True, status="RUNNABLE", missing=[], found=g["found"], assumptions=ass, result=result, warnings=warnings)
    return out


def _sensitivity(r: vd.DCFResult, p: Mapping[str, Any], v: Mapping[str, Any]) -> tuple[list[dict], list[dict]]:
    waccs = [round(r.wacc_build.wacc + k * SENSITIVITY_STEP, 6) for k in (-2, -1, 0, 1, 2)]
    growths = [round(p["g"] + k * SENSITIVITY_STEP, 6) for k in (-2, -1, 0, 1, 2)]
    grid = vd.sensitivity_grid(
        r.fcff_bridge, wacc_values=waccs, growth_values=growths, discounting_convention=r.discounting_convention,
        total_debt=v["total_debt"], cash_and_equivalents=v["cash_and_equivalents"], minority_interest=v["minority_interest"],
        preferred_equity=v["preferred_equity"], associate_investments=v["associate_investments"], diluted_shares=v["diluted_shares"])
    cols = [col("wacc", "WACC", "pct")] + [col(f"g{i}", f"g {gv * 100:.2f}%", "num") for i, gv in enumerate(growths)]
    rows = [{"wacc": w, **{f"g{i}": (None if math.isnan(x) else x) for i, x in enumerate(row)}}
            for w, row in zip(waccs, grid.values)]
    return rows, cols


# ---------------------------------------------------------------------------------------------- RV (comps)

MULTIPLES = ("ev_ebitda", "ev_ebit", "ev_sales", "pe", "pb")
MULTIPLE_LABEL = {"ev_ebitda": "EV/EBITDA", "ev_ebit": "EV/EBIT", "ev_sales": "EV/SALES", "pe": "P/E", "pb": "P/B"}


def _flow_parts(fa: Fin, fq: Fin, fn) -> tuple[float, float, float] | tuple[None, str]:
    """(last full FY, current-year-to-date, prior-year-to-date) of fn(Fin, index); LTM = FY + YTD - prior YTD."""
    k = 0
    fy_end = fa.end(0)
    while k < 4 and fq.end(k) and fy_end and fq.end(k) > fy_end:
        k += 1
    if k == 4:
        return None, "the newest quarter is a year after the last 10-K"  # type: ignore[return-value]
    for i in range(k):
        a, b = fq.end(i), fq.end(i + 4)
        if not b or not 340 <= (date.fromisoformat(a) - date.fromisoformat(b)).days <= 390:
            return None, "quarterly history is not contiguous for a year-over-year comparison"  # type: ignore[return-value]
    fy = fn(fa, 0)
    ytd = [fn(fq, i) for i in range(k)]
    pytd = [fn(fq, 4 + i) for i in range(k)]
    if fy is None or None in ytd or None in pytd:
        return None, "a needed line is not tagged in a recent filing"  # type: ignore[return-value]
    return fy, sum(ytd), sum(pytd)


def company_inputs(name: str, fa: Fin, fq: Fin, market_cap: float | None, price: float | None, target: bool) -> tuple[dict | None, str | None]:
    """Raw company dict for comps.PeerCompany / TargetCompany, or (None, why not)."""
    def ebit(f: Fin, i: int):
        return f.v("operating_income", i)

    def ebitda(f: Fin, i: int):
        o, d = f.v("operating_income", i), f.v("da", i)
        return o + d if o is not None and d is not None else None

    series: dict[str, Any] = {}
    for key, fn in (("ebitda", ebitda), ("ebit", ebit), ("revenue", lambda f, i: f.v("revenue", i)),
                    ("diluted_eps", lambda f, i: f.v("eps_diluted", i))):
        parts = _flow_parts(fa, fq, fn)
        if parts[0] is None:
            return None, f"{key.replace('_', ' ')}: {parts[1]}"
        series[key] = {"fiscal_year_end_month": int(fa.end(0)[5:7]), "last_full_fiscal_year": parts[0],
                       "current_year_to_date": parts[1], "prior_year_to_date": parts[2]}
    debt, _ = _debt(fq if fq.v("long_term_debt", 0) is not None else fa)
    cash = fq.v("cash", 0) if fq.v("cash", 0) is not None else fa.v("cash", 0)
    equity = fq.v("equity", 0) if fq.v("equity", 0) is not None else fa.v("equity", 0)
    if debt is None or cash is None or equity is None:
        return None, "debt, cash or equity not tagged"
    out: dict[str, Any] = {"name": name, "total_debt": debt, "cash_and_equivalents": cash, "book_value_of_equity": equity,
                           "eps_basis": "gaap", "minority_interest": None, "preferred_stock": None, "investments_in_associates": None,
                           **series}
    if target:
        shares = fq.v("shares_diluted", 0) or fa.v("shares_diluted", 0)
        if not shares:
            return None, "diluted shares not tagged"
        out["diluted_shares_outstanding"] = shares
    else:
        if not market_cap or not price:
            return None, "no market cap or price"
        out.update(market_cap=market_cap, price_per_share=price)
    return out, None


def _flow(x: dict) -> vc.FlowMetricPeriods:
    return vc.FlowMetricPeriods(**x)


def _co(cls, c: dict):
    kw = {k: v for k, v in c.items() if k not in ("ebitda", "ebit", "revenue", "diluted_eps")}
    for k in ("ebitda", "ebit", "revenue", "diluted_eps"):
        kw[k] = _flow(c[k])
    return cls(**kw)


def build_rv(symbol: str, target: dict | None, target_why: str | None, peers: list[dict], skipped: dict[str, str],
             price: float | None, source: str, peer_basis: str) -> dict:
    title = f"RV {symbol} · RELATIVE VALUATION (COMPS)"
    if target is None:
        return _not_runnable(symbol, title, ["target_company"], [{"input": "TARGET", "value": "MISSING", "source": target_why or "no data"}],
                             [], [], f"RV {symbol} PEERS=MSFT,GOOGL", [], source)
    if not peers:
        rows = [{"input": s, "value": "EXCLUDED", "source": why} for s, why in skipped.items()] or [
            {"input": "PEERS", "value": "MISSING", "source": "none given and none found: type PEERS=MSFT,GOOGL"}]
        return _not_runnable(symbol, title, ["peers"], rows, [], [], f"RV {symbol} PEERS=MSFT,GOOGL", [], source)
    try:
        res = vc.run_comps(_co(vc.TargetCompany, target), [_co(vc.PeerCompany, c) for c in peers], calendarisation_policy="ltm")
    except (ValuationError, MissingInputError) as e:
        return _not_runnable(symbol, title, list(getattr(e, "missing", ())), [], [], [], f"RV {symbol} PEERS=MSFT,GOOGL", [], source, reason=str(e))
    shares = target["diluted_shares_outstanding"]
    peer_rows = [{"peer": pm.name, **{m: getattr(pm, m) for m in MULTIPLES}} for pm in res.peer_multiples]
    mult_cols = [col(m, MULTIPLE_LABEL[m], "num") for m in MULTIPLES]
    dist_rows = []
    for m in MULTIPLES:
        d = res.distributions[m]
        dist_rows.append({"multiple": MULTIPLE_LABEL[m], "n": len(d.included), "min": d.minimum, "p25": d.p25, "median": d.median,
                          "p75": d.p75, "max": d.maximum})
    imp_rows = []
    for m in MULTIPLES:
        iv = res.implied_valuations.get(m)
        eq = iv.implied_equity_value_by_quantile if iv else None
        if not eq:
            imp_rows.append({"multiple": MULTIPLE_LABEL[m], "metric": iv.target_metric_value if iv else None})
            continue
        per = {k: eq[k] / shares for k in ("p25", "median", "p75")}
        imp_rows.append({"multiple": MULTIPLE_LABEL[m], "metric": iv.target_metric_value, "p25": per["p25"], "median": per["median"],
                         "p75": per["p75"], "vs_price": per["median"] / price - 1 if price else None})
    warnings = list(res.warnings) + [d.warning for d in res.distributions.values() if d.warning]
    omitted = sorted({c for pm in res.peer_multiples for c in pm.ev_bridge.omitted_components})
    notes = ["MULTIPLES ARE TRAILING-TWELVE-MONTH FROM SEC FILINGS (FY + YEAR-TO-DATE - PRIOR YEAR-TO-DATE); GAAP EPS; THE MEDIAN IS THE HEADLINE",
             f"PEERS: {peer_basis}"]
    if omitted:
        notes.append(f"EV BRIDGE OMITS ({', '.join(omitted)}): NOT IN THE FILINGS DATA, NOT ASSUMED ZERO; EV MULTIPLES ARE BIASED LOW")
    notes += [f"EXCLUDED {s}: {why}" for s, why in skipped.items()]
    sections = [
        section("implied", "IMPLIED VALUE PER SHARE OF " + symbol + " AT THE PEER QUARTILES",
                [col("multiple", "MULTIPLE", "text", 10), col("metric", "TARGET LTM", "money"), col("p25", "AT P25", "num"),
                 col("median", "AT MEDIAN", "num"), col("p75", "AT P75", "num"), col("vs_price", "MEDIAN VS PRICE", "pct")], imp_rows),
        section("peers", "PEER MULTIPLES", [col("peer", "PEER", "text", 10), *mult_cols], peer_rows),
        section("distribution", "DISTRIBUTION ACROSS PEERS",
                [col("multiple", "MULTIPLE", "text", 10), col("n", "PEERS", "int"), col("min", "MIN", "num"), col("p25", "P25", "num"),
                 col("median", "MEDIAN", "num"), col("p75", "P75", "num"), col("max", "MAX", "num")], dist_rows),
    ]
    out = payload(symbol, title, [head("PEERS USED", str(len(peers)), len(peers)), head("PRICE", f"{price:.2f}" if price else None, price),
                                  head("POLICY", "LTM")], sections, notes + warnings, source)
    out.update(runnable=True, status="RUNNABLE", missing=[], found=[], assumptions=[{"name": "calendarisation_policy", "value": "ltm",
               "basis": "the only policy built (calendar-year needs forecasts)"}],
               result={"peer_count": len(peers), "peers": [c["name"] for c in peers], "target": symbol, "distributions": {
                   m: {"median": res.distributions[m].median, "n": len(res.distributions[m].included)} for m in MULTIPLES}},
               warnings=warnings)
    return out
