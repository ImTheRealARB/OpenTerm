"""WETR: Open-Meteo forecast and geocoding parsers, degree-day maths, the demand-city basket and NWS alerts. Pure code (no network).

Degree days are in degrees Fahrenheit, base 65 F, from the daily mean (max + min) / 2: the convention gas and power desks quote.
The basket is EQUAL-WEIGHTED: it is not weighted by gas or power demand, and the panel says so.
"""

from __future__ import annotations

import re
from typing import Any

from ..providers.base import ProviderError

BASE_F = 65.0
BASKET: tuple[tuple[str, float, float], ...] = (
    ("New York", 40.71, -74.01), ("Chicago", 41.88, -87.63), ("Boston", 42.36, -71.06), ("Philadelphia", 39.95, -75.17),
    ("Detroit", 42.33, -83.05), ("Houston", 29.76, -95.37), ("Atlanta", 33.75, -84.39), ("Dallas", 32.78, -96.80),
    ("London", 51.51, -0.13), ("Berlin", 52.52, 13.41),
)
DAILY_FIELDS = "temperature_2m_max,temperature_2m_min,temperature_2m_mean,precipitation_sum,wind_speed_10m_max,weather_code"
WMO: dict[int, str] = {
    0: "CLEAR", 1: "MAINLY CLEAR", 2: "PARTLY CLOUDY", 3: "OVERCAST", 45: "FOG", 48: "RIME FOG", 51: "LIGHT DRIZZLE", 53: "DRIZZLE", 55: "HEAVY DRIZZLE",
    56: "FREEZING DRIZZLE", 57: "FREEZING DRIZZLE", 61: "LIGHT RAIN", 63: "RAIN", 65: "HEAVY RAIN", 66: "FREEZING RAIN", 67: "FREEZING RAIN",
    71: "LIGHT SNOW", 73: "SNOW", 75: "HEAVY SNOW", 77: "SNOW GRAINS", 80: "RAIN SHOWERS", 81: "RAIN SHOWERS", 82: "VIOLENT SHOWERS",
    85: "SNOW SHOWERS", 86: "HEAVY SNOW SHOWERS", 95: "THUNDERSTORM", 96: "THUNDERSTORM, HAIL", 99: "THUNDERSTORM, HEAVY HAIL",
}
SEVERITY = {"EXTREME": 0, "SEVERE": 1, "MODERATE": 2, "MINOR": 3}
MAX_ALERTS = 20
_COORDS = re.compile(r"^\s*(-?\d{1,2}(?:\.\d+)?)\s*[,; ]\s*(-?\d{1,3}(?:\.\d+)?)\s*$")


def c_to_f(c: float) -> float:
    return c * 9.0 / 5.0 + 32.0


def degree_days(tmax_c: float | None, tmin_c: float | None) -> tuple[float, float] | None:
    """(heating, cooling) degree days in F-days for one day, or None when either extreme is missing."""
    if tmax_c is None or tmin_c is None:
        return None
    mean_f = c_to_f((tmax_c + tmin_c) / 2.0)
    return max(0.0, BASE_F - mean_f), max(0.0, mean_f - BASE_F)


def parse_place_arg(text: str) -> dict[str, Any] | None:
    """`WETR` args: empty = basket only; `lat,lon` = coordinates; anything else = a place name for the geocoder."""
    q = " ".join(text.split())
    if not q:
        return None
    m = _COORDS.match(q)
    if m:
        lat, lon = float(m.group(1)), float(m.group(2))
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("COORDINATES OUT OF RANGE: LATITUDE -90..90, LONGITUDE -180..180")
        return {"lat": lat, "lon": lon, "name": f"{lat:.2f},{lon:.2f}"}
    if len(q) > 60 or not re.search(r"[A-Za-z]", q):
        raise ValueError("PLACE: A NAME (HOUSTON) OR LAT,LON (29.76,-95.37)")
    return {"name": q}


def parse_geocode(body: Any) -> list[dict[str, Any]]:
    """Open-Meteo geocoding. No match = no `results` key at all, which is NOT FOUND (never an empty success)."""
    results = body.get("results") if isinstance(body, dict) else None
    if not results:
        raise ProviderError("not_found", "NO PLACE FOUND")
    out = []
    for r in results:
        if not isinstance(r, dict) or r.get("latitude") is None or r.get("longitude") is None:
            continue
        out.append({"name": r.get("name") or "", "admin1": r.get("admin1"), "country": r.get("country"), "cc": (r.get("country_code") or "").upper() or None,
                    "lat": float(r["latitude"]), "lon": float(r["longitude"]), "tz": r.get("timezone"), "population": r.get("population")})
    if not out:
        raise ProviderError("not_found", "NO PLACE FOUND")
    return out


