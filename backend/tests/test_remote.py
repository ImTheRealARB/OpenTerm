"""Self-hosted remote mode (openterm/remote.py). The trap: behind the same-host proxy every request comes from 127.0.0.1."""

import inspect
import re
import stat

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from openterm import http_util, remote
from openterm.remote import COOKIE, RemoteAuth

ORIGIN = "https://term.example.com"
GOOD_ORIGIN = {"Origin": ORIGIN}
LOCAL_ORIGIN = {"Origin": "http://localhost:8000"}
LOGIN_OPEN = {("GET", "/login"), ("POST", "/api/remote/login")}


@pytest.fixture
def rclient(client, tmp_path, monkeypatch):
    """The app in remote mode, reached the way the proxy reaches it: from 127.0.0.1, over https. No session yet."""
    monkeypatch.setenv("OPENTERM_REMOTE", "1")
    monkeypatch.setenv("OPENTERM_PUBLIC_ORIGIN", ORIGIN)
    from openterm.main import app

    with TestClient(app, client=("127.0.0.1", 50000), base_url="https://term.example.com") as c:
        c.token_file = tmp_path / TOKEN_FILE_NAME
        yield c


TOKEN_FILE_NAME = remote.TOKEN_FILE


def new_token(c) -> str:
    return c.app.state.remote.rotate()


def login(c, token) -> object:
    return c.post("/api/remote/login", json={"token": token}, headers=GOOD_ORIGIN)


@pytest.fixture
def session(rclient):
    """A logged-in client (cookie kept by the client) and the token."""
    token = new_token(rclient)
    r = login(rclient, token)
    assert r.status_code == 200, r.text
    rclient.token = token
    return rclient


# ---------------------------------------------------------------- off by default

def test_without_the_switch_nothing_changes(client):
    assert not remote.enabled()
    assert client.get("/api/health").status_code == 200
    assert http_util.loopback(type("R", (), {"client": type("C", (), {"host": "127.0.0.1"})()})()) is True
    assert client.get("/login").status_code == 404
    assert client.post("/api/remote/login", json={"token": "x"}).status_code == 404
    assert getattr(client.app.state, "remote", None) is None


def test_remote_mode_refuses_to_start_without_a_public_https_origin(client, monkeypatch):
    from openterm.main import app

    monkeypatch.setenv("OPENTERM_REMOTE", "1")
    for bad in ("", "http://term.example.com", "https://", "https://a.example/path", "term.example.com"):
        monkeypatch.setenv("OPENTERM_PUBLIC_ORIGIN", bad)
        with pytest.raises(RuntimeError, match="OPENTERM_PUBLIC_ORIGIN"), TestClient(app):
            pass


# ---------------------------------------------------------------- the token

def test_the_token_is_made_once_printed_once_and_stored_only_hashed(tmp_path, capsys):
    a = RemoteAuth(tmp_path)
    token = a.ensure_token()
    assert token and len(token) >= 43  # token_urlsafe(32)
    assert a.ensure_token() is None  # second start: nothing new, nothing shown
    f = tmp_path / remote.TOKEN_FILE
    assert stat.S_IMODE(f.stat().st_mode) == 0o600
    assert token not in f.read_text()
    assert a.login(token) and a.login("wrong") is None
    remote.announce(token, f)
    err = capsys.readouterr().err
    assert token in err and "shown once" in err


def test_the_app_prints_the_token_on_first_start_only(client, tmp_path, monkeypatch, capsys):
    from openterm.main import app

    monkeypatch.setenv("OPENTERM_REMOTE", "1")
    monkeypatch.setenv("OPENTERM_PUBLIC_ORIGIN", ORIGIN)
    with TestClient(app):
        first = capsys.readouterr().err
    m = re.search(r"\(shown once\): (\S+)", first)
    assert m
    with TestClient(app) as c:
        assert "shown once" not in capsys.readouterr().err
        assert c.post("/api/remote/login", json={"token": m.group(1)}, headers=GOOD_ORIGIN).status_code == 200


def test_login_uses_a_constant_time_compare(monkeypatch, tmp_path):
    calls = []
    real = remote.hmac.compare_digest
    monkeypatch.setattr(remote.hmac, "compare_digest", lambda a, b: calls.append(1) or real(a, b))
    a = RemoteAuth(tmp_path)
    a.login(a.rotate())
    assert calls


def test_rotation_ends_every_session(tmp_path):
    a = RemoteAuth(tmp_path)
    old = a.rotate()
    sid = a.login(old)
    assert a.valid(sid)
    new = a.rotate()
    assert not a.valid(sid) and a.login(old) is None and a.valid(a.login(new))
    # a rotation by another process (the CLI) writes the file: this one notices without a restart
    other = RemoteAuth(tmp_path)
    sid2 = a.login(new)
    third = other.rotate()
    assert not a.valid(sid2) and a.login(new) is None and a.login(third)


def test_cli_rotate_needs_no_arguments_besides_rotate(capsys):
    assert remote.main([]) == 2


