"""Table payloads of the RATES views (research/table.py shape). Pure: they take parsed data and say what each number is (spec decision P)."""

from __future__ import annotations

from ..research.table import col, head, payload, section
from . import parse as rp

CURRENCIES = ("EUR", "GBP", "CAD", "JPY")

#: ccy -> (curve title, notes). Every note names the source, its lag and what the number is.
CURVES: dict[str, tuple[str, list[str]]] = {
    "EUR": ("ECB EURO AREA AAA GOVERNMENT SPOT CURVE", [
        "SOURCE: ECB DATA PORTAL, YIELD CURVE (SVENSSON FIT TO EURO AREA AAA CENTRAL GOVERNMENT BONDS), 3M TO 30Y.",
        "AN ESTIMATED CURVE, NOT A TRADED BOND YIELD. PUBLISHED EACH TARGET BUSINESS DAY, ABOUT ONE DAY BEHIND.",
    ]),
    "GBP": ("BANK OF ENGLAND NOMINAL PAR YIELDS", [
        "SOURCE: BANK OF ENGLAND INTERACTIVE DATABASE, NOMINAL PAR YIELDS (IUDSNPY, IUDMNPY, IUDLNPY).",
        "ONLY THE 5, 10 AND 20 YEAR POINTS ARE FREE AND KEYLESS, SO THERE IS NO SHORT END AND NO NELSON-SIEGEL FIT FOR GBP (NEEDS 4 POINTS).",
        "PUBLISHED EACH LONDON BUSINESS DAY, ONE TO TWO DAYS BEHIND.",
    ]),
    "CAD": ("BANK OF CANADA BENCHMARK BOND YIELDS", [
        "SOURCE: BANK OF CANADA VALET, GROUP bond_yields_benchmark: GOVERNMENT OF CANADA 2, 3, 5, 7 AND 10 YEAR BENCHMARKS.",
        "THE LONG-TERM AND REAL RETURN BOND SERIES HAVE NO FIXED MATURITY AND ARE NOT SHOWN. PUBLISHED DAILY, ABOUT ONE DAY BEHIND.",
    ]),
    "JPY": ("JAPAN MOF JGB INTEREST RATES", [
        "SOURCE: MINISTRY OF FINANCE JAPAN, JGB INTEREST RATES (1Y TO 40Y), DAILY CSV.",
        "A DASH FROM THE MOF (A MATURITY WITHOUT A BENCHMARK THAT DAY) IS SHOWN AS NO VALUE. PUBLISHED EACH TOKYO BUSINESS DAY, ONE DAY BEHIND.",
    ]),
}

OAS_NAMES = {
    "BAMLC0A0CM": "US CORPORATE (INVESTMENT GRADE)",
    "BAMLH0A0HYM2": "US HIGH YIELD",
    "BAMLC0A4CBBB": "BBB US CORPORATE",
    "BAMLH0A1HYBB": "BB US HIGH YIELD",
    "BAMLH0A3HYC": "CCC AND LOWER US HIGH YIELD",
}


def curve_payload(ccy: str, curve: dict, source: str, fit: dict | None = None) -> dict:
    """`fit`, when given, is {"model", "params": (b0, b1, b2, lambda), "rmse"} with yields as decimals (quant fit_yield_curve), plus
    "fitted": {tenor: percent}."""
    title, notes = CURVES[ccy]
    rows = rp.curve_rows(curve)
    columns = [col("tenor", "TENOR"), col("years", "YEARS", "num"), col("yield", "YIELD %", "num4"), col("d1", "1D BP", "bp"), col("d5", "5D BP", "bp")]
    if fit is not None:
        columns.append(col("fitted", "NS FIT %", "num4"))
        for r in rows:
            r["fitted"] = fit["fitted"].get(r["tenor"])
    date = curve["dates"][-1] if curve["dates"] else None
    shown = sum(1 for r in rows if r["yield"] is not None)
    sections = [section("curve", f"{ccy} CURVE", columns, rows,
                        "1D BP: CHANGE VS THE PREVIOUS OBSERVATION. 5D BP: VS FIVE OBSERVATIONS BACK. A TENOR WITH NO VALUE ON THE LATEST DATE SHOWS A DASH.")]
    notes = list(notes)
    if fit is not None:
        b0, b1, b2, lam = fit["params"]
        fit_rows = [
            {"name": "BETA0", "value": b0 * 100, "unit": "% (LONG-RUN LEVEL)"},
            {"name": "BETA1", "value": b1 * 100, "unit": "% (SLOPE)"},
            {"name": "BETA2", "value": b2 * 100, "unit": "% (CURVATURE)"},
            {"name": "LAMBDA", "value": lam, "unit": "YEARS (DECAY)"},
            {"name": "RMSE BP", "value": fit["rmse"] * 10000, "unit": "BP, ROOT-MEAN-SQUARE RESIDUAL"},
            {"name": "POINTS", "value": float(fit["points"]), "unit": "TENORS FITTED"},
        ]
        sections.append(section("fit", "NELSON-SIEGEL FIT", [col("name", "PARAMETER"), col("value", "VALUE", "num4"), col("unit", "UNIT")], fit_rows))
        notes.append("NELSON-SIEGEL FIT COMPUTED HERE (OPENTERM QUANT LIBRARY, VIBE-TRADING fit_yield_curve) TO THE SHOWN YIELDS TREATED AS ZERO RATES; "
                     "RESIDUAL = YIELD MINUS NS FIT. A MODEL FIT, NOT A SOURCE FIGURE.")
    headline = [head("CURRENCY", ccy), head("CURVE", title), head("AS OF", date), head("TENORS", f"{shown} OF {len(rows)}", shown)]
    return payload(ccy, f"RATES {'NS ' if fit else ''}{ccy}", headline, sections, notes, source)


