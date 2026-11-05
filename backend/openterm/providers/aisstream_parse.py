"""Pure parsers for AISstream (aisstream.io), the free beta WebSocket of live ship positions. No network, no pandas, no websockets import.

Shapes come from the official documentation (aisstream.io/documentation, read 2026-11-05) and its generated model list, NOT from
recordings: no API key existed when this was written. What the docs say, and what this file relies on:
  - Subscription (the first and only message we send): {"APIKey", "BoundingBoxes": [[[lat, lon], [lat, lon]]], "FilterMessageTypes": [...]}.
    A box is two opposite corners; the docs example lists the north-west corner first.
  - Every stream message is {"MessageType", "MetaData", "Message": {<MessageType>: {...}}}. A subscription confirmation has no MetaData.
  - PositionReport / StandardClassBPositionReport / ExtendedClassBPositionReport carry UserID (the MMSI, a ship's radio identity number),
    Latitude, Longitude, Sog (speed over ground, knots), Cog (course over ground, degrees), TrueHeading and Valid.
    PositionReport also has NavigationalStatus; the Extended class B one also has Name and Type.
  - ShipStaticData carries ImoNumber, CallSign, Name, Type, Dimension {A,B,C,D}, Eta {Month,Day,Hour,Minute}, MaximumStaticDraught, Destination.
  - The ITU AIS standard marks "not available" with sentinel numbers (Sog 102.3, Cog 360, heading 511, lat 91, lon 181) and pads text
    fields with "@". Those are turned into None here, never shown as numbers.
NOT in the docs (from memory of the live feed, unverified): the MetaData `time_utc` text format (parsed leniently below, falls back to the
time we received the message) and the exact wording of the error a bad key gets (`error_text` just passes it on).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

import orjson

URL = "wss://stream.aisstream.io/v0/stream"
POSITION_TYPES = ("PositionReport", "StandardClassBPositionReport", "ExtendedClassBPositionReport")
STATIC_TYPE = "ShipStaticData"
FILTER_TYPES = (*POSITION_TYPES, STATIC_TYPE)
MAX_SPAN_DEG = 12.0  # a bigger box floods us with messages for no benefit; the presets are all well under it


# --- subscription ---------------------------------------------------------------------------------------------------------
def check_box(lat_min: Any, lon_min: Any, lat_max: Any, lon_max: Any) -> tuple[float, float, float, float]:
    """Validates a bounding box (south, west, north, east in degrees) and returns it as floats. ValueError with a screen-ready text."""
    try:
        a, b, c, d = (float(x) for x in (lat_min, lon_min, lat_max, lon_max))
    except (TypeError, ValueError) as e:
        raise ValueError("BOX NEEDS FOUR NUMBERS: SOUTH WEST NORTH EAST") from e
    if not (-90 <= a < c <= 90):
        raise ValueError("LATITUDES MUST BE -90..90 AND SOUTH MUST BE BELOW NORTH")
    if not (-180 <= b < d <= 180):
        raise ValueError("LONGITUDES MUST BE -180..180 AND WEST MUST BE BELOW EAST (A BOX CANNOT CROSS THE DATE LINE)")
    if c - a > MAX_SPAN_DEG or d - b > MAX_SPAN_DEG:
        raise ValueError(f"BOX TOO BIG: AT MOST {MAX_SPAN_DEG:g} DEGREES EACH WAY")
    return a, b, c, d


def subscription(key: str, box: tuple[float, float, float, float], types: tuple[str, ...] = FILTER_TYPES) -> dict[str, Any]:
    """The one JSON message AISstream wants within 3 seconds of connecting. Corners: north-west first, then south-east, as in the docs."""
    south, west, north, east = box
    return {"APIKey": key, "BoundingBoxes": [[[north, west], [south, east]]], "FilterMessageTypes": list(types)}


# --- one message ----------------------------------------------------------------------------------------------------------
def decode(raw: bytes | str) -> dict[str, Any]:
    """The service sends binary frames holding UTF-8 JSON; text frames are accepted too. ValueError if it is not a JSON object."""
    try:
        msg = orjson.loads(raw)
    except orjson.JSONDecodeError as e:
        raise ValueError("NOT JSON") from e
    if not isinstance(msg, dict):
        raise ValueError("NOT A JSON OBJECT")  # noqa: TRY004  (callers catch ValueError for every unreadable frame)
    return msg


def kind_of(msg: dict[str, Any]) -> str:
    """confirmation | error | position | static | other."""
    if isinstance(msg.get("error"), str):
        return "error"
    t = msg.get("MessageType")
    if t == "SubscriptionConfirmation":
        return "confirmation"
    if t in POSITION_TYPES:
        return "position"
    if t == STATIC_TYPE:
        return "static"
    return "other"


def error_text(msg: dict[str, Any]) -> str:
    return str(msg.get("error") or "")[:200]


def _inner(msg: dict[str, Any]) -> dict[str, Any] | None:
    body = msg.get("Message")
    inner = body.get(msg.get("MessageType")) if isinstance(body, dict) else None
    return inner if isinstance(inner, dict) else None


def _text(v: Any) -> str:
    """AIS text: padded with '@' and spaces."""
    return str(v or "").replace("@", " ").strip()


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


_TIME = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})(?:\.(\d+))? \+0000 UTC$")


def _time_utc(text: Any) -> float | None:
    """MetaData.time_utc, e.g. "2022-12-29 18:22:32.318353 +0000 UTC" (format from memory of the live feed). None if it does not match."""
    m = _TIME.match(str(text or ""))
    if not m:
        return None
    day, clock, frac = m.groups()
    t = datetime.strptime(f"{day} {clock}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC).timestamp()
    return t + (int(frac[:6].ljust(6, "0")) / 1e6 if frac else 0.0)


def position(msg: dict[str, Any], now: float) -> dict[str, Any] | None:
    """A ship position, or None if the message has no usable location. `now` (epoch seconds) stands in for the time if time_utc is unreadable."""
    inner = _inner(msg)
    if inner is None or inner.get("Valid") is False:
        return None
    meta = msg.get("MetaData") if isinstance(msg.get("MetaData"), dict) else {}
    mmsi = inner.get("UserID") or meta.get("MMSI")
    lat, lon = _num(inner.get("Latitude")), _num(inner.get("Longitude"))
    if not isinstance(mmsi, int) or isinstance(mmsi, bool) or mmsi <= 0 or lat is None or lon is None:
        return None
    if abs(lat) > 90 or abs(lon) > 180:  # 91 / 181 = "not available"
        return None
    sog, cog, heading = _num(inner.get("Sog")), _num(inner.get("Cog")), inner.get("TrueHeading")
    nav = inner.get("NavigationalStatus")
    return {
        "mmsi": mmsi,
        "name": _text(meta.get("ShipName")) or _text(inner.get("Name")),
        "lat": lat, "lon": lon,
        "sog": sog if sog is not None and sog < 102.3 else None,
        "cog": cog if cog is not None and cog < 360 else None,
        "heading": heading if isinstance(heading, int) and 0 <= heading <= 359 else None,
        "nav": nav if isinstance(nav, int) and not isinstance(nav, bool) else None,
        "type": inner.get("Type") if isinstance(inner.get("Type"), int) else None,  # only the extended class B report carries it
        "seen": _time_utc(meta.get("time_utc")) or now,
        "msg": msg.get("MessageType"),
    }


def static(msg: dict[str, Any], now: float) -> dict[str, Any] | None:
    """ShipStaticData: identity, size and voyage (destination, ETA). Blank AIS fields become None."""
    inner = _inner(msg)
    if inner is None or inner.get("Valid") is False:
        return None
    meta = msg.get("MetaData") if isinstance(msg.get("MetaData"), dict) else {}
    mmsi = inner.get("UserID") or meta.get("MMSI")
    if not isinstance(mmsi, int) or isinstance(mmsi, bool) or mmsi <= 0:
        return None
    dim = inner.get("Dimension") if isinstance(inner.get("Dimension"), dict) else {}
    parts = {k: dim.get(k) for k in "ABCD"}
    ok = all(isinstance(v, int) and v >= 0 for v in parts.values())
    imo, draught = inner.get("ImoNumber"), _num(inner.get("MaximumStaticDraught"))
    return {
        "mmsi": mmsi,
        "imo": imo if isinstance(imo, int) and imo > 0 else None,
        "callsign": _text(inner.get("CallSign")) or None,
        "name": _text(inner.get("Name")) or None,
        "type": inner.get("Type") if isinstance(inner.get("Type"), int) else None,
        "length": parts["A"] + parts["B"] if ok and parts["A"] + parts["B"] > 0 else None,
        "beam": parts["C"] + parts["D"] if ok and parts["C"] + parts["D"] > 0 else None,
        "draught": draught if draught else None,
        "destination": _text(inner.get("Destination")) or None,
        "eta": _eta(inner.get("Eta")),
        "seen": _time_utc(meta.get("time_utc")) or now,
    }


def _eta(e: Any) -> str | None:
    """"MM-DD HH:MM" (UTC, no year: AIS does not carry one). Month 0 / day 0 mean "not available"; hour 24 / minute 60 drop the clock part."""
    if not isinstance(e, dict):
        return None
    mo, dy, hr, mi = (e.get(k) for k in ("Month", "Day", "Hour", "Minute"))
    if not (isinstance(mo, int) and isinstance(dy, int) and 1 <= mo <= 12 and 1 <= dy <= 31):
        return None
    if isinstance(hr, int) and isinstance(mi, int) and 0 <= hr < 24 and 0 <= mi < 60:
        return f"{mo:02d}-{dy:02d} {hr:02d}:{mi:02d}"
    return f"{mo:02d}-{dy:02d}"


# --- code names -----------------------------------------------------------------------------------------------------------
_TYPES = {30: "FISHING", 31: "TOWING", 32: "TOWING", 33: "DREDGING", 34: "DIVING", 35: "MILITARY", 36: "SAILING", 37: "PLEASURE",
          50: "PILOT", 51: "SEARCH AND RESCUE", 52: "TUG", 53: "PORT TENDER", 54: "ANTI-POLLUTION", 55: "LAW ENFORCEMENT",
          58: "MEDICAL", 59: "SPECIAL"}


def ship_type(code: int | None) -> str:
    """ITU AIS ship-and-cargo type code (0-99) as a word. 0 and missing = the ship did not say."""
    if not code:
        return "NOT REPORTED"
    if code in _TYPES:
        return _TYPES[code]
    for lo, hi, name in ((20, 29, "WING IN GROUND"), (40, 49, "HIGH SPEED CRAFT"), (60, 69, "PASSENGER"), (70, 79, "CARGO"), (80, 89, "TANKER")):
        if lo <= code <= hi:
            return name
    return "OTHER"


_NAV = {0: "UNDERWAY (ENGINE)", 1: "AT ANCHOR", 2: "NOT UNDER COMMAND", 3: "RESTRICTED MANOEUVRE", 4: "CONSTRAINED BY DRAUGHT", 5: "MOORED",
        6: "AGROUND", 7: "FISHING", 8: "UNDERWAY (SAILING)", 11: "TOWING ASTERN", 12: "PUSHING OR TOWING", 14: "AIS-SART", 15: "NOT DEFINED"}


def nav_status(code: int | None) -> str:
    """ITU navigational status code as a word (blank when the report has none, as class B reports do)."""
    return "" if code is None else _NAV.get(code, "RESERVED")
