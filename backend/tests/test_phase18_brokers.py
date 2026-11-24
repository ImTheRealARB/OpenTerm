"""Phase 18: the Alpaca PAPER order adapter, the order routes and the "AI can never reach an order" guards.

OpenTerm never places live orders (owner decision 2026-11-24): there is no live broker, and a live host or account is refused.
Broker payloads come from tests/fixtures/alpaca_*_docshape.json: DOC-SHAPED, NOT A RECORDING. The adapter runs on an httpx
MockTransport; nothing here touches the network or a broker.
"""

import json
import re
from pathlib import Path

import httpx
import pytest

from openterm import redact
from openterm.orders.brokers.alpaca import AlpacaTrading, detect_mode
from openterm.orders.errors import OrderError
from openterm.orders.model import Order

FIX = Path(__file__).parent / "fixtures"
SECRET = "SECRETKEYVALUE9876543210"


def fx(name: str):
    d = json.loads((FIX / name).read_text(encoding="utf-8"))
    assert "NOT A RECORDING" in d["_label"]
    return d["body"]


class Store:
    def __init__(self, slot: str | None = "paper"):
        self.slot = slot

    def get(self, name):
        if self.slot and name == f"alpaca_{self.slot}":
            return {f"ALPACA_{self.slot.upper()}_KEY_ID": "KEYID1234", f"ALPACA_{self.slot.upper()}_SECRET_KEY": SECRET}
        return None