def spreads_payload(rows: list[dict], failed: list[str], source: str) -> dict:
    columns = [col("series", "FRED ID"), col("name", "OPTION-ADJUSTED SPREAD"), col("bp", "OAS BP", "bp"), col("date", "AS OF", "date"),
               col("d1", "1D BP", "bp"), col("d5", "5D BP", "bp"), col("d21", "21D BP", "bp"), col("pct_1y", "1Y PCT", "num")]
    notes = [
        "SOURCE: ICE BOFA US INDEX OPTION-ADJUSTED SPREADS VIA FRED (KEYLESS fredgraph.csv). OAS IS THE SPREAD OVER THE TREASURY CURVE, IN BASIS POINTS.",
        "1D, 5D AND 21D BP ARE CHANGES OVER THAT MANY OBSERVATIONS (BUSINESS DAYS). FRED PUBLISHES ABOUT ONE BUSINESS DAY BEHIND AND ONLY THE LAST THREE YEARS OF ICE DATA.",
        "1Y PCT (COMPUTED HERE) = SHARE OF THE LAST 365 DAYS OF DAILY VALUES AT OR BELOW TODAY'S; 100 = WIDEST OF THE YEAR.",
    ]
    if failed:
        notes.append("NOT AVAILABLE RIGHT NOW: " + " ".join(failed))
    dates = [r["date"] for r in rows if r["date"]]
    headline = [head("AS OF", max(dates) if dates else None), head("SERIES", f"{len(dates)} OF {len(rows)}", len(dates))]
    return payload(None, "RATES SPRD", headline, [section("oas", "CREDIT SPREADS (OAS)", columns, rows)], notes, source)


def auctions_payload(results: list[dict], upcoming: list[dict], source: str) -> dict:
    base = [col("security_type", "TYPE"), col("term", "TERM"), col("auction_date", "AUCTION", "date"), col("issue_date", "ISSUE", "date"),
            col("maturity_date", "MATURITY", "date"), col("offering", "OFFERING", "money")]
    res_cols = [*base, col("bid_to_cover", "BID/COVER", "num"), col("high_rate", "HIGH RATE %", "num4"), col("cusip", "CUSIP")]
    up_cols = [*base, col("reopening", "REOPEN"), col("cusip", "CUSIP")]
    notes = [
        "SOURCE: TREASURYDIRECT SECURITIES API (AUCTIONED, LAST 30 DAYS; UPCOMING ANNOUNCED AUCTIONS). NO KEY.",
        "AUCTION = COMPETITIVE BID CLOSE DATE. HIGH RATE: HIGH RATE FOR NOTES AND BONDS, DISCOUNT OR INVESTMENT RATE AS REPORTED FOR BILLS. OFFERING IN US DOLLARS.",
        "RESULTS ARE POSTED WITHIN MINUTES OF THE AUCTION; THE TREASURY ANNOUNCES AN AUCTION ABOUT A WEEK BEFORE IT RUNS.",
    ]
    headline = [head("RESULTS", str(len(results)), len(results)), head("UPCOMING", str(len(upcoming)), len(upcoming)),
                head("LATEST AUCTION", results[0]["auction_date"] if results else None)]
    return payload(None, "RATES AUCT", headline, [
        section("results", "AUCTION RESULTS (NEWEST FIRST)", res_cols, results),
        section("upcoming", "UPCOMING AUCTIONS (SOONEST FIRST)", up_cols, upcoming),
    ], notes, source)
