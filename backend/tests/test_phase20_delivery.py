"""Phase 20: delivery extensions on top of Phase 17 (see test_phase17_delivery.py for the basics).

Covers: Telegram MarkdownV2 escaping and the 4,096-character split, 429 `retry_after`, retry with
backoff (30 s, 2 min, 10 min, then failed) done in the background, the daily cap per channel, and
secrets (recipient, chat id, bot token, SMTP password) staying out of log rows and answers.

Time is faked: `delivery.sleep` records the requested wait and returns at once, `delivery.now` is a settable
clock. No network: Telegram and the webhook go through `httpx.MockTransport`, email through a scripted sender.
"""

from __future__ import annotations

import asyncio
import json
import smtplib
import time

import httpx
import pytest

from openterm import delivery
from openterm.delivery import telegram, webhook
from openterm.delivery.settings import DEFAULT_DAILY_CAP, defaults, validate
from openterm.userdata import UserDataError

SMTP_KEYS = {"SMTP_HOST": "smtp.example.com", "SMTP_PORT": "587", "SMTP_USER": "me@example.com",
             "SMTP_PASSWORD": "hunter2-secret-pass"}
TG_TOKEN = "123456:abcdefghijklmnopqrstuvwx"
CHAT_ID = "987654321"
RECIPIENT = "inbox@example.org"

# every character MarkdownV2 reserves, per the Telegram Bot API docs
MDV2_SPECIAL = "_*[]()~`>#+-=|{}.!\\"


# --- helpers ---
@pytest.fixture
def waits(monkeypatch):
    """Replaces the retry sleeper: records each requested wait and returns at once."""
    recorded: list[float] = []

    async def fake_sleep(seconds):
        recorded.append(seconds)

    monkeypatch.setattr(delivery, "sleep", fake_sleep)
    return recorded


def configure(client, channels=("email",), **extra):
    r = client.put("/api/delivery", json={"channels": dict.fromkeys(channels, True),
                                          "email_to": RECIPIENT, "telegram_chat_id": CHAT_ID, **extra})
    assert r.status_code == 200, r.text


def send_test(client, channel):
    return client.post("/api/delivery/test", json={"channel": channel}).json()["results"][0]


def wait_status(client, statuses, timeout=5.0):
    """The retry runs in a background task: poll the newest log row until its status is one of `statuses`."""
    end = time.time() + timeout
    row = None
    while time.time() < end:
        rows = client.get("/api/delivery/log").json()["deliveries"]
        row = rows[0] if rows else None
        if row and row["status"] in statuses:
            return row
        time.sleep(0.02)
    raise AssertionError(f"log row never reached {statuses}: {row}")


def scripted_sender(outcomes):
    """A sender that works through `outcomes` in order: an exception is raised, None means success."""
    calls = []

    async def sender(app, values, cfg, subject, text, extra):
        calls.append(1)
        out = outcomes[min(len(calls), len(outcomes)) - 1]
        if out is not None:
            raise out

    sender.calls = calls
    return sender


# --- (a) Telegram MarkdownV2 escaper ---
def test_escape_mdv2_escapes_every_reserved_character():
    for ch in MDV2_SPECIAL:
        assert telegram.escape_mdv2(ch) == "\\" + ch
    assert telegram.escape_mdv2("AAPL crossed above 200.50 (+3%)!") == "AAPL crossed above 200\\.50 \\(\\+3%\\)\\!"


def test_escape_mdv2_leaves_plain_text_and_other_symbols_alone():
    assert telegram.escape_mdv2("Hello world 123 :, ; ? % $ & @") == "Hello world 123 :, ; ? % $ & @"
    assert telegram.escape_mdv2("") == ""


def test_escape_mdv2_backslash_is_escaped_first_not_twice():
    # a literal backslash becomes two characters; the escape added for "." is not escaped again
    assert telegram.escape_mdv2("a\\.b") == "a\\\\\\.b"


# --- (a) splitting at 4,096 on line boundaries ---
def test_short_text_is_one_message():
    assert telegram.split_message("one\ntwo") == ["one\ntwo"]


