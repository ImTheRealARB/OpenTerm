"""Pure parsers for SEC EDGAR data: XBRL company facts -> statements, submissions -> filings, Form 4 XML -> trades.

No I/O here, so every rule (tag fallbacks, dedup, fiscal labels, derived quarters) is unit-tested on recorded data.

Company facts traps handled:
- `fy`/`fp` on a fact describe the FILING, not the fact's period (a 10-K for FY2025 also carries FY2024 and
  FY2023 values tagged fy=2025). Periods are therefore keyed by their own dates (start, end); `fy`/`fp` only
  label a period when the period is the filing's own (latest) period.
- The same value is repeated in every later filing that shows it as a comparative, and restatements change it.
  Per period we keep the fact from the latest `filed` 10-K/10-Q (8-K and other forms are ignored).
- Companies switch tags over time (Apple: SalesRevenueNet -> RevenueFromContractWithCustomer...), so each row
  tries its tags in order per period.
- 10-Q cash-flow statements are year-to-date only, and nobody files a fourth-quarter 10-Q. A quarter missing a
  3-month fact is derived as YTD minus the shorter YTD with the same start (Q4 = FY - 9M); such cells are
  flagged "d". Per-share and share-count rows are never derived (subtraction is not valid for them).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date

ANNUAL_FORMS = {"10-K", "10-K/A", "10-KT", "10-KT/A"}
FORMS = ANNUAL_FORMS | {"10-Q", "10-Q/A"}
ANNUAL_DAYS = (340, 390)  # 52/53-week years are 364/371 days
QUARTER_DAYS = (80, 100)  # 13/14-week quarters are 91/98 days
MAX_PERIODS = {"A": 12, "Q": 16}

# (statement, key, label, kind dur|inst, unit, tags in priority order)
ROWS: list[tuple[str, str, str, str, str, tuple[str, ...]]] = [
    ("IS", "revenue", "Revenue", "dur", "USD", (
        "RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
        "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet", "SalesRevenueGoodsNet",
    )),
    ("IS", "cost_of_revenue", "Cost of revenue", "dur", "USD", (
        "CostOfGoodsAndServicesSold", "CostOfRevenue", "CostOfGoodsSold",
    )),
    ("IS", "gross_profit", "Gross profit", "dur", "USD", ("GrossProfit",)),
    ("IS", "rnd", "Research and development", "dur", "USD", ("ResearchAndDevelopmentExpense",)),
    ("IS", "sga", "Selling, general and admin", "dur", "USD", ("SellingGeneralAndAdministrativeExpense",)),
    ("IS", "operating_income", "Operating income", "dur", "USD", ("OperatingIncomeLoss",)),
    ("IS", "pretax_income", "Pretax income", "dur", "USD", (
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    )),
    ("IS", "income_tax", "Income tax", "dur", "USD", ("IncomeTaxExpenseBenefit",)),
    ("IS", "net_income", "Net income", "dur", "USD", ("NetIncomeLoss", "ProfitLoss")),
    ("IS", "eps_basic", "EPS basic", "dur", "USD/shares", ("EarningsPerShareBasic",)),
    ("IS", "eps_diluted", "EPS diluted", "dur", "USD/shares", ("EarningsPerShareDiluted",)),
    ("IS", "shares_diluted", "Diluted shares (avg)", "dur", "shares", ("WeightedAverageNumberOfDilutedSharesOutstanding",)),
    ("BS", "cash", "Cash and equivalents", "inst", "USD", (
        "CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    )),
    ("BS", "current_assets", "Current assets", "inst", "USD", ("AssetsCurrent",)),
    ("BS", "total_assets", "Total assets", "inst", "USD", ("Assets",)),
    ("BS", "current_liabilities", "Current liabilities", "inst", "USD", ("LiabilitiesCurrent",)),
    ("BS", "total_liabilities", "Total liabilities", "inst", "USD", ("Liabilities",)),
    ("BS", "current_debt", "Current debt", "inst", "USD", ("LongTermDebtCurrent", "DebtCurrent")),
    ("BS", "long_term_debt", "Long-term debt", "inst", "USD", ("LongTermDebtNoncurrent", "LongTermDebt")),
    ("BS", "equity", "Shareholders' equity", "inst", "USD", (
        "StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    )),
    ("CF", "operating_cf", "Operating cash flow", "dur", "USD", ("NetCashProvidedByUsedInOperatingActivities",)),
    ("CF", "capex", "Capital expenditure", "dur", "USD", ("PaymentsToAcquirePropertyPlantAndEquipment",)),
    ("CF", "investing_cf", "Investing cash flow", "dur", "USD", ("NetCashProvidedByUsedInInvestingActivities",)),
    ("CF", "financing_cf", "Financing cash flow", "dur", "USD", ("NetCashProvidedByUsedInFinancingActivities",)),
    ("CF", "dividends", "Dividends paid", "dur", "USD", ("PaymentsOfDividends", "PaymentsOfDividendsCommonStock")),
    ("CF", "buybacks", "Share repurchases", "dur", "USD", ("PaymentsForRepurchaseOfCommonStock",)),
]
# Only used to fill Total liabilities when the filer does not tag it (flagged "c" = computed).
HELPER_TAGS = ("LiabilitiesAndStockholdersEquity",)
TAGS = sorted({t for r in ROWS for t in r[5]} | set(HELPER_TAGS))
"""Every us-gaap tag OpenTerm reads (fixtures are trimmed to these)."""


def _d(s: str) -> date:
    return date.fromisoformat(s)


def _days(f: dict) -> int:
    return (_d(f["end"]) - _d(f["start"])).days + 1 if f.get("start") else 0


class _Tag:
    """Deduplicated facts of one tag in one unit: {(start, end): fact from the latest filing}."""

    def __init__(self, facts: list[dict]):
        self.by: dict[tuple[str | None, str], dict] = {}
        for f in facts:
            if f.get("form") not in FORMS or not isinstance(f.get("val"), (int, float)) or not f.get("end"):
                continue
            k = (f.get("start"), f["end"])
            cur = self.by.get(k)
            if cur is None or (f.get("filed", ""), f.get("accn", "")) > (cur.get("filed", ""), cur.get("accn", "")):
                self.by[k] = f
        self.by_end: dict[str, list[dict]] = {}
        for f in self.by.values():
            self.by_end.setdefault(f["end"], []).append(f)

    def instant(self, end: str) -> dict | None:
        for f in self.by_end.get(end, ()):
            if not f.get("start"):
                return f
        return None

    def duration(self, end: str, lo: int, hi: int, annual_only: bool = False) -> dict | None:
        for f in self.by_end.get(end, ()):
            if f.get("start") and lo <= _days(f) <= hi and (not annual_only or f["form"] in ANNUAL_FORMS):
                return f
        return None

    def derived_quarter(self, end: str) -> tuple[float, dict] | None:
        """YTD ending `end` minus the YTD with the same start that is one quarter shorter."""
        for a in sorted(self.by_end.get(end, ()), key=_days, reverse=True):
            if not a.get("start") or _days(a) <= QUARTER_DAYS[1]:
                continue
            for b in self.by.values():
                if b.get("start") == a["start"] and b["end"] < end and QUARTER_DAYS[0] <= _days(a) - _days(b) <= QUARTER_DAYS[1]:
                    return a["val"] - b["val"], a
        return None


def _tags(gaap: dict, unit: str, names: tuple[str, ...]) -> list[tuple[str, _Tag]]:
    out = []
    for n in names:
        facts = ((gaap.get(n) or {}).get("units") or {}).get(unit)
        if facts:
            out.append((n, _Tag(facts)))
    return out


def _own_periods(gaap: dict) -> dict[str, dict]:
    """Period end -> the filing whose own (latest) period ends there: its fy, fp, form and filing date."""
    best: dict[str, dict] = {}  # accn -> fact with the latest end in that filing
    for name in TAGS:
        for facts in ((gaap.get(name) or {}).get("units") or {}).values():
            for f in facts:
                if f.get("form") not in FORMS or not f.get("fy") or not f.get("fp"):
                    continue
                cur = best.get(f["accn"])
                if cur is None or f["end"] > cur["end"]:
                    best[f["accn"]] = f
    own: dict[str, dict] = {}
    for f in best.values():
        cur = own.get(f["end"])
        # The original filing names the period; amendments keep the same fy/fp anyway.
        if cur is None or f.get("filed", "") < cur.get("filed", ""):
            own[f["end"]] = {"fy": f["fy"], "fp": f["fp"], "form": f["form"], "filed": f.get("filed")}
    return own


def _label(end: str, mode: str, own: dict[str, dict]) -> tuple[str, int | None, str | None]:
    o = own.get(end)
    if o:
        fy, fp = o["fy"], o["fp"]
        if mode == "A":
            return f"FY{fy}", fy, "FY"
        return (f"Q4 FY{fy}" if fp == "FY" else f"{fp} FY{fy}"), fy, ("Q4" if fp == "FY" else fp)
    # A comparative period older than any filing in the data: name it by its end date.
    return end, None, None


def _statements(gaap: dict, mode: str, own: dict[str, dict]) -> dict:
    lo, hi = ANNUAL_DAYS if mode == "A" else QUARTER_DAYS
    rows_tags = [(r, _tags(gaap, r[4], r[5])) for r in ROWS]

    # Column set: annual = ends of ~1-year durations from 10-Ks; quarterly = ends of ~3-month durations,
    # plus fiscal-year ends (Q4) and every 10-Q's own period end.
    ends: set[str] = set()
    for (stmt, _k, _l, kind, unit, _t), tags in rows_tags:
        if kind != "dur":
            continue
        for _n, t in tags:
            for f in t.by.values():
                if not f.get("start"):
                    continue
                n = _days(f)
                annual = ANNUAL_DAYS[0] <= n <= ANNUAL_DAYS[1]
                quarter = QUARTER_DAYS[0] <= n <= QUARTER_DAYS[1]
                if (annual and f["form"] in ANNUAL_FORMS) if mode == "A" else (annual or quarter):
                    ends.add(f["end"])
    if mode == "Q":
        ends |= {e for e, o in own.items() if o["fp"] in ("Q1", "Q2", "Q3")}
    cols = sorted(ends, reverse=True)[: MAX_PERIODS[mode]]

    statements: dict[str, list[dict]] = {"IS": [], "BS": [], "CF": []}
    starts: dict[str, str] = {}
    for (stmt, key, label, kind, unit, _t), tags in rows_tags:
        values: list[float | None] = []
        flags: list[str] = []
        used: list[str | None] = []
        for end in cols:
            v, flag, tag = None, "", None
            for name, t in tags:
                if kind == "inst":
                    f = t.instant(end)
                else:
                    f = t.duration(end, lo, hi, annual_only=mode == "A")
                if f is not None:
                    v, tag = f["val"], name
                    if kind == "dur":
                        starts.setdefault(end, f["start"])
                    break
                if kind == "dur" and mode == "Q" and unit == "USD":
                    got = t.derived_quarter(end)
                    if got is not None:
                        v, flag, tag = got[0], "d", name
                        break
            values.append(v)
            flags.append(flag)
            used.append(tag)
        statements[stmt].append({"key": key, "label": label, "unit": unit, "values": values, "flags": flags, "tags": used})

    by_key = {r["key"]: r for rows in statements.values() for r in rows}
    # Total liabilities when not tagged: liabilities and equity minus equity (includes any temporary equity).
    tl, eq = by_key["total_liabilities"], by_key["equity"]
    helper = _tags(gaap, "USD", HELPER_TAGS)
    for i, end in enumerate(cols):
        if tl["values"][i] is None and eq["values"][i] is not None and helper:
            f = helper[0][1].instant(end)
            if f is not None:
                tl["values"][i] = f["val"] - eq["values"][i]
                tl["flags"][i] = "c"
                tl["tags"][i] = "LiabilitiesAndStockholdersEquity - StockholdersEquity"
    # Free cash flow is always computed: operating cash flow minus capital expenditure.
    ocf, capex = by_key["operating_cf"], by_key["capex"]
    fcf = {"key": "fcf", "label": "Free cash flow (computed)", "unit": "USD", "values": [], "flags": [], "tags": [], "computed": True}
    for i in range(len(cols)):
        a, b = ocf["values"][i], capex["values"][i]
        fcf["values"].append(a - b if a is not None and b is not None else None)
        fcf["flags"].append("d" if "d" in (ocf["flags"][i], capex["flags"][i]) else "c")
        fcf["tags"].append("NetCashProvidedByUsedInOperatingActivities - PaymentsToAcquirePropertyPlantAndEquipment")
    statements["CF"].insert(2, fcf)

    periods = []
    for i, end in enumerate(cols):
        lbl, fy, fp = _label(end, mode, own)
        o = own.get(end) or {}
        periods.append({
            "key": end, "label": lbl, "end": end, "start": starts.get(end), "fy": fy, "fp": fp,
            "form": o.get("form"), "filed": o.get("filed"),
            "derived": any(r["flags"][i] == "d" for rows in statements.values() for r in rows),
        })
    return {"periods": periods, "statements": statements}


def parse_companyfacts(body: dict) -> dict:
    """Both views at once (one upstream call serves A and Q). Raises ValueError when nothing is mapped."""
    gaap = (body.get("facts") or {}).get("us-gaap") or {}
    own = _own_periods(gaap)
    out = {"cik": body.get("cik"), "name": body.get("entityName"), "currency": "USD",
           "A": _statements(gaap, "A", own), "Q": _statements(gaap, "Q", own)}
    if not out["A"]["periods"] and not out["Q"]["periods"]:
        raise ValueError("no US-GAAP statements in the company facts")
    return out


# --- submissions ------------------------------------------------------------------------------
ITEMS_8K = {
    "1.01": "Material agreement", "1.02": "Agreement terminated", "1.03": "Bankruptcy", "1.05": "Cybersecurity incident",
    "2.01": "Acquisition or disposal", "2.02": "Results of operations", "2.03": "New obligation",
    "2.05": "Exit costs", "2.06": "Impairment", "3.01": "Delisting notice", "3.02": "Unregistered equity sale",
    "3.03": "Holder rights changed", "4.01": "Auditor change", "4.02": "Non-reliance on financials",
    "5.01": "Change in control", "5.02": "Officer/director change", "5.03": "Bylaws/charter change",
    "5.07": "Shareholder vote", "7.01": "Reg FD disclosure", "8.01": "Other events", "9.01": "Exhibits",
}
FORM_NAMES = {
    "10-K": "Annual report", "10-Q": "Quarterly report", "8-K": "Current report", "4": "Insider transaction",
    "3": "Initial insider holdings", "5": "Annual insider holdings", "144": "Proposed sale of restricted stock",
    "DEF 14A": "Proxy statement", "S-8": "Employee plan registration", "SC 13G": "Beneficial ownership (passive)",
    "SCHEDULE 13G": "Beneficial ownership (passive)", "SC 13D": "Beneficial ownership (active)",
    "SCHEDULE 13D": "Beneficial ownership (active)", "11-K": "Employee plan annual report",
    "424B2": "Prospectus", "FWP": "Free writing prospectus", "S-3ASR": "Shelf registration",
    "PX14A6G": "Exempt solicitation", "ARS": "Annual report to holders", "25-NSE": "Delisting of a class",
}


def archive_base(cik: int, accession: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}"


def describe(form: str, doc_desc: str, items: str) -> str:
    base = form.removesuffix("/A")
    text = FORM_NAMES.get(base) or (doc_desc if doc_desc and doc_desc.upper() not in (form, f"FORM {form}") else "")
    if items and base == "8-K":
        names = [f"{i} {ITEMS_8K[i]}" if i in ITEMS_8K else i for i in items.split(",") if i]
        text = f"{text}: {'; '.join(names)}" if text else "; ".join(names)
    if form.endswith("/A"):
        text = f"{text} (amendment)" if text else "Amendment"
    return text


def parse_submissions(body: dict) -> dict:
    cik = int(body.get("cik") or 0)
    r = (body.get("filings") or {}).get("recent") or {}
    n = len(r.get("accessionNumber") or [])

    def col(k: str) -> list:
        v = r.get(k) or []
        return v if len(v) == n else [""] * n

    acc, filed, report, form, items, doc, desc = (col(k) for k in (
        "accessionNumber", "filingDate", "reportDate", "form", "items", "primaryDocument", "primaryDocDescription"))
    filings = []
    for i in range(n):
        base = archive_base(cik, acc[i])
        filings.append({
            "accession": acc[i], "filed": filed[i], "report_date": report[i] or None, "form": form[i],
            "description": describe(form[i], desc[i] or "", items[i] or ""), "items": items[i] or None,
            "primary_doc": doc[i] or None,
            "url": f"{base}/{acc[i]}-index.htm",
            "doc_url": f"{base}/{doc[i]}" if doc[i] else None,
        })
    return {
        "cik": cik, "name": body.get("name"), "tickers": body.get("tickers") or [],
        "exchanges": body.get("exchanges") or [], "fiscal_year_end": body.get("fiscalYearEnd"),
        "sic": body.get("sicDescription"), "filings": filings,
    }


def form4_xml_url(cik: int, accession: str, primary_doc: str) -> str:
    """primaryDocument points at the XSL-rendered HTML (xslF345X06/form4.xml); the raw XML drops that folder."""
    return f"{archive_base(cik, accession)}/{primary_doc.rsplit('/', 1)[-1]}"


# --- Form 4 -----------------------------------------------------------------------------------
CODES = {
    "P": "Open-market purchase", "S": "Open-market sale", "A": "Grant or award", "M": "Option exercise",
    "F": "Tax withholding", "G": "Gift", "D": "Disposed to issuer", "C": "Conversion", "X": "Option exercise (ITM)",
    "O": "Option exercise (OTM)", "J": "Other", "W": "Will or inheritance", "I": "Discretionary",
    "K": "Equity swap", "L": "Small acquisition", "E": "Short derivative expired", "H": "Long derivative expired",
    "U": "Tender of shares", "Z": "Voting trust", "V": "Voluntarily reported",
}


def _text(el: ET.Element | None, path: str) -> str | None:
    if el is None:
        return None
    node = el.find(path)
    if node is None or node.text is None:
        return None
    return node.text.strip() or None


def _num(el: ET.Element | None, path: str) -> float | None:
    s = _text(el, path)
    try:
        return float(s) if s is not None else None
    except ValueError:
        return None


def _flag(el: ET.Element | None, path: str) -> bool:
    return (_text(el, path) or "").lower() in ("1", "true")


def parse_form4(xml: bytes | str, accession: str = "", filed: str = "", url: str = "") -> list[dict]:
    """One row per reported transaction (holdings without a transaction are skipped). Raises ValueError on bad XML."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        raise ValueError(f"form 4 XML: {e}") from e
    if root.tag != "ownershipDocument":
        raise ValueError("not a Form 4 ownership document")
    owners = []
    for ro in root.findall("reportingOwner"):
        rel = ro.find("reportingOwnerRelationship")
        roles = []
        if _flag(rel, "isDirector"):
            roles.append("Director")
        if _flag(rel, "isOfficer"):
            roles.append(_text(rel, "officerTitle") or "Officer")
        if _flag(rel, "isTenPercentOwner"):
            roles.append("10% owner")
        if _flag(rel, "isOther"):
            roles.append(_text(rel, "otherText") or "Other")
        owners.append({
            "owner": _text(ro, "reportingOwnerId/rptOwnerName") or "",
            "owner_cik": _text(ro, "reportingOwnerId/rptOwnerCik"),
            "relation": ", ".join(roles),
        })
    if not owners:
        owners = [{"owner": "", "owner_cik": None, "relation": ""}]
    owner = owners[0]
    if len(owners) > 1:  # joint filers: the first is the primary reporting person
        owner = {**owner, "owner": f"{owner['owner']} +{len(owners) - 1}"}
    out = []
    for table, tag, derivative in (("nonDerivativeTable", "nonDerivativeTransaction", False),
                                   ("derivativeTable", "derivativeTransaction", True)):
        for t in root.findall(f"{table}/{tag}"):
            code = _text(t, "transactionCoding/transactionCode") or ""
            shares = _num(t, "transactionAmounts/transactionShares/value")
            price = _num(t, "transactionAmounts/transactionPricePerShare/value")
            out.append({
                **owner,
                "date": _text(t, "transactionDate/value"),
                "code": code,
                "code_text": CODES.get(code, code),
                "acq_disp": _text(t, "transactionAmounts/transactionAcquiredDisposedCode/value"),
                "shares": shares,
                "price": price,
                "value": shares * price if shares is not None and price else None,
                "owned_after": _num(t, "postTransactionAmounts/sharesOwnedFollowingTransaction/value"),
                "direct": _text(t, "ownershipNature/directOrIndirectOwnership/value"),
                "security": _text(t, "securityTitle/value"),
                "derivative": derivative,
                "accession": accession,
                "filed": filed,
                "url": url,
            })
    return out
