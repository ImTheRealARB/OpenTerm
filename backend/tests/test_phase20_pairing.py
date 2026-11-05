"""Phase 20: recipients hidden from the browser, and Telegram pairing (delivery/pairing.py). No network.

Telegram is a scripted `httpx.MockTransport`. The delivery code treats an injected `delivery_senders["telegram"]` as
"a test supplied the transport", so that is how these tests leave fixture mode (as test_phase20_delivery.py does).
"""

from __future__ import annotations

import logging

import httpx
import pytest
from fastapi.testclient import TestClient

from openterm import delivery
from openterm.delivery import pairing, telegram
from openterm.delivery.settings import mask_email, public

TG_TOKEN = "123456:abcdefghijklmnopqrstuvwx"
CHAT_ID = 987654321
BOT = "OpenTermTestBot"


class FakeTelegram:
    """Scripted Bot API: answers getMe and getUpdates, remembers every call."""

    def __init__(self):
        self.messages: list[dict] = []  # what users "sent to the bot"
        self.calls: list[str] = []
        self.status = 200  # set to something else to make every call fail

    def say(self, text, chat_id=CHAT_ID):
        self.messages.append({"update_id": len(self.messages) + 1, "message": {"chat": {"id": chat_id}, "text": text}})

    def __call__(self, req: httpx.Request) -> httpx.Response:
        method = req.url.path.rsplit("/", 1)[-1]
        self.calls.append(method)
        if self.status != 200:
            return httpx.Response(self.status, json={"ok": False, "description": f"denied for {TG_TOKEN}"})
        if method == "getMe":
            return httpx.Response(200, json={"ok": True, "result": {"username": BOT}})
        if method == "getUpdates":
            return httpx.Response(200, json={"ok": True, "result": self.messages})
        return httpx.Response(404, json={"ok": False})


@pytest.fixture
def tg(client):
    fake = FakeTelegram()
    client.app.state.keys_http = httpx.AsyncClient(transport=httpx.MockTransport(fake))
    client.app.state.keys.set("telegram", {"TELEGRAM_BOT_TOKEN": TG_TOKEN})
    client.app.state.delivery_senders = {"telegram": telegram.send}  # leaves fixture mode
    client.app.state.telegram_pairing = None
    yield fake
    client.app.state.delivery_senders = {}  # the app object is shared between tests: leave no override behind
    client.app.state.telegram_pairing = None


def stored(client) -> dict:
    """The REAL stored settings, read inside the app's own event loop (what the senders use)."""
    from openterm.delivery import settings as dsettings

    async def read():
        return await dsettings.get(client.app.state.userdata.db)

    return client.portal.call(read)


def start(client):
    r = client.post("/api/delivery/telegram/pair/start")
    assert r.status_code == 200, r.text
    return r.json()


def check(client):
    return client.post("/api/delivery/telegram/pair/check")


# --- recipients hidden from the browser -------------------------------------------------------------------------
def test_mask_email_shapes():
    assert mask_email("alice@gmail.com") == "a•••@gmail.com"
    assert mask_email("a@b.co") == "a•••@b.co"
    assert mask_email("") == "•••"


def test_get_put_and_test_never_return_the_recipient_or_chat_id(client):
    r = client.put("/api/delivery", json={"email_to": "secret.person@example.org", "telegram_chat_id": "424242",
                                          "channels": {"email": True}})
    assert r.status_code == 200
    for body in (r.text, client.get("/api/delivery").text, client.post("/api/delivery/test", json={"channel": "email"}).text):
        assert "secret.person" not in body and "424242" not in body
    s = r.json()["settings"]
    assert s["recipients"] == {"email": {"configured": True, "hint": "s•••@example.org"},
                               "telegram": {"configured": True, "hint": "chat linked"}}


def test_public_does_not_mutate_the_stored_settings():
    cfg = {"email_to": "a@b.co", "telegram_chat_id": "1", "channels": {}}
    public(cfg)
    assert cfg["email_to"] == "a@b.co" and cfg["telegram_chat_id"] == "1"


