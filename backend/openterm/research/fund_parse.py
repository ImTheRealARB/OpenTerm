"""Pure parsers and payload builders for ETF, MEMB and MGR: SEC N-PORT fund holdings, 13F information tables, Yahoo fund data.

The 13F quarter-over-quarter diff follows the logic of Vibe-Trading's `_diff_positions` (HKUDS/Vibe-Trading @ d0db2e3
agent/src/tools/institutional_holdings_tool.py, MIT): positions are keyed on (CUSIP, put/call), shares and value are summed
over duplicate lines, and a position is NEW, EXITED, ADDED, TRIMMED or UNCHANGED by its share count. Written fresh here, not
copied; see THIRD_PARTY.md.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from ..providers.base import ProviderError
from ..providers.yahoo import _raw
from .table import col, head, payload, section

# ---------------------------------------------------------------------------------------------- XML helpers


def _strip(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(el: ET.Element, name: str) -> ET.Element | None:
    for c in el:
        if _strip(c.tag) == name:
            return c
    return None


def _text(el: ET.Element | None, name: str) -> str | None:
    c = _child(el, name) if el is not None else None
    t = (c.text or "").strip() if c is not None else ""
    return t or None


def _num(s: str | None) -> float | None:
    try:
        return float(s) if s is not None else None
    except ValueError:
        return None


def _root(xml: bytes | str) -> ET.Element:
    try:
        return ET.fromstring(xml)
    except ET.ParseError as e:
        raise ValueError(f"not XML: {e}") from e


# ---------------------------------------------------------------------------------------------- N-PORT


def parse_nport(xml: bytes | str) -> dict:
    """Fund name, period end, net assets and every position of one NPORT-P filing. `weight` is a ratio (pctVal is percent)."""
    root = _root(xml)
    if _strip(root.tag) != "edgarSubmission":
        raise ValueError("not an N-PORT filing")
    form = _child(root, "formData")
    if form is None:
        raise ValueError("N-PORT filing without formData")
    gen, info, secs = _child(form, "genInfo"), _child(form, "fundInfo"), _child(form, "invstOrSecs")
    holdings = []
    for s in (secs if secs is not None else []):
        isin = None
        ids = _child(s, "identifiers")
        if ids is not None:
            node = _child(ids, "isin")
            isin = node.get("value") if node is not None else None
        pct = _num(_text(s, "pctVal"))
        holdings.append({"name": _text(s, "name"), "title": _text(s, "title"), "cusip": _text(s, "cusip"), "isin": isin,
                         "balance": _num(_text(s, "balance")), "value": _num(_text(s, "valUSD")),
                         "weight": pct / 100.0 if pct is not None else None, "country": _text(s, "invCountry"),
                         "asset_cat": _text(s, "assetCat"), "payoff": _text(s, "payoffProfile"), "symbol": None})
    return {"reg_name": _text(gen, "regName"), "series_name": _text(gen, "seriesName"), "period_end": _text(gen, "repPdDate"),
            "net_assets": _num(_text(info, "netAssets")), "holdings": holdings}


_SUFFIX = {"inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited", "plc", "holdings", "holding", "group",
           "the", "class", "cl", "a", "b", "c", "common", "stock", "sa", "nv", "ag", "lp", "llc", "de", "new", "ord", "shs"}


def norm_name(name: str | None) -> str:
    words = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower().replace("&", " and ")).split()
    return " ".join(w for w in words if w not in _SUFFIX)


def name_index(tickers_body: dict) -> dict[str, list[str]]:
    """SEC company_tickers.json -> {normalised company name: [tickers]}."""
    out: dict[str, list[str]] = {}
    for r in (tickers_body or {}).values():
        n = norm_name(r.get("title"))
        if n and r.get("ticker"):
            out.setdefault(n, []).append(str(r["ticker"]).upper())
    return out


def match_tickers(holdings: list[dict], index: dict[str, list[str]]) -> int:
    """Fills `symbol` only when the normalised issuer name has exactly one SEC ticker. Returns how many matched."""
    n = 0
    for h in holdings:
        found = index.get(norm_name(h["name"]))
        if found and len(set(found)) == 1:
            h["symbol"] = found[0]
            n += 1
    return n


HOLDING_COLUMNS = [col("rank", "#", "int"), col("name", "NAME", "text", 34), col("symbol", "SYMBOL", "text", 8),
                   col("weight", "WEIGHT", "pct"), col("value", "VALUE USD", "money"), col("balance", "SHARES", "money"),
                   col("cusip", "CUSIP", "text", 9), col("country", "CTRY", "text", 4)]


def holding_rows(holdings: list[dict]) -> list[dict]:
    rows = sorted(holdings, key=lambda h: h["weight"] if h["weight"] is not None else -1.0, reverse=True)
    return [{"rank": i + 1, **{k: h[k] for k in ("name", "symbol", "weight", "value", "balance", "cusip", "country")}}
            for i, h in enumerate(rows)]


def yahoo_top_holdings(summary: dict) -> list[dict]:
    th = summary.get("topHoldings") or {}
    return [{"rank": i + 1, "name": h.get("holdingName"), "symbol": h.get("symbol"), "weight": _raw(h, "holdingPercent"),
             "value": None, "balance": None, "cusip": None, "country": None}
            for i, h in enumerate(th.get("holdings") or [])]


def fund_facts(summary: dict) -> dict:
    fp = summary.get("fundProfile") or {}
    fees = fp.get("feesExpensesInvestment") or {}
    th = summary.get("topHoldings") or {}
    sectors = []
    for item in th.get("sectorWeightings") or []:
        for k, v in item.items():
            sectors.append({"sector": k, "weight": _raw({"w": v}, "w")})
    sectors.sort(key=lambda s: s["weight"] or 0.0, reverse=True)
    return {"family": fp.get("family"), "category": fp.get("categoryName"), "legal": fp.get("legalType"),
            "expense_ratio": _raw(fees, "annualReportExpenseRatio"), "turnover": _raw(fees, "annualHoldingsTurnover"),
            "sectors": sectors, "stock_position": _raw(th, "stockPosition")}


def _pct(v: float | None, digits: int = 2) -> str | None:
    return f"{v * 100:.{digits}f}%" if v is not None else None


def _money(v: float | None) -> str | None:
    if v is None:
        return None
    a = abs(v)
    for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if a >= div:
            return f"{v / div:.2f}{suf}"
    return f"{v:,.0f}"


def etf_payload(symbol: str, summary: dict, nport: dict | None, source: str, title_prefix: str = "ETF",
                proxy: str | None = None, index_label: str | None = None) -> dict:
    facts = fund_facts(summary)
    notes: list[str] = []
    if nport:
        rows = holding_rows(nport["holdings"])
        matched = sum(1 for h in nport["holdings"] if h["symbol"])
        notes.append(f"TICKERS MATCHED BY NAME: {matched} OF {len(rows)} (APPROXIMATE: N-PORT HAS NO TICKER; AMBIGUOUS NAMES STAY BLANK)")
        notes.append("N-PORT IS FILED QUARTERLY AND PUBLISHED ABOUT 60 DAYS LATER: WEIGHTS ARE AS OF THE DATE SHOWN, NOT TODAY")
    else:
        rows = yahoo_top_holdings(summary)
        notes.append("TOP 10 ONLY (YAHOO): THE SEC N-PORT FILING WAS UNAVAILABLE")
    head_items = [head("FUND", (nport or {}).get("reg_name") or symbol),
                  head("FAMILY", facts["family"]), head("CATEGORY", facts["category"]),
                  head("EXPENSE RATIO", _pct(facts["expense_ratio"], 3) if facts["expense_ratio"] is not None else None, facts["expense_ratio"]),
                  head("NET ASSETS", _money(nport["net_assets"]) if nport else None, nport["net_assets"] if nport else None),
                  head("HOLDINGS AS OF", nport["period_end"] if nport else None),
                  head("HOLDINGS LISTED", str(len(rows)), len(rows))]
    if proxy:
        head_items.insert(0, head("PROXY ETF", proxy))
    first = "members" if proxy else "holdings"
    sections = [section(first, "CONSTITUENTS" if proxy else "HOLDINGS", HOLDING_COLUMNS, rows)]
    if facts["sectors"] and not proxy:
        sections.append(section("sectors", "SECTOR WEIGHTS (YAHOO)", [col("sector", "SECTOR", "text", 26), col("weight", "WEIGHT", "pct")],
                                facts["sectors"]))
    return payload(symbol, f"{title_prefix} {index_label or symbol}" + (" · INDEX MEMBERS" if proxy else " · FUND HOLDINGS"),
                   head_items, sections, notes, source)


# ---------------------------------------------------------------------------------------------- 13F

# The information-table `value` field was in thousands of dollars until the SEC changed it to whole dollars for filings
# made from 2023-01-03; older tables are multiplied so every period prints in dollars.
VALUE_IN_DOLLARS_FROM = "2023-01-03"


def parse_13f_table(xml: bytes | str, filed: str = "") -> list[dict]:
    root = _root(xml)
    mult = 1.0 if (filed or VALUE_IN_DOLLARS_FROM) >= VALUE_IN_DOLLARS_FROM else 1000.0
    out = []
    for t in root:
        if _strip(t.tag) != "infoTable":
            continue
        sh = _child(t, "shrsOrPrnAmt")
        out.append({"issuer": _text(t, "nameOfIssuer"), "class": _text(t, "titleOfClass"), "cusip": _text(t, "cusip"),
                    "value": (_num(_text(t, "value")) or 0.0) * mult, "shares": _num(_text(sh, "sshPrnamt")) or 0.0,
                    "unit": _text(sh, "sshPrnamtType") or "SH", "put_call": _text(t, "putCall")})
    if not out:
        raise ValueError("no positions in the information table")
    return out


def parse_13f_primary(xml: bytes | str) -> dict:
    root = _root(xml)
    period = None
    for el in root.iter():
        if _strip(el.tag) == "periodOfReport":
            period = (el.text or "").strip()
    manager = None
    for el in root.iter():
        if _strip(el.tag) == "filingManager":
            manager = _text(el, "name")
    total = entries = None
    for el in root.iter():
        if _strip(el.tag) == "tableValueTotal":
            total = _num(el.text)
        elif _strip(el.tag) == "tableEntryTotal":
            entries = _num(el.text)
    iso = None
    if period and re.fullmatch(r"\d\d-\d\d-\d{4}", period):
        iso = f"{period[6:]}-{period[:2]}-{period[3:5]}"
    return {"period": iso, "manager": manager, "table_value": total, "table_entries": int(entries) if entries else None}


def _aggregate(positions: list[dict]) -> dict[tuple, dict]:
    out: dict[tuple, dict] = {}
    for p in positions:
        m = out.setdefault((p["cusip"], p["put_call"]), {"issuer": p["issuer"], "class": p["class"], "shares": 0.0, "value": 0.0})
        m["shares"] += p["shares"]
        m["value"] += p["value"]
    return out


def diff_13f(current: list[dict], prior: list[dict] | None) -> list[dict]:
    """One row per position of either quarter; sorted by the size of the dollar move, then by holding size."""
    now = _aggregate(current)
    before = _aggregate(prior) if prior is not None else {}
    total_now = sum(v["value"] for v in now.values()) or None
    rows = []
    for key in set(now) | set(before):
        n, b = now.get(key), before.get(key)
        ns, bs = (n["shares"] if n else 0.0), (b["shares"] if b else 0.0)
        if prior is None:
            status = "HELD"
        elif n is None:
            status = "EXITED"
        elif b is None:
            status = "NEW"
        elif ns > bs:
            status = "ADDED"
        elif ns < bs:
            status = "TRIMMED"
        else:
            status = "UNCHANGED"
        nv, bv = (n["value"] if n else 0.0), (b["value"] if b else 0.0)
        rows.append({"status": status, "issuer": (n or b)["issuer"], "class": (n or b)["class"], "cusip": key[0],
                     "put_call": key[1], "shares_before": bs if b else None, "shares_now": ns if n else None,
                     "shares_change": ns - bs, "shares_change_pct": (ns - bs) / bs if bs else None,
                     "value_now": nv if n else None, "value_change": nv - bv,
                     "weight": nv / total_now if total_now and n else None})
    rows.sort(key=lambda r: (abs(r["value_change"]), r["value_now"] or 0.0), reverse=True)
    return rows


def mgr_payload(manager: str, name: str | None, now: dict, before: dict | None, rows: list[dict], source: str) -> dict:
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    heads = [head("MANAGER", name or manager), head("PERIOD", now["period"]),
             head("PRIOR PERIOD", before["period"] if before else None),
             head("REPORTED VALUE", _money(now["table_value"]), now["table_value"]),
             head("POSITIONS", str(now.get("positions")), now.get("positions"))]
    heads += [head(k, str(counts[k]), counts[k]) for k in ("NEW", "ADDED", "TRIMMED", "EXITED") if k in counts]
    notes = ["13F-HR LONG POSITIONS ONLY, FILED UP TO 45 DAYS AFTER QUARTER END: NOT CURRENT HOLDINGS, NO SHORTS, NO NON-US OR NON-13F SECURITIES",
             "CHANGE IS BY SHARE COUNT; DUPLICATE LINES FOR THE SAME CUSIP ARE ADDED TOGETHER (OTHER-MANAGER SPLITS)"]
    if before is None:
        notes.append("ONLY ONE 13F-HR IN THE RECENT FILINGS FEED: NO QUARTER-OVER-QUARTER CHANGE TO SHOW")
    return payload(
        None, f"MGR {manager} · 13F POSITIONS", heads,
        [section("changes", "POSITIONS AND CHANGES (LARGEST DOLLAR MOVE FIRST)",
                 [col("status", "STATUS", "text", 9), col("issuer", "ISSUER", "text", 30), col("class", "CLASS", "text", 10),
                  col("put_call", "P/C", "text", 4), col("shares_before", "SHARES BEFORE", "money"), col("shares_now", "SHARES NOW", "money"),
                  col("shares_change_pct", "SHARE CHG", "pct"), col("value_now", "VALUE NOW", "money"),
                  col("value_change", "VALUE CHG", "money"), col("weight", "WEIGHT", "pct"), col("cusip", "CUSIP", "text", 9)], rows)],
        notes, source)


# Managers whose CIK was checked against the SEC submissions `name` on 2026-10-18 (scripts/record_phase13.py prints the name
# it finds; the panel shows the name SEC returns, so a stale entry is visible). Any numeric CIK also works.
MANAGERS: dict[str, int] = {
    "BERKSHIRE": 1067983, "BRIDGEWATER": 1350694, "RENAISSANCE": 1037389, "CITADEL": 1423053, "TWOSIGMA": 1179392,
    "POINT72": 1603466, "TIGERGLOBAL": 1167483, "SCION": 1649339, "PERSHING": 1336528, "THIRDPOINT": 1040273,
    "SOROS": 1029160, "APPALOOSA": 1656456, "DUQUESNE": 1536411, "GREENLIGHT": 1079114, "BAUPOST": 1061768,
    "ELLIOTT": 1791786, "ICAHN": 921669, "VANGUARD": 102909, "STATESTREET": 93751, "FIDELITY": 315066,
    "MILLENNIUM": 1273087, "DESHAW": 1009207, "AQR": 1167557, "LONEPINE": 1061165, "VIKING": 1103804, "COATUE": 1135730,
    "ARKINVEST": 1697748,
}


def manager_cik(text: str) -> int:
    key = re.sub(r"[^A-Z0-9]", "", text.upper())
    if key.isdigit():
        return int(key)
    if key in MANAGERS:
        return MANAGERS[key]
    raise ProviderError("not_found", f"unknown manager {text!r}: use a number (CIK) or one of {' '.join(sorted(MANAGERS))}")


# Index shorthand -> the ETF whose N-PORT stands in for the index (spec decision G/H).
INDEX_PROXY: dict[str, str] = {"SPX": "SPY", "NDX": "QQQ", "DJI": "DIA", "RUT": "IWM", "MID": "MDY"}
# Unit investment trusts are not in SEC's mutual-fund ticker list; their trust CIKs (one series each).
UIT_CIKS: dict[str, int] = {"SPY": 884394, "DIA": 1041130, "MDY": 936958}
