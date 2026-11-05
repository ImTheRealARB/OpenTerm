"""MAP layers (`/api/world/geo/...`): USGS earthquakes, NASA EONET events, PortWatch ports, chokepoint boxes.

The parsers are tested on REAL recordings made on 2026-11-05 (`usgs_quakes_4_5_week`, `eonet_open_no_wildfires`,
`portwatch_ports_db_top25`; recorder: scripts/record_map_fixtures.mjs). No test touches the network.
"""

import json
from pathlib import Path

import pytest

from openterm.world import geo, ports

FIX = Path(__file__).parent / "fixtures"


def body(name: str):
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))["body"]


# --- pure parsers -------------------------------------------------------------------------------------------------------------
def test_quakes_parse_the_real_feed():
    out = geo.quakes(body("usgs_quakes_4_5_week"))
    rows = out["rows"]
    assert len(rows) + out["skipped"] == 95 and out["skipped"] == 0
    assert all(-90 <= r["lat"] <= 90 and -180 <= r["lon"] <= 180 for r in rows)
    assert all(r["mag"] is not None and r["mag"] >= 4.4 for r in rows)  # the feed is M4.5+ (magnitudes are rounded)
    assert [r["time"] for r in rows] == sorted((r["time"] for r in rows), reverse=True)  # newest first
    assert rows[0]["time"] < 4_000_000_000  # epoch SECONDS, not the feed's milliseconds
    assert "earthquake" in out["title"].lower() and out["generated"] is not None


def test_quakes_skip_what_cannot_be_placed_and_count_it():
    good = {"id": "a", "properties": {"mag": 5.0, "time": 1_700_000_000_000, "place": "X"}, "geometry": {"coordinates": [10, 20, 5]}}
    no_geo = {"id": "b", "properties": {"mag": 5.0, "time": 1}, "geometry": None}
    off_globe = {"id": "c", "properties": {"mag": 5.0, "time": 1}, "geometry": {"coordinates": [10, 95, 5]}}
    no_time = {"id": "d", "properties": {"mag": 5.0}, "geometry": {"coordinates": [10, 20, 5]}}
    out = geo.quakes({"features": [good, no_geo, off_globe, no_time]})
    assert [r["id"] for r in out["rows"]] == ["a"] and out["skipped"] == 3
    assert out["rows"][0]["time"] == 1_700_000_000.0 and out["rows"][0]["depth_km"] == 5.0


def test_quakes_refuse_a_body_that_is_not_the_feed():
    with pytest.raises(ValueError):
        geo.quakes({"error": "nope"})


def test_events_parse_the_real_answer_with_tracks():
    out = geo.events(body("eonet_open_no_wildfires"))
    rows = out["rows"]
    assert len(rows) + out["skipped"] == 69
    assert all(r["category"] != "wildfires" for r in rows)  # the request leaves them out
    assert [r["time"] for r in rows] == sorted((r["time"] for r in rows), reverse=True)
    # The point is the NEWEST position; the track holds every position oldest first, so its last point is the point.
    for r in rows:
        assert r["track"][-1] == [r["lon"], r["lat"]]
    assert any(len(r["track"]) > 1 for r in rows)  # at least one storm or volcano has a path


def test_events_use_the_newest_geometry_and_skip_unplaceable_ones():
    ev = {"id": "E1", "title": "Storm", "categories": [{"id": "severeStorms", "title": "Severe Storms"}], "sources": [{"id": "JTWC"}],
          "geometry": [{"type": "Point", "date": "2026-11-02T00:00:00Z", "coordinates": [80, 14], "magnitudeValue": 60, "magnitudeUnit": "kts"},
                       {"type": "Point", "date": "2026-11-01T00:00:00Z", "coordinates": [86, 11]}]}
    poly = {"id": "E2", "title": "Ice", "categories": [{"id": "seaLakeIce"}],
            "geometry": [{"type": "Polygon", "date": "2026-11-02T00:00:00Z", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}]}
    out = geo.events({"events": [ev, poly]})
    assert out["skipped"] == 1 and len(out["rows"]) == 1
    r = out["rows"][0]
    assert (r["lon"], r["lat"], r["mag"], r["mag_unit"]) == (80, 14, 60, "kts")
    assert r["track"] == [[86, 11], [80, 14]]


def test_ports_join_sums_with_coordinates_and_drop_ports_without_them():
    top = [{"portid": "p1", "calls7": 700}, {"portid": "p2", "calls7": 70}, {"portid": "p3", "calls7": 7}]
    meta = [{"portid": "p1", "portname": "One", "country": "A", "lat": 1.5, "lon": 2.5, "LOCODE": "AA ONE"},
            {"portid": "p2", "portname": "Two", "country": "B", "lat": None, "lon": None}]
    out = geo.ports(top, meta, "2026-10-30", 7)
    assert [r["id"] for r in out["rows"]] == ["p1"] and out["skipped"] == 2
    assert out["rows"][0]["calls_per_day"] == 100 and out["rows"][0]["rank"] == 1
    with pytest.raises(ValueError, match="NO PORTS"):
        geo.ports(top, [], "2026-10-30", 7)


def test_ports_ids_where_checks_the_ids():
    assert ports.ids_where(["port1", "port2"]) == "portid IN ('port1','port2')"
    with pytest.raises(ValueError):
        ports.ids_where(["x') OR 1=1 --"])
    with pytest.raises(ValueError):
        ports.ids_where([])


def test_chokepoints_are_the_ais_presets_with_centres():
    from openterm.world.ais import PRESETS

    rows = geo.chokepoints()
    assert [r["id"] for r in rows] == list(PRESETS)
    h = next(r for r in rows if r["id"] == "HORMUZ")
    assert h["box"] == [25.8, 55.6, 27.0, 57.0] and h["lat"] == pytest.approx(26.4) and h["lon"] == pytest.approx(56.3)


# --- routes, in fixture mode ---------------------------------------------------------------------------------------------------
def test_quakes_route_answers_the_envelope(client):
    r = client.get("/api/world/geo/quakes").json()
    assert r["source"].startswith("USGS") and r["stale"] is False
    assert len(r["data"]["rows"]) == 95 and "M4.5" in r["data"]["note"]


def test_events_route_answers_the_envelope(client):
    r = client.get("/api/world/geo/events").json()
    assert r["source"].startswith("NASA EONET") and len(r["data"]["rows"]) == 69
    assert "WILDFIRES" in r["data"]["note"]  # the omission is stated, not hidden


def test_ports_route_joins_the_recorded_coordinates(client):
    r = client.get("/api/world/geo/ports").json()
    rows = r["data"]["rows"]
    assert r["source"].startswith("IMF PORTWATCH") and len(rows) == 25 and r["data"]["skipped"] == 0
    singapore = next(p for p in rows if p["name"] == "Singapore")
    assert 1 < singapore["lat"] < 2 and 103 < singapore["lon"] < 105 and singapore["calls_per_day"] > 50


def test_chokepoints_route(client):
    r = client.get("/api/world/geo/chokepoints").json()
    assert len(r["data"]["rows"]) == 8 and r["source"].startswith("OPENTERM PRESETS")


def test_the_sources_screen_lists_the_two_new_adapters(client):
    rows = {p["name"]: p for p in client.get("/api/sources").json()["providers"]}
    assert {"usgs", "eonet"} <= set(rows)