def _num(x: Any) -> float | None:
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def parse_forecast(body: Any) -> dict[str, Any]:
    """One location's daily forecast: days with temperatures in C, degree days in F-days, totals over the days that have both extremes."""
    if not isinstance(body, dict) or not isinstance(body.get("daily"), dict) or not body["daily"].get("time"):
        raise ProviderError("unavailable", "FORECAST HAS NO DAILY BLOCK")
    d = body["daily"]
    n = len(d["time"])

    def col(name: str) -> list[Any]:
        v = d.get(name)
        return list(v) if isinstance(v, list) and len(v) == n else [None] * n

    tmax, tmin, tmean, rain, wind, code = (col(k) for k in ("temperature_2m_max", "temperature_2m_min", "temperature_2m_mean", "precipitation_sum", "wind_speed_10m_max", "weather_code"))
    days, hdd_total, cdd_total, counted = [], 0.0, 0.0, 0
    for i in range(n):
        dd = degree_days(_num(tmax[i]), _num(tmin[i]))
        if dd:
            hdd_total += dd[0]
            cdd_total += dd[1]
            counted += 1
        wc = int(code[i]) if _num(code[i]) is not None else None
        days.append({"date": d["time"][i], "tmax": _num(tmax[i]), "tmin": _num(tmin[i]), "tmean": _num(tmean[i]), "precip": _num(rain[i]), "wind": _num(wind[i]),
                     "code": wc, "sky": WMO.get(wc, f"WMO {wc}") if wc is not None else None, "hdd": dd[0] if dd else None, "cdd": dd[1] if dd else None})
    return {"lat": _num(body.get("latitude")), "lon": _num(body.get("longitude")), "tz": body.get("timezone"), "elevation": _num(body.get("elevation")),
            "days": days, "hdd": round(hdd_total, 1), "cdd": round(cdd_total, 1), "days_counted": counted}


def parse_forecast_many(body: Any, n: int) -> list[dict[str, Any]]:
    """A multi-location Open-Meteo request answers a list in request order; a single location answers one object."""
    items = body if isinstance(body, list) else [body]
    if len(items) != n:
        raise ProviderError("unavailable", f"FORECAST ANSWERED {len(items)} LOCATIONS FOR {n}")
    return [parse_forecast(b) for b in items]


def basket_rows(forecasts: list[dict[str, Any]]) -> dict[str, Any]:
    """The demand-city basket: 7-day heating / cooling degree days per city, then the equal-weighted average."""
    rows = []
    for (name, lat, lon), f in zip(BASKET, forecasts, strict=True):
        means = [x["tmean"] for x in f["days"] if x["tmean"] is not None]
        rows.append({"city": name, "lat": lat, "lon": lon, "hdd": f["hdd"], "cdd": f["cdd"], "days": f["days_counted"],
                     "tmean": round(sum(means) / len(means), 1) if means else None,
                     "tmax": max((x["tmax"] for x in f["days"] if x["tmax"] is not None), default=None),
                     "tmin": min((x["tmin"] for x in f["days"] if x["tmin"] is not None), default=None)})
    ok = [r for r in rows if r["days"]]
    avg = {"hdd": round(sum(r["hdd"] for r in ok) / len(ok), 1), "cdd": round(sum(r["cdd"] for r in ok) / len(ok), 1)} if ok else None
    return {"rows": rows, "average": avg, "weighting": "EQUAL-WEIGHTED, NOT WEIGHTED BY GAS OR POWER DEMAND"}


def parse_alerts(body: Any) -> list[dict[str, Any]]:
    """NWS `alerts/active` GeoJSON, most severe first (then soonest end), at most MAX_ALERTS."""
    feats = body.get("features") if isinstance(body, dict) else None
    if feats is None:
        raise ProviderError("unavailable", "NWS ANSWER HAS NO FEATURES")
    out = []
    for f in feats:
        p = f.get("properties") if isinstance(f, dict) else None
        if not isinstance(p, dict):
            continue
        out.append({"event": p.get("event") or "ALERT", "severity": p.get("severity") or "Unknown", "urgency": p.get("urgency"),
                    "area": p.get("areaDesc"), "headline": p.get("headline"), "onset": p.get("onset") or p.get("effective"),
                    "ends": p.get("ends") or p.get("expires"), "sender": p.get("senderName")})
    out.sort(key=lambda a: (SEVERITY.get(str(a["severity"]).upper(), 9), a["ends"] or "9"))
    return out[:MAX_ALERTS]


def in_nws_coverage(lat: float, lon: float) -> bool:
    """Rough box around the US states, Alaska, Hawaii and territories: NWS answers an error outside its area, so skip the call."""
    return (24.0 <= lat <= 50.0 and -125.0 <= lon <= -66.0) or (51.0 <= lat <= 72.0 and -180.0 <= lon <= -129.0) or (18.0 <= lat <= 23.0 and -161.0 <= lon <= -154.0) or (17.5 <= lat <= 18.6 and -68.0 <= lon <= -64.0)
