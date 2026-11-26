"""Pure parsers for the Phase 30 sources. Each takes the raw answer (text, bytes or decoded JSON) and returns plain dicts and lists;
anything that is not the documented shape raises `ParseError` so the panel says so instead of guessing. No network.

Sources: NY Fed markets API (SOFR, EFFR, OBFR, TGCR, BGCR), ECB data portal (ESTR), Bank of England IADB (SONIA), Atlanta Fed GDPNow
workbook, Philadelphia Fed SPF median workbooks, IMF DataMapper, OECD Economic Outlook (SDMX CSV), federalreserve.gov FOMC statements,
TreasuryDirect securities, USDA WASDE XML (Cornell library copy), EIA API v2 and USDA NASS QuickStats (both keyed, doc-shaped fixtures),
Yahoo quoteSummary fund modules (WPE).
"""

from __future__ import annotations

import csv
import difflib
import html as _html
import io
import re
from datetime import datetime
from typing import Any
from xml.etree import ElementTree as ET

from . import xlsx


class ParseError(ValueError):
    """The answer is not the shape the source documents."""


def _num(x: Any) -> float | None:
    if x is None or x == "" or isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    try:
        return float(str(x).replace(",", "").strip())
    except ValueError:
        return None


# --- NY Fed reference rates ---------------------------------------------------------------------------------------------------


def nyfed(body: Any) -> list[dict]:
    """`/api/rates/<group>/<type>/last/<n>.json` -> [{date, rate, p1, p25, p75, p99, volume_bn}] newest first."""
    if not isinstance(body, dict) or not isinstance(body.get("refRates"), list):
        raise ParseError("NY FED ANSWER HAS NO refRates LIST")
    out = []
    for r in body["refRates"]:
        if r.get("percentRate") is None:
            continue
        out.append({"date": r.get("effectiveDate"), "type": r.get("type"), "rate": _num(r.get("percentRate")),
                    "p1": _num(r.get("percentPercentile1")), "p25": _num(r.get("percentPercentile25")),
                    "p75": _num(r.get("percentPercentile75")), "p99": _num(r.get("percentPercentile99")),
                    "volume_bn": _num(r.get("volumeInBillions"))})
    if not out:
        raise ParseError("NY FED ANSWER HAS NO RATES")
    return sorted(out, key=lambda r: r["date"] or "", reverse=True)


def ecb_csv(text: str) -> list[tuple[str, float]]:
    """ECB data portal `format=csvdata`: (TIME_PERIOD, OBS_VALUE) pairs, newest first."""
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows or "TIME_PERIOD" not in rows[0] or "OBS_VALUE" not in rows[0]:
        raise ParseError("ECB CSV HAS NO TIME_PERIOD / OBS_VALUE COLUMNS")
    out = [(r["TIME_PERIOD"], v) for r in rows if (v := _num(r["OBS_VALUE"])) is not None]
    return sorted(out, reverse=True)


def boe_csv(text: str, code: str) -> list[tuple[str, float]]:
    """Bank of England IADB CSV ('DATE,<CODE>' then '01 Oct 2026,3.7331'): (YYYY-MM-DD, value), newest first."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines or not lines[0].upper().startswith("DATE") or code.upper() not in lines[0].upper():
        raise ParseError(f"BOE CSV HAS NO DATE,{code} HEADER")
    out = []
    for ln in lines[1:]:
        d, _, v = ln.partition(",")
        try:
            iso = datetime.strptime(d.strip(), "%d %b %Y").date().isoformat()
        except ValueError as e:
            raise ParseError(f"BOE CSV BAD DATE {d[:12]}") from e
        if (x := _num(v)) is not None:
            out.append((iso, x))
    return sorted(out, reverse=True)


# --- GDPNow and SPF workbooks -------------------------------------------------------------------------------------------------


def gdpnow(data: bytes) -> dict:
    """Current quarter's nowcast path (sheet CurrentQtrEvolution: date, releases, GDP) and the final nowcast of each past quarter
    (sheet TrackingArchives: forecast date, quarter, ..., GDP), with each past quarter's own path."""
    try:
        cur = xlsx.read_sheet(data, "CurrentQtrEvolution")
        arch = xlsx.read_sheet(data, "TrackingArchives")
    except xlsx.XlsxError as e:
        raise ParseError(f"GDPNOW WORKBOOK: {e}") from e
    if not cur or [str(x).strip() for x in cur[0][:3]] != ["Date", "Major Releases", "GDP*"]:
        raise ParseError("GDPNOW CurrentQtrEvolution HEADER CHANGED")
    path = []
    for r in cur[1:]:
        d = xlsx.excel_date(r[0] if r else None)
        if d is None or len(r) < 3 or _num(r[2]) is None:
            continue
        path.append({"date": d.isoformat(), "releases": str(r[1] or "").strip(), "gdp": _num(r[2])})
    if not path:
        raise ParseError("GDPNOW HAS NO CURRENT-QUARTER PATH")
    head = [str(x or "").strip() for x in arch[0]] if arch else []
    need = ("Forecast Date", "Quarter being forecasted", "GDP Nowcast", "Advance Estimate From BEA")
    if any(h not in head for h in need):
        raise ParseError("GDPNOW TrackingArchives HEADER CHANGED")
    i_d, i_q, i_g, i_b = (head.index(h) for h in need)
    quarters: dict[str, list[dict]] = {}
    for r in arch[1:]:
        if len(r) <= max(i_d, i_q, i_g):
            continue
        d, q, g = xlsx.excel_date(r[i_d]), xlsx.excel_date(r[i_q]), _num(r[i_g])
        if d is None or q is None or g is None:
            continue
        bea = _num(r[i_b]) if len(r) > i_b else None
        quarters.setdefault(f"{q.year}Q{(q.month - 1) // 3 + 1}", []).append({"date": d.isoformat(), "gdp": g, "bea": bea})
    past = [{"quarter": k, "first": v[0]["gdp"], "final": v[-1]["gdp"], "first_date": v[0]["date"], "final_date": v[-1]["date"],
             "bea": next((x["bea"] for x in reversed(v) if x["bea"] is not None), None), "n": len(v),
             "path": [{"date": x["date"], "gdp": x["gdp"]} for x in v]} for k, v in sorted(quarters.items())]
    return {"path": path, "past": past}


