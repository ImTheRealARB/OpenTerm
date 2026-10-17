"""Phase 8: portfolios (migration 6) and price / percent alerts (migration 7)."""


import pytest

from openterm.portfolio import MAX_ALERTS, MAX_POSITIONS, add_lot, check_currency, check_positions
from openterm.userdata import UserDataError


def lot(symbol="AAPL", qty=10.0, cost=100.0, currency=None, notes=None):
    return {"symbol": symbol, "qty": qty, "cost": cost, "currency": currency, "notes": notes}


# --- average cost ----------------------------------------------------------------------------
def test_add_lot_average_cost_rules():
    assert add_lot(None, lot()) == lot()
    # Same side: weighted average.
    assert add_lot(lot(qty=10, cost=100), lot(qty=30, cost=200))["cost"] == pytest.approx(175.0)
    # Reducing keeps the average cost; closing returns None.
    r = add_lot(lot(qty=10, cost=100), lot(qty=-4, cost=150))
    assert r["qty"] == 6 and r["cost"] == 100
    assert add_lot(lot(qty=10), lot(qty=-10, cost=1)) is None
    # Flipping through zero starts at the new lot's cost.
    r = add_lot(lot(qty=10, cost=100), lot(qty=-15, cost=120))
    assert r["qty"] == -5 and r["cost"] == 120
    # Unknown cost on either side is never guessed.
    assert add_lot(lot(cost=None), lot(cost=100))["cost"] is None
    with pytest.raises(UserDataError):
        add_lot(lot(currency="USD"), lot(currency="EUR"))


def test_check_positions_combines_duplicates_and_validates():
    out = check_positions([
        {"symbol": "aapl", "qty": 10, "cost": 100},
        {"symbol": "eurusd", "qty": 1000, "currency": "usd"},
        {"symbol": "AAPL", "qty": 10, "cost": 200, "notes": "  second buy "},
    ])
    assert [p["symbol"] for p in out] == ["AAPL", "EURUSD=X"]
    assert out[0]["qty"] == 20 and out[0]["cost"] == 150 and out[0]["notes"] == "second buy"
    assert out[1]["currency"] == "USD" and out[1]["cost"] is None
    for bad in (
        [{"symbol": "AAPL", "qty": 0}], [{"symbol": "AAPL", "qty": "10"}], [{"symbol": "AAPL", "qty": True}],
        [{"symbol": "AAPL", "qty": 1, "cost": -1}], [{"symbol": "<x>", "qty": 1}], [{"qty": 1}],
        [{"symbol": "AAPL", "qty": 1, "currency": "DOLLARS"}], [{"symbol": "AAPL", "qty": float("inf")}], "AAPL",
    ):
        with pytest.raises(UserDataError):
            check_positions(bad)


def test_currency_minor_units_keep_their_meaning():
    assert check_currency("GBp") == "GBp" and check_currency("GBX") == "GBp"
    assert check_currency("gbp") == "GBP" and check_currency("ZAc") == "ZAc" and check_currency(None) is None


# --- portfolio REST --------------------------------------------------------------------------
def test_portfolio_crud(client):
    assert client.get("/api/portfolios").json() == {"portfolios": []}
    r = client.patch("/api/portfolios/core", json={"add": [{"symbol": "aapl", "qty": 10, "cost": 150}]})
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "CORE" and body["base"] == "USD"
    assert body["positions"] == [{"symbol": "AAPL", "qty": 10.0, "cost": 150.0, "currency": None, "notes": None}]

    # add = another lot (averaged); set = replace that position; remove; base.
    r = client.patch("/api/portfolios/CORE", json={"add": [{"symbol": "AAPL", "qty": 10, "cost": 250}]})
    assert r.json()["positions"][0]["qty"] == 20 and r.json()["positions"][0]["cost"] == 200
    r = client.patch("/api/portfolios/CORE", json={"set": [{"symbol": "MSFT", "qty": 5, "cost": 400, "currency": "USD"}]})
    assert [p["symbol"] for p in r.json()["positions"]] == ["AAPL", "MSFT"]
    r = client.patch("/api/portfolios/CORE", json={"set": [{"symbol": "AAPL", "qty": 1, "cost": 1}]})
    assert r.json()["positions"][0] == {"symbol": "AAPL", "qty": 1.0, "cost": 1.0, "currency": None, "notes": None}
    r = client.patch("/api/portfolios/CORE", json={"remove": ["aapl"], "base": "eur"})
    assert [p["symbol"] for p in r.json()["positions"]] == ["MSFT"] and r.json()["base"] == "EUR"

    listed = client.get("/api/portfolios").json()["portfolios"]
    assert [(p["name"], p["base"], p["count"]) for p in listed] == [("CORE", "EUR", 1)]

    # PUT replaces everything (CSV import REPLACE); base is kept unless given.
    r = client.put("/api/portfolios/core", json={"positions": [{"symbol": "NVDA", "qty": 3, "cost": 100}]})
    assert r.json()["base"] == "EUR" and [p["symbol"] for p in r.json()["positions"]] == ["NVDA"]
    assert client.get("/api/portfolios/Core").json()["positions"][0]["symbol"] == "NVDA"

    assert client.patch("/api/portfolios/nope", json={"remove": ["X"]}).status_code == 404
    assert client.delete("/api/portfolios/core").json() == {"deleted": "CORE"}
    assert client.delete("/api/portfolios/core").status_code == 404
    assert client.get("/api/portfolios/core").status_code == 404


