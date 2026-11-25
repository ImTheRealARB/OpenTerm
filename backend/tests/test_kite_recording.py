"""REC for Indian symbols: prints and book changes of the Kite ticker are written to a local session and replayed by TAS / DOM
(`REC=<id>`) with the tick-rule label. Real recorded frames (`kite_ws_packets_real`); no network, no Kite login needed."""

from __future__ import annotations

import time

import orjson
import pytest
from test_kite_flow import make_ticker
from test_kite_wrapup import WS

from openterm.kite.ws import decode

JSON = {"content-type": "application/json"}
NFO = "NIFTY26NOVFUT.NFO"


def _post(client, path, body):
    return client.post(path, content=orjson.dumps(body), headers=JSON)


def _wait(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def kite_client(client):
    t = make_ticker()
    rec = client.app.state.recorder
    rec.poll_s = 0.02
    rec.kite = t
    client.app.state.hub.kite = t
    yield client, t, rec
    rec.kite = None
    client.app.state.hub.kite = None


def _frames():
    return [bytes.fromhex(f["data"]) for f in WS["frames"] if f["kind"] == "binary"]


def test_without_a_ticker_it_says_why(client):
    r = _post(client, "/api/recorder/start", {"symbol": "RELIANCE.NS"})
    assert r.status_code == 400 and "KITE" in r.text and "FIXTURE MODE" in r.text


def test_a_kite_recording_keeps_prints_and_book_changes_and_replays_them(kite_client):
    client, t, rec = kite_client
    a = _post(client, "/api/recorder/start", {"symbol": "RELIANCE.NS"})
    b = _post(client, "/api/recorder/start", {"symbol": NFO})
    assert a.status_code == 200 and b.status_code == 200, (a.text, b.text)
    rid, nid = a.json()["id"], b.json()["id"]
    assert rid.startswith("RELIANCENS/") and nid.startswith("NIFTY26NOVFUTNFO/")
    assert set(t._held) == {"RELIANCE.NS", NFO} and len(t.listeners) == 2  # held in full mode, listening
    assert _post(client, "/api/recorder/start", {"symbol": "reliance.ns"}).status_code == 409
    for f in _frames():
        t.on_message(f)
    assert _wait(lambda: rec.active["RELIANCENS"].trades >= 2 and rec.active["NIFTY26NOVFUTNFO"].snapshots >= 1)
    _post(client, "/api/recorder/stop", {"symbol": "RELIANCE.NS"})
    _post(client, "/api/recorder/stop", {"symbol": NFO})
    assert t._held == {} and t.listeners == []  # released: the instrument goes back to quote mode

    s = client.get(f"/api/recorder/session/{rid}").json()
    assert s["meta"]["kite"] is True and s["meta"]["symbol"] == "RELIANCE.NS" and s["end"]["reason"] == "STOPPED"
    assert s["kticks"][0]["q"] == 0 and [k["q"] for k in s["kticks"][1:3]] == [675, 394]  # the real recording's volume steps
    assert "side" not in s["kticks"][1] and "buy" not in s["kticks"][1]  # a side is never stored: the feed has none

    tas = client.get("/api/recorder/tas", params={"id": rid, "limit": 10}).json()
    assert tas["source"] == "recorder" and tas["data"]["basis"] == "ESTIMATED (TICK RULE)"
    assert tas["data"]["venue"] == "KITE (RECORDED)" and tas["data"]["recorded"]["id"] == rid
    assert tas["data"]["rows"] and all(r["q"] > 0 for r in tas["data"]["rows"])

    dom = client.get("/api/recorder/depth", params={"id": nid, "i": -1}).json()["data"]
    assert dom["best_bid"] < dom["best_ask"] and dom["venue"].startswith("KITE (RECORDED)") and dom["recorded"]["count"] >= 1
    assert client.get("/api/recorder/footprint", params={"id": rid}).status_code == 400  # no exact trades to draw
    assert client.get("/api/recorder/depth", params={"id": rid}).status_code == 404  # RELIANCE came in quote mode: no book


def test_an_unchanged_book_is_written_once(kite_client):
    client, t, rec = kite_client
    assert _post(client, "/api/recorder/start", {"symbol": NFO}).status_code == 200
    full = next(f for f in _frames() if any(d["token"] == 15736578 and "depth_buy" in d for d in decode(f)))
    for _ in range(3):
        t.on_message(full)
    assert rec.active["NIFTY26NOVFUTNFO"].snapshots == 1
    _post(client, "/api/recorder/stop", {"symbol": NFO})


def test_the_login_ending_stops_the_recording_loudly(kite_client):
    client, t, rec = kite_client
    assert _post(client, "/api/recorder/start", {"symbol": "RELIANCE.NS"}).status_code == 200
    t.session = type("S", (), {"logged_in": False})()
    assert _wait(lambda: "RELIANCENS" in rec.stopped_notes)
    assert rec.stopped_notes["RELIANCENS"] == "KITE LOGIN ENDED" and t._held == {}


def test_a_symbol_that_is_neither_crypto_nor_kite_is_refused(kite_client):
    client, _, _ = kite_client
    assert _post(client, "/api/recorder/start", {"symbol": "AAPL"}).status_code == 400
