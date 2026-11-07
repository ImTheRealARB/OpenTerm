"""AIS: live ship positions from AISstream (free key, beta WebSocket). No network and no real key.

What is real and what is not:
  - The WIRE tests below talk to a real WebSocket server started inside the test (localhost), so the provider's actual
    connect / subscribe / read / close code runs. The REAL_* messages are copied unchanged from the live feed (recorded 2026-11-05 with a real
    key); the helper `position()` builds small synthetic ones for count/cap tests and is not meant to look real.
  - tests/fixtures/ais_stream_recording.json is a real recording; fixture mode replays the messages inside the requested box.
  - A wrong key is answered by the live service with a dropped connection and no close frame (checked live); the tests reproduce that.
"""

import asyncio
import json
import time
from pathlib import Path

import orjson
import pytest
import websockets

from openterm.providers import aisstream_parse as ap
from openterm.providers.aisstream import AisStreamProvider, PositionMemory, check_key
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


# Real messages, copied unchanged from the live AISstream feed on 2026-11-05 (ship identity numbers are public radio data).
REAL_POSITION = json.loads(
    '{"MetaData":{"MMSI":563009210,"MMSI_String":563009210,"ShipName":"NOBLE ORION TG46    ","latitude":1.26082,"longitude":103.82537,'
    '"time_utc":"2026-11-05 06:13:54.598188257 +0000 UTC"},"MessageType":"PositionReport","Message":{"PositionReport":{"MessageID":1,'
    '"RepeatIndicator":0,"UserID":563009210,"Valid":true,"NavigationalStatus":0,"RateOfTurn":-128,"Sog":0,"PositionAccuracy":false,'
    '"Longitude":103.82537333333333,"Latitude":1.260815,"Cog":322.4,"TrueHeading":511,"Timestamp":55,"SpecialManoeuvreIndicator":0,'
    '"Spare":0,"Raim":false,"CommunicationState":83151}}}')
REAL_BUOY = json.loads(  # an ExtendedClassBPositionReport from a navigation buoy: TrueHeading 456 and Type 0 are real out-of-range / empty values
    '{"MetaData":{"MMSI":995251113,"MMSI_String":995251113,"ShipName":"BUOY 0 PUTIH JEPARA","latitude":-6.55158,"longitude":110.62619,'
    '"time_utc":"2026-11-05 06:16:11.670740071 +0000 UTC"},"MessageType":"ExtendedClassBPositionReport","Message":{"ExtendedClassBPositionReport":'
    '{"AssignedMode":false,"Cog":0,"Dimension":{"A":5,"B":5,"C":5,"D":5},"Dte":false,"FixType":1,"Latitude":-6.5515783333333335,'
    '"Longitude":110.626185,"MessageID":19,"Name":"BUOY 0 PUTIH JEPARA","PositionAccuracy":false,"Raim":false,"RepeatIndicator":0,"Sog":0,'
    '"Spare1":0,"Spare2":0,"Spare3":0,"Timestamp":60,"TrueHeading":456,"Type":0,"UserID":995251113,"Valid":true}}}')
REAL_STATIC_A = json.loads(  # class A ShipStaticData: ImoNumber 0 and an all-zero Eta are what many ships really send
    '{"MetaData":{"MMSI":211235160,"MMSI_String":211235160,"ShipName":"WAL","latitude":53.52104,"longitude":9.95461,'
    '"time_utc":"2026-11-05 06:16:09.807640161 +0000 UTC"},"MessageType":"ShipStaticData","Message":{"ShipStaticData":{"AisVersion":2,'
    '"CallSign":"DD8682","Destination":"HAMBURG","Dimension":{"A":20,"B":30,"C":16,"D":5},"Dte":false,"Eta":{"Day":0,"Hour":0,"Minute":0,'
    '"Month":0},"FixType":1,"ImoNumber":0,"MaximumStaticDraught":2.2,"MessageID":5,"Name":"WAL","RepeatIndicator":0,"Spare":false,"Type":33,'
    '"UserID":211235160,"Valid":true}}}')
