"""Pure parsers for the Phase 14 rates sources (no I/O). A curve is

    {"dates": [YYYY-MM-DD ascending], "tenors": [{"tenor": "10Y", "years": 10.0, "values": [percent | None per date]}]}

with tenors sorted by maturity. A tenor a source did not publish on a date is None: nothing is carried forward or invented.
Dates with no value at all (holidays) are dropped so a "previous observation" is always a real one.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from ..research.table import number

MONTHS = {m: i for i, m in enumerate(("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1)}
_TENOR = re.compile(r"^(\d+)([MY])$")


class RatesParseError(ValueError):
    """The source answered something that is not the expected shape."""


def tenor_years(tenor: str) -> float:
    m = _TENOR.match(tenor.upper())
    if not m:
        raise RatesParseError(f"not a tenor: {tenor}")
    n = int(m.group(1))
    return n / 12.0 if m.group(2) == "M" else float(n)


def _curve(series: dict[str, dict[str, float | None]]) -> dict:
    """series: tenor -> {iso date: percent | None}."""
    dates = sorted({d for obs in series.values() for d, v in obs.items() if v is not None})
    tenors = [{"tenor": t, "years": tenor_years(t), "values": [series[t].get(d) for d in dates]} for t in series]
    tenors.sort(key=lambda r: r["years"])
    return {"dates": dates, "tenors": tenors}


def _float(text: Any) -> float | None:
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    s = str(text).strip()
    if s in ("", "-", "."):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_ecb(doc: dict) -> dict:
    """ECB SDMX-JSON (`format=jsondata`) for the AAA spot curve: one series per DATA_TYPE_FM value `SR_<tenor>`."""
    try:
        dims = doc["structure"]["dimensions"]
        series_dims = dims["series"]
        pos = next(i for i, d in enumerate(series_dims) if d["id"] == "DATA_TYPE_FM")
        times = [v["id"] for v in dims["observation"][0]["values"]]
        raw = doc["dataSets"][0]["series"]
        out: dict[str, dict[str, float | None]] = {}
        for key, ser in raw.items():
            label = series_dims[pos]["values"][int(key.split(":")[pos])]["id"].removeprefix("SR_")
            out[label] = {times[int(i)]: _float(v[0]) for i, v in ser.get("observations", {}).items()}
    except (KeyError, IndexError, StopIteration, ValueError, TypeError) as e:
        raise RatesParseError(f"ECB answer is not the expected SDMX-JSON ({type(e).__name__})") from e
    if not out:
        raise RatesParseError("ECB answer has no series")
    return _curve(out)


_BOC = re.compile(r"^BD\.CDN\.(\d+)YR\.DQ\.YLD$")


def parse_boc(doc: dict) -> dict:
    """Bank of Canada Valet group `bond_yields_benchmark`. Only the fixed-maturity benchmarks (2, 3, 5, 7, 10 years) are curve points: the
    `LONG` and real-return series have no fixed maturity."""
    try:
        rows = doc["observations"]
        out: dict[str, dict[str, float | None]] = {}
        for row in rows:
            for key, cell in row.items():
                m = _BOC.match(key)
                if m:
                    out.setdefault(f"{int(m.group(1))}Y", {})[row["d"]] = _float(cell.get("v") if isinstance(cell, dict) else None)
    except (KeyError, TypeError, AttributeError) as e:
        raise RatesParseError(f"Bank of Canada answer is not the expected Valet JSON ({type(e).__name__})") from e
    if not out:
        raise RatesParseError("Bank of Canada answer has no benchmark yields")
    return _curve(out)


def _ymd(text: str) -> str:
    y, m, d = (int(x) for x in text.strip().split("/"))
    return date(y, m, d).isoformat()


def parse_mof(text: str, keep: int = 40) -> dict:
    """Japan MoF `jgbcme_all.csv`: `Date,1Y,2Y,...,40Y` then rows like `2026/7/31,1.255,...`; `-` means no value. Only the newest `keep` days
    are kept (the file holds the whole history)."""
    header: list[str] | None = None
    rows: list[tuple[str, list[str]]] = []
    for line in text.lstrip("﻿").splitlines():
        cells = [c.strip() for c in line.split(",")]
        if cells and cells[0].lower() == "date":
            header = cells[1:]
        elif header is not None and cells and re.match(r"^\d{4}/\d{1,2}/\d{1,2}$", cells[0]):
            rows.append((_ymd(cells[0]), cells[1:]))
    if not header or not rows:
        raise RatesParseError("MoF answer has no Date header or no rows")
    rows = rows[-keep:]
    out: dict[str, dict[str, float | None]] = {t: {} for t in header if _TENOR.match(t.upper())}
    for iso, cells in rows:
        for t, c in zip(header, cells, strict=False):
            if t in out:
                out[t][iso] = _float(c)
    return _curve(out)


BOE_SERIES = {"IUDSNPY": "5Y", "IUDMNPY": "10Y", "IUDLNPY": "20Y"}


def _dmy(text: str) -> str:
    d, mon, y = text.strip().split()
    return date(int(y), MONTHS[mon[:3].title()], int(d)).isoformat()


def parse_boe(text: str) -> dict:
    """Bank of England IADB CSV: `DATE,IUDSNPY,IUDMNPY,IUDLNPY` (nominal par yields 5, 10 and 20 years), dates like `14 Oct 2026`."""
    lines = [ln for ln in text.lstrip("﻿").splitlines() if ln.strip()]
    if not lines or not lines[0].upper().startswith("DATE"):
        raise RatesParseError("Bank of England answer has no DATE header")
    cols = [c.strip().upper() for c in lines[0].split(",")][1:]
    out: dict[str, dict[str, float | None]] = {BOE_SERIES[c]: {} for c in cols if c in BOE_SERIES}
    for line in lines[1:]:
        cells = [c.strip() for c in line.split(",")]
        try:
            iso = _dmy(cells[0])
        except (ValueError, KeyError):
            continue
        for c, v in zip(cols, cells[1:], strict=False):
            if c in BOE_SERIES:
                out[BOE_SERIES[c]][iso] = _float(v)
    if not out:
        raise RatesParseError("Bank of England answer has none of the nominal par yield series")
    return _curve(out)


# --- curve views ----------------------------------------------------------------------------------

def bp(now: float | None, before: float | None) -> float | None:
    return None if now is None or before is None else (now - before) * 100.0


def curve_rows(curve: dict) -> list[dict]:
    """One row per tenor: latest yield (percent) and the changes in bp against the previous observation and five observations back."""
    rows = []
    for t in curve["tenors"]:
        v = t["values"]
        now = v[-1] if v else None
        rows.append({"tenor": t["tenor"], "years": t["years"], "yield": now,
                     "d1": bp(now, v[-2]) if len(v) >= 2 else None,
                     "d5": bp(now, v[-6]) if len(v) >= 6 else None})
    return rows


def curve_points(curve: dict) -> list[tuple[float, float]]:
    """(years, yield percent) for every tenor that has a value on the latest date."""
    return [(r["years"], r["yield"]) for r in curve_rows(curve) if r["yield"] is not None]


# --- credit spreads (FRED OAS) -----------------------------------------------------------------------

def parse_oas_csv(text: str, series_id: str) -> list[tuple[str, float]]:
    """fredgraph.csv: `observation_date,<ID>` then `YYYY-MM-DD,value` (`.` or empty = missing). Returns ascending (date, percent)."""
    lines = text.lstrip("﻿").splitlines()
    if not lines or series_id.upper() not in lines[0].upper():
        raise RatesParseError(f"CSV is not for {series_id}")
    out = []
    for line in lines:
        d, _, v = line.partition(",")
        if re.match(r"^\d{4}-\d{2}-\d{2}$", d.strip()):
            x = _float(v)
            if x is not None:
                out.append((d.strip(), x))
    out.sort()
    return out


def oas_row(series_id: str, name: str, obs: list[tuple[str, float]]) -> dict:
    """Latest option-adjusted spread in bp, changes over 1, 5 and 21 observations, and the percentile of today's value within the last
    365 days of data (share of those days at or below today)."""
    row: dict[str, Any] = {"series": series_id, "name": name, "bp": None, "date": None, "d1": None, "d5": None, "d21": None, "pct_1y": None}
    if not obs:
        return row
    last_date, last = obs[-1]
    row.update(bp=last * 100.0, date=last_date)
    for key, n in (("d1", 1), ("d5", 5), ("d21", 21)):
        if len(obs) > n:
            row[key] = (last - obs[-1 - n][1]) * 100.0
    cut = (date.fromisoformat(last_date) - timedelta(days=365)).isoformat()
    window = [v for d, v in obs if d >= cut]
    row["pct_1y"] = 100.0 * sum(1 for v in window if v <= last) / len(window)
    return row


# --- Treasury auctions -------------------------------------------------------------------------------

def _day(text: Any) -> str | None:
    return str(text)[:10] if text else None


def parse_auctions(rows: list[dict]) -> list[dict]:
    """TreasuryDirect securities rows -> table rows. Empty strings are missing values (None)."""
    out = []
    for r in rows:
        rate = next((x for x in (number(r.get(k)) for k in ("highRate", "highYield", "highDiscountRate")) if x is not None), None)
        out.append({
            "security_type": r.get("securityType") or None, "term": r.get("securityTerm") or None,
            "auction_date": _day(r.get("competitiveAuctionCloseDate")), "issue_date": _day(r.get("issueDate")),
            "maturity_date": _day(r.get("maturityDate")), "offering": number(r.get("offeringAmount")),
            "bid_to_cover": number(r.get("bidToCoverRatio")), "high_rate": rate, "cusip": r.get("cusip") or None,
            "reopening": r.get("reopening") or None,
        })
    return out


def newest_first(rows: list[dict]) -> list[dict]:
    """Stable: rows on the same day keep the order the source gave."""
    return sorted(rows, key=lambda r: r["auction_date"] or "", reverse=True)


def soonest_first(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda r: r["auction_date"] or "9999-12-31")
