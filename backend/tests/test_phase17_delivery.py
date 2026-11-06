"""Phase 17 B: alert delivery (email, Telegram, webhook), its settings, log and TLS rules. No network.

Real send paths are exercised through `app.state.delivery_senders` (an override that calls the real
channel code with a fake SMTP connection or a fake HTTP transport), because fixture mode never sends.
"""

import asyncio
import json
import ssl
import time
from typing import ClassVar

import httpx
import pytest
from fastapi.testclient import TestClient

from openterm import delivery
from openterm.delivery import email as dmail
from openterm.delivery import format as dfmt
from openterm.delivery import log as dlog
from openterm.delivery import telegram, webhook
from openterm.delivery.settings import defaults, public, validate
from openterm.userdata import UserDataError

SMTP_KEYS = {"SMTP_HOST": "smtp.example.com", "SMTP_PORT": "587", "SMTP_USER": "me@example.com",
             "SMTP_PASSWORD": "hunter2-secret-pass"}


@pytest.fixture(autouse=True)
def no_retry_wait(monkeypatch):
    # Phase 20: retries run in the background after 30 s / 2 min / 10 min; tests skip the waiting.
    async def instant(_seconds):
        return None

    monkeypatch.setattr(delivery, "sleep", instant)


# --- helpers ---
class FakeSMTP:
    """Stands in for a logged-in smtplib connection: remembers the messages it was asked to send."""

    sent: ClassVar[list] = []

    def __init__(self, *a, **k):
        pass

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)

    def close(self):
        pass


def fake_email_sender():
    """The REAL email code path (message building, threading) with the SMTP connection faked."""
    FakeSMTP.sent = []

    async def sender(app, values, cfg, subject, text, extra):
        await asyncio.to_thread(dmail.send_sync, values, cfg["email_to"], subject, text, lambda *a: FakeSMTP())

    return sender


def configure(client, channels=("email",), **extra):
    r = client.put("/api/delivery", json={"channels": dict.fromkeys(channels, True),
                                          "email_to": "me@example.com", "telegram_chat_id": "12345", **extra})
    assert r.status_code == 200, r.text


def new_alert(client, symbol="SYN0001", value=100):
    r = client.post("/api/alerts", json={"symbol": symbol, "op": ">", "value": value})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def wait_rows(client, n, timeout=5.0):
    """Delivery runs in a background task, so poll the log until it has n rows (or time out)."""
    end = time.time() + timeout
    rows = []
    while time.time() < end:
        rows = client.get("/api/delivery/log").json()["deliveries"]
        if len(rows) >= n:
            return rows
        time.sleep(0.05)
    return rows


# --- settings ---
def test_settings_default_off(client):
    d = client.get("/api/delivery").json()
    assert d["settings"] == public(defaults())
    assert not any(d["settings"]["channels"].values())
    assert d["settings"]["brief"] == {"enabled": False, "time": "08:30", "days": "mon-fri", "tz": ""}
    assert set(d["status"].values()) == {"off"}


@pytest.mark.parametrize("body", [
    {"channels": {"fax": True}}, {"channels": {"email": "yes"}}, {"email_to": "not an email"},
    {"telegram_chat_id": "abc"}, {"nope": 1}, {"brief": {"time": "25:00"}}, {"brief": {"days": "weekends"}},
    {"brief": {"tz": "Mars/Base"}}, {"brief": {"enabled": "yes"}}, {"brief": {"extra": 1}}, ["list"],
])
def test_settings_validation_errors(client, body):
    r = client.put("/api/delivery", json=body)
    assert r.status_code == 400, r.text
    assert client.get("/api/delivery").json()["settings"] == public(defaults())  # nothing was stored


def test_settings_roundtrip_and_partial_merge(client):
    configure(client, ("email",), brief={"enabled": True, "time": "07:15", "days": "daily", "tz": "Asia/Kolkata"})
    client.put("/api/delivery", json={"channels": {"telegram": True}})  # merges, does not wipe email
    s = client.get("/api/delivery").json()["settings"]
    assert s["channels"]["email"] and s["channels"]["telegram"] and not s["channels"]["webhook"]
    assert s["brief"]["time"] == "07:15" and s["recipients"]["email"] == {"configured": True, "hint": "m•••@example.com"}
    assert "email_to" not in s and "telegram_chat_id" not in s  # Phase 20: never sent to the browser