REAL_STATIC_B_A = json.loads(  # class B static, part A: only ReportA is Valid (the name)
    '{"MetaData":{"MMSI":258201740,"MMSI_String":258201740,"ShipName":"OHOI","latitude":59.42917,"longitude":10.46414,'
    '"time_utc":"2026-11-05 06:16:10.186949514 +0000 UTC"},"MessageType":"StaticDataReport","Message":{"StaticDataReport":{"MessageID":24,'
    '"PartNumber":false,"RepeatIndicator":0,"ReportA":{"Name":"OHOI","Valid":true},"ReportB":{"CallSign":"","Dimension":{"A":0,"B":0,"C":0,'
    '"D":0},"FixType":0,"ShipType":0,"Spare":0,"Valid":false,"VenderIDModel":0,"VenderIDSerial":0,"VendorIDName":""},"Reserved":0,'
    '"UserID":258201740,"Valid":true}}}')
REAL_STATIC_B_B = json.loads(  # part B of the same boat, 1.5 s later: only ReportB is Valid (call sign, size, ship type 36 = sailing)
    '{"MetaData":{"MMSI":258201740,"MMSI_String":258201740,"ShipName":"","latitude":59.42917,"longitude":10.46414,'
    '"time_utc":"2026-11-05 06:16:11.681398286 +0000 UTC"},"MessageType":"StaticDataReport","Message":{"StaticDataReport":{"MessageID":24,'
    '"PartNumber":true,"RepeatIndicator":0,"ReportA":{"Name":"","Valid":false},"ReportB":{"CallSign":"LG4505","Dimension":{"A":13,"B":1,'
    '"C":1,"D":3},"FixType":0,"ShipType":36,"Spare":0,"Valid":true,"VenderIDModel":3,"VenderIDSerial":42442,"VendorIDName":"VSP"},"Reserved":0,'
    '"UserID":258201740,"Valid":true}}}')
REAL_CONFIRMATION = {"Message": {"CompressionEnabled": True}, "MessageType": "SubscriptionConfirmation"}


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


def test_a_real_position_report_parses_with_nine_digit_fractional_seconds():
    p = ap.position(REAL_POSITION, 1.0)
    assert (p["mmsi"], p["name"], p["lat"], p["lon"], p["sog"], p["cog"], p["nav"]) == (563009210, "NOBLE ORION TG46", 1.260815, 103.82537333333333, 0.0, 322.4, 0)
    assert p["heading"] is None  # 511 = not available
    assert p["seen"] == pytest.approx(1793859234.598188)  # 2026-11-05 06:13:54.598188 UTC read from "...54.598188257 +0000 UTC", not the fallback 1.0


def test_a_real_buoy_report_has_no_heading_and_no_ship_type():
    p = ap.position(REAL_BUOY, 1.0)
    assert p["heading"] is None and p["type"] == 0 and p["name"] == "BUOY 0 PUTIH JEPARA" and p["msg"] == "ExtendedClassBPositionReport"
    assert ap.ship_type(p["type"]) == "NOT REPORTED"


def test_a_real_class_a_static_record_with_zeros_means_not_available():
    s = ap.static(REAL_STATIC_A, 1.0)
    assert s["destination"] == "HAMBURG" and s["name"] == "WAL" and s["type"] == 33 and s["length"] == 50 and s["beam"] == 21
    assert s["imo"] is None and s["eta"] is None  # ImoNumber 0 and an all-zero Eta are "not available", not data
    assert s["partial"] is False


def test_class_b_static_parts_each_carry_only_their_own_half():
    a, b = ap.static(REAL_STATIC_B_A, 1.0), ap.static(REAL_STATIC_B_B, 1.0)
    assert ap.kind_of(REAL_STATIC_B_A) == "static" and a["partial"] and b["partial"]
    assert (a["name"], a["type"], a["length"], a["callsign"]) == ("OHOI", None, None, None)  # part A: the invalid ReportB is ignored, not read as type 0
    assert (b["name"], b["type"], b["length"], b["beam"], b["callsign"]) == (None, 36, 14, 4, "LG4505")
    assert "StaticDataReport" in ap.FILTER_TYPES  # the subscription must ask for it or these never arrive


def test_confirmation_is_the_real_first_frame():
    assert ap.kind_of(REAL_CONFIRMATION) == "confirmation" and ap.position(REAL_CONFIRMATION, 1.0) is None


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