def test_portfolio_validation(client):
    assert client.patch("/api/portfolios/my port", json={"add": [{"symbol": "A", "qty": 1}]}).status_code == 400
    assert client.patch("/api/portfolios/X", json={}).status_code == 400
    assert client.patch("/api/portfolios/X", json={"add": {"symbol": "A", "qty": 1}}).status_code == 400
    assert client.patch("/api/portfolios/X", json={"add": [{"symbol": "A", "qty": 0}]}).status_code == 400
    assert client.put("/api/portfolios/X", json={"nope": []}).status_code == 400
    assert client.put("/api/portfolios/X", json={"positions": [], "base": "EURO"}).status_code == 400
    many = [{"symbol": f"S{i}", "qty": 1} for i in range(MAX_POSITIONS + 1)]
    assert client.put("/api/portfolios/X", json={"positions": many}).status_code == 413
    # Selling the whole position removes it; an empty portfolio stays until deleted.
    client.patch("/api/portfolios/X", json={"add": [{"symbol": "AAPL", "qty": 2, "cost": 10}]})
    assert client.patch("/api/portfolios/X", json={"add": [{"symbol": "AAPL", "qty": -2}]}).json()["positions"] == []



# --- alerts ----------------------------------------------------------------------------------
def test_alert_state_transitions(client):
    assert client.get("/api/alerts").json() == {"alerts": []}
    a = client.post("/api/alerts", json={"symbol": "aapl", "op": ">", "unit": "price", "value": 200}).json()
    assert a["id"] == 1 and a["symbol"] == "AAPL" and a["status"] == "active" and a["trigger_price"] is None
    b = client.post("/api/alerts", json={"symbol": "spx", "op": "<", "unit": "pct", "value": -3}).json()
    assert b["symbol"] == "^GSPC" and b["unit"] == "pct"

    # active -> triggered, once: a second report changes nothing (another tab saw the same tick).
    r = client.post("/api/alerts/1/trigger", json={"price": 201.5, "at": 1_800_000_000})
    assert r.json()["changed"] is True
    assert r.json()["alert"] == {**a, "status": "triggered", "trigger_price": 201.5, "triggered_at": 1_800_000_000}
    r = client.post("/api/alerts/1/trigger", json={"price": 205})
    assert r.json()["changed"] is False and r.json()["alert"]["trigger_price"] == 201.5

    # triggered -> active on rearm, trigger fields cleared.
    r = client.post("/api/alerts/1/rearm").json()
    assert r["status"] == "active" and r["trigger_price"] is None and r["triggered_at"] is None

    # CLEAR removes triggered alerts only.
    client.post("/api/alerts/2/trigger", json={"price": 4000})
    assert client.delete("/api/alerts", params={"status": "triggered"}).json() == {"deleted": 1}
    assert [x["id"] for x in client.get("/api/alerts").json()["alerts"]] == [1]
    assert client.delete("/api/alerts", params={"status": "active"}).status_code == 400

    assert client.delete("/api/alerts/1").json() == {"deleted": 1}
    assert client.delete("/api/alerts/1").status_code == 404
    assert client.post("/api/alerts/1/trigger", json={"price": 1}).status_code == 404
    assert client.post("/api/alerts/1/rearm").status_code == 404


def test_alert_validation(client):
    def post(**kw):
        return client.post("/api/alerts", json={"symbol": "AAPL", "op": ">", "unit": "price", "value": 1, **kw})

    assert post(op=">=").status_code == 400
    assert post(unit="bps").status_code == 400
    assert post(value=0).status_code == 400
    assert post(value=-5).status_code == 400
    assert post(value="200").status_code == 400
    assert post(unit="pct", value=0).status_code == 400
    assert post(unit="pct", value=5000).status_code == 400
    assert post(symbol="a b").status_code == 400
    assert post(symbol="").status_code == 400
    assert client.post("/api/alerts", content=b"[]").status_code == 400
    assert post().status_code == 200
    a = post().json()
    assert client.post(f"/api/alerts/{a['id']}/trigger", json={"price": "x"}).status_code == 400


def test_alert_cap(client, monkeypatch):
    import openterm.portfolio as pf

    monkeypatch.setattr(pf, "MAX_ALERTS", 2)
    for _ in range(2):
        assert client.post("/api/alerts", json={"symbol": "AAPL", "op": "<", "value": 10}).status_code == 200
    assert client.post("/api/alerts", json={"symbol": "AAPL", "op": "<", "value": 10}).status_code == 413
    assert MAX_ALERTS == 200
