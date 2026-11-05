"""Pure query building and maths for PORTS: IMF PortWatch daily activity at about 1,600 ports.

No network and no pandas here (the server process must never import pandas). The provider (`providers/portwatch.py`)
fetches; this file builds the ArcGIS `where` strings, picks the ids, and turns the daily rows into board rows.

Why the queries look the way they do: the ArcGIS layer answers at most 1000 rows per call, and 1,600 ports x 40 days is
64,000 rows. So PORTS never downloads everything:
  * bare `PORTS`           -> a server-side sum of port calls per port over the newest 7 days (`outStatistics`), the 25 busiest
                              ids from it, then the daily rows of just those 25 (25 x ~35 days = ~875 rows);
  * `PORTS <words>`        -> the port list (`PortWatch_ports_database`) filtered by the words, the 20 biggest matches, then
                              their daily rows.
Same honesty rules as SHIP: every row shows its own date, STALE past `STALE_DAYS`, nothing is estimated by us (a missing number
stays None). The import / export columns are PortWatch's own modelled estimates, not measured cargo.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Any

# Private helpers of the SHIP module are reused on purpose: same service, same field types (date string, numbers or null).
from .shipping import PortWatchError, _avg, _day, _num, check_body

__all__ = ["PortWatchError", "check_body"]

WINDOW = 7  # days averaged for the "now" figure
BASE_DAYS = 21  # the days before that window, used as the comparison base
STALE_DAYS = 21  # PortWatch lags about 6 to 12 days; past 21 something is wrong upstream
HISTORY_DAYS = 40  # how far back the daily rows are asked for (covers 7 + 21 days plus the publishing lag)
TOP_N = 25  # bare PORTS: the busiest 25 ports (25 ports x 40 days stays under the 1000-row page)
MATCH_N = 20  # PORTS <words>: at most the 20 biggest matching ports (20 x 40 days = 800 rows)
GEO_N = 100  # MAP ports layer: the busiest 100 ports (no daily rows are fetched, so the 1000-row page limit does not bite)
MAX_WORDS = 4
MAX_WORD_LEN = 30

# Fields asked for from the daily layer. portcalls_* = ships calling that day by type; import / export = PortWatch's estimates.
DAILY_FIELDS = ("date,portid,portname,country,ISO3,portcalls,portcalls_container,portcalls_dry_bulk,portcalls_general_cargo,"
                "portcalls_roro,portcalls_tanker,import,export")
# Fields asked for from the port list. vessel_count_total ranks the matches (bigger = more ships seen over the years).
PORT_FIELDS = "portid,portname,country,ISO3,continent,fullname,lat,lon,vessel_count_total,LOCODE"

# One server-side aggregation: sum of port calls per port over a date window. No row ever leaves the server except the 25 results.
TOP_STATS = json.dumps([{"statisticType": "sum", "onStatisticField": "portcalls", "outStatisticFieldName": "calls7"}])
NEWEST_STATS = json.dumps([{"statisticType": "max", "onStatisticField": "date", "outStatisticFieldName": "newest"}])

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


# --- query building -----------------------------------------------------------------------------------------------------
def words_of(query: str) -> list[str]:
    """Search words from the command line, upper-cased. Only letters, digits, space . ' - are kept, so no SQL wildcard
    (% or _) and no quote trick can reach the `where` string (an apostrophe is doubled later). Raises ValueError when too long."""
    clean = "".join(c if c.isalnum() or c in " .'-" else " " for c in query)
    words = [w.strip(".'-") for w in clean.upper().split()]
    words = [w for w in words if w]
    if len(words) > MAX_WORDS:
        raise ValueError(f"TOO MANY WORDS (MAX {MAX_WORDS}): TRY A PORT NAME OR A COUNTRY")
    if any(len(w) > MAX_WORD_LEN for w in words):
        raise ValueError("A WORD IS TOO LONG FOR A PORT OR COUNTRY NAME")
    return words


def ports_where(words: list[str]) -> str:
    """A port matches when EVERY word is found in its name, country or full name (so `port said` finds Port Said, Egypt)."""
    if not words:
        raise ValueError("NO SEARCH WORDS")
    parts = []
    for w in words:
        w = w.replace("'", "''")  # SQL string escape: a single quote is doubled
        parts.append(f"(UPPER(portname) LIKE '%{w}%' OR UPPER(country) LIKE '%{w}%' OR UPPER(fullname) LIKE '%{w}%')")
    return " AND ".join(parts)


def daily_where(ids: list[str], since: date) -> str:
    """Daily rows of these ports since `since`. Ids come from the service itself but are still checked before going into SQL."""
    bad = [i for i in ids if not _ID_RE.match(i)]
    if bad or not ids:
        raise ValueError("UNEXPECTED PORT ID FROM PORTWATCH")
    quoted = ",".join(f"'{i}'" for i in ids)
    return f"portid IN ({quoted}) AND date >= DATE '{since.isoformat()}'"


def newest_day(attrs: list[dict[str, Any]]) -> date:
    """The newest date on record, from the one-row `max(date)` answer."""
    d = _day(attrs[0].get("newest")) if attrs else None
    if d is None:
        raise ValueError("PORTWATCH GAVE NO NEWEST DATE")
    return d


def top_window_start(newest: date) -> date:
    """First day of the 7-day window that ends on the newest day on record (the `>` side of the where is exclusive)."""
    return newest - timedelta(days=WINDOW)


def top_ids(attrs: list[dict[str, Any]], limit: int = TOP_N) -> list[str]:
    """Port ids of the busiest ports, in the order the server sent them (already sorted by calls, biggest first)."""
    ids = [a["portid"] for a in attrs if isinstance(a.get("portid"), str)]
    if not ids:
        raise ValueError("PORTWATCH ANSWER HAD NO PORTS")
    return ids[:limit]


def ids_where(ids: list[str]) -> str:
    """Port-list rows for these ids (the ids come from the service itself but are still checked before going into SQL)."""
    bad = [i for i in ids if not _ID_RE.match(i)]
    if bad or not ids:
        raise ValueError("UNEXPECTED PORT ID FROM PORTWATCH")
    return f"portid IN ({','.join(repr(i) for i in ids)})"


def match_ids(meta: list[dict[str, Any]]) -> list[str]:
    """Ids of the matching ports (the service already sorted them by size and capped the list)."""
    return [a["portid"] for a in meta if isinstance(a.get("portid"), str)][:MATCH_N]


# --- rows ---------------------------------------------------------------------------------------------------------------
def group(attrs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Group daily rows by port id. Each value: {"name", "country", "iso3", "days": [(date, row)] oldest first}."""
    out: dict[str, dict[str, Any]] = {}
    for a in attrs:
        pid, d = a.get("portid"), _day(a.get("date"))
        if not isinstance(pid, str) or d is None:
            continue
        slot = out.setdefault(pid, {"name": str(a.get("portname") or pid), "country": a.get("country"), "iso3": a.get("ISO3"), "days": []})
        slot["days"].append((d, a))
    for slot in out.values():
        slot["days"].sort(key=lambda x: x[0])
    return out