def test_the_panel_says_the_same_listen_time_as_the_backend_and_it_is_the_providers_cap():
    import re

    from openterm.providers import aisstream
    from openterm.world import ais

    ts = (Path(__file__).parents[2] / "frontend" / "src" / "functions" / "aisArgs.ts").read_text(encoding="utf-8")
    assert float(re.search(r"AIS_LISTEN_S = (\d+)", ts).group(1)) == ais.LISTEN_S == aisstream.MAX_SECONDS  # "LISTENING FOR ABOUT 15 SECONDS" is true
    assert float(re.search(r"AIS_MEMORY_S = (\d+)", ts).group(1)) == aisstream.POSITION_TTL_S  # "UP TO 5 MIN OLD" is true


def test_args_pick_a_preset_or_a_custom_box():
    from openterm.errors import DataError
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


async def test_class_b_static_parts_are_merged_across_messages_and_listens():
    box = (59.0, 10.0, 60.0, 11.0)
    pos = json.loads(json.dumps(REAL_POSITION))  # a position for the same boat (copy, then point it at its MMSI)
    pos["MetaData"]["MMSI"] = pos["Message"]["PositionReport"]["UserID"] = 258201740

    async def statics_only(ws, sub):
        await send_all(ws, [CONFIRM, REAL_STATIC_B_A, REAL_STATIC_B_B])  # the two halves arrive as separate messages
        await ws.close()

    async def position_only(ws, sub):
        await send_all(ws, [CONFIRM, pos])
        await ws.close()

    async with Server(statics_only) as srv1, Server(position_only) as srv2:
        p = provider(srv1.url)
        await p.ais_listen(box, seconds=2, max_messages=100)
        p.url = srv2.url
        out = await p.ais_listen(box, seconds=2, max_messages=100)  # this listen saw no static message: the memory supplies the merged one
    s = out["statics"][258201740]
    assert s["name"] == "OHOI" and s["type"] == 36 and s["length"] == 14 and s["callsign"] == "LG4505" and "partial" not in s


