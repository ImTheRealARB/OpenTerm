"""Pure parsers for the MAP panel's geo layers (no network, no pandas): USGS earthquakes, NASA EONET natural events, PortWatch ports.

Every parser takes the raw upstream body and returns plain rows with `lat` / `lon` in degrees and a `time` in epoch SECONDS (UTC),
so the panel can show "age" for each point. A feature the parser cannot place on the map (no coordinates, an unknown shape) is
counted in `skipped`, never guessed at. Longitudes are -180..180, latitudes -90..90; anything outside is dropped and counted.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from .ais import PRESETS


def _num(v: Any) -> float | None:
    """A finite number or None (bool and strings are not numbers)."""
    if isinstance(v, bool) or not isinstance(v, int | float):
        return None
    return float(v) if math.isfinite(v) else None


def _in_range(lat: float | None, lon: float | None) -> bool:
    return lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180


def _iso_to_s(text: Any) -> float | None:
    """'2026-11-02T06:00:00Z' -> epoch seconds; None for anything that is not an ISO time."""
    if not isinstance(text, str):
        return None
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


# --- USGS earthquakes --------------------------------------------------------------------------------------------------------
def quakes(body: Any) -> dict[str, Any]:
    """USGS GeoJSON summary feed -> {"rows", "skipped", "title", "generated"}. Raises ValueError when the body is not that feed."""
    if not isinstance(body, dict) or not isinstance(body.get("features"), list):
        raise ValueError("USGS ANSWER HAS NO FEATURES LIST")  # noqa: TRY004  (geosvc turns ValueError into a data error)
    rows, skipped = [], 0
    for f in body["features"]:
        props = f.get("properties") if isinstance(f, dict) else None
        coords = (f.get("geometry") or {}).get("coordinates") if isinstance(f, dict) else None
        if not isinstance(props, dict) or not isinstance(coords, list) or len(coords) < 2:
            skipped += 1
            continue
        lon, lat = _num(coords[0]), _num(coords[1])
        t = _num(props.get("time"))
        if not _in_range(lat, lon) or t is None:
            skipped += 1
            continue
        rows.append({
            "id": str(f.get("id") or props.get("code") or ""), "lat": lat, "lon": lon,
            "depth_km": _num(coords[2]) if len(coords) > 2 else None,
            "mag": _num(props.get("mag")), "mag_type": props.get("magType"),
            "place": props.get("place") or "", "time": t / 1000.0,  # USGS times are epoch milliseconds
            "url": props.get("url"), "tsunami": bool(props.get("tsunami")), "alert": props.get("alert"),
            "status": props.get("status"),
        })
    rows.sort(key=lambda r: -r["time"])
    meta = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
    gen = _num(meta.get("generated"))
    return {"rows": rows, "skipped": skipped, "title": meta.get("title") or "", "generated": gen / 1000.0 if gen is not None else None}


# --- NASA EONET natural events ----------------------------------------------------------------------------------------------
def events(body: Any) -> dict[str, Any]:
    """EONET v3 `events` answer -> one row per event at its NEWEST position, plus the earlier positions as a `track` (a storm's path).

    Only `Point` geometries are placed; an event whose newest geometry is anything else is counted in `skipped` (EONET documents
    polygons, but none were open when this was written)."""
    if not isinstance(body, dict) or not isinstance(body.get("events"), list):
        raise ValueError("EONET ANSWER HAS NO EVENTS LIST")  # noqa: TRY004
    rows, skipped = [], 0
    for ev in body["events"]:
        if not isinstance(ev, dict):
            skipped += 1
            continue
        pts = []
        for g in ev.get("geometry") or []:
            c = g.get("coordinates") if isinstance(g, dict) and g.get("type") == "Point" else None
            if isinstance(c, list) and len(c) >= 2:
                lon, lat, t = _num(c[0]), _num(c[1]), _iso_to_s(g.get("date"))
                if _in_range(lat, lon) and t is not None:
                    pts.append((t, lat, lon, _num(g.get("magnitudeValue")), g.get("magnitudeUnit")))
        if not pts:
            skipped += 1
            continue
        pts.sort(key=lambda p: p[0])
        t, lat, lon, mag, unit = pts[-1]
        cat = (ev.get("categories") or [{}])[0]
        src = (ev.get("sources") or [{}])[0]
        rows.append({
            "id": str(ev.get("id") or ""), "title": ev.get("title") or "", "category": cat.get("id") or "other",
            "category_title": cat.get("title") or "Other", "lat": lat, "lon": lon, "time": t,
            "mag": mag, "mag_unit": unit, "source": src.get("id"), "url": ev.get("link"),
            "track": [[p[2], p[1]] for p in pts],  # [lon, lat] oldest first; a single point means no path
        })
    rows.sort(key=lambda r: -r["time"])
    return {"rows": rows, "skipped": skipped, "title": body.get("title") or ""}


# --- PortWatch ports (position + activity) ----------------------------------------------------------------------------------
def ports(top: list[dict[str, Any]], meta: list[dict[str, Any]], newest: str, window: int) -> dict[str, Any]:
    """Join the server-side port-call sums (`calls7` per port, biggest first) with the port list's coordinates.

    `calls_per_day` = calls7 / window. A port with no coordinates in the list is counted in `skipped` (it cannot be drawn)."""
    by_id = {a["portid"]: a for a in meta if isinstance(a, dict) and isinstance(a.get("portid"), str)}
    rows, skipped = [], 0
    for rank, a in enumerate(top):
        pid, calls = a.get("portid"), _num(a.get("calls7"))
        m = by_id.get(pid)
        lat, lon = (_num(m.get("lat")), _num(m.get("lon"))) if m else (None, None)
        if not isinstance(pid, str) or calls is None or not _in_range(lat, lon):
            skipped += 1
            continue
        rows.append({"id": pid, "name": str(m.get("portname") or pid), "country": m.get("country"), "locode": m.get("LOCODE"),
                     "lat": lat, "lon": lon, "rank": rank + 1, "calls_per_day": calls / window, "newest": newest})
    if not rows:
        raise ValueError("PORTWATCH GAVE NO PORTS WITH COORDINATES")
    return {"rows": rows, "skipped": skipped, "newest": newest}


# --- Chokepoint boxes (the AIS presets) --------------------------------------------------------------------------------------
def chokepoints() -> list[dict[str, Any]]:
    """The AIS preset boxes as map rectangles. `box` = [south, west, north, east]; `lat`/`lon` = the centre (the point a jump goes to)."""
    return [{"id": name, "name": name, "box": list(box), "lat": (box[0] + box[2]) / 2, "lon": (box[1] + box[3]) / 2}
            for name, box in PRESETS.items()]