# ---------------------------------------------------------------- login, cookie, logout

def test_login_sets_a_hardened_cookie_and_logout_ends_it(rclient):
    token = new_token(rclient)
    r = login(rclient, token)
    assert r.status_code == 200
    cookie = r.headers["set-cookie"]
    for part in ("HttpOnly", "Secure", "SameSite=Strict", "Path=/", f"{COOKIE}="):
        assert part in cookie
    assert "Domain" not in cookie and "Max-Age=" in cookie
    sid = re.search(rf"{COOKIE}=([^;]+)", cookie).group(1)
    assert len(sid) >= 43 and sid != token
    assert rclient.get("/api/remote/session").json() == {"remote": True, "authenticated": True}
    out = rclient.post("/api/remote/logout", headers=GOOD_ORIGIN)
    assert out.status_code == 200 and "Max-Age=0" in out.headers["set-cookie"]
    rclient.cookies.clear()
    rclient.cookies.set(COOKIE, sid, domain="term.example.com")  # the old cookie, replayed
    assert rclient.get("/api/remote/session").status_code == 401


def test_each_login_gets_a_new_random_session_id(rclient):
    token = new_token(rclient)
    ids = set()
    for _ in range(3):
        c = TestClient(rclient.app, client=("127.0.0.1", 1), base_url="https://term.example.com")
        ids.add(re.search(rf"{COOKIE}=([^;]+)", login(c, token).headers["set-cookie"]).group(1))
    assert len(ids) == 3


def test_a_session_expires(rclient, monkeypatch):
    token = new_token(rclient)
    login(rclient, token)
    assert rclient.get("/api/remote/session").status_code == 200
    real = remote.time.time
    monkeypatch.setattr(remote.time, "time", lambda: real() + remote.SESSION_TTL_S + 5)
    assert rclient.get("/api/remote/session").status_code == 401


def test_wrong_token_and_junk_are_refused(rclient):
    new_token(rclient)
    for body in ({"token": "nope"}, {"token": 5}, {"token": ""}, {}):
        assert rclient.post("/api/remote/login", json=body, headers=GOOD_ORIGIN).status_code == 401
    assert COOKIE not in rclient.cookies


def test_failed_logins_are_rate_limited_even_for_the_right_token(rclient):
    token = new_token(rclient)
    for _ in range(remote.FAIL_LIMIT):
        assert login(rclient, "wrong").status_code == 401
    r = login(rclient, token)
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0
    assert rclient.get("/api/remote/session").status_code == 401
    rclient.app.state.remote.fails.clear()  # the window passing
    assert login(rclient, token).status_code == 200


def test_login_needs_the_public_origin_and_json(rclient):
    token = new_token(rclient)
    for hdr in ({"Origin": "https://evil.example"}, LOCAL_ORIGIN, {"Origin": "null"}):
        r = rclient.post("/api/remote/login", json={"token": token}, headers=hdr)
        assert r.status_code == 403 and "ORIGIN" in r.text
    assert rclient.post("/api/remote/login", content=b'{"token": "x"}', headers={**GOOD_ORIGIN, "Content-Type": "text/plain"}).status_code == 400


# ---------------------------------------------------------------- the gate

def test_the_login_page_is_open_and_self_contained(rclient):
    r = rclient.get("/login")
    assert r.status_code == 200 and "OPENTERM ACCESS TOKEN" in r.text
    assert "src=" not in r.text and "default-src 'none'" in r.headers["content-security-policy"]