SPF_FILES = {"RGDP": ("median_rgdp_growth.xlsx", "Median_Growth", "DRGDP", "REAL GDP GROWTH, ANNUALISED Q/Q %"),
             "CPI": ("median_cpi_level.xlsx", "CPI", "CPI", "CPI INFLATION, ANNUALISED Q/Q %"),
             "UNEMP": ("median_unemp_level.xlsx", "UNEMP", "UNEMP", "UNEMPLOYMENT RATE %"),
             "TBOND": ("median_tbond_level.xlsx", "TBOND", "TBOND", "10-YEAR TREASURY YIELD %")}


def spf(data: bytes, sheet: str | None = None) -> dict:
    """One SPF median workbook: the latest survey's row. Columns <VAR>2..6 are the current quarter and the next four; <VAR>A..D (level
    files) are annual averages for this year and the next ones. Returns {survey: '2026Q4', quarterly: [..5], annual: [..]}."""
    try:
        name = sheet or xlsx.sheet_names(data)[0]
        rows = xlsx.read_sheet(data, name)
    except xlsx.XlsxError as e:
        raise ParseError(f"SPF WORKBOOK: {e}") from e
    if not rows or [str(x).upper() for x in rows[0][:2]] != ["YEAR", "QUARTER"]:
        raise ParseError("SPF HEADER IS NOT YEAR, QUARTER, ...")
    head = [str(x or "") for x in rows[0]]
    body = [r for r in rows[1:] if len(r) > 2 and _num(r[0]) is not None]
    if not body:
        raise ParseError("SPF FILE HAS NO SURVEY ROWS")
    last = body[-1]
    y, q = int(_num(last[0]) or 0), int(_num(last[1]) or 0)
    quarterly, annual = [], []
    for i, h in enumerate(head[2:], start=2):
        v = _num(last[i]) if i < len(last) else None
        m = re.match(r"^[A-Z]+?(\d)$", h)
        if m:
            k = int(m.group(1))  # 1 = previous quarter (known), 2 = current, 3..6 = the next four
            qi = (y * 4 + (q - 1)) + (k - 2)
            quarterly.append({"col": h, "period": f"{qi // 4}Q{qi % 4 + 1}", "value": v})
        elif re.match(r"^[A-Z]+[A-D]$", h):
            annual.append({"col": h, "period": str(y + "ABCD".index(h[-1])), "value": v})
    return {"survey": f"{y}Q{q}", "quarterly": quarterly, "annual": annual}


# --- IMF DataMapper and OECD Economic Outlook ---------------------------------------------------------------------------------


def imf_datamapper(body: Any, indicator: str) -> dict[str, dict[str, float]]:
    """{country: {year: value}} for one indicator. The API answers {"values": {IND: {ISO3: {year: value}}}}."""
    try:
        block = body["values"][indicator]
    except (KeyError, TypeError) as e:
        raise ParseError(f"IMF DATAMAPPER ANSWER HAS NO values.{indicator}") from e
    return {c: {y: float(v) for y, v in ys.items() if isinstance(v, (int, float))} for c, ys in block.items() if isinstance(ys, dict)}


