"""BLS Public Data API v2 (US jobs, prices, wages): request builder and response parser. Pure code.

Endpoint: POST https://api.bls.gov/publicAPI/v2/timeseries/data/ with a JSON body
    {"seriesid": [...], "startyear": "2023", "endyear": "2026", "registrationkey": "<key>"}
Answer: {"status": "REQUEST_SUCCEEDED", "responseTime": 12, "message": [...],
         "Results": {"series": [{"seriesID": "...", "data": [{"year": "2026", "period": "M09", "periodName": "September",
                                  "latest": "true", "value": "4.3", "footnotes": [{"code": "P", "text": "..."}]}]}]}}
Shape checked against https://www.bls.gov/developers/api_signature_v2.htm (2026-11-05). Free registered key: 500 queries a day,
50 series per query, 20 years per query. Newest data first. A value of "-" means the BLS published nothing for that period.
"""

from __future__ import annotations

import re
from typing import Any

from .seriesboard import KeyRejected, NoData, NotUnderstood, build_series, num, safe_id

URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
SOURCE = "BLS PUBLIC DATA API V2 (US BUREAU OF LABOR STATISTICS)"
MAX_SERIES = 12

# alias -> (BLS series id, label, unit). All are the headline seasonally adjusted series.
CATALOG: dict[str, tuple[str, str, str]] = {
    "CPI": ("CUSR0000SA0", "CPI-U ALL ITEMS, SA", "INDEX 1982-84=100"),
    "CORECPI": ("CUSR0000SA0L1E", "CPI-U LESS FOOD AND ENERGY, SA", "INDEX 1982-84=100"),
    "PPI": ("WPSFD4", "PPI FINAL DEMAND, SA", "INDEX 2009-11=100"),
    "UNEMP": ("LNS14000000", "UNEMPLOYMENT RATE, SA", "%"),
    "LFPR": ("LNS11300000", "LABOR FORCE PARTICIPATION RATE, SA", "%"),
    "PAYROLL": ("CES0000000001", "TOTAL NONFARM EMPLOYEES, SA", "THOUSANDS"),
    "AHE": ("CES0500000003", "AVG HOURLY EARNINGS, TOTAL PRIVATE, SA", "USD"),
    "JOLTS": ("JTS000000000000000JOL", "JOB OPENINGS, TOTAL NONFARM, SA", "THOUSANDS"),
}
BY_ID = {v[0]: k for k, v in CATALOG.items()}
_RAW_ID = re.compile(r"^[A-Z0-9_#-]{5,40}$")  # the API rejects lowercase and other symbols in ids


def parse_ids(q: str) -> list[tuple[str, str]]:
    """'' -> the whole board. Words are aliases (CPI, UNEMP...) or raw BLS series ids. Returns [(alias, series id)]."""
    words = [w for w in re.split(r"[\s,]+", q.strip().upper()) if w]
    if not words:
        return [(a, v[0]) for a, v in CATALOG.items()]
    if len(words) > MAX_SERIES:
        raise ValueError(f"AT MOST {MAX_SERIES} SERIES A LOOKUP")
    out: list[tuple[str, str]] = []
    for w in words:
        if w in CATALOG:
            out.append((w, CATALOG[w][0]))
        elif _RAW_ID.match(w):
            out.append((BY_ID.get(w, w), safe_id(w)))
        else:
            raise ValueError(f"UNKNOWN BLS SERIES {w[:20]}. USE: {' '.join(CATALOG)} OR A BLS SERIES ID")
    return list(dict.fromkeys(out))


def build_body(ids: list[str], start_year: int, end_year: int, key: str) -> dict[str, Any]:
    return {"seriesid": ids, "startyear": str(start_year), "endyear": str(end_year), "registrationkey": key}


def _period(year: str, code: str) -> tuple[str, str] | None:
    """(sortable label, freq) for a BLS period code, or None for M13 / Q05 (annual averages, not a month or quarter)."""
    kind, n = code[:1], code[1:]
    if kind == "M" and n.isdigit() and 1 <= int(n) <= 12:
        return f"{year}-{int(n):02d}", "M"
    if (kind == "M" and n == "13") or (kind == "Q" and n == "05"):
        return None
    if kind == "Q" and n.isdigit() and 1 <= int(n) <= 4:
        return f"{year}-Q{int(n)}", "Q"
    if kind == "S" and n.isdigit() and int(n) in (1, 2):
        return f"{year}-S{int(n)}", "S"
    if kind == "A" and n == "01":
        return year, "A"
    raise NotUnderstood(f"UNKNOWN BLS PERIOD CODE {code[:6]}")


def parse(body: Any, wanted: list[tuple[str, str]]) -> dict[str, Any]:
    """The payload for `wanted` [(alias, id)]. A series the BLS did not return is listed in `missing`, never invented."""
    if not isinstance(body, dict) or "status" not in body:
        raise NotUnderstood("BLS ANSWER HAS NO status FIELD")
    messages = [str(m) for m in (body.get("message") or [])]
    if body["status"] != "REQUEST_SUCCEEDED":
        text = " ".join(messages) or str(body["status"])
        if re.search(r"(?i)\bkey\b.*\b(invalid|not valid|incorrect|unknown)|\b(invalid|unknown)\b.*\bkey\b|registration", text):
            raise KeyRejected("BLS REFUSED THE KEY")
        raise NotUnderstood(f"BLS DID NOT PROCESS THE REQUEST: {text[:160]}")
    results = (body.get("Results") or {}).get("series")
    if not isinstance(results, list):
        raise NotUnderstood("BLS ANSWER HAS NO Results.series LIST")
    by_id = {s.get("seriesID"): s for s in results if isinstance(s, dict)}
    out, missing = [], []
    for alias, sid in wanted:
        s = by_id.get(sid)
        rows = (s or {}).get("data") or []
        if not rows:
            missing.append(alias)
            continue
        pts: dict[str, float | None] = {}
        notes: list[str] = []
        freq = "M"
        for r in rows:
            got = _period(str(r["year"]), str(r["period"]))
            if got is None:
                continue
            label, freq = got
            pts[label] = num(r.get("value"))
            notes += [str(f["text"]).strip() for f in (r.get("footnotes") or []) if isinstance(f, dict) and f.get("text")]
        cat = CATALOG.get(alias)
        cat_info = s.get("catalog") if isinstance(s.get("catalog"), dict) else {}
        title = cat_info.get("series_title")
        out.append(build_series(sid, alias, cat[1] if cat else (title or sid).upper(), cat[2] if cat else "", freq,
                                sorted(pts.items()), notes))
    if not out:
        raise NoData("BLS RETURNED NO DATA FOR " + ", ".join(a for a, _ in wanted) + (f" ({' '.join(messages)[:120]})" if messages else ""))
    return {"series": out, "missing": missing, "messages": messages[:4], "source": SOURCE,
            "note": "BLS VALUES ARE AS PUBLISHED, SEASONALLY ADJUSTED WHERE MARKED. LAST = NEWEST PERIOD WITH A VALUE."}
