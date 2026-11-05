"""AIS: live ship positions from AISstream (free key, beta WebSocket). No network and no real key.

What is real and what is not:
  - The WIRE tests below talk to a real WebSocket server started inside the test (localhost), so the provider's actual
    connect / subscribe / read / close code runs. The messages that server sends are built from the official documentation
    (aisstream.io/documentation, read 2026-11-05): DOC-SHAPED, not recordings. No AISstream key existed when this was written.
  - Anything about how the real service answers a bad key, or how fast ShipStaticData arrives, is a guess (see HANDOFF.md).
"""

import asyncio
import json
import time
from pathlib import Path

import orjson
import pytest
import websockets

from openterm.providers import aisstream_parse as ap
from openterm.providers.aisstream import AisStreamProvider, check_key
from openterm.providers.base import ProviderError

KEY = "ais-test-key-0123456789abcdef"
FIX = Path(__file__).parent / "fixtures"

# A position report shaped like the documentation's own example (MetaData spells Latitude/Longitude with capitals there).
DOC_POSITION = {
    "MessageType": "PositionReport",
    "MetaData": {"MMSI": 368207620, "ShipName": "EXAMPLE VESSEL      ", "Latitude": 25.7617, "Longitude": -80.1918,
                 "time_utc": "2026-11-05 10:00:00.123456789 +0000 UTC"},
    "Message": {"PositionReport": {"MessageID": 1, "UserID": 368207620, "Sog": 12.4, "Cog": 86.7, "TrueHeading": 87, "Valid": True,
                                   "NavigationalStatus": 0, "Latitude": 25.7617, "Longitude": -80.1918}},
}
DOC_STATIC = {
    "MessageType": "ShipStaticData",
    "MetaData": {"MMSI": 368207620, "ShipName": "EXAMPLE VESSEL", "time_utc": "2026-11-05 10:01:00.5 +0000 UTC"},
    "Message": {"ShipStaticData": {"UserID": 368207620, "ImoNumber": 9876543, "CallSign": "WXYZ   ", "Name": "EXAMPLE VESSEL@@@@",
                                   "Type": 70, "Dimension": {"A": 150, "B": 30, "C": 10, "D": 12}, "Destination": "ROTTERDAM@@@@@@@",
                                   "Eta": {"Month": 11, "Day": 20, "Hour": 14, "Minute": 30}, "MaximumStaticDraught": 9.8, "Valid": True}},
}


def position(mmsi: int, lat: float = 25.7, lon: float = -80.1, **over) -> dict:
    inner = {"UserID": mmsi, "Sog": 5.0, "Cog": 90.0, "TrueHeading": 91, "Valid": True, "NavigationalStatus": 0, "Latitude": lat, "Longitude": lon, **over}
    return {"MessageType": "PositionReport", "MetaData": {"MMSI": mmsi, "ShipName": f"SHIP{mmsi}"}, "Message": {"PositionReport": inner}}


# --- pure parsing ---------------------------------------------------------------------------------------------------------
def test_subscription_has_the_documented_fields_and_corner_order():
    sub = ap.subscription(KEY, (25.603, -80.208, 25.835, -79.879))
    assert sub["APIKey"] == KEY
    assert sub["BoundingBoxes"] == [[[25.835, -80.208], [25.603, -79.879]]]  # north-west corner, then south-east, as in the docs
    assert sub["FilterMessageTypes"] == list(ap.FILTER_TYPES) and "FiltersShipMMSI" not in sub


@pytest.mark.parametrize("box", [(91, 0, 92, 1), (0, 0, -1, 1), (0, 5, 1, 5), (0, -181, 1, 0), (0, 0, 1, 181), (0, 0, 30, 1), (0, 0, 1, 30)])
def test_bad_boxes_are_refused(box):
    with pytest.raises(ValueError):
        ap.check_box(*box)


def test_a_good_box_comes_back_as_floats():
    assert ap.check_box("25.6", "-80.2", "25.8", "-79.9") == (25.6, -80.2, 25.8, -79.9)


def test_position_report_from_the_documentation_example():
    p = ap.position(DOC_POSITION, 1000.0)
    assert p["mmsi"] == 368207620 and p["name"] == "EXAMPLE VESSEL"  # the padding spaces are gone
    assert (p["lat"], p["lon"], p["sog"], p["cog"], p["heading"], p["nav"]) == (25.7617, -80.1918, 12.4, 86.7, 87, 0)
    assert p["seen"] == pytest.approx(1793872800.123456)  # 2026-11-05 10:00:00 UTC, taken from the message's own time_utc