def oecd_csv(text: str) -> dict[tuple[str, str], dict[str, float]]:
    """SDMX `format=csvfile`: {(REF_AREA, MEASURE): {TIME_PERIOD: OBS_VALUE}}."""
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows or not {"REF_AREA", "MEASURE", "TIME_PERIOD", "OBS_VALUE"} <= set(rows[0]):
        raise ParseError("OECD CSV HAS NO REF_AREA / MEASURE / TIME_PERIOD / OBS_VALUE")
    out: dict[tuple[str, str], dict[str, float]] = {}
    for r in rows:
        v = _num(r["OBS_VALUE"])
        if v is not None:
            out.setdefault((r["REF_AREA"], r["MEASURE"]), {})[r["TIME_PERIOD"]] = v
    return out


# --- FOMC statements ----------------------------------------------------------------------------------------------------------

_P = re.compile(r"<p[^>]*>(.*?)</p>", re.DOTALL | re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")


def fomc_statement(page: str) -> list[str]:
    """The statement's paragraphs from a federalreserve.gov press release page (the 8-column article body), up to the vote."""
    i = page.find('<div class="col-xs-12 col-sm-8 col-md-8">')
    if i < 0:
        raise ParseError("FOMC PAGE HAS NO ARTICLE BODY")
    paras = []
    for m in _P.finditer(page, i):
        text = " ".join(_html.unescape(_TAG.sub("", m.group(1))).split())
        if not text:
            continue
        if text.startswith(("For media inquiries", "Implementation Note")):
            break
        paras.append(text)
    if len(paras) < 2:
        raise ParseError("FOMC PAGE HAS NO STATEMENT TEXT")
    return paras


def word_diff(old: list[str], new: list[str]) -> list[dict]:
    """Word-level differences between two statements: [{op: SAME|ADDED|REMOVED, text}] in reading order (paragraph breaks = ¶)."""
    a = " ¶ ".join(old).split()
    b = " ¶ ".join(new).split()
    out: list[dict] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if tag == "equal":
            out.append({"op": "SAME", "text": " ".join(a[i1:i2])})
            continue
        if tag in ("delete", "replace"):
            out.append({"op": "REMOVED", "text": " ".join(a[i1:i2])})
        if tag in ("insert", "replace"):
            out.append({"op": "ADDED", "text": " ".join(b[j1:j2])})
    return out


# --- TreasuryDirect securities --------------------------------------------------------------------------------------------------

TD_KEEP = ("cusip", "securityType", "securityTerm", "auctionDate", "issueDate", "maturityDate", "interestRate", "highYield",
           "highDiscountRate", "highInvestmentRate", "bidToCoverRatio", "offeringAmount", "totalAccepted", "type", "announcementDate")


def td_securities(body: Any) -> list[dict]:
    if not isinstance(body, list):
        raise ParseError("TREASURYDIRECT ANSWER IS NOT A LIST")
    out = []
    for r in body:
        if not isinstance(r, dict) or not r.get("cusip"):
            continue
        row = {k: r.get(k) for k in TD_KEEP}
        for k in ("auctionDate", "issueDate", "maturityDate", "announcementDate"):
            row[k] = (row[k] or "")[:10] or None
        for k in ("interestRate", "highYield", "highDiscountRate", "highInvestmentRate", "bidToCoverRatio", "offeringAmount", "totalAccepted"):
            row[k] = _num(row[k])
        out.append(row)
    return out


# --- WASDE XML ----------------------------------------------------------------------------------------------------------------

#: The three US tables AGRI shows: (sub-report, matrix tag, label)
WASDE_TABLES = (("sr11", "matrix1", "US WHEAT"), ("sr12", "matrix2", "US CORN"), ("sr15", "matrix1", "US SOYBEANS"))


def wasde(text: str) -> dict:
    """{month, tables: [{label, unit_note, columns: [..], rows: [{item, values: {column: value}}]}]} for WASDE_TABLES."""
    try:
        root = ET.fromstring(text.lstrip("﻿"))
    except ET.ParseError as e:
        raise ParseError("WASDE XML DOES NOT PARSE") from e
    tables, month = [], None
    for sr, mx, label in WASDE_TABLES:
        node = root.find(sr)
        rep = node[0] if node is not None and len(node) else None
        matrix = rep.find(mx) if rep is not None else None
        if matrix is None:
            raise ParseError(f"WASDE HAS NO {sr}/{mx}")
        month = month or rep.get("Report_Month")
        cols: list[str] = []
        rows = []
        for el in matrix.iter():
            name = next((v for k, v in el.attrib.items() if re.fullmatch(r"attribute\d+", k)), None)
            if name is None:
                continue
            values: dict[str, float | None] = {}
            for yg in el.iter():
                year = next((v for k, v in yg.attrib.items() if re.fullmatch(r"market_year\d+", k)), None)
                if year is None:
                    continue
                for mg in yg.iter():
                    fm = next((v for k, v in mg.attrib.items() if re.fullmatch(r"forecast_month\d+", k)), None)
                    if fm is None:
                        continue
                    cell = mg.find("Cell")
                    val = next((v for k, v in (cell.attrib.items() if cell is not None else []) if re.fullmatch(r"cell_value\d+", k)), None)
                    col = f"{year.strip()} {fm.strip()}".strip()
                    if col not in cols:
                        cols.append(col)
                    values[col] = _num(val)
            rows.append({"item": " ".join(name.split()), "values": values})
        tables.append({"label": label, "title": " ".join((rep.get("sub_report_title") or "").split()), "columns": cols, "rows": rows})
    return {"month": month, "tables": tables}


def wasde_links(page: str) -> list[dict]:
    """Release files on the Cornell WASDE publication page: [{month: 'MMYY', xml, txt, xls}] newest first."""
    found: dict[str, dict] = {}
    for m in re.finditer(r'href="(/sites/default/release-files/\d+/wasde(\d{4})\.(xml|txt|xls|pdf))"', page):
        found.setdefault(m.group(2), {"mmyy": m.group(2)})[m.group(3)] = "https://usda.library.cornell.edu" + m.group(1)
    rows = list(found.values())
    rows.sort(key=lambda r: (r["mmyy"][2:], r["mmyy"][:2]), reverse=True)
    if not rows:
        raise ParseError("CORNELL WASDE PAGE LISTS NO RELEASE FILES")
    return rows


# --- EIA API v2 and NASS QuickStats (keyed) -------------------------------------------------------------------------------------


def eia_series(body: Any) -> dict:
    """EIA v2 `seriesid/<ID>` answer -> {description, units, points: [(period, value)] newest first}."""
    try:
        data = body["response"]["data"]
    except (KeyError, TypeError) as e:
        raise ParseError("EIA ANSWER HAS NO response.data") from e
    if not data:
        raise ParseError("EIA ANSWER HAS NO OBSERVATIONS")
    pts = sorted(((str(r.get("period")), _num(r.get("value"))) for r in data if _num(r.get("value")) is not None), reverse=True)
    first = data[0]
    return {"description": first.get("series-description") or first.get("seriesDescription"), "units": first.get("units"), "points": pts}


def nass(body: Any) -> list[dict]:
    """QuickStats api_GET JSON -> rows {commodity, statistic, unit, week_ending, year, value}."""
    if not isinstance(body, dict) or not isinstance(body.get("data"), list):
        raise ParseError("NASS ANSWER HAS NO data LIST")
    out = []
    for r in body["data"]:
        out.append({"commodity": r.get("commodity_desc"), "statistic": r.get("short_desc"), "unit": r.get("unit_desc"),
                    "week_ending": r.get("week_ending"), "year": r.get("year"), "value": _num(r.get("Value"))})
    return out


# --- Yahoo fund modules (WPE) -------------------------------------------------------------------------------------------------


def etf_valuation(body: Any) -> dict:
    """quoteSummary modules summaryDetail + topHoldings -> {pe, pb, ps, yield, price}. Values are what Yahoo reports for the fund.
    Yahoo prints the holdings' ratios as RECIPROCALS (topHoldings.equityHoldings.priceToEarnings = 0.0416 for SPY = earnings yield,
    i.e. P/E 24.0; checked against the fund pages 2026-11-24), so they are inverted here. summaryDetail.trailingPE is a plain P/E."""
    try:
        res = body["quoteSummary"]["result"][0]
    except (KeyError, TypeError, IndexError) as e:
        raise ParseError("YAHOO ANSWER HAS NO quoteSummary.result") from e

    def raw(d: Any, k: str) -> float | None:
        v = (d or {}).get(k)
        return _num(v.get("raw")) if isinstance(v, dict) else _num(v)

    def inv(d: Any, k: str) -> float | None:
        v = raw(d, k)
        return 1.0 / v if v else None

    sd, eq = res.get("summaryDetail") or {}, ((res.get("topHoldings") or {}).get("equityHoldings") or {})
    pe = inv(eq, "priceToEarnings")
    return {"pe": pe if pe is not None else raw(sd, "trailingPE"), "pb": inv(eq, "priceToBook"), "ps": inv(eq, "priceToSales"),
            "yield": raw(sd, "yield"), "price": raw(sd, "previousClose"), "pe_source": "holdings" if pe is not None else "fund"}