def test_empty_value_keeps_the_stored_recipient_and_a_new_one_replaces_it(client):
    client.put("/api/delivery", json={"email_to": "first@example.org"})
    client.put("/api/delivery", json={"email_to": "", "telegram_chat_id": "  "})  # the browser cannot send the old value back
    assert client.get("/api/delivery").json()["settings"]["recipients"]["email"]["hint"] == "f•••@example.org"
    client.put("/api/delivery", json={"email_to": "second@example.org"})
    assert client.get("/api/delivery").json()["settings"]["recipients"]["email"]["hint"] == "s•••@example.org"
    assert stored(client)["email_to"] == "second@example.org"  # the backend itself still has the real value


# --- pairing ----------------------------------------------------------------------------------------------------
def test_pairing_success_stores_the_chat_id_without_echoing_it(client, tg, caplog):
    caplog.set_level(logging.INFO)  # the level the app runs at (aiosqlite's DEBUG echoes SQL parameters for every setting)
    s = start(client)
    assert s["link"] == f"https://t.me/{BOT}" and s["bot"] == BOT and s["expires_in"] == 600
    assert s["code"].startswith("OT-") and len(s["code"]) == 9 and s["code"][3:].isdigit()
    assert check(client).json() == {"paired": False, "expires_in": pytest.approx(600, abs=5)}  # nobody wrote yet
    tg.say(f"/start {s['code']}")
    r = check(client)
    assert r.status_code == 200 and r.json() == {"paired": True}
    assert str(CHAT_ID) not in r.text
    assert str(CHAT_ID) not in client.get("/api/delivery").text
    assert client.get("/api/delivery").json()["settings"]["recipients"]["telegram"]["configured"] is True
    assert stored(client)["telegram_chat_id"] == str(CHAT_ID)  # what the sender will use
    assert str(CHAT_ID) not in caplog.text and TG_TOKEN not in caplog.text


def test_the_code_may_sit_anywhere_in_the_message(client, tg):
    s = start(client)
    tg.say(f"hello {s['code']} thanks")
    assert check(client).json() == {"paired": True}
    assert stored(client)["telegram_chat_id"] == str(CHAT_ID)


def test_a_group_chat_with_a_negative_id_pairs_too(client, tg):
    s = start(client)
    tg.say(s["code"], chat_id=-1001234567890)
    assert check(client).json() == {"paired": True}


def test_wrong_code_does_not_pair(client, tg):
    s = start(client)
    wrong = "OT-000000" if s["code"] != "OT-000000" else "OT-000001"
    tg.say(wrong)
    tg.say("/start")  # a bare /start (no code) proves nothing either
    tg.say(s["code"] + "7")  # the code with an extra digit is a different code
    r = check(client)
    assert r.status_code == 200 and r.json()["paired"] is False
    assert client.get("/api/delivery").json()["settings"]["recipients"]["telegram"]["configured"] is False
    tg.say(s["code"])  # the right one still works afterwards
    assert check(client).json() == {"paired": True}


def test_expired_code_is_refused_and_cleared(client, tg, monkeypatch):
    clock = {"t": 1_000_000.0}
    monkeypatch.setattr(delivery, "now", lambda: clock["t"])
    s = start(client)
    tg.say(s["code"])  # the right code is waiting in Telegram, but too late
    clock["t"] += 601
    r = check(client)
    assert r.status_code == 400 and "EXPIRED" in r.json()["error"]
    assert client.get("/api/delivery").json()["settings"]["recipients"]["telegram"]["configured"] is False
    assert check(client).status_code == 400  # the expired code is gone, not just ignored once


def test_code_just_inside_ten_minutes_still_works(client, tg, monkeypatch):
    clock = {"t": 5_000.0}
    monkeypatch.setattr(delivery, "now", lambda: clock["t"])
    s = start(client)
    tg.say(s["code"])
    clock["t"] += 599
    assert check(client).json() == {"paired": True}