def test_unavailable_markers_become_none_not_numbers():
    p = ap.position(position(1, Sog=102.3, Cog=360, TrueHeading=511, NavigationalStatus=15), 5.0)
    assert p["sog"] is None and p["cog"] is None and p["heading"] is None
    assert p["nav"] == 15 and ap.nav_status(15) == "NOT DEFINED"


def test_a_position_without_a_real_location_or_marked_invalid_is_dropped():
    assert ap.position(position(1, lat=91.0, lon=181.0), 5.0) is None  # AIS's "not available" value
    assert ap.position(position(1, Valid=False), 5.0) is None
    assert ap.position(position(0), 5.0) is None  # MMSI 0 is not a vessel
    assert ap.position({"MessageType": "PositionReport", "Message": {}}, 5.0) is None


def test_seen_falls_back_to_the_time_we_received_it_when_time_utc_is_missing_or_odd():
    msg = position(7)
    assert ap.position(msg, 1234.5)["seen"] == 1234.5
    msg["MetaData"]["time_utc"] = "yesterday-ish"
    assert ap.position(msg, 1234.5)["seen"] == 1234.5


def test_class_b_reports_parse_like_class_a():
    msg = {"MessageType": "StandardClassBPositionReport", "MetaData": {"MMSI": 5, "ShipName": "SMALLBOAT"},
           "Message": {"StandardClassBPositionReport": {"UserID": 5, "Sog": 3.1, "Cog": 10.0, "TrueHeading": 511, "Valid": True,
                                                          "Latitude": 1.5, "Longitude": 103.5}}}
    p = ap.position(msg, 5.0)
    assert p["mmsi"] == 5 and p["nav"] is None and p["heading"] is None and p["msg"] == "StandardClassBPositionReport"
    ext = {"MessageType": "ExtendedClassBPositionReport", "MetaData": {"MMSI": 6, "ShipName": ""},
           "Message": {"ExtendedClassBPositionReport": {"UserID": 6, "Sog": 0.0, "Cog": 0.0, "TrueHeading": 0, "Valid": True, "Latitude": 1.6,
                                                         "Longitude": 103.6, "Name": "YACHT@@@@", "Type": 37}}}
    q = ap.position(ext, 5.0)
    assert q["name"] == "YACHT" and q["type"] == 37


def test_static_data_is_cleaned():
    s = ap.static(DOC_STATIC, 5.0)
    assert s["mmsi"] == 368207620 and s["imo"] == 9876543 and s["callsign"] == "WXYZ" and s["name"] == "EXAMPLE VESSEL"
    assert s["type"] == 70 and s["destination"] == "ROTTERDAM" and s["eta"] == "11-20 14:30" and s["draught"] == 9.8
    assert s["length"] == 180 and s["beam"] == 22


def test_static_blank_fields_are_none():
    blank = json.loads(json.dumps(DOC_STATIC))
    inner = blank["Message"]["ShipStaticData"]
    inner.update(Destination="@@@@@@@@@@", ImoNumber=0, Eta={"Month": 0, "Day": 0, "Hour": 24, "Minute": 60}, MaximumStaticDraught=0, Dimension={})
    s = ap.static(blank, 5.0)
    assert s["destination"] is None and s["imo"] is None and s["eta"] is None and s["draught"] is None and s["length"] is None


def test_kinds_and_error_text():
    assert ap.kind_of({"MessageType": "SubscriptionConfirmation", "Message": {"CompressionEnabled": True}}) == "confirmation"
    assert ap.kind_of({"error": "Api Key Is Not Valid"}) == "error" and ap.error_text({"error": "Api Key Is Not Valid"}) == "Api Key Is Not Valid"
    assert ap.kind_of(DOC_POSITION) == "position" and ap.kind_of(DOC_STATIC) == "static"
    assert ap.kind_of({"MessageType": "BaseStationReport"}) == "other"


def test_decode_takes_bytes_or_text_and_refuses_junk():
    assert ap.decode(orjson.dumps(DOC_POSITION))["MessageType"] == "PositionReport"
    assert ap.decode(json.dumps(DOC_POSITION))["MessageType"] == "PositionReport"
    with pytest.raises(ValueError):
        ap.decode(b"\x00not json")
    with pytest.raises(ValueError):
        ap.decode(b"[1, 2]")


