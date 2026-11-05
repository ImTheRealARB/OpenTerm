"""Pure parsing and maths for SHIP: IMF PortWatch daily ship transits through 28 sea chokepoints.

No network and no pandas here (the server process must never import pandas). The provider
(`providers/portwatch.py`) fetches; this file turns the ArcGIS answer into the board rows.

PortWatch counts ships from satellite AIS (ship radio) signals. It is published weekly, so the newest
day is usually 8 to 12 days old: every row shows its own date and turns STALE past `STALE_DAYS`.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

# The ArcGIS layer answers with HTTP 200 and an {"error": ...} body when it fails. The service sits behind
# several nodes and some of them answer a perfectly valid request with these two messages (seen 2026-11-05,
# about two calls in three). They are worth a retry; any other error is real and is raised at once.
# "Invalid query parameters" is a third face of the same glitch, seen 2026-11-05 on the Daily_Ports_Data layer: identical, valid
# requests failed with it in 2 of 5 live runs and succeeded on the next try (PORTS).
FLAKY_MESSAGES = ("Invalid URL", "Object reference not set", "Invalid query parameters")

# Fields we ask for. n_* are ship counts per day by type, `capacity` is PortWatch's own ship-capacity figure.
FIELDS = "date,portid,portname,n_total,n_tanker,n_container,n_dry_bulk,n_general_cargo,n_roro,capacity"
WINDOW = 7  # days averaged for the "now" figure
BASE_DAYS = 21  # the days before that window, used as the comparison base
STALE_DAYS = 21  # PortWatch normally lags 8 to 12 days; past 21 something is wrong upstream


class PortWatchError(Exception):
    """The ArcGIS service answered with an error body. `flaky` marks the node glitch worth retrying."""

    def __init__(self, message: str, flaky: bool):
        super().__init__(message)
        self.flaky = flaky


def check_body(body: Any) -> list[dict[str, Any]]:
    """Return the feature attribute dicts, or raise PortWatchError for an error body / unexpected shape."""
    if not isinstance(body, dict):
        raise PortWatchError("PORTWATCH ANSWERED WITH SOMETHING THAT IS NOT JSON OBJECT", False)
    err = body.get("error")
    if err:
        msg = str(err.get("message", "")) if isinstance(err, dict) else str(err)
        raise PortWatchError(f"PORTWATCH ERROR: {msg[:120]}", any(m in msg for m in FLAKY_MESSAGES))
    feats = body.get("features")
    if not isinstance(feats, list):
        raise PortWatchError("PORTWATCH ANSWER HAS NO FEATURES LIST (FORMAT CHANGED?)", False)
    return [f["attributes"] for f in feats if isinstance(f, dict) and isinstance(f.get("attributes"), dict)]


def _day(v: Any) -> date | None:
    """PortWatch's `date` is a plain 'YYYY-MM-DD' string; accept epoch milliseconds too (older layers)."""
    if isinstance(v, str):
        try:
            return date.fromisoformat(v[:10])
        except ValueError:
            return None
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v / 1000, tz=None).date()
    return None


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def group(attrs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Group daily rows by chokepoint id. Each value: {"name", "days": [(date, row)] oldest first}."""
    out: dict[str, dict[str, Any]] = {}
    for a in attrs:
        pid, d = a.get("portid"), _day(a.get("date"))
        if not isinstance(pid, str) or d is None:
            continue
        slot = out.setdefault(pid, {"name": str(a.get("portname") or pid), "days": []})
        slot["days"].append((d, a))
    for slot in out.values():
        slot["days"].sort(key=lambda x: x[0])
    return out


def _avg(rows: list[dict[str, Any]], key: str) -> float | None:
    vals = [v for r in rows if (v := _num(r.get(key))) is not None]
    return sum(vals) / len(vals) if vals else None


def make_row(pid: str, slot: dict[str, Any], today: date) -> dict[str, Any]:
    """One board row: the last 7 days against the 21 days before them. Nothing is estimated: a missing number stays None."""
    days = slot["days"]
    rows = [r for _, r in days]
    last_day = days[-1][0]
    recent, base = rows[-WINDOW:], rows[-(WINDOW + BASE_DAYS) : -WINDOW]
    now, then = _avg(recent, "n_total"), _avg(base, "n_total")
    chg = None if now is None or not then else (now / then - 1) * 100
    age = (today - last_day).days
    return {
        "id": pid, "name": slot["name"], "date": last_day.isoformat(), "age_days": age, "stale": age > STALE_DAYS,
        "last": _num(rows[-1].get("n_total")), "avg7": now, "base": then, "chg_pct": chg,
        "tanker": _avg(recent, "n_tanker"), "container": _avg(recent, "n_container"),
        "dry_bulk": _avg(recent, "n_dry_bulk"), "capacity": _avg(recent, "capacity"),
        "n_days": len(days), "base_days": len(base),
        # the daily totals of the last 28 days, oldest first, for the sparkline and the detail view
        "series": [[d.isoformat(), _num(r.get("n_total"))] for d, r in days[-(WINDOW + BASE_DAYS) :]],
    }


def board(attrs: list[dict[str, Any]], today: date) -> list[dict[str, Any]]:
    """All chokepoints, busiest first by 7-day average. Raises ValueError when the answer had no usable rows."""
    grouped = group(attrs)
    if not grouped:
        raise ValueError("PORTWATCH ANSWER HAD NO USABLE ROWS")
    rows = [make_row(pid, slot, today) for pid, slot in grouped.items()]
    rows.sort(key=lambda r: -(r["avg7"] or 0))
    return rows