def test_a_code_works_once_and_old_codes_die_when_a_new_one_starts(client, tg):
    s = start(client)
    tg.say(s["code"])
    assert check(client).json() == {"paired": True}
    again = check(client)  # reuse: the code was consumed
    assert again.status_code == 400 and "NO PAIRING" in again.json()["error"]
    # the old message is still in Telegram's history, but a new pairing has a new code and ignores it
    s2 = start(client)
    if s2["code"] == s["code"]:
        pytest.skip("1 in a million: the two random codes collided")
    assert check(client).json()["paired"] is False


def test_a_second_start_replaces_the_first_code(client, tg):
    first = start(client)
    second = start(client)
    if first["code"] == second["code"]:
        pytest.skip("1 in a million: the two random codes collided")
    tg.say(first["code"])
    assert check(client).json()["paired"] is False
    tg.say(second["code"])
    assert check(client).json() == {"paired": True}


def test_check_without_start_is_an_error(client, tg):
    r = check(client)
    assert r.status_code == 400 and "NO PAIRING" in r.json()["error"]
    assert tg.calls == []  # no Telegram call was made


def test_needs_the_bot_token(client):
    client.app.state.delivery_senders = {"telegram": telegram.send}
    client.app.state.keys.delete("telegram")  # make sure no earlier test left a token behind
    r = client.post("/api/delivery/telegram/pair/start")
    assert r.status_code == 424 and "TELEGRAM_BOT_TOKEN" in r.json()["error"]


def test_fixture_mode_makes_no_telegram_call(client):
    client.app.state.keys.set("telegram", {"TELEGRAM_BOT_TOKEN": TG_TOKEN})
    client.app.state.delivery_senders = {}
    r = client.post("/api/delivery/telegram/pair/start")  # fixture mode and no injected sender
    assert r.status_code == 503 and "FIXTURE MODE" in r.json()["error"]


def test_token_never_appears_in_errors(client, tg, caplog):
    caplog.set_level(logging.DEBUG)
    tg.status = 403
    r = client.post("/api/delivery/telegram/pair/start")
    assert r.status_code == 503 and TG_TOKEN not in r.text and "123456:abc" not in r.text
    tg.status = 401
    r = client.post("/api/delivery/telegram/pair/start")
    assert "REJECTED" in r.json()["error"] and TG_TOKEN not in r.text

    # a network failure: httpx's own message holds the URL, and so the token
    def boom(req):
        raise httpx.ConnectError(f"cannot reach {req.url}")

    client.app.state.keys_http = httpx.AsyncClient(transport=httpx.MockTransport(boom))
    r = client.post("/api/delivery/telegram/pair/start")
    assert r.status_code == 503 and "ConnectError" in r.json()["error"]
    assert TG_TOKEN not in r.text and TG_TOKEN not in caplog.text


def test_pairing_routes_need_loopback(client, tg):
    remote = TestClient(client.app, client=("10.1.2.3", 40000))
    assert remote.post("/api/delivery/telegram/pair/start").status_code == 403
    assert remote.post("/api/delivery/telegram/pair/check").status_code == 403
    assert tg.calls == []


def test_chat_with_code_ignores_malformed_updates():
    code = "OT-123456"
    updates = [None, 5, {"message": None}, {"message": {"text": code}},  # no chat
               {"message": {"chat": {"id": True}, "text": code}},  # bool is not a chat id
               {"message": {"chat": {"id": 7}, "text": 5}}, {"message": {"chat": {"id": 8}, "text": f"x {code.lower()} y"}}]
    assert pairing._chat_with_code(updates, code) == "8"  # case-insensitive, malformed entries skipped
    assert pairing._chat_with_code("nope", code) is None


def test_new_code_format():
    for _ in range(50):
        c = pairing.new_code()
        assert len(c) == 9 and c[:3] == "OT-" and c[3:].isdigit()