def test_names_for_codes():
    assert [ap.ship_type(c) for c in (None, 0, 30, 37, 52, 60, 70, 79, 80, 89, 99, 150)] == [
        "NOT REPORTED", "NOT REPORTED", "FISHING", "PLEASURE", "TUG", "PASSENGER", "CARGO", "CARGO", "TANKER", "TANKER", "OTHER", "OTHER"]
    assert ap.nav_status(0) == "UNDERWAY (ENGINE)" and ap.nav_status(1) == "AT ANCHOR" and ap.nav_status(5) == "MOORED" and ap.nav_status(None) == ""


# --- chokepoint presets and arguments --------------------------------------------------------------------------------------
def test_every_preset_is_a_valid_box():
    from openterm.world import ais

    assert {"SUEZ", "HORMUZ", "MALACCA", "PANAMA"} <= set(ais.PRESETS)
    for name, box in ais.PRESETS.items():
        assert ap.check_box(*box) == box, name


def test_the_panel_lists_the_same_presets_as_the_backend():
    import re

    from openterm.world import ais

    ts = (Path(__file__).parents[2] / "frontend" / "src" / "functions" / "aisArgs.ts").read_text(encoding="utf-8")
    listed = re.search(r"AIS_AREAS = \[(.*?)\]", ts, re.DOTALL).group(1)
    assert re.findall(r'"([A-Z]+)"', listed) == list(ais.PRESETS)


def test_args_pick_a_preset_or_a_custom_box():
    from openterm.service import DataError
    from openterm.world import ais

    assert ais.parse_args("suez") == ("SUEZ", ais.PRESETS["SUEZ"])
    assert ais.parse_args("BOX 25.6 -80.2 25.8 -79.9") == ("BOX 25.6,-80.2,25.8,-79.9", (25.6, -80.2, 25.8, -79.9))
    for bad in ("", "ATLANTIS", "BOX 1 2 3", "BOX a b c d", "BOX 0 0 40 1", "SUEZ PANAMA"):
        with pytest.raises(DataError) as e:
            ais.parse_args(bad)
        assert e.value.kind == "bad_request"


# --- the provider against a real local WebSocket server ----------------------------------------------------------------------
class Server:
    """A throwaway AISstream stand-in. `script(ws, subscription)` decides what it sends; the subscription it got is kept."""

    def __init__(self, script):
        self.script, self.subs, self.connections = script, [], 0
        self.server = None
        self.url = ""

    async def __aenter__(self):
        async def handler(ws):
            self.connections += 1
            # The real service closes a connection that sends no valid subscription within 3 seconds.
            sub = json.loads(await asyncio.wait_for(ws.recv(), 3))
            self.subs.append(sub)
            await self.script(ws, sub)

        self.server = await websockets.serve(handler, "127.0.0.1", 0)
        self.url = f"ws://127.0.0.1:{self.server.sockets[0].getsockname()[1]}"
        return self

    async def __aexit__(self, *exc):
        self.server.close()
        await self.server.wait_closed()


CONFIRM = {"MessageType": "SubscriptionConfirmation", "Message": {"CompressionEnabled": True}}


async def send_all(ws, msgs):
    for m in msgs:  # the real service sends binary frames holding UTF-8 JSON
        await ws.send(orjson.dumps(m))


def provider(url: str, key: str | None = KEY) -> AisStreamProvider:
    p = AisStreamProvider(None)  # the WebSocket path never uses the HTTP client
    p.url = url
    p.set_keys({"AISSTREAM_API_KEY": key} if key else None)
    return p


BOX = (25.603, -80.208, 25.835, -79.879)


async def test_a_listen_returns_the_latest_position_per_ship_and_the_static_data():
    async def script(ws, sub):
        await send_all(ws, [CONFIRM, position(1, lat=25.7), DOC_POSITION, position(1, lat=25.71), DOC_STATIC, {"MessageType": "BaseStationReport"}])
        await ws.close()

    async with Server(script) as srv:
        out = await provider(srv.url).ais_listen(BOX, seconds=3, max_messages=100)
    assert srv.subs[0]["APIKey"] == KEY and srv.subs[0]["BoundingBoxes"] == [[[25.835, -80.208], [25.603, -79.879]]]
    assert set(out["positions"]) == {1, 368207620} and out["positions"][1]["lat"] == 25.71  # the newer report wins
    assert out["statics"][368207620]["destination"] == "ROTTERDAM"
    assert out["received"] == 5 and out["capped"] is False  # the confirmation is not counted as a data message
    assert KEY not in json.dumps(out)