def make_row(pid: str, slot: dict[str, Any], today: date, meta: dict[str, Any] | None) -> dict[str, Any]:
    """One board row: the last 7 days of port calls against the 21 days before them. A missing number stays None."""
    days = slot["days"]
    rows = [r for _, r in days]
    last_day = days[-1][0]
    recent, base = rows[-WINDOW:], rows[-(WINDOW + BASE_DAYS) : -WINDOW]
    now, then = _avg(recent, "portcalls"), _avg(base, "portcalls")
    chg = None if now is None or not then else (now / then - 1) * 100
    age = (today - last_day).days
    meta = meta or {}
    return {
        "id": pid, "name": slot["name"], "country": slot["country"] or meta.get("country"), "iso3": slot["iso3"] or meta.get("ISO3"),
        "date": last_day.isoformat(), "age_days": age, "stale": age > STALE_DAYS,
        "last": _num(rows[-1].get("portcalls")), "avg7": now, "base": then, "chg_pct": chg,
        "tanker": _avg(recent, "portcalls_tanker"), "container": _avg(recent, "portcalls_container"),
        "dry_bulk": _avg(recent, "portcalls_dry_bulk"),
        # PortWatch's own modelled daily trade estimates, averaged over the same 7 days (units: see the service NOTE)
        "imp7": _avg(recent, "import"), "exp7": _avg(recent, "export"),
        "n_days": len(days), "base_days": len(base),
        "lat": _num(meta.get("lat")), "lon": _num(meta.get("lon")), "locode": meta.get("LOCODE"),
        "series": [[d.isoformat(), _num(r.get("portcalls"))] for d, r in days[-(WINDOW + BASE_DAYS) :]],
    }


def board(daily: list[dict[str, Any]], meta: list[dict[str, Any]], today: date) -> tuple[list[dict[str, Any]], int]:
    """Rows for every port that has daily data, busiest first by 7-day average, plus how many wanted ports had NO daily rows.
    Raises ValueError when the answer had no usable rows at all."""
    grouped = group(daily)
    if not grouped:
        raise ValueError("PORTWATCH ANSWER HAD NO USABLE ROWS")
    by_id = {a["portid"]: a for a in meta if isinstance(a.get("portid"), str)}
    rows = [make_row(pid, slot, today, by_id.get(pid)) for pid, slot in grouped.items()]
    rows.sort(key=lambda r: -(r["avg7"] or 0))
    missing = len([i for i in by_id if i not in grouped])  # ports the list knows but the daily layer has nothing for
    return rows, missing