# --- position memory (the free feed is sparse, so repeated listens share the last 5 minutes of positions) -----------------------------
class Clock:
    """A fake clock: tests move time by assigning `.t`, so 5 minutes pass without sleeping."""

    def __init__(self, t: float = 1_800_000_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


def sequence_server(*listens):
    """A Server whose Nth connection sends the Nth list of messages (then closes), so each listen can hear different ships."""
    calls = {"n": 0}

    async def script(ws, sub):
        msgs = listens[min(calls["n"], len(listens) - 1)]
        calls["n"] += 1
        await send_all(ws, [CONFIRM, *msgs])
        await ws.close()

    return Server(script)


async def test_a_second_listen_also_returns_ships_remembered_from_the_first_and_flags_them():
    # Listen 1 hears ships 1 and 2. Listen 2 hears ship 2 again (moved) and a new ship 3, and nothing of ship 1.
    async with sequence_server([position(1, lat=25.65), position(2, lat=25.70)], [position(2, lat=25.75), position(3, lat=25.80)]) as srv:
        p = provider(srv.url)
        clock = p.clock = Clock()
        first = await p.ais_listen(BOX, seconds=2, max_messages=100)
        clock.t += 60  # a minute later
        second = await p.ais_listen(BOX, seconds=2, max_messages=100)
    assert set(first["positions"]) == {1, 2} and first["remembered"] == 0
    assert not any(v["remembered"] for v in first["positions"].values())  # nothing to remember yet: every ship is from this listen
    assert set(second["positions"]) == {1, 2, 3} and second["remembered"] == 1 and second["memory_s"] == 300.0
    assert [second["positions"][m]["remembered"] for m in (1, 2, 3)] == [True, False, False]  # only ship 1 came from memory
    assert second["positions"][2]["lat"] == 25.75  # a fresh report replaces the remembered one for the same ship
    assert second["positions"][1]["lat"] == 25.65 and clock.t - second["positions"][1]["seen"] == 60  # remembered keeps its own report time


async def test_a_remembered_ship_expires_after_five_minutes():
    async with sequence_server([position(1)], [], [], []) as srv:
        p = provider(srv.url)
        clock = p.clock = Clock()
        await p.ais_listen(BOX, seconds=2, max_messages=100)
        clock.t += 299  # 4 min 59 s old: still shown
        still = await p.ais_listen(BOX, seconds=2, max_messages=100)
        clock.t += 2  # now 301 s old
        gone = await p.ais_listen(BOX, seconds=2, max_messages=100)
    assert list(still["positions"]) == [1] and still["positions"][1]["remembered"] is True
    assert gone["positions"] == {} and gone["remembered"] == 0  # never shown past 5 minutes
    assert len(p.positions) == 0  # and the memory itself dropped it


async def test_remembered_ships_are_filtered_by_the_box_asked_about_at_answer_time():
    far_box = (1.0, 103.0, 2.0, 104.0)
    async with sequence_server([position(1, lat=25.7, lon=-80.1)], []) as srv:
        p = provider(srv.url)
        p.clock = Clock()
        await p.ais_listen(BOX, seconds=2, max_messages=100)  # ship 1 is in the Miami box
        elsewhere = await p.ais_listen(far_box, seconds=2, max_messages=100)  # ... but not in the Singapore box
        back = await p.ais_listen(BOX, seconds=2, max_messages=100)
    assert elsewhere["positions"] == {}  # a ship outside the requested box is not returned, even though it is remembered
    assert list(back["positions"]) == [1]  # the same memory answers the Miami box again


async def test_fixture_mode_neither_stores_nor_recalls_positions():
    p = AisStreamProvider(None, "aisstream:fixture", fixture=True)
    p.set_keys({"AISSTREAM_API_KEY": KEY})
    gib = (35.8, -5.8, 36.2, -5.2)
    first = await p.ais_listen(gib)
    second = await p.ais_listen(gib)
    assert first["positions"] and len(p.positions) == 0  # nothing was stored
    assert second["remembered"] == 0 and not any(v["remembered"] for v in second["positions"].values())
    assert set(first["positions"]) == set(second["positions"])  # a replay is the same every time


def pos(mmsi: int, now: float, lat: float = 1.5, lon: float = 103.0, age: float = 0.0) -> dict:
    return {"mmsi": mmsi, "lat": lat, "lon": lon, "seen": now - age}


def test_memory_evicts_the_least_recently_updated_ship_beyond_its_bound():
    mem = PositionMemory(keep=3, ttl_s=300)
    now = 1000.0
    mem.update({1: pos(1, now), 2: pos(2, now), 3: pos(3, now)}, now)
    mem.update({1: pos(1, now)}, now)  # ship 1 reports again: it is now the most recently updated, so ship 2 is the oldest
    mem.update({4: pos(4, now), 5: pos(5, now)}, now)  # two more ships push two out: 2, then 3
    assert len(mem) == 3
    assert set(mem.recall((0, 0, 3, 110), set(), now)) == {1, 4, 5}


def test_memory_age_uses_the_older_of_the_message_clock_and_the_arrival_time():
    mem = PositionMemory(keep=10, ttl_s=300)
    now = 5000.0
    mem.update({1: pos(1, now, age=400)}, now)  # a message that arrived just now but says it is 400 s old: too old
    assert len(mem) == 0
    mem.update({2: pos(2, now, age=100)}, now)
    assert set(mem.recall((0, 0, 3, 110), set(), now)) == {2}
    assert mem.recall((0, 0, 3, 110), set(), now + 201) == {}  # 100 s old + 201 s = 301 s: expired at answer time even before the next update
    assert mem.recall((0, 0, 3, 110), {2}, now) == {}  # a ship the current listen heard is "skipped" (the fresh one wins)


def test_rows_carry_the_remembered_flag_and_the_age_of_the_report():
    from openterm.world.ais import rows_of

    now = 10_000.0
    p = {"mmsi": 1, "name": "A", "lat": 1.0, "lon": 2.0, "sog": 3.0, "cog": 4.0, "heading": 5, "nav": 0, "type": None, "msg": "PositionReport"}
    listen = {"positions": {1: {**p, "seen": now - 5, "remembered": False}, 2: {**p, "mmsi": 2, "seen": now - 120, "remembered": True}}, "statics": {}}
    rows = {r["mmsi"]: r for r in rows_of(listen, now)}
    assert (rows[1]["remembered"], rows[1]["age_s"]) == (False, 5) and (rows[2]["remembered"], rows[2]["age_s"]) == (True, 120)
    assert [r["mmsi"] for r in rows_of(listen, now)] == [1, 2]  # newest first


async def test_the_real_service_drops_the_connection_on_a_wrong_key_and_the_text_says_so():
    # What the live service did with a wrong key (2026-11-05): no JSON error, the socket just goes away with no close frame (code 1006).
    async def script(ws, sub):
        ws.transport.abort()  # hard drop: no close handshake

    async with Server(script) as srv:
        with pytest.raises(ProviderError) as e:
            await provider(srv.url).ais_listen(BOX, seconds=2, max_messages=10)
        state, detail = await check_key({"AISSTREAM_API_KEY": KEY}, url=srv.url)
    assert e.value.kind == "unavailable" and "DROPPED THE CONNECTION" in str(e.value) and "WRONG KEY" in str(e.value) and KEY not in str(e.value)
    assert state == "ERROR" and "WRONG KEY" in detail and KEY not in detail


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


# --- keys, routes and the panel's data over HTTP (fixture mode: a real recording replayed) --------------------------------
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


def test_the_route_replays_the_real_recording_inside_the_box_and_labels_it(client):
    client.put("/api/keys/aisstream", json={"fields": {"AISSTREAM_API_KEY": KEY}})
    r = client.get("/api/world/ais", params={"q": "GIBRALTAR"})
    assert r.status_code == 200 and KEY not in r.text
    j = r.json()
    assert "REPLAY" in j["source"] and "NOT LIVE" in j["source"] and j["data"]["fixture"] is True and j["data"]["area"] == "GIBRALTAR"
    rows = j["data"]["rows"]
    assert len(rows) >= 15 and {"mmsi", "name", "type", "sog", "cog", "dest", "seen", "lat", "lon", "nav_name"} <= set(rows[0])
    assert all(35.8 <= row["lat"] <= 36.2 and -5.8 <= row["lon"] <= -5.2 for row in rows)  # only ships inside the box asked for
    assert any(row["dest"] == "CEUTA BUNKER" and row["type"] == "TANKER" for row in rows)  # the one real static record in the recording
    assert "AS REPORTED BY SHIPS" in j["data"]["note"] and "SPOOF" in j["data"]["note"] and "PATCHY" in j["data"]["note"]
    assert j["data"]["listened_s"] > 0 and j["data"]["received"] >= len(rows)
    assert j["data"]["remembered"] == 0 and j["data"]["memory_s"] == 300 and not any(row["remembered"] for row in rows)  # a replay never uses memory
    assert all("age_s" in row for row in rows)


def test_the_replay_of_an_area_the_recording_does_not_cover_is_empty_not_invented(client):
    client.put("/api/keys/aisstream", json={"fields": {"AISSTREAM_API_KEY": KEY}})
    j = client.get("/api/world/ais", params={"q": "SUEZ"}).json()
    assert j["data"]["rows"] == [] and j["data"]["received"] == 0 and j["data"]["fixture"] is True


def test_the_route_refuses_bad_arguments(client):
    client.put("/api/keys/aisstream", json={"fields": {"AISSTREAM_API_KEY": KEY}})
    for q in ("", "ATLANTIS", "BOX 0 0 40 1"):
        assert client.get("/api/world/ais", params={"q": q}).status_code == 400


def test_sources_lists_the_provider_without_the_key(client):
    client.put("/api/keys/aisstream", json={"fields": {"AISSTREAM_API_KEY": KEY}})
    s = client.get("/api/sources")
    assert "aisstream" in {p["name"] for p in s.json()["providers"]} and KEY not in s.text


def test_the_fixture_is_a_real_recording_and_holds_no_key():
    files = list(FIX.glob("ais*"))
    assert [f.name for f in files] == ["ais_stream_recording.json"]
    raw = files[0].read_text(encoding="utf-8")
    rec = json.loads(raw)
    assert "REAL RECORDING" in rec["_note"] and "APIKey" not in raw and "DOC SHAPE" not in raw
    msgs = rec["messages"]
    assert 30 <= len(msgs) <= 80 and ap.kind_of(msgs[0]) == "confirmation"  # small, as promised
    assert {ap.kind_of(m) for m in msgs} >= {"position", "static"}
    assert all(isinstance(m["MetaData"]["MMSI"], int) for m in msgs[1:])  # genuine MetaData on every data message
