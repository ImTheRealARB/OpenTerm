"""US Census Bureau API: monthly retail sales (EITS MARTS) and US goods trade by country and HS chapter. Pure code.

Every Census answer is an array of arrays: the first row names the columns, the rest are data, all values are strings.
    GET https://api.census.gov/data/timeseries/eits/marts?get=cell_value,data_type_code,category_code,time_slot_date,error_data,seasonally_adj
        &time=from 2024-01&category_code=44X72,441&data_type_code=SM&seasonally_adj=yes&key=<key>
    GET https://api.census.gov/data/timeseries/intltrade/exports/hs?get=E_COMMODITY,E_COMMODITY_LDESC,CTY_CODE,CTY_NAME,ALL_VAL_MO
        &COMM_LVL=HS2&E_COMMODITY=85&CTY_CODE=5700&time=from 2024-01&key=<key>      (imports/hs: I_COMMODITY, GEN_VAL_MO)
Endpoint names and variable names were read from Census's own pages on 2026-11-05 (eits/marts variables, intltrade endpoints list,
the exports/hs example). DOC-SHAPED: no key was available, so the `time=from YYYY-MM` range form, the comma list in
`category_code`, the `COMM_LVL` value HS2 and the answer's `time` column are from Census's general timeseries documentation and
memory. The parser reads columns by name and fails loudly if one is missing. Retail sales are millions of US dollars; trade is dollars.
"""

from __future__ import annotations

from typing import Any

from .seriesboard import KeyRejected, NoData, NotUnderstood, build_series, num

BASE = "https://api.census.gov/data/timeseries"
SOURCE_RETAIL = "US CENSUS BUREAU, MONTHLY RETAIL TRADE SURVEY (EITS MARTS)"
SOURCE_TRADE = "US CENSUS BUREAU, USA TRADE ONLINE (INTERNATIONAL TRADE, HS CHAPTERS)"

# alias -> (NAICS retail category code, label)
RETAIL = {
    "TOTAL": ("44X72", "RETAIL AND FOOD SERVICES, TOTAL"),
    "AUTO": ("441", "MOTOR VEHICLE AND PARTS DEALERS"),
    "FOOD": ("445", "FOOD AND BEVERAGE STORES"),
    "GEN": ("452", "GENERAL MERCHANDISE STORES"),
    "REST": ("722", "FOOD SERVICES AND DRINKING PLACES"),
}
# Census trade country codes (Schedule C). Only the large partners; a number is passed through as it is.
COUNTRIES = {
    "CANADA": "1220", "MEXICO": "2010", "BRAZIL": "3510", "UK": "4120", "FRANCE": "4279", "GERMANY": "4280", "ITALY": "4759",
    "VIETNAM": "5520", "CHINA": "5700", "INDIA": "5330", "KOREA": "5800", "TAIWAN": "5830", "JAPAN": "5880",
}


def parse_retail(words: list[str]) -> list[str]:
    """['AUTO', 'FOOD'] -> category aliases; [] -> TOTAL."""
    if not words:
        return ["TOTAL"]
    bad = [w for w in words if w not in RETAIL]
    if bad:
        raise ValueError(f"UNKNOWN RETAIL CATEGORY {bad[0][:20]}. USE: {' '.join(RETAIL)}")
    return list(dict.fromkeys(words))


def parse_trade(words: list[str]) -> tuple[str, str, str]:
    """['CHINA', '85'] -> (country name, Census country code, HS chapter)."""
    if len(words) != 2:
        raise ValueError("USAGE: TRADE <COUNTRY> <HS CHAPTER 01-99>, FOR EXAMPLE TRADE CHINA 85")
    name, hs = words
    code = COUNTRIES.get(name) or (name if name.isdigit() and len(name) == 4 else None)
    if code is None:
        raise ValueError(f"UNKNOWN COUNTRY {name[:20]}. USE: {' '.join(COUNTRIES)} OR A 4-DIGIT CENSUS COUNTRY CODE")
    if not (hs.isdigit() and len(hs) == 2 and hs != "00"):
        raise ValueError(f"HS CHAPTER MUST BE TWO DIGITS (01-99), NOT {hs[:8]}")
    return name, code, hs


def retail_params(cats: list[str], start: str, key: str) -> dict[str, str]:
    return {"get": "cell_value,data_type_code,category_code,time_slot_date,error_data,seasonally_adj",
            "time": f"from {start}", "category_code": ",".join(RETAIL[c][0] for c in cats),
            "data_type_code": "SM", "seasonally_adj": "yes", "key": key}


def trade_params(flow: str, code: str, hs: str, start: str, key: str) -> tuple[str, dict[str, str]]:
    """(path under BASE, query) for exports ('X') or imports ('M')."""
    if flow == "X":
        return "intltrade/exports/hs", {"get": "E_COMMODITY,E_COMMODITY_LDESC,CTY_CODE,CTY_NAME,ALL_VAL_MO", "COMM_LVL": "HS2",
                                        "E_COMMODITY": hs, "CTY_CODE": code, "time": f"from {start}", "key": key}
    return "intltrade/imports/hs", {"get": "I_COMMODITY,I_COMMODITY_LDESC,CTY_CODE,CTY_NAME,GEN_VAL_MO", "COMM_LVL": "HS2",
                                    "I_COMMODITY": hs, "CTY_CODE": code, "time": f"from {start}", "key": key}


