"""FLT: live aircraft from the OpenSky Network. Pure code (no network, no pandas: the server process must never import pandas).

OpenSky (https://opensky-network.org) collects the ADS-B broadcasts that aircraft transmit (ADS-B = the position/speed message a transponder sends
about once a second) with a volunteer receiver network. `providers/opensky.py` fetches; this file turns its answer into the panel's rows.

The call is `GET https://opensky-network.org/api/states/all?lamin=<S>&lomin=<W>&lamax=<N>&lomax=<E>` (documented at
https://openskynetwork.github.io/opensky-api/rest.html). The answer is `{"time": <epoch s>, "states": [<state vector>, ...]}`, `states` is JSON
null when no aircraft is in the box, and a state vector is a POSITIONAL array (no field names):

   0 icao24 (hex transponder address)   1 callsign (8 chars, space padded, may be null)   2 origin_country (country of REGISTRATION, not of the flight)
   3 time_position (epoch s, null if no position yet)   4 last_contact (epoch s)   5 longitude   6 latitude   (degrees, null if unknown)
   7 baro_altitude (metres, from air pressure)   8 on_ground (bool)   9 velocity (m/s over ground)   10 true_track (degrees clockwise from north)
  11 vertical_rate (m/s, positive = climbing)   12 sensors (receiver ids, null)   13 geo_altitude (metres, from GPS)   14 squawk (transponder code, text)
  15 spi (special purpose indicator, bool)   16 position_source (0 ADS-B, 1 ASTERIX, 2 MLAT, 3 FLARM)   17 category (only with `extended=1`)

HONESTY: the fixtures behind the tests are DOC-SHAPED (invented numbers in the documented layout), not recordings. OpenSky refused every connection from
the machine this was built on (TCP timeout on 2026-11-05), so the shapes above come from the documentation alone and have never been compared with a live answer.
"""

from __future__ import annotations

from typing import Any

# --- what is on the wire ------------------------------------------------------------------------------------------------
STATE_FIELDS = 17  # indices 0..16 always; index 17 (category) exists only when `extended=1` was asked, and we do not ask
POSITION_SOURCES = {0: "ADS-B", 1: "ASTERIX", 2: "MLAT", 3: "FLARM"}

# --- unit conversions (the source speaks metres and m/s; pilots and the panel speak feet, knots and feet per minute) -----------------
M_TO_FT = 3.280839895
MS_TO_KT = 1.943844492
MS_TO_FPM = 196.8503937

# --- areas ------------------------------------------------------------------------------------------------------------------
# Presets are small boxes on purpose: OpenSky charges credits by AREA (see `credits_for`), and anonymous use has only 400 credits a day.
PRESETS: dict[str, tuple[float, float, float, float]] = {  # south, west, north, east
    "LONDON": (51.3, -0.6, 51.7, 0.2),
    "NYC": (40.5, -74.3, 41.0, -73.6),
    "DUBAI": (24.9, 54.9, 25.5, 55.7),
    "SINGAPORE": (1.1, 103.5, 1.6, 104.2),
    "MUMBAI": (18.8, 72.6, 19.3, 73.2),
    "BENGALURU": (12.7, 77.3, 13.3, 77.9),
    "FRANKFURT": (49.8, 8.2, 50.3, 9.0),
}
MAX_AREA_SQ_DEG = 100.0  # a box above this would cost 3+ credits a click; a global call is only made by the CALLSIGN search, which says so
MAX_ROWS = 500  # rows sent to the panel; the payload says how many were left out
MAX_CALLSIGN = 8  # a callsign is at most 8 characters
CALLSIGN_CREDITS = 4  # OpenSky has no callsign filter: a CALLSIGN search downloads every aircraft (a global call = 4 credits)

FLIGHTS = "flights"  # the router capability name
SOURCE = "OPENSKY"
NOTE = ("AS REPORTED BY AIRCRAFT TRANSPONDERS (ADS-B). COVERAGE IS PARTIAL: AIRCRAFT OUT OF RANGE OF A VOLUNTEER RECEIVER, WITH THE TRANSPONDER OFF, "
        "OR FILTERED AT THE OWNER'S REQUEST DO NOT APPEAR. A SNAPSHOT, NOT A COUNT OF TRAFFIC. NOT FOR NAVIGATION. NOT FINANCIAL DATA.")
