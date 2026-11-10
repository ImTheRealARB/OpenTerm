"""Phase 18 step 2: READ-ONLY broker sync (Kite holdings, IBKR Client Portal gateway) into PORT.

Every payload below comes from tests/fixtures/broker_*_docshape.json: DOC-SHAPED FIXTURES, NOT A RECORDING. Nothing here touches the
network: the Kite client's `get_json` is replaced and the IBKR gateway client runs on an httpx mock transport.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from openterm.brokers import kite_map
from openterm.brokers.ibkr import (
    DEFAULT_GATEWAY_URL,
    GatewayUrlError,
    IbkrGateway,
    map_cash,
    map_position,
    validate_gateway_url,
)

FIX = Path(__file__).parent / "fixtures"
KITE = json.loads((FIX / "broker_kite_docshape.json").read_bytes().decode("utf-8"))
IBKR = json.loads((FIX / "broker_ibkr_docshape.json").read_bytes().decode("utf-8"))


def test_fixtures_are_labelled_not_a_recording():
    for doc in (KITE, IBKR):
        assert "NOT A RECORDING" in doc["_label"].upper()


# --- Kite mapping -----------------------------------------------------------------------------------------------------------------------

def test_kite_holdings_map_to_inr_lots():
    lots, skipped, warnings = kite_map.map_holdings(KITE["holdings"])
    by = {lot["symbol"]: lot for lot in lots}
    assert by["INFY.NS"] == {"symbol": "INFY.NS", "qty": 10.0, "cost": 1400.5, "currency": "INR", "notes": None}
    assert by["RELIANCE.BO"]["qty"] == 4.0 and by["RELIANCE.BO"]["cost"] == 2450.0  # BSE -> .BO
    assert by["M&M.NS"]["qty"] == 3.0 and by["M&M.NS"]["cost"] == 0.0
    assert {lot["currency"] for lot in lots} == {"INR"}
    assert "SOLDOUT.NS" not in by  # zero quantity is not a lot
    assert sorted(s["symbol"] for s in skipped) == ["NSE:WEIRD NAME", "XYZ:ODDBALL"]  # reported, not dropped silently
    assert any("COLLATERAL" in w and "RELIANCE.BO" in w for w in warnings)


def test_kite_positions_only_intraday_and_derivative_products_with_signed_qty():
    lots, skipped = kite_map.map_positions(KITE["positions"])
    by = {lot["symbol"]: lot for lot in lots}
    assert set(by) == {"NIFTY26NOVFUT.NFO", "TCS.NS"}  # CNC row is the holding, qty 0 row is closed
    assert by["NIFTY26NOVFUT.NFO"]["qty"] == -50.0 and by["NIFTY26NOVFUT.NFO"]["currency"] == "INR"
    assert skipped == []


# --- IBKR mapping -----------------------------------------------------------------------------------------------------------------------

def test_ibkr_positions_map_with_per_position_currency():
    rows = IBKR["positions"]["U1111111"] + IBKR["positions"]["U2222222"][:1] + IBKR["positions"]["U2222222"][2:]  # SAP, zero row
    out = [(r["contractDesc"], *map_position(r)) for r in rows]
    lots = {lot["symbol"] + "/" + lot["currency"]: lot for _, lot, _, _ in out if lot}
    assert lots["AAPL/USD"]["qty"] == 25.0 and lots["AAPL/USD"]["cost"] == 150.5
    assert lots["BRK-B/USD"]["qty"] == 3.0  # "BRK B" -> BRK-B
    assert lots["SAP.DE/EUR"]["qty"] == 12.0  # multi-currency: EUR stays EUR
    assert lots["VOD.L/GBp"]["cost"] == 72.5  # LSE: pence, with a warning
    reasons = {desc: why for desc, lot, why, _ in out if why}
    assert "OPT" in reasons["AAPL DEC2026 250 C"] and "MOON" in reasons["XYZ"]
    assert [w for _, _, _, w in out if w] == ["LSE PRICES TAKEN AS PENCE (GBp), THE UNIT IBKR QUOTES THEM IN. CHECK ONE LSE LOT AGAINST TWS"]
    assert map_position(IBKR["positions"]["U2222222"][2]) == (None, None, None)  # zero position: nothing to say


def test_ibkr_ledger_keeps_every_currency_and_marks_base():
    cash = map_cash(IBKR["ledger"]["U1111111"])
    assert [(c["currency"], c["base"], c["cash"]) for c in cash] == [("GBP", False, 200.0), ("USD", False, 1500.25), ("BASE", True, 1750.0)]


# --- loopback-only gateway URL ----------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("url", [
    "https://localhost:5000/v1/api", "https://127.0.0.1:5000/v1/api/", "http://localhost:5001", "https://[::1]:5000/v1/api",
    "https://LOCALHOST/v1/api", "https://127.0.0.5:5000/v1/api",
])
def test_loopback_gateway_urls_are_accepted(url):
    assert validate_gateway_url(url).endswith("/v1/api")


@pytest.mark.parametrize("url", [
    "https://example.com:5000/v1/api", "https://192.168.1.5:5000/v1/api", "https://localhost.evil.com:5000/v1/api",
    "https://127.0.0.1.evil.com/v1/api", "https://localhost@evil.com/v1/api", "https://user:pw@localhost:5000/v1/api",
    "ftp://localhost/v1/api", "https://localhost:5000/v1/api?x=1", "https://localhost:5000/other", "https://0.0.0.0:5000/v1/api",
    "https://10.0.0.1/v1/api", "", "localhost:5000", None, 5,
])
def test_non_loopback_gateway_urls_are_refused(url):
    with pytest.raises(GatewayUrlError):
        validate_gateway_url(url)
    with pytest.raises(GatewayUrlError):
        IbkrGateway(url)


def test_settings_route_refuses_a_remote_gateway_and_keeps_the_old_one(client):
    assert client.get("/api/sync/ibkr/settings").json() == {"gateway_url": DEFAULT_GATEWAY_URL}
    r = client.put("/api/sync/ibkr/settings", json={"gateway_url": "https://broker.example.com/v1/api"})
    assert r.status_code == 400 and "ON THIS MACHINE" in r.json()["error"]
    assert client.get("/api/sync/ibkr/settings").json() == {"gateway_url": DEFAULT_GATEWAY_URL}
    ok = client.put("/api/sync/ibkr/settings", json={"gateway_url": "https://127.0.0.1:5001/v1/api"})
    assert ok.status_code == 200 and ok.json()["gateway_url"] == "https://127.0.0.1:5001/v1/api"
    assert client.get("/api/sync/status").json()["ibkr"]["gateway_url"] == "https://127.0.0.1:5001/v1/api"


def test_a_stored_remote_url_is_never_connected_to(client):
    from openterm.brokers.sync import GATEWAY_KEY

    db = client.app.state.userdata.db

    async def poison():
        await db.execute("INSERT INTO kv (key, value) VALUES (?, ?)", (GATEWAY_KEY, b'"https://evil.example.com/v1/api"'))
        await db.commit()

    client.portal.call(poison)  # run on the app's own event loop
    assert client.get("/api/sync/ibkr/settings").json()["gateway_url"] == DEFAULT_GATEWAY_URL


# --- helpers for the route tests ---------------------------------------------------------------------------------------------------------

def fake_kite(client, holdings=None, positions=None, calls=None):
    kite = client.app.state.kite
    kite.session.auth = lambda: ("fake-key", "fake-token")  # a logged-in session without a key store

    async def get_json(path, params=None, historical=False):
        if calls is not None:
            calls.append(path)
        return {"/portfolio/holdings": holdings if holdings is not None else KITE["holdings"],
                "/portfolio/positions": positions if positions is not None else KITE["positions"]}[path]

    kite.client.get_json = get_json


def gateway_transport(state: dict):
    """A mock IBKR gateway. `state['up']` False raises a connect error; every request is recorded in state['requests']."""

    def handler(request: httpx.Request) -> httpx.Response:
        state.setdefault("requests", []).append((request.method, request.url.path))
        if not state.get("up", True):
            raise httpx.ConnectError("refused")
        path = request.url.path.removeprefix("/v1/api")
        if path == "/iserver/auth/status":
            return httpx.Response(200, json=state.get("auth", IBKR["auth"]))
        if path == "/portfolio/accounts":
            return httpx.Response(200, json=IBKR["accounts"])
        parts = path.split("/")  # ['', 'portfolio', ACCT, 'positions', '0'] | ['', 'portfolio', ACCT, 'ledger']
        if parts[3] == "positions":
            rows = state.get("positions", IBKR["positions"])[parts[2]]
            return httpx.Response(200, json=rows if parts[4] == "0" else [])
        if parts[3] == "ledger":
            return httpx.Response(200, json=IBKR["ledger"][parts[2]])
        return httpx.Response(404, json={})

    return httpx.MockTransport(handler)


def fake_ibkr(client, state):
    client.app.state.ibkr_http = httpx.AsyncClient(transport=gateway_transport(state))


def portfolio(client, name):
    return client.get(f"/api/portfolios/{name}").json()


# --- Kite sync --------------------------------------------------------------------------------------------------------------------------

def test_kite_sync_writes_labelled_inr_lots_and_resync_does_not_duplicate(client):
    fake_kite(client)
    client.patch("/api/portfolios/KITE", json={"add": [{"symbol": "MSFT", "qty": 2, "cost": 300, "currency": "USD"}]})  # a manual lot
    first = client.post("/api/sync/kite", json={})
    assert first.status_code == 200
    rec = first.json()
    assert rec["ok"] and rec["counts"]["imported"] == 3 and rec["counts"]["manual_kept"] == 1 and rec["counts"]["skipped"] == 2
    assert rec["diff"]["added"] == ["INFY.NS", "M&M.NS", "RELIANCE.BO"] and rec["diff"]["removed"] == []
    pf = portfolio(client, "KITE")
    assert pf["base"] == "USD"  # the existing portfolio keeps its base; a new KITE portfolio would be INR
    synced = [p for p in pf["positions"] if p.get("source") == "kite"]
    assert len(synced) == 3 and all(p["synced_at"] and p["notes"].startswith("KITE SYNC ") and p["currency"] == "INR" for p in synced)
    assert [p["symbol"] for p in pf["positions"] if "source" not in p] == ["MSFT"]  # manual lot untouched

    # Kite changed: INFY sold down, RELIANCE gone, TCS bought. Same call again.
    changed = [dict(KITE["holdings"][0], quantity=4), {"tradingsymbol": "TCS", "exchange": "NSE", "quantity": 2, "average_price": 4000.0}]
    fake_kite(client, holdings=changed)
    second = client.post("/api/sync/kite", json={}).json()
    assert second["diff"]["added"] == ["TCS.NS"] and second["diff"]["removed"] == ["M&M.NS", "RELIANCE.BO"]
    assert second["diff"]["changed"] == [{"symbol": "INFY.NS", "qty_from": 10.0, "qty_to": 4.0, "cost_from": 1400.5, "cost_to": 1400.5}]
    pf = portfolio(client, "KITE")
    assert sorted(p["symbol"] for p in pf["positions"]) == ["INFY.NS", "MSFT", "TCS.NS"]  # replaced, never duplicated
    again = client.post("/api/sync/kite", json={}).json()  # identical re-sync: no difference at all
    assert again["diff"] == {"added": [], "removed": [], "changed": []}
    assert len(portfolio(client, "KITE")["positions"]) == 3


def test_kite_sync_defaults_to_a_new_inr_portfolio_and_can_include_positions(client):
    calls: list[str] = []
    fake_kite(client, calls=calls)
    rec = client.post("/api/sync/kite", json={"portfolio": "zerodha", "positions": True}).json()
    assert rec["portfolio"] == "ZERODHA" and rec["base"] == "INR"
    assert rec["holdings"] == 3 and rec["positions"] == 2 and "/portfolio/positions" in calls
    assert {p["symbol"] for p in portfolio(client, "ZERODHA")["positions"]} >= {"TCS.NS", "NIFTY26NOVFUT.NFO"}
    calls.clear()
    client.post("/api/sync/kite", json={"portfolio": "zerodha"})
    assert calls == ["/portfolio/holdings"]  # positions are opt-in


def test_a_synced_symbol_that_is_also_a_manual_lot_is_a_conflict_not_a_merge(client):
    fake_kite(client)
    client.patch("/api/portfolios/KITE", json={"add": [{"symbol": "INFY.NS", "qty": 1, "cost": 1000, "currency": "INR"}]})
    rec = client.post("/api/sync/kite", json={}).json()
    assert rec["counts"]["conflicts"] == 1 and "INFY.NS" in rec["conflicts"][0]
    infy = next(p for p in portfolio(client, "KITE")["positions"] if p["symbol"] == "INFY.NS")
    assert infy["qty"] == 1 and "source" not in infy


def test_kite_sync_without_a_login_says_so_and_changes_nothing(client):
    client.patch("/api/portfolios/KITE", json={"add": [{"symbol": "AAPL", "qty": 1, "cost": 1}]})
    r = client.post("/api/sync/kite", json={})
    assert r.status_code == 424 and r.json()["error"].startswith("KEY REQUIRED")
    assert portfolio(client, "KITE")["positions"][0]["symbol"] == "AAPL" and len(portfolio(client, "KITE")["positions"]) == 1
    st = client.get("/api/sync/status").json()["kite"]
    assert st["last_ok"] is None and st["last_error"]["error"].startswith("KEY REQUIRED") and st["last_error"]["ok"] is False


def test_kite_error_text_is_redacted(client):
    fake_kite(client)

    async def boom(path, params=None, historical=False):
        raise __import__("openterm.errors", fromlist=["DataError"]).DataError("unavailable", "KITE: bad access_token=abcdef123456789 here")

    client.app.state.kite.client.get_json = boom
    r = client.post("/api/sync/kite", json={})
    assert r.status_code == 503 and "abcdef123456789" not in r.text
    assert "abcdef123456789" not in json.dumps(client.get("/api/sync/status").json())


# --- IBKR sync --------------------------------------------------------------------------------------------------------------------------

def test_ibkr_sync_merges_accounts_keeps_currencies_and_reports_cash(client):
    state: dict = {}
    fake_ibkr(client, state)
    rec = client.post("/api/sync/ibkr", json={}).json()
    assert rec["ok"] and rec["portfolio"] == "IBKR" and rec["base"] == "USD" and rec["accounts"] == ["U1111111", "U2222222"]
    pf = portfolio(client, "IBKR")
    by = {p["symbol"]: p for p in pf["positions"]}
    assert set(by) == {"AAPL", "BRK-B", "VOD.L", "SAP.DE"}
    assert by["AAPL"]["qty"] == 30.0 and by["AAPL"]["cost"] == pytest.approx((25 * 150.5 + 5 * 200.0) / 30)  # two accounts averaged
    assert by["SAP.DE"]["currency"] == "EUR" and by["VOD.L"]["currency"] == "GBp" and by["AAPL"]["source"] == "ibkr"
    assert {s["symbol"] for s in rec["skipped"]} >= {"AAPL DEC2026 250 C", "XYZ"}
    assert rec["warnings"] and "LSE" in rec["warnings"][0]
    cash = {c["account"]: {r["currency"]: r["cash"] for r in c["rows"]} for c in rec["cash"]}
    assert cash["U1111111"]["USD"] == 1500.25 and cash["U1111111"]["GBP"] == 200.0 and cash["U2222222"]["EUR"] == 50.0


def test_ibkr_resync_is_idempotent_and_shows_what_changed(client):
    state: dict = {}
    fake_ibkr(client, state)
    client.post("/api/sync/ibkr", json={})
    again = client.post("/api/sync/ibkr", json={}).json()
    assert again["diff"] == {"added": [], "removed": [], "changed": []} and len(portfolio(client, "IBKR")["positions"]) == 4
    state["positions"] = {"U1111111": [IBKR["positions"]["U1111111"][0] | {"position": 10.0}], "U2222222": []}
    third = client.post("/api/sync/ibkr", json={"account": "U1111111"}).json()
    assert third["diff"]["removed"] == ["BRK-B", "SAP.DE", "VOD.L"] and third["diff"]["changed"][0]["qty_to"] == 10.0
    assert [p["symbol"] for p in portfolio(client, "IBKR")["positions"]] == ["AAPL"]


def test_ibkr_gateway_down_says_not_running_with_the_next_step(client):
    state = {"up": False}
    fake_ibkr(client, state)
    client.patch("/api/portfolios/IBKR", json={"add": [{"symbol": "AAPL", "qty": 1, "cost": 1}]})
    r = client.post("/api/sync/ibkr", json={})
    assert r.status_code == 503
    err = r.json()["error"]
    assert err.startswith("IBKR GATEWAY NOT RUNNING") and "run.sh" in err and "SYNC IBKR" in err
    assert len(portfolio(client, "IBKR")["positions"]) == 1  # nothing changed
    assert client.get("/api/sync/ibkr/check").json()["error"].startswith("IBKR GATEWAY NOT RUNNING")
    st = client.get("/api/sync/status").json()["ibkr"]
    assert st["last_error"]["error"].startswith("IBKR GATEWAY NOT RUNNING") and st["last_ok"] is None


def test_ibkr_gateway_up_but_logged_out(client):
    fake_ibkr(client, {"auth": {"authenticated": False, "connected": True}})
    r = client.post("/api/sync/ibkr", json={})
    assert r.status_code == 401 and r.json()["error"].startswith("IBKR GATEWAY NOT LOGGED IN")


def test_ibkr_client_only_ever_sends_get_requests(client):
    state: dict = {}
    fake_ibkr(client, state)
    client.post("/api/sync/ibkr", json={})
    assert state["requests"] and {m for m, _ in state["requests"]} == {"GET"}
    assert not [p for _, p in state["requests"] if "order" in p]


def test_sync_routes_refuse_a_client_that_is_not_this_machine(client):
    from fastapi.testclient import TestClient

    with TestClient(client.app, client=("203.0.113.9", 50000)) as remote:
        assert remote.post("/api/sync/kite", json={}).status_code == 403
        assert remote.post("/api/sync/ibkr", json={}).status_code == 403
        assert remote.put("/api/sync/ibkr/settings", json={"gateway_url": DEFAULT_GATEWAY_URL}).status_code == 403


def test_synced_fields_survive_put_and_the_portfolio_still_reads(client):
    fake_kite(client)
    client.post("/api/sync/kite", json={})
    pf = portfolio(client, "KITE")
    back = client.put("/api/portfolios/KITE", json={"positions": pf["positions"]}).json()  # PORT undo path
    assert [p.get("source") for p in back["positions"]] == ["kite"] * 3


# --- no order surface -------------------------------------------------------------------------------------------------------------------

def test_brokers_package_and_routes_have_no_order_surface():
    root = Path(__file__).resolve().parents[1] / "openterm"
    files = [*(root / "brokers").rglob("*.py"), root / "brokers_routes.py"]
    forbidden = ("/orders", "place_order", "modify_order", "cancel_order", "/gtt", "/whatif", "client.post(", "http.post(")
    for f in files:
        text = f.read_text(encoding="utf-8")
        assert not [w for w in forbidden if w in text], (f.name, [w for w in forbidden if w in text])