def test_split_cuts_between_lines_and_loses_nothing():
    lines = [f"line {i:04d} " + "x" * 90 for i in range(200)]  # ~19 KB, each line far below the limit
    text = "\n".join(lines)
    parts = telegram.split_message(text, 4096)
    assert len(parts) > 1 and all(len(p) <= 4096 for p in parts)
    for p in parts:  # every part is whole lines, so no line was cut in the middle
        assert all(part_line in lines for part_line in p.split("\n"))
    assert "\n".join(parts) == text  # nothing lost, order kept


def test_split_slices_a_single_overlong_line():
    parts = telegram.split_message("y" * 9000, 4096)
    assert [len(p) for p in parts] == [4096, 4096, 808]


def test_split_measures_the_escaped_length():
    # 3,000 dots become 6,000 characters once escaped, so they must not share one message
    text = "." * 3000
    msgs = telegram.build_messages("S", text)
    assert len(msgs) >= 2 and all(len(m) <= 4096 for m in msgs)
    # no part ends in a lone backslash (that would escape the next character and break parsing)
    for m in msgs:
        trailing = len(m) - len(m.rstrip("\\"))
        assert trailing % 2 == 0


def test_build_messages_bolds_the_escaped_subject_on_the_first_part_only():
    msgs = telegram.build_messages("Alert: AAPL > 200.5", "body.\n" + "z" * 5000)
    assert msgs[0].startswith("*Alert: AAPL \\> 200\\.5*\n\n")
    assert len(msgs) >= 2 and not any(m.startswith("*") for m in msgs[1:])
    assert all(len(m) <= 4096 for m in msgs)


def telegram_app(client, handler):
    client.app.state.keys_http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client.app.state.keys.set("telegram", {"TELEGRAM_BOT_TOKEN": TG_TOKEN})
    client.app.state.delivery_senders = {"telegram": telegram.send}
    configure(client, ("telegram",))


def test_telegram_posts_markdownv2_and_every_part(client, waits):
    posts = []

    def handler(req):
        posts.append(json.loads(req.content))
        return httpx.Response(200, json={"ok": True})

    telegram_app(client, handler)
    # the test route sends a short message; call the sender with a long one through the app directly
    async def go():
        cfg = {"telegram_chat_id": CHAT_ID}
        await telegram.send(client.app, {"TELEGRAM_BOT_TOKEN": TG_TOKEN}, cfg, "Subj.", "line.\n" * 1500, {})

    asyncio.run(go())
    assert len(posts) >= 2
    assert all(p["parse_mode"] == "MarkdownV2" and len(p["text"]) <= 4096 and p["chat_id"] == CHAT_ID for p in posts)


# --- (a) 429 honours retry_after ---
def test_429_waits_at_least_retry_after_then_sends(client, waits):
    answers = [httpx.Response(429, json={"ok": False, "parameters": {"retry_after": 700}}),
               httpx.Response(200, json={"ok": True})]
    telegram_app(client, lambda req: answers.pop(0))
    assert send_test(client, "telegram")["status"] == "retrying"
    row = wait_status(client, ("sent", "failed"))
    assert row["status"] == "sent"
    assert waits == [700.0]  # the server asked for longer than the 30 s step, so we waited 700


def test_429_with_a_short_retry_after_still_waits_the_schedule_step(client, waits):
    answers = [httpx.Response(429, json={"parameters": {"retry_after": 3}}), httpx.Response(200, json={"ok": True})]
    telegram_app(client, lambda req: answers.pop(0))
    send_test(client, "telegram")
    assert wait_status(client, ("sent", "failed"))["status"] == "sent"
    assert waits == [30.0]


def test_retry_does_not_repost_the_parts_that_already_went_out(client, waits):
    posted = []
    state = {"n": 0}

    def handler(req):
        state["n"] += 1
        if state["n"] == 2:  # the second part is rate limited once
            return httpx.Response(429, json={"parameters": {"retry_after": 1}})
        posted.append(json.loads(req.content)["text"])
        return httpx.Response(200, json={"ok": True})

    telegram_app(client, handler)
    long_text = "\n".join(f"row {i} " + "w" * 80 for i in range(120))  # ~10 KB = 3 parts

    async def go():
        extra = {}
        cfg = {"telegram_chat_id": CHAT_ID}
        values = {"TELEGRAM_BOT_TOKEN": TG_TOKEN}
        with pytest.raises(delivery.RetryableError) as e:
            await telegram.send(client.app, values, cfg, "S", long_text, extra)
        assert e.value.retry_after == 1.0 and extra["_tg_sent"] == 1
        await telegram.send(client.app, values, cfg, "S", long_text, extra)  # the retry
        return len(telegram.build_messages("S", long_text))

    total = asyncio.run(go())
    assert len(posted) == total and len(set(posted)) == total  # each part exactly once


