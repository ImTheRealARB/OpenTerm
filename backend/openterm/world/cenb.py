"""CENB: policy-rate parsers (FRED CSV, ECB SDMX-JSON, Bank of Canada Valet, Bank of England IADB CSV) and the table builder (pure)."""

from __future__ import annotations

import csv
import io
from datetime import date, datetime
from typing import Any

from ..providers.base import ProviderError
from . import cb_calendar as cal

RATE_SOURCES = {
    "FED": ("FRED DFEDTARU", "TARGET RANGE UPPER BOUND"),
    "ECB": ("ECB DATA PORTAL FM/MRR_FR", "MAIN REFINANCING OPERATIONS RATE"),
    "BOE": ("BANK OF ENGLAND IADB IUDBEDR", "BANK RATE"),
    "BOC": ("BANK OF CANADA VALET V39079", "TARGET FOR THE OVERNIGHT RATE"),
}


def parse_fred_csv_last(text: str) -> tuple[str, float]:
    last = None
    for row in csv.reader(io.StringIO(text)):
        if len(row) >= 2 and row[0][:2] == "20":
            try:
                last = (row[0], float(row[1]))
            except ValueError:
                continue  # FRED writes "." for a missing day
    if last is None:
        raise ProviderError("unavailable", "FRED CSV HAS NO VALUES")
    return last


def parse_ecb_last(body: Any) -> tuple[str, float]:
    try:
        series = next(iter(body["dataSets"][0]["series"].values()))
        obs = series["observations"]
        idx = max(obs, key=int)
        dates = body["structure"]["dimensions"]["observation"][0]["values"]
        return str(dates[int(idx)]["id"])[:10], float(obs[idx][0])
    except (KeyError, IndexError, StopIteration, TypeError, ValueError) as e:
        raise ProviderError("unavailable", "ECB ANSWER HAS NO OBSERVATION") from e


def parse_boc_last(body: Any) -> tuple[str, float]:
    try:
        row = body["observations"][-1]
        return str(row["d"]), float(row["V39079"]["v"])
    except (KeyError, IndexError, TypeError, ValueError) as e:
        raise ProviderError("unavailable", "BANK OF CANADA ANSWER HAS NO OBSERVATION") from e


def parse_boe_last(text: str) -> tuple[str, float]:
    last = None
    for row in csv.reader(io.StringIO(text)):
        if len(row) >= 2:
            try:
                last = (datetime.strptime(row[0].strip(), "%d %b %Y").date().isoformat(), float(row[1]))
            except ValueError:
                continue
    if last is None:
        raise ProviderError("unavailable", "BANK OF ENGLAND CSV HAS NO VALUES")
    return last


def days_until(iso: str | None, today: date) -> int | None:
    return None if iso is None else (date.fromisoformat(iso) - today).days


def build(rates: dict[str, dict[str, Any]], fomc: list[str] | None, today: date) -> dict[str, Any]:
    """One row per bank. A bank whose current/next year is not loaded says so in `note`; nothing is estimated."""
    rows = []
    for key in cal.ORDER:
        info = cal.BANKS[key]
        live = fomc if info.get("live") else None
        this = cal.decisions(key, today.year, live)
        nxt = cal.decisions(key, today.year + 1, live)
        every = sorted([*(this or []), *(nxt or [])])
        prev, nxt1, nxt2 = cal.around(every, today)
        notes = []
        if this is None:
            notes.append(f"CALENDAR NOT LOADED FOR {today.year}" + (" (FOMC PAGE DID NOT ANSWER)" if info.get("live") and fomc is None else ""))
        elif (key, today.year) in cal.PARTIAL:
            notes.append(cal.PARTIAL[(key, today.year)])
        if nxt1 is None and this is not None:
            notes.append(f"NO MEETING LISTED AFTER {today.isoformat()}")
        r = rates.get(key)
        rows.append({
            "bank": key, "name": info["name"], "last": prev, "next": nxt1, "after": nxt2, "days": days_until(nxt1, today),
            "rate": r.get("rate") if r else None, "rate_as_of": r.get("as_of") if r else None,
            "rate_label": RATE_SOURCES[key][1] if key in RATE_SOURCES else None,
            "rate_note": (r or {}).get("error") if key in RATE_SOURCES else "NO KEYLESS POLICY-RATE SOURCE",
            "dates": every, "url": info["url"], "note": "; ".join(notes) or None,
        })
    return {"today": today.isoformat(), "rows": rows, "calendar_as_of": cal.AS_OF, "note": cal.RANGE_NOTE}