def alpaca(slot, routes, store=None, calls=None):
    def handler(req: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append((req.method, req.url.host, req.url.path, dict(req.headers), req.content))
        status, body = routes[(req.method, req.url.path)]
        return httpx.Response(status, json=body)

    return AlpacaTrading(slot, store or Store(slot), httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def order(**kw):
    return Order.from_body({"broker": "alpaca-paper", "symbol": "AAPL", "side": "buy", "qty": 10, "type": "limit", "limit_price": 190.5, "tif": "day", **kw})


# --- Alpaca: paper only -------------------------------------------------------------------------------------------------------------
async def test_the_paper_host_gives_a_paper_account():
    calls = []
    p = alpaca("paper", {("GET", "/v2/account"): (200, fx("alpaca_account_paper_docshape.json"))}, calls=calls)
    a = await p.account()
    assert a["mode"] == "paper" and "PLAY MONEY" in a["note"] and calls[0][1] == "paper-api.alpaca.markets"
    assert (a["equity"], a["currency"]) == (float(fx("alpaca_account_paper_docshape.json")["equity"]), "USD")


async def test_live_is_always_refused_and_an_unknown_host_too():
    with pytest.raises(OrderError, match="NEVER PLACES LIVE ORDERS"):
        detect_mode("https://api.alpaca.markets", "912345678")  # the live host, even with a live account number
    with pytest.raises(OrderError):
        detect_mode("https://evil.example.com", "PA3ABCDEFGH")
    with pytest.raises(OrderError) as e:
        detect_mode("https://paper-api.alpaca.markets", "912345678")  # the paper host answering with a non-paper account
    assert e.value.kind == "mode_mismatch"
    wrong = alpaca("paper", {("GET", "/v2/account"): (200, fx("alpaca_account_live_docshape.json"))})
    with pytest.raises(OrderError) as e:
        await wrong.account()
    assert e.value.kind == "mode_mismatch"


def test_there_is_no_live_slot_and_no_key_means_key_required():
    for slot in ("live", "sandbox"):
        with pytest.raises(ValueError):
            AlpacaTrading(slot, Store(), httpx.AsyncClient())
    b = AlpacaTrading("paper", Store(None), httpx.AsyncClient())
    err = b.not_ready()
    assert err.kind == "key_required" and "ALPACA_PAPER_KEY_ID" in str(err) and b.host == "https://paper-api.alpaca.markets"


async def test_keys_go_only_in_headers_and_a_missing_key_never_calls_the_network():
    calls = []
    ok = alpaca("paper", {("POST", "/v2/orders"): (200, fx("alpaca_order_accepted_docshape.json"))}, calls=calls)
    res = await ok.submit(order(), "OTclient123")
    assert res["status"] in ("NEW", "PENDING") and res["id"]
    _, _, path, headers, content = calls[0]
    body = json.loads(content)
    assert headers["apca-api-secret-key"] == SECRET and SECRET not in path and SECRET not in content.decode()
    assert body["client_order_id"] == "OTclient123" and body["qty"] == "10" and body["limit_price"] == "190.5" and "mode" not in body

    def no_network(req):
        pytest.fail("network used")

    none = AlpacaTrading("paper", Store(None), httpx.AsyncClient(transport=httpx.MockTransport(no_network)))
    with pytest.raises(OrderError) as e:
        await none.submit(order(), "x")
    assert e.value.kind == "key_required"


async def test_alpaca_reads_open_orders_positions_and_fills():
    routes = {("GET", "/v2/orders"): (200, fx("alpaca_orders_open_docshape.json")), ("GET", "/v2/positions"): (200, fx("alpaca_positions_docshape.json")),
              ("GET", "/v2/account/activities/FILL"): (200, fx("alpaca_fills_docshape.json")), ("GET", "/v2/account"): (200, fx("alpaca_account_paper_docshape.json"))}
    b = alpaca("paper", routes)
    opens = await b.open_orders()
    assert opens and all(o["status"] in ("NEW", "PARTIAL", "PENDING") for o in opens)
    pos = await b.positions()
    assert pos and all(isinstance(p["qty"], float) for p in pos)
    fills = await b.fills_today()
    assert fills[0]["fill_id"].startswith("2026") and fills[0]["qty"] == 10 and fills[0]["price"] == 189.5 and fills[0]["currency"] == "USD"


async def test_alpaca_cancel_all_reports_each_order_and_bad_ids_never_reach_a_url():
    b = alpaca("paper", {("DELETE", "/v2/orders"): (207, fx("alpaca_cancel_all_docshape.json"))})
    rows = await b.cancel_all()
    assert [r["ok"] for r in rows] == [True, False]
    for bad in ("../account", "a/b", "", 5):
        with pytest.raises(OrderError) as e:
            await b.cancel(bad)
        assert e.value.kind == "bad_request"


async def test_alpaca_errors_are_redacted_and_typed():
    redact.register([SECRET])
    try:
        for status, body, kind in ((401, {"message": "unauthorized"}, "forbidden"), (403, {"message": f"insufficient buying power {SECRET}"}, "broker_rejected"),
                                   (422, {"message": f"bad {SECRET}"}, "broker_rejected"), (429, {}, "unavailable"), (500, {"message": SECRET}, "unavailable")):
            b = alpaca("paper", {("POST", "/v2/orders"): (status, body)})
            with pytest.raises(OrderError) as e:
                await b.submit(order(), "x")
            assert e.value.kind == kind and SECRET not in str(e.value), status
    finally:
        redact.unregister([SECRET])


async def test_alpaca_network_failure_is_unavailable_and_leaks_nothing():
    def boom(req):
        raise httpx.ConnectError(f"cannot reach {req.url} with {SECRET}")

    b = AlpacaTrading("paper", Store(), httpx.AsyncClient(transport=httpx.MockTransport(boom)))
    with pytest.raises(OrderError) as e:
        await b.account()
    assert e.value.kind == "unavailable" and SECRET not in str(e.value)


# --- routes -------------------------------------------------------------------------------------------------------------------------------
PREVIEW = {"order": {"broker": "alpaca-paper", "symbol": "AAPL", "side": "buy", "qty": 1, "type": "market"}}


def test_routes_status_lists_only_the_paper_broker(client):
    s = client.get("/api/orders/status").json()
    assert "live_enabled" not in s and s["kill"]["on"] is False and s["trades_today"] == 0
    assert [(b["id"], b["slot_mode"]) for b in s["brokers"]] == [("alpaca-paper", "paper")]
    assert not s["brokers"][0]["ready"] and "KEY REQUIRED" in s["brokers"][0]["message"]  # zero keys: KEY REQUIRED, never a crash


def test_routes_refuse_a_non_loopback_client(client):
    from fastapi.testclient import TestClient

    other = TestClient(client.app, client=("203.0.113.9", 5))
    for method, path in (("GET", "/api/orders/status"), ("GET", "/api/orders/blotter"), ("GET", "/api/orders/ledger"),("POST", "/api/orders/preview"), ("POST", "/api/orders/submit"),
                         ("POST", "/api/orders/cancel"), ("POST", "/api/orders/kill"), ("POST", "/api/orders/unkill"), ("PUT", "/api/orders/mandate"),
                         ("POST", "/api/orders/import")):
        r = other.request(method, path, json={})
        assert r.status_code == 403, path
    assert client.get("/api/orders/status").status_code == 200


def test_routes_never_accept_a_mode_and_errors_are_typed(client):
    r = client.post("/api/orders/preview", json={"order": {**PREVIEW["order"], "mode": "live"}})
    assert r.status_code == 400 and "NEVER SET BY A REQUEST" in r.json()["error"]
    r = client.post("/api/orders/preview", json=PREVIEW)
    assert r.json()["kind"] == "key_required" and "ALPACA_PAPER_KEY_ID" in r.json()["error"]  # no keys: the answer says which key to set
    assert client.put("/api/orders/live", json={"on": True}).status_code in (404, 405)  # the live switch is gone
    assert client.post("/api/orders/submit", json={"order": {}, "token": "x", "mode": "live"}).status_code == 400


def test_kill_switch_over_http_persists_and_blocks_and_unkill_restores(client):
    assert client.post("/api/orders/kill").json()["kill"]["on"] is True
    assert client.get("/api/orders/status").json()["kill"]["on"] is True
    r = client.post("/api/orders/preview", json=PREVIEW)
    assert r.json()["kind"] == "kill_switch"
    assert client.post("/api/orders/unkill").json()["kill"]["on"] is False


# --- the AI can never reach an order ------------------------------------------------------------------------------------------------------
def test_no_ai_or_mcp_tool_points_at_an_order_route():
    from openterm.ai import tools
    from openterm.mcp import server

    for t in tools.REGISTRY.values():
        assert "/api/orders" not in t.path.lower() and not t.path.startswith("/api/sync"), t.name
    for t in server.exposed_tools():
        assert "/api/orders" not in t.path, t.name


def test_ai_and_agent_code_never_imports_or_names_the_order_package():
    root = Path(__file__).parents[1] / "openterm"
    seen = 0
    for pkg in ("ai", "mcp"):
        for f in (root / pkg).rglob("*.py"):
            text = f.read_text(encoding="utf-8")
            if pkg == "ai" and f.name == "tools.py":
                text = text.replace('"/api/orders" in str(spec["path"])', "")  # the guard itself names the path
            assert not re.search(r"openterm\.orders|from \.\.orders|from \.\.\.orders|/api/orders", text), f
            seen += 1
    assert seen > 5


async def test_the_tool_runner_refuses_a_route_under_api_orders(client, monkeypatch):
    from openterm.ai import tools

    evil = tools.Tool("evil_probe", "probe", tools.obj({}), "/api/orders/kill", method="POST")
    monkeypatch.setitem(tools.REGISTRY, "evil_probe", evil)
    res = await tools.ToolRunner(client.app).call("evil_probe", {})
    assert not res.ok and "NOT ALLOWED" in res.text
    assert client.get("/api/orders/status").json()["kill"]["on"] is False