ANON_LABEL = "ANONYMOUS: LIMITED CREDITS (400 A DAY, POSITIONS EVERY 10 S). SET OPENSKY_CLIENT_ID AND OPENSKY_CLIENT_SECRET IN APIKEYS FOR MORE"
AUTH_LABEL = "SIGNED IN TO OPENSKY (ACCOUNT CREDITS, 4000 A DAY ON THE STANDARD PLAN)"
COUNTRY_NOTE = "COUNTRY IS WHERE THE AIRCRAFT IS REGISTERED, NOT WHERE IT IS FLYING OR GOING"
USAGE = f"FLT <{'|'.join(PRESETS)}> OR FLT BOX <SOUTH> <WEST> <NORTH> <EAST> OR FLT CALLSIGN <PREFIX>"


class FlightsError(Exception):
    """The input or the upstream answer is unusable. `kind`: bad_request | unavailable."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


# --- what the user typed --------------------------------------------------------------------------------------------------------
def check_box(south: Any, west: Any, north: Any, east: Any) -> tuple[float, float, float, float]:
    """Validates a bounding box in degrees. FlightsError("bad_request") with a screen-ready text."""
    try:
        s, w, n, e = (float(x) for x in (south, west, north, east))
    except (TypeError, ValueError) as err:
        raise FlightsError("bad_request", "BOX NEEDS FOUR NUMBERS: SOUTH WEST NORTH EAST") from err
    if not all(abs(x) < 1e6 for x in (s, w, n, e)):  # float("nan") compares false with everything; this also rejects inf
        raise FlightsError("bad_request", "BOX NEEDS FOUR FINITE NUMBERS")
    if not (-90 <= s < n <= 90):
        raise FlightsError("bad_request", "LATITUDES MUST BE -90..90 AND SOUTH MUST BE BELOW NORTH")
    if not (-180 <= w < e <= 180):
        raise FlightsError("bad_request", "LONGITUDES MUST BE -180..180 AND WEST MUST BE BELOW EAST (A BOX CANNOT CROSS THE DATE LINE)")
    if area_sq_deg((s, w, n, e)) > MAX_AREA_SQ_DEG:
        raise FlightsError("bad_request", f"BOX TOO BIG: AT MOST {MAX_AREA_SQ_DEG:g} SQUARE DEGREES (EACH ONE COSTS OPENSKY CREDITS). USE A SMALLER BOX")
    return s, w, n, e


def area_sq_deg(box: tuple[float, float, float, float]) -> float:
    s, w, n, e = box
    return (n - s) * (e - w)


def credits_for(box: tuple[float, float, float, float] | None) -> int:
    """What one `states/all` call costs, from the documentation: <= 25 sq deg 1 credit, <= 100 2, <= 400 3, more (or global) 4."""
    if box is None:
        return CALLSIGN_CREDITS
    a = area_sq_deg(box)
    return 1 if a <= 25 else 2 if a <= 100 else 3 if a <= 400 else 4


def parse_args(q: str) -> tuple[str, str, tuple[float, float, float, float] | None, str | None]:
    """`(kind, label, box, callsign_prefix)`. kind is AREA | BOX | CALLSIGN; box is None for CALLSIGN (a global call)."""
    words = (q or "").upper().split()
    if len(words) == 1 and words[0] in PRESETS:
        return "AREA", words[0], PRESETS[words[0]], None
    if words and words[0] == "BOX":
        box = check_box(*words[1:]) if len(words) == 5 else None
        if box is None:
            raise FlightsError("bad_request", f"BOX NEEDS FOUR NUMBERS. USAGE: {USAGE}")
        return "BOX", "BOX " + " ".join(f"{v:g}" for v in box), box, None
    if len(words) == 2 and words[0] == "CALLSIGN":
        prefix = words[1]
        if not prefix.isalnum() or len(prefix) > MAX_CALLSIGN:
            raise FlightsError("bad_request", f"A CALLSIGN PREFIX IS 1-{MAX_CALLSIGN} LETTERS OR DIGITS (E.G. FLT CALLSIGN BAW)")
        return "CALLSIGN", f"CALLSIGN {prefix}", None, prefix
    raise FlightsError("bad_request", f"USAGE: {USAGE}")


# --- the answer ----------------------------------------------------------------------------------------------------------------
def _num(v: Any, what: str) -> float | None:
    """A JSON number or null. Booleans are rejected (Python counts them as ints), as is anything else: a wrong type means the shape changed."""
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise FlightsError("unavailable", f"OPENSKY SENT A NON-NUMBER FOR {what}")
    return float(v)


def parse_states(body: Any) -> tuple[float, list[dict[str, Any]], int]:
    """`(source time, rows, no_position)` from a `states/all` answer.

    A row is one aircraft that has a position. Aircraft without one (receivers heard them but no position yet) cannot be placed, so they are
    not rows, but they are COUNTED in `no_position` and the panel says so. A malformed state vector raises: nothing is dropped silently.
    """
    if not isinstance(body, dict) or not isinstance(body.get("time"), int) or "states" not in body:
        raise FlightsError("unavailable", "OPENSKY ANSWER HAS NO time/states FIELDS")
    states = body["states"]
    if states is None:  # OpenSky answers null (not []) when no aircraft is in the box
        return float(body["time"]), [], 0
    if not isinstance(states, list):
        raise FlightsError("unavailable", "OPENSKY states IS NOT A LIST")
    now = float(body["time"])
    rows: list[dict[str, Any]] = []
    no_position = 0
    for sv in states:
        if not isinstance(sv, list) or len(sv) < STATE_FIELDS or not isinstance(sv[0], str):
            raise FlightsError("unavailable", "OPENSKY SENT A STATE VECTOR OF AN UNEXPECTED SHAPE")
        lon, lat = _num(sv[5], "longitude"), _num(sv[6], "latitude")
        if lat is None or lon is None:
            no_position += 1
            continue
        baro, geo = _num(sv[7], "baro_altitude"), _num(sv[13], "geo_altitude")
        vel, track, vrate = _num(sv[9], "velocity"), _num(sv[10], "true_track"), _num(sv[11], "vertical_rate")
        tpos, last = _num(sv[3], "time_position"), _num(sv[4], "last_contact")
        seen = tpos if tpos is not None else last  # when the POSITION was reported; last_contact is the fallback (any message)
        src = sv[16]
        rows.append({
            "icao24": sv[0],
            "callsign": (sv[1] or "").strip(),  # blank = the aircraft did not send one (never invented)
            "country": sv[2] or "",
            "lat": lat, "lon": lon,
            "alt_m": baro, "geo_alt_m": geo,  # source units; baro (pressure) is what the cockpit altimeter shows, geo is GPS
            "alt_ft": None if baro is None else round(baro * M_TO_FT),
            "speed_ms": vel, "speed_kt": None if vel is None else round(vel * MS_TO_KT),
            "heading": None if track is None else round(track) % 360,
            "vrate_ms": vrate, "vrate_fpm": None if vrate is None else round(vrate * MS_TO_FPM),
            "on_ground": bool(sv[8]),
            "squawk": sv[14] or "",
            "spi": bool(sv[15]),
            "source": POSITION_SOURCES.get(src, "UNKNOWN") if isinstance(src, int) and not isinstance(src, bool) else "UNKNOWN",
            "seen": seen,  # epoch seconds: a MAP layer can place (lat, lon, heading) and age it with this
            "age_s": None if seen is None else max(0.0, now - seen),
        })
    return now, rows, no_position


def order_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Airborne aircraft first (highest first), then those on the ground; ties by callsign."""
    return sorted(rows, key=lambda r: (r["on_ground"], -(r["alt_m"] or 0), r["callsign"] or "~", r["icao24"]))


def filter_callsign(rows: list[dict[str, Any]], prefix: str) -> list[dict[str, Any]]:
    return [r for r in rows if r["callsign"].upper().startswith(prefix)]


def payload(kind: str, label: str, box: tuple[float, float, float, float] | None, prefix: str | None, meta: dict[str, Any]) -> dict[str, Any]:
    """The panel's data from the provider's `meta` (see `providers/opensky.py states()`): rows, counts, credits and honest labels."""
    rows = order_rows(filter_callsign(meta["rows"], prefix) if prefix else meta["rows"])
    shown = rows[:MAX_ROWS]
    return {
        "area": label, "kind": kind, "box": None if box is None else list(box), "rows": shown, "truncated": len(rows) - len(shown),
        "received": meta["received"], "no_position": meta["no_position"], "source_time": meta["time"],
        "credits_cost": credits_for(box), "credits_remaining": meta["credits_remaining"], "authenticated": meta["authenticated"],
        "access": AUTH_LABEL if meta["authenticated"] else ANON_LABEL, "note": NOTE, "country_note": COUNTRY_NOTE,
        "fixture": meta["fixture"],
    }
