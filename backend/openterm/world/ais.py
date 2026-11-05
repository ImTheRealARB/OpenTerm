"""AIS: a bounded snapshot of ship positions in a box, from AISstream (free key AISSTREAM_API_KEY, beta WebSocket).

`AIS SUEZ` = the Suez Canal box; `AIS BOX 25.6 -80.2 25.8 -79.9` = a box you give as south west north east (degrees). The provider
listens for a few seconds with hard caps and the newest position per ship is kept. Positions are what ships REPORT: they can be late,
switched off or false, and a short listen sees only part of the traffic. The panel says so (NOTE), and an empty answer says "quiet
area or slow feed", never "no ships".

Presets are my own rough boxes around well-known chokepoints (checked on a map by eye, not from a gazetteer): they are a starting
point; use BOX for anything else.
"""

from __future__ import annotations

import time
from typing import Any

from ..providers import aisstream_parse as ap
from ..service import DataError

LISTEN_S = 8.0  # one listen; the provider hard-caps this at 15 s
MAX_MESSAGES = 3000
MAX_ROWS = 300
TTL_S = 20.0  # a refresh inside this reuses the last listen (and never opens a second connection)

# name -> (south, west, north, east) in degrees
PRESETS: dict[str, tuple[float, float, float, float]] = {
    "SUEZ": (29.8, 32.2, 31.4, 32.7),       # Suez Canal, Port Said to Suez
    "PANAMA": (8.8, -80.1, 9.5, -79.4),     # Panama Canal, Cristobal to Balboa
    "HORMUZ": (25.8, 55.6, 27.0, 57.0),     # Strait of Hormuz
    "MALACCA": (1.0, 101.5, 2.8, 104.5),    # Singapore Strait and the southern Malacca Strait
    "BABEL": (12.3, 42.9, 13.2, 43.9),      # Bab el-Mandeb
    "BOSPHORUS": (40.9, 28.9, 41.3, 29.2),  # Bosphorus
    "GIBRALTAR": (35.8, -5.8, 36.2, -5.2),  # Strait of Gibraltar
    "DOVER": (50.7, 0.8, 51.3, 1.9),        # Dover Strait
}

NOTE = ("AISSTREAM: POSITIONS ARE AS REPORTED BY SHIPS AND ARE NOT VERIFIED. THEY CAN BE DELAYED, SWITCHED OFF OR SPOOFED, AND COVERAGE IS PARTIAL. "
        "A SHORT LISTEN IS A SAMPLE, NOT A COUNT OF SHIPS (FREE BETA FEED, NO UPTIME PROMISE). DESTINATION AND ETA ARE TYPED BY THE CREW. NOT FINANCIAL DATA.")
USAGE = f"AIS <{'|'.join(PRESETS)}> OR AIS BOX <SOUTH> <WEST> <NORTH> <EAST>"


def parse_args(q: str) -> tuple[str, tuple[float, float, float, float]]:
    """(label, box). DataError('bad_request') with the usage line for anything else."""
    words = (q or "").upper().split()
    if len(words) == 1 and words[0] in PRESETS:
        return words[0], PRESETS[words[0]]
    if words and words[0] == "BOX":
        try:
            box = ap.check_box(*words[1:]) if len(words) == 5 else None
        except ValueError as e:
            raise DataError("bad_request", str(e)) from e
        if box is not None:
            return "BOX " + ",".join(f"{v:g}" for v in box), box
    raise DataError("bad_request", f"USAGE: {USAGE}")


def rows_of(listen: dict[str, Any], now: float) -> list[dict[str, Any]]:
    """One row per ship: its newest position joined with the static record we hold for it (destination, ETA, size, type). Newest first."""
    statics = listen["statics"]
    rows = []
    for mmsi, p in listen["positions"].items():
        s = statics.get(mmsi)
        code = s["type"] if s and s["type"] is not None else p["type"]
        rows.append({
            "mmsi": mmsi,
            "name": p["name"] or (s["name"] if s and s["name"] else ""),
            "imo": s["imo"] if s else None,
            "type": ap.ship_type(code), "type_code": code,
            "sog": p["sog"], "cog": p["cog"], "heading": p["heading"],
            "nav": p["nav"], "nav_name": ap.nav_status(p["nav"]),
            "dest": s["destination"] if s else None, "eta": s["eta"] if s else None,
            "length": s["length"] if s else None, "draught": s["draught"] if s else None,
            "lat": p["lat"], "lon": p["lon"], "seen": p["seen"],
            "static_age_s": round(now - s["rx"]) if s else None,  # destination and ETA are only as fresh as this
        })
    rows.sort(key=lambda r: (-r["seen"], r["mmsi"]))
    return rows


async def snapshot(svc: Any, q: str) -> dict[str, Any]:
    label, box = parse_args(q)

    async def fetch() -> dict:
        listen, failed = await svc.router.call("ais", lambda p: p.ais_listen(box, LISTEN_S, MAX_MESSAGES))
        rows = rows_of(listen, time.time())
        data = {
            "area": label, "box": list(box), "rows": rows[:MAX_ROWS], "truncated": max(0, len(rows) - MAX_ROWS),
            "received": listen["received"], "capped": listen["capped"], "listened_s": listen["listened_s"],
            "fixture": "DOC-SHAPED" in listen["source"], "note": NOTE,
        }
        return {"data": data, "fallback_from": failed, "source": listen["source"]}

    return await svc._swr(f"w:ais:{label}", TTL_S, fetch)
