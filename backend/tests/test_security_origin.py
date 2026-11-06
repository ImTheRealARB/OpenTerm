"""Audit D-2: a web page on another site must not be able to change anything or open the socket."""

import pytest
from starlette.websockets import WebSocketDisconnect

from openterm.origin import origin_ok

EVIL = {"Origin": "https://evil.example"}


@pytest.mark.parametrize("origin,ok", [
    (None, True), ("http://localhost:5173", True), ("http://localhost:8000", True), ("http://127.0.0.1:8000", True),
    ("http://[::1]:5173", True), ("http://localhost", True),
    ("https://evil.example", False), ("http://localhost.evil.example", False), ("null", False), ("http://127.0.0.1.evil.example", False),
])
def test_origin_allowlist(origin, ok):
    assert origin_ok(origin) is ok


@pytest.mark.parametrize("method,path", [
    ("post", "/api/delivery/test"), ("post", "/api/ai/chat"), ("post", "/api/bt/run"), ("put", "/api/settings"),
    ("delete", "/api/jobs"), ("post", "/mcp"),
])
def test_foreign_origin_cannot_change_anything(client, method, path):
    r = client.request(method.upper(), path, content=b'{"x": 1}', headers={**EVIL, "Content-Type": "text/plain"})
    assert r.status_code == 403
    assert "ORIGIN" in r.text


def test_local_origin_still_works(client):
    # The Vite dev server (5173) and the served app (8000) both send these Origins on their POSTs.
    for origin in ("http://localhost:5173", "http://localhost:8000", "http://127.0.0.1:8000"):
        r = client.put("/api/layouts/a", json={"panels": []}, headers={"Origin": origin})
        assert r.status_code != 403, origin


def test_reads_are_not_blocked_by_origin(client):
    # A GET carries no side effects and the app sends no Origin on same-origin GETs; only changes are guarded.
    assert client.get("/api/health", headers=EVIL).status_code == 200


def test_json_routes_demand_a_json_content_type(client):
    r = client.post("/api/bt/run", content=b'{"symbols": ["SYN0001"]}', headers={"Content-Type": "text/plain"})
    assert r.status_code == 400 and "CONTENT-TYPE" in r.text
    r = client.post("/api/ai/chat", content=b'{"question": "hi"}', headers={"Content-Type": "text/plain"})
    assert r.status_code == 400 and "CONTENT-TYPE" in r.text


def test_websocket_refuses_a_foreign_origin(client):
    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws", headers=EVIL):
        pass


def test_websocket_accepts_local_and_originless(client):
    with client.websocket_connect("/ws", headers={"Origin": "http://localhost:5173"}) as ws:
        ws.send_text('["ping", 1]')
        assert ws.receive_json()[0] == "pong"
    with client.websocket_connect("/ws") as ws:
        ws.send_text('["ping", 2]')
        assert ws.receive_json()[0] == "pong"


def test_hidden_secret_in_dotenv_is_redacted_from_startup(tmp_path):
    """Audit D-5: a Kite access token sitting in .env is registered for redaction as soon as the store is built."""
    from openterm import redact
    from openterm.keys import KeyStore

    env_file = tmp_path / "k.env"
    env_file.write_text("KITE_ACCESS_TOKEN=tok-abcdef-123456\n")
    KeyStore({}, env_file)
    assert "tok-abcdef-123456" not in redact.redact("error: tok-abcdef-123456 refused")


def test_every_provider_with_set_keys_is_refreshed_on_key_change(client):
    calls = []
    prov = client.app.state.service.router.providers
    target = next(p for p in prov.values() if hasattr(p, "set_keys"))
    target.set_keys = lambda values: calls.append(values)  # type: ignore[method-assign]
    client.app.state.on_key_change(target.name)
    assert calls, "on_key_change must reach every provider that has set_keys"