# --- (b) retry with backoff, in the background ---
def test_backoff_schedule_then_failed(client, waits):
    client.app.state.keys.set("smtp", SMTP_KEYS)
    sender = scripted_sender([ConnectionResetError("blip")])  # fails every time
    client.app.state.delivery_senders = {"email": sender}
    configure(client)
    assert send_test(client, "email")["status"] == "retrying"
    row = wait_status(client, ("failed", "sent"))
    assert row["status"] == "failed" and row["detail"].startswith("GAVE UP AFTER 4 ATTEMPTS")
    assert waits == [30.0, 120.0, 600.0] and len(sender.calls) == 4
    assert len(client.get("/api/delivery/log").json()["deliveries"]) == 1  # one row, rewritten, not four


def test_succeeds_on_the_second_retry(client, waits):
    client.app.state.keys.set("smtp", SMTP_KEYS)
    sender = scripted_sender([ConnectionResetError("a"), ConnectionResetError("b"), None])
    client.app.state.delivery_senders = {"email": sender}
    configure(client)
    send_test(client, "email")
    assert wait_status(client, ("failed", "sent"))["status"] == "sent"
    assert waits == [30.0, 120.0] and len(sender.calls) == 3


def test_a_permanent_error_during_a_retry_stops_the_retries(client, waits):
    client.app.state.keys.set("smtp", SMTP_KEYS)
    sender = scripted_sender([ConnectionResetError("blip"), delivery.DeliveryError("SMTP SERVER OFFERS NO TLS")])
    client.app.state.delivery_senders = {"email": sender}
    configure(client)
    send_test(client, "email")
    row = wait_status(client, ("failed", "sent"))
    assert row["status"] == "failed" and row["detail"] == "SMTP SERVER OFFERS NO TLS" and len(sender.calls) == 2


def test_a_failing_channel_never_blocks_the_caller(client, monkeypatch):
    """While the retry is waiting (its sleep is blocked), the answer has long been delivered."""
    client.app.state.keys.set("smtp", SMTP_KEYS)
    real_sleep = asyncio.sleep
    released = {"go": False}

    async def blocked_sleep(_seconds):
        while not released["go"]:
            await real_sleep(0.01)

    monkeypatch.setattr(delivery, "sleep", blocked_sleep)
    client.app.state.delivery_senders = {"email": scripted_sender([ConnectionResetError("blip"), None])}
    configure(client)
    t0 = time.time()
    result = send_test(client, "email")
    assert result["status"] == "retrying" and time.time() - t0 < 2.0
    assert client.get("/api/delivery/log").json()["deliveries"][0]["status"] == "retrying"  # still waiting
    released["go"] = True  # let the retry finish so the app shuts down cleanly
    assert wait_status(client, ("sent", "failed"))["status"] == "sent"


def test_webhook_5xx_and_429_are_retried_but_4xx_is_not(client, waits):
    client.app.state.keys.set("webhook", {"ALERT_WEBHOOK_URL": "https://hooks.example.com/secret-path-123"})
    answers = [httpx.Response(503), httpx.Response(429, headers={"retry-after": "700"}), httpx.Response(200)]
    client.app.state.keys_http = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: answers.pop(0)))
    client.app.state.delivery_senders = {"webhook": webhook.send}
    configure(client, ("webhook",))
    assert send_test(client, "webhook")["status"] == "retrying"
    assert wait_status(client, ("sent", "failed"))["status"] == "sent"
    assert waits == [30.0, 700.0]  # step 1 = 30 s; the 429's Retry-After (700 s) is longer than step 2 (120 s)


def test_webhook_4xx_fails_at_once(client, waits):
    client.app.state.keys.set("webhook", {"ALERT_WEBHOOK_URL": "https://hooks.example.com/x"})
    client.app.state.keys_http = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(404)))
    client.app.state.delivery_senders = {"webhook": webhook.send}
    configure(client, ("webhook",))
    assert send_test(client, "webhook")["status"] == "failed" and waits == []


