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
    assert {p["name"] for p in s["providers"]} == {
        "yahoo", "nasdaq", "synthetic", "rss", "yahoo_rss", "gdelt", "coingecko", "binance", "sec", "yahoo_own",
        "fred", "fred_csv", "treasury", "nasdaq_earnings", "agency_ics",  # Phase 7
    }
    assert s["fixtures"] is True
    keyed = {k["name"]: k["status"] for k in s["keyed"]}
    assert keyed["fred"] in ("KEY REQUIRED", "NOT BUILT") and keyed["stooq"] == "RETIRED"


def test_cached_path_is_fast(client):
    client.get("/api/quote", params={"symbols": "AAPL"})
    for _ in range(50):
        client.get("/api/quote", params={"symbols": "AAPL"})
    p95 = client.get("/api/perf").json()["/api/quote"]["p95"]
    assert p95 < 20
