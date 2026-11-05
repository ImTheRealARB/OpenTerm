"""BEA data API (US GDP, trade balance, value added by industry): request builder and response parser. Pure code.

Endpoint: GET https://apps.bea.gov/api/data?UserID=<key>&method=GetData&datasetname=NIPA&TableName=T10101&Frequency=Q&Year=2024,2025&ResultFormat=JSON
Answer: {"BEAAPI": {"Request": {...}, "Results": {"Statistic": "...", "UTCProductionTime": "...", "Data": [
           {"TableName": "T10101", "SeriesCode": "A191RL", "LineNumber": "1", "LineDescription": "Gross domestic product",
            "TimePeriod": "2025Q1", "CL_UNIT": "Percent change, annualized", "UNIT_MULT": "0", "DataValue": "2.0", "NoteRef": "T10101"}]}}}
An error comes as {"BEAAPI": {"Error": {"APIErrorCode": "...", "APIErrorDescription": "..."}}} (sometimes inside Results).

Checked against live answers on 2026-11-05 (real key). Two facts that matter:
  - UNIT_MULT is a power of ten: the real value is DataValue * 10**UNIT_MULT in CL_UNIT. NIPA T10105 (GDP) and every ITA indicator
    come with UNIT_MULT=6, i.e. the numbers are MILLIONS of dollars (GDP 30,171,979 = 30.2 trillion). T10101 percentages have
    UNIT_MULT=0. GDPbyIndustry rows carry no unit fields at all; table 1 is documented in billions of dollars.
  - `parse` therefore rescales every NIPA / ITA value to the unit the catalogue promises (`Entry.power`: 9 = billions, 6 = millions,
    0 = as printed) and fails loudly when UNIT_MULT is missing, so a wrong "USD BN" label can no longer slip through.
The parser reads field names case-insensitively (BEA prints `IndustrYDescription` with a capital Y) and fails loudly on a missing
field. Values print with thousands commas ("23,456.7"); `num` strips them.
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
    value_kind: str  # level | rate (seriesboard.KINDS): "rate" = the values are already percentages, so changes read in percentage points
    line: str | None = None  # NIPA: the LineNumber to keep
    power: int = 0  # power of ten of `unit` in dollars: 9 = USD BN, 6 = USD MN, 0 = a percentage / as printed (see the module doc)


_NIPA_1 = (("datasetname", "NIPA"), ("TableName", "T10101"), ("Frequency", "Q"))
CATALOG: dict[str, Entry] = {e.alias: e for e in (
    Entry("GDPG", "REAL GDP, % CHANGE FROM PRECEDING PERIOD, ANNUAL RATE", "%", "Q", "nipa", _NIPA_1, "rate", "1"),
    Entry("PCEG", "PERSONAL CONSUMPTION, % CHANGE, ANNUAL RATE", "%", "Q", "nipa", _NIPA_1, "rate", "2"),
    Entry("GDP", "GDP, CURRENT DOLLARS, SEASONALLY ADJUSTED ANNUAL RATE", "USD BN", "Q", "nipa",
          (("datasetname", "NIPA"), ("TableName", "T10105"), ("Frequency", "Q")), "level", "1", 9),
    Entry("TRADEBAL", "BALANCE ON GOODS, ALL COUNTRIES, SA", "USD MN", "Q", "ita",
          (("datasetname", "ITA"), ("Indicator", "BalGds"), ("AreaOrCountry", "AllCountries"), ("Frequency", "QSA")), "level", None, 6),
    Entry("SERVBAL", "BALANCE ON SERVICES, ALL COUNTRIES, SA", "USD MN", "Q", "ita",
          (("datasetname", "ITA"), ("Indicator", "BalServ"), ("AreaOrCountry", "AllCountries"), ("Frequency", "QSA")), "level", None, 6),
    Entry("CURACCT", "CURRENT ACCOUNT BALANCE, ALL COUNTRIES, SA", "USD MN", "Q", "ita",
          (("datasetname", "ITA"), ("Indicator", "BalCurrAcct"), ("AreaOrCountry", "AllCountries"), ("Frequency", "QSA")), "level", None, 6),
    Entry("INDUSTRY", "VALUE ADDED BY INDUSTRY (GDP BY INDUSTRY, TABLE 1)", "USD BN", "A", "industry",
          (("datasetname", "GDPbyIndustry"), ("TableID", "1"), ("Frequency", "A"), ("Industry", "ALL")), "level"),
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


_FOOTNOTE = re.compile(r"<sup>.*?</sup>", re.IGNORECASE)  # the whole footnote marker, digit included: "industries<sup>1</sup>"
_TAGS = re.compile(r"<[^>]*>")  # any other markup: tags go, their text stays


def _plain(text: Any) -> str:
    """Industry names arrive with footnote markup ("Private goods-producing industries<sup>1</sup>"); drop it, upper-case for the panel."""
    return _TAGS.sub("", _FOOTNOTE.sub("", str(text))).strip().upper()


def _scaled(row: dict, entry: Entry) -> float | None:
    """The row's DataValue converted to the catalogue unit using the row's own UNIT_MULT (value * 10**UNIT_MULT dollars, then / 10**power).

    Dividing by a power of ten (instead of multiplying by 10**-3) keeps 30,171,979 -> 30171.979 exact in floating point.
    """
    v = num(_g(row, "DataValue"))
    if v is None:
        return None
    try:
        mult = int(str(_g(row, "UNIT_MULT")).strip())
    except ValueError:
        raise NotUnderstood(f"BEA UNIT_MULT IS NOT A NUMBER: {str(_g(row, 'UNIT_MULT'))[:12]}") from None
    shift = mult - entry.power
    return v * 10 ** shift if shift >= 0 else v / 10 ** -shift


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
            s = by.setdefault(code, {"label": _plain(_g(r, "IndustrYDescription")), "pts": {}})
            s["pts"][str(_g(r, "Year"))] = num(_g(r, "DataValue"))
        # Live answers mix levels of the hierarchy: the GDP total, "Private industries", sectors (Manufacturing) AND their parts
        # (Real estate inside Real estate and rental). Say so on every row, since adding the rows up would double count.
        note = ["MIXES TOTALS, SECTORS AND SUB-INDUSTRIES: DO NOT ADD THE ROWS UP"]
        series = [build_series(f"GDPbyIndustry:{code}", entry.alias, s["label"], entry.unit, "A", sorted(s["pts"].items()), note, kind=entry.value_kind)
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
        pts[period] = _scaled(r, entry)
    if not pts:
        raise NoData(f"BEA RETURNED NO ROWS FOR {entry.alias} LINE {entry.line}")
    return [build_series(sid, entry.alias, entry.label, entry.unit, entry.freq, sorted(pts.items()), kind=entry.value_kind)]
