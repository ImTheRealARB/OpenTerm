import asyncio
import json
from pathlib import Path

import pytest

from openterm.streaming.hub import Hub
from openterm.streaming.pricing import decode_b64
from openterm.streaming.tick import Tick
from openterm.streaming.upstream import NullStream

FIX = Path(__file__).parent / "fixtures"


def test_decode_recorded_stream_messages():
    btc, eth = (decode_b64(m) for m in json.loads((FIX / "yahoo_stream_msgs.json").read_text()))
    assert btc["id"] == "BTC-USD" and eth["id"] == "ETH-USD"
    assert 1_700_000_000_000 < btc["time"] < 2_000_000_000_000  # zigzag sint64 epoch ms
    assert btc["currency"] == "USD" and btc["price_hint"] == 2
    assert btc["price"] == round(btc["price"], 2)  # float32 noise trimmed to the price hint
    assert btc["day_low"] <= btc["price"] <= btc["day_high"]
    assert btc["change"] == pytest.approx(btc["price"] - btc["open"], abs=1000)  # sanity, same order
    assert btc["day_volume"] > 0


class FakeWS:
    def __init__(self):
        self.frames = []

    async def send_text(self, s):
        self.frames.append(json.loads(s))


class Rec(NullStream):
    def __init__(self):
        super().__init__()
        self.history = []

    async def set_symbols(self, symbols):
        await super().set_symbols(symbols)
        self.history.append(set(symbols))


async def test_hub_one_upstream_per_symbol_and_coalescing():
    from openterm.streaming.hub import Client

    up, poll = Rec(), Rec()
    hub = Hub(up, poll)
    hub.start()
    a, b = Client(FakeWS()), Client(FakeWS())
    hub.clients |= {a, b}
    senders = [asyncio.create_task(c.sender()) for c in (a, b)]
    await hub.subscribe(a, ["AAPL", "MSFT"])
    await hub.subscribe(b, ["AAPL"])
    assert up.symbols == {"AAPL", "MSFT"} and len(up.history) == 1  # second AAPL sub caused no upstream change
    for px in (1.0, 2.0, 3.0):
        hub.emit(Tick("AAPL", px, None, None, None, None, None, 0, "y"))
    hub.emit(Tick("MSFT", 9.0, None, None, None, None, None, 0, "y"))
    await asyncio.sleep(0.08)
    rows_a = [r for f in a.ws.frames for r in f[1]]
    rows_b = [r for f in b.ws.frames for r in f[1]]
    assert [r[:2] for r in rows_a if r[0] == "AAPL"] == [["AAPL", 3.0]]  # latest wins within a flush
    assert {r[0] for r in rows_b} == {"AAPL"}  # b never sees MSFT
    await hub.unsubscribe(a, ["AAPL", "MSFT"])
    assert up.symbols == {"AAPL"}  # still held by b
    await hub.disconnect(b)
    assert up.symbols == set()
    for s in senders:
        s.cancel()
    await hub.stop()


def test_ws_synthetic_ticks_end_to_end(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_text('["sub", ["SYN0001", "SYN0002"]]')
        seen = set()
        for _ in range(40):
            frame = ws.receive_json()
            if frame[0] == "T":
                for row in frame[1]:
                    assert row[8] == "s"  # labelled synthetic on the wire
                    seen.add(row[0])
            if seen == {"SYN0001", "SYN0002"}:
                break
        assert seen == {"SYN0001", "SYN0002"}
    stats = client.get("/api/sources").json()["stream"]
    assert stats["synthetic"] is True and stats["yahoo_stream"] == "OFF"


def test_profile_api_and_fallback(client):
    r = client.get("/api/profile", params={"symbol": "RELIANCE.NS"}).json()
    assert r["data"]["sector"] and r["data"]["currency"] == "INR" and r["data"]["market_cap"] > 0
    a = client.get("/api/profile", params={"symbol": "AAPL"}).json()["data"]
    assert a["description"] and a["pe"] and a["source"] == "yahoo:fixture"
    assert client.get("/api/profile", params={"symbol": "NOPE"}).status_code == 404
