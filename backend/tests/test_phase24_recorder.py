"""Phase 24 recorder: start / stop through the API with a fast injected poll, de-duplication of trades, the disk cap, the retention
sweep and the settings validator. Fixture mode (no network): every poll returns the same recorded BTCUSDT trades, so a correct
de-duplication writes each aggregate id exactly once however many polls ran."""

import os
import time

import orjson
import pytest

JSON = {"content-type": "application/json"}


def _post(client, path, body):
    return client.post(path, content=orjson.dumps(body), headers=JSON)


def _recorder(client):
    rec = client.app.state.recorder
    rec.poll_s = 0.02  # the injectable interval: a few polls in well under a second
    return rec


def _wait(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_nothing_records_until_the_user_starts_it(client):
    d = client.get("/api/recorder").json()
    assert d["active"] == [] and d["sessions"] == []
    assert d["label"] == "OFF BY DEFAULT · KEPT ON THIS COMPUTER ONLY"
    assert d["cap_mb"] == 500 and d["retention_days"] == 14


def test_start_records_and_stop_ends_the_session_and_trades_are_deduplicated(client):
    rec = _recorder(client)
    r = _post(client, "/api/recorder/start", {"symbol": "BTCUSDT"})
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    assert sid.startswith("BTCUSDT/")
    # several polls happen; the fixture answers the same 1000 trades each time
    assert _wait(lambda: rec.active["BTCUSDT"].snapshots >= 4)
    assert _post(client, "/api/recorder/start", {"symbol": "BTC-USDT"}).status_code == 409  # already recording
    assert client.get("/api/recorder").json()["active"][0]["id"] == sid
    st = _post(client, "/api/recorder/stop", {"symbol": "BTCUSDT"})
    assert st.status_code == 200 and st.json()["id"] == sid
    assert _post(client, "/api/recorder/stop", {"symbol": "BTCUSDT"}).status_code == 404

    s = client.get(f"/api/recorder/session/{sid}").json()
    ids = [t["id"] for t in s["trades"]]
    assert len(ids) == 1000 and len(set(ids)) == 1000 and ids == sorted(ids)  # each aggregate id once, oldest first
    assert len(s["depth"]) >= 4 and "bids" in s["depth"][-1] or "asks" in s["depth"][-1] or s["depth"][-1]["t"] > 0
    assert s["meta"]["symbol"] == "BTCUSDT" and s["meta"]["venue"] == "BINANCE SPOT"
    assert s["end"]["reason"] == "STOPPED" and s["truncated"] is False

    listed = client.get("/api/recorder").json()
    assert listed["active"] == [] and [x["id"] for x in listed["sessions"]] == [sid]
    assert listed["sessions"][0]["bytes"] > 1000


def test_delete_removes_the_file_and_refuses_a_running_session(client):
    rec = _recorder(client)
    sid = _post(client, "/api/recorder/start", {"symbol": "BTCUSDT"}).json()["id"]
    assert client.delete(f"/api/recorder/session/{sid}").status_code == 409  # still recording: stop it first
    _post(client, "/api/recorder/stop", {"symbol": "BTCUSDT"})
    assert client.delete(f"/api/recorder/session/{sid}").json() == {"deleted": sid}
    assert client.get(f"/api/recorder/session/{sid}").status_code == 404
    assert client.get("/api/recorder").json()["sessions"] == []
    assert rec.active == {}


def test_bad_symbols_and_session_ids_are_refused(client):
    _recorder(client)
    assert _post(client, "/api/recorder/start", {"symbol": "AAPL"}).status_code == 400  # not a crypto pair shape
    assert client.get("/api/recorder/session/..%2F..%2Fsecret").status_code in (400, 404)
    assert client.get("/api/recorder/session/BTCUSDT/not-a-stamp").status_code == 400
    assert client.delete("/api/recorder/session/x").status_code == 400


def test_the_disk_cap_stops_a_recording_and_says_so(client):
    rec = _recorder(client)
    put = client.put("/api/settings", content=orjson.dumps({"settings": {"recorder": {"capMb": 1}}}), headers=JSON)
    assert put.status_code == 200, put.text
    assert _post(client, "/api/recorder/start", {"symbol": "BTCUSDT"}).status_code == 200
    # Another session's file fills the cap (1 MB); the next poll sees the folder over the cap and stops the recording.
    other = rec.root / "ETHUSDT"
    other.mkdir(parents=True)
    (other / "2026-01-01-000000.jsonl").write_bytes(b"x" * 1_100_000)
    assert _wait(lambda: "BTCUSDT" not in rec.active)
    assert rec.stopped_notes["BTCUSDT"] == "DISK CAP 1 MB"
    listed = client.get("/api/recorder").json()
    assert listed["notes"]["BTCUSDT"] == "DISK CAP 1 MB"
    sid = next(s["id"] for s in listed["sessions"] if s["symbol"] == "BTCUSDT")
    assert client.get(f"/api/recorder/session/{sid}").json()["end"]["reason"] == "DISK CAP 1 MB"
    # and a new recording is refused while the folder is still over the cap
    r = _post(client, "/api/recorder/start", {"symbol": "BTCUSDT"})
    assert r.status_code == 409 and "RECORDER STOPPED: DISK CAP 1 MB" in r.json()["error"]


def test_retention_deletes_old_sessions_when_a_recording_starts(client):
    rec = _recorder(client)
    old = rec.root / "BTCUSDT" / "2026-01-01-000000.jsonl"
    old.parent.mkdir(parents=True)
    old.write_bytes(b'{"k":"meta"}\n')
    age = time.time() - 20 * 86400
    os.utime(old, (age, age))  # 20 days old; the default retention is 14
    fresh = rec.root / "BTCUSDT" / "2026-01-02-000000.jsonl"
    fresh.write_bytes(b'{"k":"meta"}\n')
    assert _post(client, "/api/recorder/start", {"symbol": "BTCUSDT"}).status_code == 200
    _post(client, "/api/recorder/stop", {"symbol": "BTCUSDT"})
    assert not old.exists() and fresh.exists()


def test_recorder_settings_validator(client):
    def put(v):
        return client.put("/api/settings", content=orjson.dumps({"settings": {"recorder": v}}), headers=JSON)

    ok = put({"capMb": 200})
    assert ok.status_code == 200 and ok.json()["settings"]["recorder"] == {"capMb": 200, "retentionDays": 14}
    for bad in ({"capMb": 0}, {"capMb": "5"}, {"retentionDays": 1.5}, {"nope": 1}, {"capMb": True}, []):
        assert put(bad).status_code == 400, bad


def test_a_half_written_last_line_is_skipped(client):
    rec = _recorder(client)
    f = rec.root / "BTCUSDT" / "2026-02-01-000000.jsonl"
    f.parent.mkdir(parents=True)
    f.write_bytes(b'{"k":"meta","v":1,"symbol":"BTCUSDT"}\n{"k":"t","id":1,"t":5,"p":1.0,"q":2.0,"buy":true}\n{"k":"t","id":2,"t"')
    s = client.get("/api/recorder/session/BTCUSDT/2026-02-01-000000").json()
    assert [t["id"] for t in s["trades"]] == [1]


@pytest.mark.parametrize("sym", ["BTCUSDT", "BTC-USDT"])
def test_both_spellings_record_the_same_file_name(client, sym):
    _recorder(client)
    sid = _post(client, "/api/recorder/start", {"symbol": sym}).json()["id"]
    assert sid.startswith("BTCUSDT/")
    _post(client, "/api/recorder/stop", {"symbol": sym})


def test_a_recorded_session_replays_in_the_live_panel_shapes(client):
    rec = _recorder(client)
    sid = _post(client, "/api/recorder/start", {"symbol": "BTCUSDT"}).json()["id"]
    assert _wait(lambda: rec.active["BTCUSDT"].snapshots >= 3)
    _post(client, "/api/recorder/stop", {"symbol": "BTCUSDT"})

    tas = client.get("/api/recorder/tas", params={"id": sid, "limit": 5}).json()
    assert tas["source"] == "recorder" and tas["stale"] is False
    rows = tas["data"]["rows"]
    assert len(rows) == 5 and rows[0]["id"] > rows[-1]["id"] and rows[0]["side"] in ("BUY", "SELL")  # newest first, like live TAS
    assert tas["data"]["recorded"]["id"] == sid and tas["data"]["n"] == 1000

    foot = client.get("/api/recorder/footprint", params={"id": sid, "interval": "1m", "bars": 10}).json()["data"]
    assert foot["bars"] and foot["levels"] and foot["recorded"]["id"] == sid and foot["interval"] == "1m"
    assert client.get("/api/recorder/footprint", params={"id": sid, "interval": "9m"}).status_code == 400

    last = client.get("/api/recorder/depth", params={"id": sid}).json()["data"]  # default i=-1: the newest snapshot
    first = client.get("/api/recorder/depth", params={"id": sid, "i": 0}).json()["data"]
    assert last["recorded"]["index"] == last["recorded"]["count"] - 1 and first["recorded"]["index"] == 0
    assert last["bids"] and last["asks"] and last["symbol"] == "BTCUSDT"
    assert client.get("/api/recorder/depth", params={"id": sid, "i": 9999}).status_code == 400
    assert client.get("/api/recorder/tas", params={"id": "BTCUSDT/2020-01-01-000000"}).status_code == 404
