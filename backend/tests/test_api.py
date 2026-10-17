import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENTERM_FIXTURES", "1")
    monkeypatch.setenv("OPENTERM_DB_PATH", str(tmp_path / "api.db"))
    from openterm.config import get_settings

    get_settings.cache_clear()
    from openterm.main import app

    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


def test_history_envelope(client):
    r = client.get("/api/history", params={"symbol": "aapl", "range": "1Y"})
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "yahoo:fixture" and body["stale"] is False
    assert body["data"]["interval"] == "1d" and len(body["data"]["c"]) > 200


def test_history_errors(client):
    assert client.get("/api/history", params={"symbol": "ZZZZ", "range": "1Y"}).json()["error"] == "NO DATA FOR SYMBOL"
    r = client.get("/api/history", params={"symbol": "AAPL", "range": "1Y", "interval": "1m"})
    assert r.status_code == 400


def test_quotes_with_fallback_and_missing(client):
    r = client.get("/api/quote", params={"symbols": "AAPL,RELIANCE.NS,NOPE"}).json()["results"]
    assert r["AAPL"]["data"]["price"] > 0 and r["AAPL"]["source"] == "yahoo:fixture"
    assert r["RELIANCE.NS"]["data"]["currency"] == "INR"
    assert r["NOPE"]["error"] == "NO DATA FOR SYMBOL"


def test_search_and_sources(client):
    hits = client.get("/api/search", params={"q": "relian"}).json()
    assert hits["data"][0]["symbol"] == "RELIANCE.NS"
    s = client.get("/api/sources").json()
    assert {p["name"] for p in s["providers"]} == {"yahoo", "nasdaq"}
    assert s["fixtures"] is True
    keyed = {k["name"]: k["status"] for k in s["keyed"]}
    assert keyed["fred"] in ("KEY REQUIRED", "NOT BUILT") and keyed["stooq"] == "RETIRED"


def test_cached_path_is_fast(client):
    client.get("/api/quote", params={"symbols": "AAPL"})
    for _ in range(50):
        client.get("/api/quote", params={"symbols": "AAPL"})
    p95 = client.get("/api/perf").json()["/api/quote"]["p95"]
    assert p95 < 20