async def test_a_listen_stops_at_the_message_cap():
    async def script(ws, sub):
        await send_all(ws, [CONFIRM, *[position(i) for i in range(1, 51)]])
        await asyncio.sleep(2)

    async with Server(script) as srv:
        t0 = time.monotonic()
        out = await provider(srv.url).ais_listen(BOX, seconds=5, max_messages=10)
        took = time.monotonic() - t0  # measured inside the block: leaving it waits for the slow fake server's handler
    assert out["received"] == 10 and out["capped"] is True and len(out["positions"]) == 10
    assert took < 2  # it did not wait for the clock


async def test_a_listen_stops_at_the_time_cap_even_if_the_feed_goes_quiet():
    async def script(ws, sub):
        await send_all(ws, [CONFIRM, position(1)])
        await asyncio.sleep(5)

    async with Server(script) as srv:
        t0 = time.monotonic()
        out = await provider(srv.url).ais_listen(BOX, seconds=0.6, max_messages=100)
        took = time.monotonic() - t0
    assert 0.5 < took < 2.5 and list(out["positions"]) == [1] and out["capped"] is False


async def test_a_quiet_area_is_an_empty_answer_not_an_error():
    async def script(ws, sub):
        await send_all(ws, [CONFIRM])
        await asyncio.sleep(3)

    async with Server(script) as srv:
        out = await provider(srv.url).ais_listen(BOX, seconds=0.5, max_messages=100)
    assert out["positions"] == {} and out["received"] == 0


async def test_static_data_is_remembered_between_listens():
    calls = {"n": 0}

    async def script(ws, sub):
        calls["n"] += 1
        await send_all(ws, [CONFIRM, DOC_POSITION, *([DOC_STATIC] if calls["n"] == 1 else [])])
        await ws.close()

    async with Server(script) as srv:
        p = provider(srv.url)
        await p.ais_listen(BOX, seconds=2, max_messages=100)
        second = await p.ais_listen(BOX, seconds=2, max_messages=100)
    assert second["statics"][368207620]["destination"] == "ROTTERDAM"  # the second listen saw no static message, the memory supplied it


async def test_no_key_raises_key_required_before_any_connection():
    async def script(ws, sub):
        pytest.fail("a connection was opened without a key")

    async with Server(script) as srv:
        p = provider(srv.url, key=None)
        assert p.supports("ais") and p.key_name == "AISSTREAM_API_KEY"
        with pytest.raises(ProviderError) as e:
            await p.ais_listen(BOX, seconds=1, max_messages=10)
    assert e.value.kind == "key_required" and srv.connections == 0


async def test_a_refused_key_is_key_required_and_never_echoed():
    async def script(ws, sub):
        await ws.send(orjson.dumps({"error": f"Api Key Is Not Valid {sub['APIKey']}"}))
        await ws.close()

    async with Server(script) as srv:
        with pytest.raises(ProviderError) as e:
            await provider(srv.url).ais_listen(BOX, seconds=2, max_messages=10)
    assert e.value.kind == "key_required" and KEY not in str(e.value)


async def test_a_connection_closed_before_the_confirmation_is_unavailable():
    async def script(ws, sub):
        await ws.close(1008, "policy")

    async with Server(script) as srv:
        with pytest.raises(ProviderError) as e:
            await provider(srv.url).ais_listen(BOX, seconds=2, max_messages=10)
    assert e.value.kind == "unavailable" and "CLOSED" in str(e.value) and KEY not in str(e.value)


async def test_an_unreachable_service_is_unavailable_and_says_which_error():
    with pytest.raises(ProviderError) as e:
        await provider("ws://127.0.0.1:9").ais_listen(BOX, seconds=1, max_messages=10)
    assert e.value.kind == "unavailable" and KEY not in str(e.value)


async def test_a_bad_box_is_refused_before_connecting():
    async def script(ws, sub):
        pytest.fail("connected with a bad box")

    async with Server(script) as srv:
        with pytest.raises(ValueError):
            await provider(srv.url).ais_listen((0, 0, 30, 30), seconds=1, max_messages=10)
    assert srv.connections == 0


async def test_listens_run_one_at_a_time_so_the_three_connection_limit_is_never_hit():
    live = {"now": 0, "max": 0}

    async def script(ws, sub):
        live["now"] += 1
        live["max"] = max(live["max"], live["now"])
        await send_all(ws, [CONFIRM, position(1)])
        await asyncio.sleep(0.3)
        live["now"] -= 1

    async with Server(script) as srv:
        p = provider(srv.url)
        await asyncio.gather(*[p.ais_listen(BOX, seconds=0.5, max_messages=10) for _ in range(3)])
    assert live["max"] == 1


