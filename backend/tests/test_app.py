from fastapi.testclient import TestClient

from openterm import perf
from openterm.main import app

client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert "server-timing" in r.headers


def test_perf_records_requests():
    client.get("/api/health")
    summary = client.get("/api/perf").json()
    assert summary["/api/health"]["n"] >= 1


def test_ws_ping():
    with client.websocket_connect("/ws") as ws:
        ws.send_text('["ping", 123]')
        msg = ws.receive_json()
        assert msg[0] == "pong" and msg[1] == 123


def test_percentile():
    assert perf.percentile([], 95) == 0.0
    assert perf.percentile(list(range(101)), 95) == 95