def test_validate_is_pure():
    cur = defaults()
    validate({"email_to": "a@b.co"}, cur)
    assert cur == defaults()
    with pytest.raises(UserDataError):
        validate({"brief": {"time": "7:5"}})


def test_put_and_test_need_loopback(client):
    remote = TestClient(client.app, client=("10.1.2.3", 40000))
    assert remote.put("/api/delivery", json={"channels": {"email": True}}).status_code == 403
    assert remote.post("/api/delivery/test", json={"channel": "email"}).status_code == 403
    assert remote.get("/api/delivery").status_code == 200  # reading is fine
    assert client.get("/api/delivery").json()["settings"]["channels"]["email"] is False


# --- triggering ---
def test_all_channels_off_logs_nothing(client):
    client.app.state.delivery_senders = {"email": fake_email_sender()}
    aid = new_alert(client)
    assert client.post(f"/api/alerts/{aid}/trigger", json={"price": 101}).json()["changed"] is True
    time.sleep(0.3)
    assert client.get("/api/delivery/log").json()["deliveries"] == []
    assert FakeSMTP.sent == []


def test_alert_email_sent_once_with_symbol_and_price(client):
    client.app.state.keys.set("smtp", SMTP_KEYS)
    client.app.state.delivery_senders = {"email": fake_email_sender()}
    configure(client)
    aid = new_alert(client, "SYN0007", 100)
    for _ in range(2):  # a second tab reporting the same firing must not deliver again
        client.post(f"/api/alerts/{aid}/trigger", json={"price": 101.5})
    rows = wait_rows(client, 1)
    time.sleep(0.3)
    rows = client.get("/api/delivery/log").json()["deliveries"]
    assert len(rows) == 1
    assert rows[0]["status"] == "sent" and rows[0]["channel"] == "email" and rows[0]["kind"] == "alert"
    assert len(FakeSMTP.sent) == 1
    msg = FakeSMTP.sent[0]
    body = msg.get_content()
    assert "SYN0007" in msg["Subject"] and "SYN0007" in body and "101.5" in body
    assert msg["To"] == "me@example.com" and msg["From"] == "me@example.com"


def test_news_alert_delivers(client):
    client.app.state.keys.set("smtp", SMTP_KEYS)
    client.app.state.delivery_senders = {"email": fake_email_sender()}
    configure(client)
    r = client.post("/api/newsalerts", json={"word": "merger"})
    aid = r.json()["id"]
    client.post(f"/api/newsalerts/{aid}/trigger", json={"headline": "Big merger announced", "url": "https://x.example/a"})
    rows = wait_rows(client, 1)
    assert rows[0]["kind"] == "news" and rows[0]["status"] == "sent"
    assert "Big merger announced" in FakeSMTP.sent[0].get_content()


def test_missing_key_is_skipped_with_key_required(client):
    configure(client, ("email", "telegram", "webhook"))
    aid = new_alert(client)
    client.post(f"/api/alerts/{aid}/trigger", json={"price": 101})
    rows = wait_rows(client, 3)
    assert {r["channel"] for r in rows} == {"email", "telegram", "webhook"}
    assert all(r["status"] == "skipped" for r in rows)
    by = {r["channel"]: r["detail"] for r in rows}
    assert by["telegram"] == "KEY REQUIRED: set TELEGRAM_BOT_TOKEN in APIKEYS"
    assert by["webhook"] == "KEY REQUIRED: set ALERT_WEBHOOK_URL in APIKEYS"
    assert by["email"].startswith("KEY REQUIRED: set SMTP_HOST")
    assert client.get("/api/delivery").json()["status"]["email"].startswith("KEY REQUIRED")


def test_fixture_mode_never_sends(client):
    client.app.state.keys.set("telegram", {"TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwx"})
    configure(client, ("telegram",))
    aid = new_alert(client)
    client.post(f"/api/alerts/{aid}/trigger", json={"price": 101})
    rows = wait_rows(client, 1)
    assert rows[0]["status"] == "skipped" and rows[0]["detail"] == "FIXTURE MODE"