def test_is_retryable_classification():
    assert delivery.is_retryable(ConnectionResetError())
    assert delivery.is_retryable(httpx.ConnectError("x"))
    assert delivery.is_retryable(delivery.RetryableError("429"))
    assert delivery.is_retryable(smtplib.SMTPResponseException(451, b"try again later"))
    assert delivery.is_retryable(smtplib.SMTPServerDisconnected())
    assert not delivery.is_retryable(smtplib.SMTPResponseException(550, b"mailbox unavailable"))
    assert not delivery.is_retryable(smtplib.SMTPAuthenticationError(535, b"bad credentials"))
    assert not delivery.is_retryable(smtplib.SMTPRecipientsRefused({}))
    assert not delivery.is_retryable(delivery.DeliveryError("SMTP SERVER OFFERS NO TLS"))
    assert not delivery.is_retryable(ValueError("bug"))


def test_smtp_451_is_retried_and_550_is_not(client, waits):
    client.app.state.keys.set("smtp", SMTP_KEYS)
    sender = scripted_sender([smtplib.SMTPResponseException(451, b"greylisted, try later"), None])
    client.app.state.delivery_senders = {"email": sender}
    configure(client)
    assert send_test(client, "email")["status"] == "retrying"
    assert wait_status(client, ("sent", "failed"))["status"] == "sent"
    client.app.state.delivery_senders = {"email": scripted_sender([smtplib.SMTPResponseException(550, b"no such user")])}
    assert send_test(client, "email")["status"] == "failed"


# --- (c) daily cap per channel ---
def test_cap_default_and_validation():
    assert defaults()["daily_cap"] == DEFAULT_DAILY_CAP == 50
    assert validate({"daily_cap": 5})["daily_cap"] == 5
    for bad in (0, -1, 1001, True, "5", 2.5, None):
        with pytest.raises(UserDataError):
            validate({"daily_cap": bad})


def test_over_cap_send_is_logged_as_skipped_with_the_reason(client, waits):
    client.app.state.keys.set("smtp", SMTP_KEYS)
    sender = scripted_sender([None])
    client.app.state.delivery_senders = {"email": sender}
    configure(client, daily_cap=2)
    results = [send_test(client, "email") for _ in range(3)]
    assert [r["status"] for r in results] == ["sent", "sent", "skipped"]
    assert "DAILY CAP OF 2" in results[2]["detail"] and "EMAIL" in results[2]["detail"]
    assert len(sender.calls) == 2  # the third was never handed to the sender
    rows = client.get("/api/delivery/log").json()["deliveries"]
    assert rows[0]["status"] == "skipped" and "DAILY CAP" in rows[0]["detail"]  # logged, not silently dropped


def test_cap_is_per_channel(client, waits):
    client.app.state.keys.set("smtp", SMTP_KEYS)
    client.app.state.keys.set("telegram", {"TELEGRAM_BOT_TOKEN": TG_TOKEN})
    client.app.state.delivery_senders = {"email": scripted_sender([None]), "telegram": scripted_sender([None])}
    configure(client, ("email", "telegram"), daily_cap=1)
    assert send_test(client, "email")["status"] == "sent"
    assert send_test(client, "email")["status"] == "skipped"
    assert send_test(client, "telegram")["status"] == "sent"  # its own count


def test_cap_resets_on_the_next_day(client, waits, monkeypatch):
    client.app.state.keys.set("smtp", SMTP_KEYS)
    client.app.state.delivery_senders = {"email": scripted_sender([None])}
    configure(client, daily_cap=1)
    clock = {"t": 1_800_000_000.0}
    monkeypatch.setattr(delivery, "now", lambda: clock["t"])
    assert send_test(client, "email")["status"] == "sent"
    assert send_test(client, "email")["status"] == "skipped"
    clock["t"] += 2 * 86400  # two days later: a fresh count whatever the time zone
    assert send_test(client, "email")["status"] == "sent"


def test_skips_and_retries_do_not_use_up_the_cap(client, waits):
    client.app.state.keys.set("smtp", SMTP_KEYS)
    sender = scripted_sender([ConnectionResetError("a"), ConnectionResetError("b"), None, None])
    client.app.state.delivery_senders = {"email": sender}
    configure(client, daily_cap=2)
    send_test(client, "email")  # first attempt + 2 retries = ONE send against the cap
    wait_status(client, ("sent", "failed"))
    assert send_test(client, "email")["status"] == "sent"  # second slot still free