def _table(body: Any) -> list[dict[str, str]]:
    """Header row + data rows -> list of dicts. A body that is not an array of arrays is not a Census data answer."""
    if isinstance(body, dict):  # error bodies from the API gateway are small JSON objects
        text = str(body.get("error") or body.get("message") or body)[:160]
        if "key" in text.lower():
            raise KeyRejected("CENSUS REFUSED THE KEY")
        raise NotUnderstood(f"CENSUS ERROR: {text}")
    if not isinstance(body, list) or not body or not all(isinstance(r, list) for r in body):
        raise NotUnderstood("CENSUS ANSWER IS NOT AN ARRAY OF ARRAYS")
    head = [str(h) for h in body[0]]
    out = []
    for r in body[1:]:
        if len(r) != len(head):
            raise NotUnderstood("CENSUS ROW LENGTH DIFFERS FROM THE HEADER")
        out.append(dict(zip(head, r, strict=True)))
    return out


def _need(row: dict, col: str) -> str:
    if col not in row:
        raise NotUnderstood(f"CENSUS ANSWER HAS NO {col} COLUMN")
    return row[col]


def _month(row: dict) -> str:
    """'2026-08' from the `time` column, else the first 7 characters of time_slot_date."""
    t = row.get("time") or row.get("time_slot_date")
    if not t or len(t) < 7:
        raise NotUnderstood("CENSUS ROW HAS NO MONTH (time / time_slot_date)")
    return t[:7]


def parse_retail_answer(body: Any, cats: list[str]) -> dict[str, Any]:
    rows = _table(body)
    series = []
    for cat in cats:
        code, label = RETAIL[cat]
        pts: dict[str, float | None] = {}
        for r in rows:
            if _need(r, "category_code") != code or _need(r, "seasonally_adj").lower() not in ("yes", "true"):
                continue
            m = _month(r)
            if m in pts:
                raise NotUnderstood(f"CENSUS REPEATS {code} {m}")
            pts[m] = num(_need(r, "cell_value"))
        if pts:
            series.append(build_series(f"marts:{code}:SM:SA", cat, label, "USD MN", "M", sorted(pts.items()), kind="level"))
    if not series:
        raise NoData("CENSUS RETURNED NO RETAIL ROWS FOR " + ", ".join(cats))
    return {"series": series, "missing": [c for c in cats if c not in {s["alias"] for s in series}], "messages": [],
            "source": SOURCE_RETAIL, "note": "SEASONALLY ADJUSTED MONTHLY SALES, MILLIONS OF USD. THE NEWEST MONTH IS AN ADVANCE ESTIMATE AND IS REVISED."}


def parse_trade_answers(exports: Any, imports: Any, name: str, hs: str) -> dict[str, Any]:
    ex, im = {}, {}
    desc = ""
    for rows, col, val, out in ((_table(exports), "E_COMMODITY", "ALL_VAL_MO", ex), (_table(imports), "I_COMMODITY", "GEN_VAL_MO", im)):
        for r in rows:
            if _need(r, col) != hs:
                continue
            m = _month(r)
            if m in out:
                raise NotUnderstood(f"CENSUS REPEATS HS{hs} {m}")
            out[m] = num(_need(r, val))
            desc = desc or str(r.get(col + "_LDESC", ""))
    if not ex and not im:
        raise NoData(f"CENSUS RETURNED NO TRADE ROWS FOR {name} HS{hs}")
    both = sorted(set(ex) & set(im))
    bal = [(m, (ex[m] - im[m]) if ex[m] is not None and im[m] is not None else None) for m in both]
    tag = f"{name} HS{hs}" + (f" {desc.upper()}" if desc else "")
    series = [build_series(f"intltrade:exports:{hs}", "EXPORTS", f"US EXPORTS TO {tag}", "USD", "M", sorted(ex.items()), kind="level"),
              build_series(f"intltrade:imports:{hs}", "IMPORTS", f"US IMPORTS FROM {tag}", "USD", "M", sorted(im.items()), kind="level"),
              build_series(f"intltrade:balance:{hs}", "BALANCE", f"US BALANCE WITH {tag} (EXPORTS MINUS IMPORTS)", "USD", "M", bal, kind="level")]
    return {"series": [s for s in series if s["points"]], "missing": [], "messages": [], "source": SOURCE_TRADE,
            "note": "MONTHLY, NOT SEASONALLY ADJUSTED. EXPORTS = TOTAL EXPORTS (ALL_VAL_MO), IMPORTS = GENERAL IMPORTS (GEN_VAL_MO). BALANCE ONLY WHERE BOTH MONTHS EXIST."}
