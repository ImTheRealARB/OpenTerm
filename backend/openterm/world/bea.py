"""BEA data API (US GDP, trade balance, value added by industry): request builder and response parser. Pure code.

Endpoint: GET https://apps.bea.gov/api/data?UserID=<key>&method=GetData&datasetname=NIPA&TableName=T10101&Frequency=Q&Year=2024,2025&ResultFormat=JSON
Answer: {"BEAAPI": {"Request": {...}, "Results": {"Statistic": "...", "UTCProductionTime": "...", "Data": [
           {"TableName": "T10101", "SeriesCode": "A191RL", "LineNumber": "1", "LineDescription": "Gross domestic product",
            "TimePeriod": "2025Q1", "CL_UNIT": "Percent change, annualized", "UNIT_MULT": "0", "DataValue": "2.0", "NoteRef": "T10101"}]}}}
An error comes as {"BEAAPI": {"Error": {"APIErrorCode": "...", "APIErrorDescription": "..."}}} (sometimes inside Results).

DOC-SHAPED: BEA's user guide could not be read when this was written (2026-11-05); the field names above come from the guide as
remembered and from the beaapi / bea.R client packages. The ITA (International Transactions) and GDPbyIndustry row fields are the
least certain; the parser reads field names case-insensitively (BEA prints `IndustrYDescription` with a capital Y) and fails loudly
on a missing field. The first real call is the test. Values print with thousands commas ("23,456.7"); `num` strips them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .seriesboard import KeyRejected, NoData, NotUnderstood, build_series, num

URL = "https://apps.bea.gov/api/data"
SOURCE = "BEA DATA API (US BUREAU OF ECONOMIC ANALYSIS)"
MAX_INDUSTRIES = 30


@dataclass(frozen=True)
class Entry:
    alias: str
    label: str
    unit: str
    freq: str
    kind: str  # nipa | ita | industry
    params: tuple[tuple[str, str], ...]  # everything except UserID / method / ResultFormat / Year
    line: str | None = None  # NIPA: the LineNumber to keep


_NIPA_1 = (("datasetname", "NIPA"), ("TableName", "T10101"), ("Frequency", "Q"))
CATALOG: dict[str, Entry] = {e.alias: e for e in (
    Entry("GDPG", "REAL GDP, % CHANGE FROM PRECEDING PERIOD, ANNUAL RATE", "%", "Q", "nipa", _NIPA_1, "1"),
    Entry("PCEG", "PERSONAL CONSUMPTION, % CHANGE, ANNUAL RATE", "%", "Q", "nipa", _NIPA_1, "2"),
    Entry("GDP", "GDP, CURRENT DOLLARS, SEASONALLY ADJUSTED ANNUAL RATE", "USD BN", "Q", "nipa",
          (("datasetname", "NIPA"), ("TableName", "T10105"), ("Frequency", "Q")), "1"),
    Entry("TRADEBAL", "BALANCE ON GOODS, ALL COUNTRIES, SA", "USD MN", "Q", "ita",
          (("datasetname", "ITA"), ("Indicator", "BalGds"), ("AreaOrCountry", "AllCountries"), ("Frequency", "QSA"))),
    Entry("SERVBAL", "BALANCE ON SERVICES, ALL COUNTRIES, SA", "USD MN", "Q", "ita",
          (("datasetname", "ITA"), ("Indicator", "BalServ"), ("AreaOrCountry", "AllCountries"), ("Frequency", "QSA"))),
    Entry("CURACCT", "CURRENT ACCOUNT BALANCE, ALL COUNTRIES, SA", "USD MN", "Q", "ita",
          (("datasetname", "ITA"), ("Indicator", "BalCurrAcct"), ("AreaOrCountry", "AllCountries"), ("Frequency", "QSA"))),
    Entry("INDUSTRY", "VALUE ADDED BY INDUSTRY (GDP BY INDUSTRY, TABLE 1)", "USD BN", "A", "industry",
          (("datasetname", "GDPbyIndustry"), ("TableID", "1"), ("Frequency", "A"), ("Industry", "ALL"))),
)}
DEFAULT_BOARD = ("GDPG", "PCEG", "GDP", "TRADEBAL", "SERVBAL", "CURACCT")

_KEY_WORDS = re.compile(r"(?i)user\s*id|api\s*key|not\s+registered|invalid\s+key")


def parse_aliases(q: str) -> list[str]:
    words = [w for w in re.split(r"[\s,]+", q.strip().upper()) if w]
    if not words:
        return list(DEFAULT_BOARD)
    bad = [w for w in words if w not in CATALOG]
    if bad:
        raise ValueError(f"UNKNOWN BEA TABLE {bad[0][:20]}. USE: {' '.join(CATALOG)}")
    return list(dict.fromkeys(words))


def build_params(entry: Entry, this_year: int, key: str) -> dict[str, str]:
    """Query for one table. Years are listed out (this year back five, or four for annual tables): a year BEA has not
    published yet simply has no rows."""
    n = 4 if entry.freq == "A" else 5
    years = ",".join(str(y) for y in range(this_year - n + 1, this_year + 1))
    return {"UserID": key, "method": "GetData", "ResultFormat": "JSON", "Year": years, **dict(entry.params)}


def call_key(entry: Entry) -> tuple[tuple[str, str], ...]:
    """Aliases with the same call (GDPG and PCEG share table T10101) are fetched once."""
    return tuple(sorted(entry.params))


def _g(row: dict, name: str) -> Any:
    """Case-insensitive field read. A missing field raises NotUnderstood (the shape is documented, not guessed)."""
    low = name.lower()
    for k, v in row.items():
        if k.lower() == low:
            return v
    raise NotUnderstood(f"BEA ROW HAS NO {name} FIELD")


def _rows(body: Any) -> list[dict]:
    if not isinstance(body, dict) or not isinstance(body.get("BEAAPI"), dict):
        raise NotUnderstood("BEA ANSWER HAS NO BEAAPI OBJECT")
    api = body["BEAAPI"]
    res = api.get("Results")
    if isinstance(res, list):
        res = res[0] if res else {}
    err = api.get("Error") or (res or {}).get("Error")
    if err:
        err = err[0] if isinstance(err, list) and err else err
        desc = str(err.get("APIErrorDescription") or err.get("ErrorDetail", {}).get("Description") or err) if isinstance(err, dict) else str(err)
        if _KEY_WORDS.search(desc):
            raise KeyRejected("BEA REFUSED THE KEY")
        raise NotUnderstood(f"BEA ERROR: {desc[:160]}")
    data = (res or {}).get("Data")
    if not isinstance(data, list):
        raise NotUnderstood("BEA ANSWER HAS NO Results.Data LIST")
    return [r for r in data if isinstance(r, dict)]


def _label_period(tp: str) -> str:
    return tp.strip()  # '2025Q1' or '2025': already sortable


def parse(body: Any, entry: Entry) -> list[dict[str, Any]]:
    """Series for one catalogue entry (one series, or one per industry)."""
    rows = _rows(body)
    if not rows:
        raise NoData(f"BEA RETURNED NO ROWS FOR {entry.alias}")
    if entry.kind == "industry":
        by: dict[str, dict] = {}
        for r in rows:
            code = str(_g(r, "Industry"))
            s = by.setdefault(code, {"label": str(_g(r, "IndustrYDescription")).upper(), "pts": {}})
            s["pts"][str(_g(r, "Year"))] = num(_g(r, "DataValue"))
        series = [build_series(f"GDPbyIndustry:{code}", entry.alias, s["label"], entry.unit, "A", sorted(s["pts"].items()))
                  for code, s in by.items()]
        series.sort(key=lambda x: -(x["last"] or 0))
        return series[:MAX_INDUSTRIES]
    if entry.kind == "nipa":
        rows = [r for r in rows if str(_g(r, "LineNumber")) == entry.line]
        sid = str(_g(rows[0], "SeriesCode")) if rows else entry.alias
    else:
        ids = {str(_g(r, "TimeSeriesId")) for r in rows}
        if len(ids) != 1:
            raise NotUnderstood(f"BEA ITA ANSWER HAS {len(ids)} SERIES, EXPECTED 1")
        sid = ids.pop()
    pts: dict[str, float | None] = {}
    for r in rows:
        period = _label_period(str(_g(r, "TimePeriod")))
        if period in pts:
            raise NotUnderstood(f"BEA ANSWER REPEATS PERIOD {period}")
        pts[period] = num(_g(r, "DataValue"))
    if not pts:
        raise NoData(f"BEA RETURNED NO ROWS FOR {entry.alias} LINE {entry.line}")
    return [build_series(sid, entry.alias, entry.label, entry.unit, entry.freq, sorted(pts.items()))]