def test_cap_counter_survives_log_trimming(client, waits, monkeypatch):
    """The count is in kv, not in the deliveries log, so a log that forgets old rows cannot reset it."""
    from openterm.delivery import log as dlog

    monkeypatch.setattr(dlog, "KEEP", 1)  # the log now keeps ONE row: the `sent` row is gone after the next send
    client.app.state.keys.set("smtp", SMTP_KEYS)
    client.app.state.delivery_senders = {"email": scripted_sender([None])}
    configure(client, daily_cap=1)
    assert send_test(client, "email")["status"] == "sent"
    assert send_test(client, "email")["status"] == "skipped"
    assert send_test(client, "email")["status"] == "skipped"  # a log-counting design would let this one through


# --- (d) SMTP safety stays in force through the sender used by delivery ---
def test_real_email_sender_goes_through_the_verifying_helper(client, monkeypatch):
    """`email.send` must call `smtp_connect` (verified TLS, loopback-only plaintext), not smtplib directly."""
    import ssl

    from openterm.delivery import email as dmail

    seen = {}

    class Spy:
        def __init__(self, host, port, timeout=None, context=None):
            seen.update(host=host, ctx=context)

        def ehlo(self):
            pass

        def has_extn(self, name):
            return True

        def starttls(self, context=None):
            seen["ctx"] = context

        def login(self, *a):
            pass

        def send_message(self, msg):
            seen["sent"] = True

        def close(self):
            pass

    monkeypatch.setattr(dmail.smtplib, "SMTP", Spy)
    dmail.send_sync(SMTP_KEYS, RECIPIENT, "s", "t")
    assert seen["sent"] and seen["ctx"].check_hostname is True and seen["ctx"].verify_mode == ssl.CERT_REQUIRED


# --- (f) secrets stay out of log rows, errors and answers ---
def test_recipient_chat_id_token_and_password_never_reach_the_log_or_answers(client, waits):
    client.app.state.keys.set("smtp", SMTP_KEYS)
    client.app.state.keys.set("telegram", {"TELEGRAM_BOT_TOKEN": TG_TOKEN})

    async def leaky(app, values, cfg, subject, text, extra):
        raise delivery.DeliveryError(
            f"550 rejected {RECIPIENT} chat {CHAT_ID} token {TG_TOKEN} user {SMTP_KEYS['SMTP_USER']} "
            f"pw {SMTP_KEYS['SMTP_PASSWORD']}")

    client.app.state.delivery_senders = {"email": leaky, "telegram": leaky}
    configure(client, ("email", "telegram"))
    answers = [send_test(client, "email"), send_test(client, "telegram")]
    log = client.get("/api/delivery/log").json()
    blob = json.dumps([answers, log])
    for secret in (RECIPIENT, CHAT_ID, TG_TOKEN, SMTP_KEYS["SMTP_USER"], SMTP_KEYS["SMTP_PASSWORD"]):
        assert secret not in blob, secret
    assert "***" in log["deliveries"][0]["detail"]


def test_secrets_are_scrubbed_from_a_retry_row_too(client, waits):
    client.app.state.keys.set("smtp", SMTP_KEYS)
    sender = scripted_sender([ConnectionResetError(f"451 try later for {RECIPIENT}"),
                              ConnectionResetError(f"451 still failing for {RECIPIENT}")])
    client.app.state.delivery_senders = {"email": sender}
    configure(client)
    first = send_test(client, "email")
    wait_status(client, ("failed", "sent"))
    log = json.dumps(client.get("/api/delivery/log").json())
    assert RECIPIENT not in log and RECIPIENT not in json.dumps(first)


def test_telegram_url_with_token_in_a_transport_error_is_scrubbed(client, waits):
    def handler(req):
        raise httpx.ConnectError(f"cannot reach {req.url}")  # httpx errors can quote the request URL

    telegram_app(client, handler)
    send_test(client, "telegram")
    wait_status(client, ("failed", "sent"))
    log = json.dumps(client.get("/api/delivery/log").json())
    assert TG_TOKEN not in log