def test_a_browser_page_request_without_a_session_goes_to_login_but_the_api_gets_401(rclient):
    r = rclient.get("/", headers={"Accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/login"
    r = rclient.get("/api/health", headers={"Accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 401 and r.json()["kind"] == "login_required"


def _fill(path: str) -> str:
    return re.sub(r"\{[^}:]+(:[^}]+)?\}", "1", path)


def _flat(routes, prefix=""):
    """Every concrete route, looking inside the included routers (this FastAPI keeps them nested)."""
    for r in routes:
        inner = getattr(r, "original_router", None)
        if inner is not None:
            yield from _flat(inner.routes, prefix + r.include_context.prefix)
        else:
            yield prefix, r


def _routes(app):
    for prefix, r in _flat(app.routes):
        if hasattr(r, "methods") and hasattr(r, "endpoint"):
            for m in sorted((r.methods or set()) - {"HEAD", "OPTIONS"}):
                yield r, m, _fill(prefix + r.path)


def _sockets(app):
    return [prefix + r.path for prefix, r in _flat(app.routes) if r.__class__.__name__.endswith("WebSocketRoute")]


def test_there_are_routes_to_walk(client):
    assert len(list(_routes(client.app))) > 150


def test_every_route_needs_a_session_in_remote_mode(rclient):
    """Walks the real route table: nothing but the login page and login call answers a visitor with no session."""
    leaks = []
    for _route, method, path in _routes(rclient.app):
        if (method, path) in LOGIN_OPEN:
            continue
        r = rclient.request(method, path, json={}, headers=GOOD_ORIGIN)
        if r.status_code not in (401, 403):
            leaks.append((method, path, r.status_code))
    assert not leaks, leaks
    assert rclient.get("/anything-else-or-static").status_code == 401


def test_every_websocket_needs_a_session_in_remote_mode(rclient):
    sockets = _sockets(rclient.app)
    assert "/ws" in sockets
    for path in sockets:
        with pytest.raises(WebSocketDisconnect), rclient.websocket_connect(path, headers=GOOD_ORIGIN):
            pass


def test_a_websocket_works_with_a_session_from_the_proxy_and_still_checks_origin(session):
    cookie = {"Cookie": f"{COOKIE}={session.cookies.get(COOKIE)}"}  # the test client would not send a Secure cookie on ws://
    with session.websocket_connect("/ws", headers={**GOOD_ORIGIN, **cookie}) as ws:
        ws.send_text('["ping", 1]')
        assert ws.receive_json()[0] == "pong"
    for bad in ({"Origin": "https://evil.example"}, LOCAL_ORIGIN):
        with pytest.raises(WebSocketDisconnect), session.websocket_connect("/ws", headers={**bad, **cookie}):
            pass


def test_a_session_cookie_from_another_origin_cannot_change_anything(session):
    r = session.put("/api/layouts/a", json={"panels": []}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and "ORIGIN" in r.text
    assert session.put("/api/layouts/a", json={"panels": []}, headers=GOOD_ORIGIN).status_code != 403


def test_ordinary_data_routes_work_with_a_session(session):
    assert session.get("/api/health").status_code == 200


# ---------------------------------------------------------------- loopback is never trusted remotely

def _loopback_routes(app):
    """Every route whose handler (through its decorators) calls loopback(), found from the source, not from a hand-kept list."""
    found = []
    for route, method, path in _routes(app):
        layer, srcs = route.endpoint, []
        while layer is not None:  # every decorator layer too: a guard decorator (orders' `guarded`) calls loopback() in its wrapper
            try:
                srcs.append(inspect.getsource(getattr(layer, "__code__", layer)))  # __code__: getsource() would unwrap to the inner function
            except (OSError, TypeError):
                pass
            layer = getattr(layer, "__wrapped__", None)
        if any(re.search(r"\b(loopback|_body|_guard)\(request", src) for src in srcs):
            found.append((method, path))
    return found


def test_the_walk_finds_the_loopback_only_routes(client):
    found = _loopback_routes(client.app)
    assert len(found) >= 40
    for must in (("POST", "/api/ai/chat"), ("POST", "/mcp"), ("PUT", "/api/keys/1"), ("POST", "/api/ext/1/enable"),
                 ("POST", "/api/orders/submit"), ("PUT", "/api/orders/live"), ("POST", "/api/orders/kill"), ("POST", "/api/sync/kite"),
                 ("POST", "/api/journal/import")):
        assert must in found, must


def test_loopback_only_routes_are_refused_even_from_127_0_0_1_with_a_valid_session(session):
    refused, wrong = [], []
    for method, path in _loopback_routes(session.app):
        r = session.request(method, path, json={}, headers=GOOD_ORIGIN)
        (refused if r.status_code in (403, 401) else wrong).append((method, path, r.status_code))
    assert not wrong, wrong
    assert refused


def test_loopback_is_false_for_everyone_in_remote_mode(rclient):
    class Req:
        def __init__(self, host):
            self.client = type("C", (), {"host": host})()

    for host in ("127.0.0.1", "::1", "localhost", "203.0.113.9"):
        assert http_util.loopback(Req(host)) is False


def test_forwarded_headers_never_make_a_request_local(session):
    hdrs = {**GOOD_ORIGIN, "X-Forwarded-For": "127.0.0.1", "X-Real-IP": "127.0.0.1", "Forwarded": "for=127.0.0.1"}
    assert session.put("/api/keys/fred", json={}, headers=hdrs).status_code == 403
    assert session.post("/api/ext/hello/enable", headers=hdrs).status_code == 403


def test_the_mcp_endpoint_is_refused_in_remote_mode_with_or_without_a_session(rclient):
    msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    assert rclient.post("/mcp", json=msg).status_code == 403  # refused before the session is even asked about
    token = new_token(rclient)
    login(rclient, token)
    r = rclient.post("/mcp", json=msg)
    assert r.status_code == 403
    assert rclient.get("/mcp").status_code == 403


def test_extensions_cannot_be_enabled_remotely_but_can_be_listed(session):
    assert session.post("/api/ext/hello/enable", headers=GOOD_ORIGIN).status_code == 403
    assert session.get("/api/ext").status_code == 200


def test_local_mode_still_allows_loopback_after_remote_mode_was_on(client):
    r = client.post("/api/ext/nope/enable")
    assert r.status_code == 404  # not found, not "FORBIDDEN: THIS MACHINE ONLY"