def test_missing_recipient_is_skipped(client):
    client.app.state.keys.set("smtp", SMTP_KEYS)
    client.app.state.delivery_senders = {"email": fake_email_sender()}
    client.put("/api/delivery", json={"channels": {"email": True}})  # no email_to
    aid = new_alert(client)
    client.post(f"/api/alerts/{aid}/trigger", json={"price": 101})
    rows = wait_rows(client, 1)
    assert rows[0]["status"] == "skipped" and "email_to" in rows[0]["detail"]


# --- channels ---
def test_telegram_through_mock_transport(client):
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append((str(req.url), json.loads(req.content)))
        return httpx.Response(200, json={"ok": True})

    client.app.state.keys_http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client.app.state.keys.set("telegram", {"TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwx"})
    client.app.state.delivery_senders = {"telegram": telegram.send}
    configure(client, ("telegram",))
    aid = new_alert(client, "SYN0003")
    client.post(f"/api/alerts/{aid}/trigger", json={"price": 55})
    rows = wait_rows(client, 1)
    assert rows[0]["status"] == "sent"
    url, body = seen[0]
    assert url.endswith("/sendMessage") and body["chat_id"] == "12345" and "SYN0003" in body["text"]
    assert "abcdefghijklmnopqrstuvwx" not in json.dumps(rows)  # the token never reaches the log


def test_telegram_http_error_is_failed_and_redacted(client):
    client.app.state.keys_http = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda req: httpx.Response(401, json={"ok": False, "description": "Unauthorized"})))
    client.app.state.keys.set("telegram", {"TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwx"})
    client.app.state.delivery_senders = {"telegram": telegram.send}
    configure(client, ("telegram",))
    r = client.post("/api/delivery/test", json={"channel": "telegram"}).json()["results"][0]
    assert r["status"] == "failed" and "401" in r["detail"]


def test_webhook_url_rules(monkeypatch):
    monkeypatch.delenv(webhook.ALLOW_LOCAL_ENV, raising=False)
    assert webhook.check_url("https://hooks.example.com/x")
    for bad in ("http://hooks.example.com/x", "ftp://x.example/a", "hooks.example.com", "https://",
                # audit D-4: nothing inside this machine or its network, with or without the local-receiver switch
                "http://127.0.0.1:9000/x", "http://localhost/x", "https://localhost/x", "https://127.0.0.1/x",
                "https://192.168.1.10/x", "https://10.0.0.5/x", "https://172.16.3.4/x", "https://[::1]/x",
                "https://169.254.169.254/latest/meta-data", "https://printer.local/x", "https://0.0.0.0/x"):
        with pytest.raises(delivery.DeliveryError):
            webhook.check_url(bad)


def test_webhook_local_receiver_needs_the_switch_and_never_this_app(monkeypatch):
    monkeypatch.setenv(webhook.ALLOW_LOCAL_ENV, "1")
    assert webhook.check_url("http://127.0.0.1:9000/x")
    assert webhook.check_url("http://localhost:5678/hook")
    for bad in ("http://127.0.0.1:8000/api/delivery/test", "http://localhost:8000/x", "https://192.168.1.10/x"):
        with pytest.raises(delivery.DeliveryError):
            webhook.check_url(bad)


def test_webhook_http_non_loopback_refused_and_logged(client):
    client.app.state.keys.set("webhook", {"ALERT_WEBHOOK_URL": "http://hooks.example.com/abc123secret"})
    client.app.state.delivery_senders = {"webhook": webhook.send}
    configure(client, ("webhook",))
    r = client.post("/api/delivery/test", json={"channel": "webhook"}).json()["results"][0]
    assert r["status"] == "failed" and "https" in r["detail"]