# --- the key test (APIKEYS) ------------------------------------------------------------------------------------------------
async def test_check_key_ok_when_the_service_confirms_the_subscription():
    async def script(ws, sub):
        assert sub["FilterMessageTypes"] == ["PositionReport"] and len(sub["BoundingBoxes"]) == 1  # one tiny box, one message type
        await send_all(ws, [CONFIRM])
        await asyncio.sleep(1)

    async with Server(script) as srv:
        assert await check_key({"AISSTREAM_API_KEY": KEY}, url=srv.url) == ("OK", None)


async def test_check_key_invalid_when_the_service_says_so():
    async def script(ws, sub):
        await ws.send(orjson.dumps({"error": "Api Key Is Not Valid"}))
        await ws.close()

    async with Server(script) as srv:
        state, detail = await check_key({"AISSTREAM_API_KEY": KEY}, url=srv.url)
    assert state == "INVALID" and KEY not in (detail or "")


async def test_check_key_error_when_the_connection_just_closes():
    async def script(ws, sub):
        await ws.close(1011, "boom")

    async with Server(script) as srv:
        state, detail = await check_key({"AISSTREAM_API_KEY": KEY}, url=srv.url)
    assert state == "ERROR" and "CLOSED" in detail


async def test_check_key_error_when_nothing_answers_in_time():
    async def script(ws, sub):
        await asyncio.sleep(5)

    async with Server(script) as srv:
        state, detail = await check_key({"AISSTREAM_API_KEY": KEY}, url=srv.url, wait_s=0.5)
    assert state == "ERROR" and "NO ANSWER" in detail


# --- keys, routes and the panel's data over HTTP (fixture mode: replayed doc-shaped messages) --------------------------------
def test_the_key_is_declared_and_the_test_is_not_an_http_call():
    from openterm.keys import KEY_SPECS, TESTS

    spec = KEY_SPECS["aisstream"]
    assert spec.fields == ("AISSTREAM_API_KEY",) and spec.signup.startswith("https://aisstream.io") and "aisstream" not in TESTS


async def test_run_test_in_fixture_mode_does_not_pretend(tmp_path):
    from openterm import keys as keystore

    store = keystore.KeyStore(env={"AISSTREAM_API_KEY": KEY}, dotenv=tmp_path / ".env", keyring=keystore.MemoryKeyring())
    st = await keystore.run_test(store, "aisstream", None, fixtures=True)
    assert st["state"] == "ERROR" and "FIXTURE" in (st.get("detail") or "")


def test_the_route_says_key_required_without_a_key(client):
    r = client.get("/api/world/ais", params={"q": "SUEZ"})
    assert r.status_code == 424 and r.json()["key"] == "AISSTREAM_API_KEY"
    assert r.json()["detail"] == "KEY REQUIRED: set AISSTREAM_API_KEY in APIKEYS"


def test_the_route_returns_labelled_doc_shaped_vessels_in_fixture_mode(client):
    client.put("/api/keys/aisstream", json={"fields": {"AISSTREAM_API_KEY": KEY}})
    r = client.get("/api/world/ais", params={"q": "SUEZ"})
    assert r.status_code == 200 and KEY not in r.text
    j = r.json()
    assert "DOC-SHAPED" in j["source"] and j["data"]["fixture"] is True and j["data"]["area"] == "SUEZ"
    rows = j["data"]["rows"]
    assert len(rows) >= 3 and {"mmsi", "name", "type", "sog", "cog", "dest", "seen", "lat", "lon", "nav_name"} <= set(rows[0])
    assert any(row["dest"] for row in rows) and any(row["sog"] is None for row in rows)  # one fixture ship reports "speed not available"
    assert "AS REPORTED BY SHIPS" in j["data"]["note"] and "SPOOF" in j["data"]["note"]
    assert j["data"]["listened_s"] > 0 and j["data"]["received"] >= len(rows)


def test_the_route_refuses_bad_arguments(client):
    client.put("/api/keys/aisstream", json={"fields": {"AISSTREAM_API_KEY": KEY}})
    for q in ("", "ATLANTIS", "BOX 0 0 40 1"):
        assert client.get("/api/world/ais", params={"q": q}).status_code == 400


def test_sources_lists_the_provider_without_the_key(client):
    client.put("/api/keys/aisstream", json={"fields": {"AISSTREAM_API_KEY": KEY}})
    s = client.get("/api/sources")
    assert "aisstream" in {p["name"] for p in s.json()["providers"]} and KEY not in s.text


def test_the_fixture_file_is_labelled_doc_shaped():
    names = [p.name for p in FIX.glob("ais*")]
    assert names and all("docshape" in n for n in names)
