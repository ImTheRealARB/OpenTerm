"""Phase 13 step 6: news keyword alert storage (ALRT NEWS WORD [SYM]). Evaluation is in the browser (vitest + Playwright)."""

import pytest


def make(client, **body):
    return client.post("/api/newsalerts", json=body)


def test_create_list_normalise(client):
    r = make(client, word="  split  ", symbol="aapl")
    assert r.status_code == 200
    a = r.json()
    assert (a["word"], a["symbol"], a["status"]) == ("SPLIT", "AAPL", "active")
    assert a["headline"] is None and a["url"] is None and a["triggered_at"] is None
    market = make(client, word="recall").json()
    assert market["symbol"] is None  # no symbol: the market top stories
    assert [x["id"] for x in client.get("/api/newsalerts").json()["alerts"]] == [a["id"], market["id"]]


@pytest.mark.parametrize("word", ["", "a", " ", "x" * 41, "bad;word", "<b>"])
def test_bad_words_are_refused(client, word):
    assert make(client, word=word).status_code == 400


def test_bad_symbol_is_refused(client):
    assert make(client, word="split", symbol="NOT A SYMBOL").status_code == 400


def test_trigger_records_the_headline_once_and_rearm_resets(client):
    a = make(client, word="probe", symbol="AAPL").json()
    first = client.post(f"/api/newsalerts/{a['id']}/trigger", json={
        "headline": "Apple faces probe", "url": "https://example.com/x", "at": 1792300000}).json()
    assert first["changed"] is True
    t = first["alert"]
    assert (t["status"], t["headline"], t["url"], t["triggered_at"]) == ("triggered", "Apple faces probe", "https://example.com/x", 1792300000)
    again = client.post(f"/api/newsalerts/{a['id']}/trigger", json={"headline": "other", "url": "https://example.com/y"}).json()
    assert again["changed"] is False and again["alert"]["headline"] == "Apple faces probe"
    re = client.post(f"/api/newsalerts/{a['id']}/rearm").json()
    assert re["status"] == "active" and re["headline"] is None and re["created_at"] > a["created_at"]


def test_trigger_ignores_a_link_that_is_not_http(client):
    a = make(client, word="probe").json()
    t = client.post(f"/api/newsalerts/{a['id']}/trigger", json={"headline": "h", "url": "javascript:alert(1)"}).json()
    assert t["alert"]["url"] is None


def test_delete_clear_and_missing(client):
    a, b = make(client, word="alpha").json(), make(client, word="bravo").json()
    client.post(f"/api/newsalerts/{a['id']}/trigger", json={"headline": "h"})
    assert client.delete("/api/newsalerts", params={"status": "all"}).status_code == 400
    assert client.delete("/api/newsalerts", params={"status": "triggered"}).json() == {"deleted": 1}
    assert [x["id"] for x in client.get("/api/newsalerts").json()["alerts"]] == [b["id"]]
    assert client.delete(f"/api/newsalerts/{b['id']}").json() == {"deleted": b["id"]}
    assert client.delete(f"/api/newsalerts/{b['id']}").status_code == 404
    assert client.post("/api/newsalerts/99/trigger", json={}).status_code == 404
    assert client.post("/api/newsalerts/99/rearm").status_code == 404


def test_price_alerts_are_a_separate_list(client):
    make(client, word="split")
    assert client.get("/api/alerts").json() == {"alerts": []}