def test_webhook_posts_json(client):
    seen = []

    def handler(req):
        seen.append(json.loads(req.content))
        return httpx.Response(204)

    client.app.state.keys_http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client.app.state.keys.set("webhook", {"ALERT_WEBHOOK_URL": "https://hooks.example.com/abc123secret"})
    client.app.state.delivery_senders = {"webhook": webhook.send}
    configure(client, ("webhook",))
    aid = new_alert(client, "SYN0009")
    client.post(f"/api/alerts/{aid}/trigger", json={"price": 7})
    assert wait_rows(client, 1)[0]["status"] == "sent"
    assert seen[0]["kind"] == "alert" and "SYN0009" in seen[0]["text"] and seen[0]["content"] == seen[0]["text"]


def test_webhook_key_test_checks_shape_only(client):
    client.app.state.keys.set("webhook", {"ALERT_WEBHOOK_URL": "http://hooks.example.com/abc123secret"})
    r = client.post("/api/keys/webhook/test")
    assert r.status_code == 200 and r.json()["state"] == "INVALID"


# --- retry, timeout, redaction ---
def test_network_error_is_retried_in_the_background_then_sent(client):
    client.app.state.keys.set("smtp", SMTP_KEYS)
    calls = []

    async def flaky(app, values, cfg, subject, text, extra):
        calls.append(1)
        if len(calls) == 1:
            raise ConnectionResetError("blip")

    client.app.state.delivery_senders = {"email": flaky}
    configure(client)
    r = client.post("/api/delivery/test", json={"channel": "email"}).json()["results"][0]
    assert r["status"] == "retrying"  # the caller is answered after the first attempt, not after the retries
    end = time.time() + 5
    while time.time() < end and client.get("/api/delivery/log").json()["deliveries"][0]["status"] != "sent":
        time.sleep(0.05)
    assert client.get("/api/delivery/log").json()["deliveries"][0]["status"] == "sent" and len(calls) == 2


def test_non_network_error_is_not_retried(client):
    client.app.state.keys.set("smtp", SMTP_KEYS)
    calls = []

    async def bad(app, values, cfg, subject, text, extra):
        calls.append(1)
        raise delivery.DeliveryError("SMTP SERVER OFFERS NO TLS")

    client.app.state.delivery_senders = {"email": bad}
    configure(client)
    r = client.post("/api/delivery/test", json={"channel": "email"}).json()["results"][0]
    assert r["status"] == "failed" and r["detail"] == "SMTP SERVER OFFERS NO TLS" and len(calls) == 1


def test_password_in_error_is_redacted_and_truncated(client):
    client.app.state.keys.set("smtp", SMTP_KEYS)

    async def leaky(app, values, cfg, subject, text, extra):
        raise RuntimeError(f"login failed for password {SMTP_KEYS['SMTP_PASSWORD']} " + "x" * 600)

    client.app.state.delivery_senders = {"email": leaky}
    configure(client)
    client.post("/api/delivery/test", json={"channel": "email"})
    detail = client.get("/api/delivery/log").json()["deliveries"][0]["detail"]
    assert SMTP_KEYS["SMTP_PASSWORD"] not in detail
    assert len(detail) <= 300 and detail.startswith("RuntimeError")


def test_log_keeps_only_the_newest_rows(client, monkeypatch):
    monkeypatch.setattr(dlog, "KEEP", 5)
    client.app.state.keys.set("smtp", SMTP_KEYS)
    client.app.state.delivery_senders = {"email": fake_email_sender()}
    configure(client)
    for _ in range(8):
        client.post("/api/delivery/test", json={"channel": "email"})
    rows = client.get("/api/delivery/log").json()["deliveries"]
    assert len(rows) == 5  # exactly KEEP rows remain, the newest ones
    assert rows[0]["id"] > rows[-1]["id"]


def test_log_constant_is_500():
    assert dlog.KEEP == 500 and dlog.DETAIL_MAX == 300


# --- /api/delivery/test ---
def test_test_route_validates_channel_and_ignores_the_switch(client):
    client.app.state.keys.set("smtp", SMTP_KEYS)
    client.app.state.delivery_senders = {"email": fake_email_sender()}
    assert client.post("/api/delivery/test", json={"channel": "fax"}).status_code == 400
    assert client.post("/api/delivery/test", json={}).status_code == 400
    client.put("/api/delivery", json={"email_to": "me@example.com"})  # channel stays OFF
    r = client.post("/api/delivery/test", json={"channel": "email"}).json()["results"][0]
    assert r["status"] == "sent" and len(FakeSMTP.sent) == 1
    row = client.get("/api/delivery/log").json()["deliveries"][0]
    assert row["kind"] == "test" and row["channel"] == "email"


# --- SMTP TLS helper ---
class TlsSMTP:
    """Fake smtplib.SMTP / SMTP_SSL that records what smtp_connect did to it."""

    offers_starttls = True
    cert_error = False
    instances: ClassVar[list] = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port, self.context = host, port, context
        self.calls = []
        TlsSMTP.instances.append(self)
        if TlsSMTP.cert_error and context is not None:  # SMTP_SSL does its handshake in the constructor
            raise ssl.SSLCertVerificationError("bad cert")

    def ehlo(self):
        self.calls.append("ehlo")

    def has_extn(self, name):
        return name == "starttls" and TlsSMTP.offers_starttls

    def starttls(self, context=None):
        self.calls.append("starttls")
        self.context = context
        if TlsSMTP.cert_error:
            raise ssl.SSLCertVerificationError("bad cert")

    def login(self, user, password):
        self.calls.append("login")

    def close(self):
        self.calls.append("close")


@pytest.fixture
def tls(monkeypatch):
    TlsSMTP.offers_starttls, TlsSMTP.cert_error, TlsSMTP.instances = True, False, []
    monkeypatch.setattr(dmail.smtplib, "SMTP", TlsSMTP)
    monkeypatch.setattr(dmail.smtplib, "SMTP_SSL", TlsSMTP)
    return TlsSMTP


def test_smtp_starttls_with_a_verifying_context(tls):
    s = dmail.smtp_connect("smtp.example.com", 587, "u", "p", 5)
    assert "starttls" in s.calls and "login" in s.calls
    assert s.context.verify_mode == ssl.CERT_REQUIRED and s.context.check_hostname


def test_smtp_port_465_uses_implicit_tls(tls):
    s = dmail.smtp_connect("smtp.example.com", 465, "u", "p", 5)
    assert s.context is not None and s.context.verify_mode == ssl.CERT_REQUIRED
    assert "starttls" not in s.calls


def test_smtp_without_starttls_refused_on_remote_host(tls):
    tls.offers_starttls = False
    with pytest.raises(delivery.DeliveryError, match="SMTP SERVER OFFERS NO TLS"):
        dmail.smtp_connect("smtp.example.com", 587, "u", "p", 5)
    assert "close" in tls.instances[0].calls and "login" not in tls.instances[0].calls  # never sent a password


def test_smtp_without_starttls_allowed_on_loopback(tls):
    tls.offers_starttls = False
    s = dmail.smtp_connect("127.0.0.1", 1025, "u", "p", 5)
    assert "login" in s.calls and "starttls" not in s.calls


@pytest.mark.parametrize("port", [587, 465])
def test_smtp_cert_error_is_mapped(tls, port):
    tls.cert_error = True
    with pytest.raises(delivery.DeliveryError, match="SMTP TLS CERTIFICATE NOT TRUSTED"):
        dmail.smtp_connect("smtp.example.com", port, "u", "p", 5)


def test_keys_smtp_check_uses_the_helper(tls):
    from openterm import keys

    tls.offers_starttls = False
    assert keys._smtp_check(SMTP_KEYS) == ("ERROR", "SMTP SERVER OFFERS NO TLS")
    tls.offers_starttls = True
    assert keys._smtp_check(SMTP_KEYS) == ("OK", None)


# --- pure formatting ---
def test_format_alert_and_news():
    subject, text = dfmt.alert_message({"symbol": "AAPL", "op": "<", "unit": "pct", "value": 5, "trigger_price": 180.25,
                                        "triggered_at": 0})
    assert "AAPL" in subject and "below 5%" in subject and "180.25" in text and "1970-01-01" in text
    subject, text = dfmt.news_alert_message({"word": "SEC", "symbol": "AAPL", "headline": "SEC sues", "url": "https://a.b/c",
                                             "triggered_at": 0})
    assert "[AAPL]" in subject and "SEC sues" in text and "https://a.b/c" in text
