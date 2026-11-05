"""Telegram pairing (Phase 20): link a chat to the bot without ever typing or showing the chat id.

Why: a Telegram "chat id" is a number the user cannot easily find, and (spec rule 5) the browser must never
receive it. So the user proves they own the chat by sending a one-time code to the bot, and the BACKEND reads
the chat id out of Telegram's reply and stores it in the delivery settings. The browser only learns `paired: true`.

Flow
1. `start`  asks Telegram `getMe` (using the bot token from the key store) for the bot's username and makes a
   code like `OT-123456`. The panel shows `https://t.me/<bot>` and the code. The user opens the link and sends
   the code (or presses Start, which sends `/start`; the user then types the code as well).
2. `check`  asks Telegram `getUpdates` ONCE for the bot's recent messages. A message containing the code gives
   us its chat id, which is saved with `settings.put`. The code is then deleted: it works once.

Rules kept here
- The code lives only in memory (`app.state.telegram_pairing`), expires after 10 minutes, and a new `start`
  replaces the old one. A restart forgets it, which is fine: pairing takes a minute.
- The bot token never appears in an error. httpx error text contains the request URL (which holds the token),
  so we report only the exception's class name, and run Telegram's own error text through `redact()`.
- The chat id is never returned, logged or put in an error.
- Fixture mode makes no real call, unless a test injected a Telegram sender (the same signal `dispatch` uses).
"""

from __future__ import annotations

import re
import secrets

import httpx

from .. import (
    delivery as _delivery,  # `_delivery.now` is read at call time so tests can fake the clock
)
from ..redact import redact
from ..userdata import UserDataError
from . import settings as dsettings

CODE_TTL_S = 600.0  # a code is valid for 10 minutes
TIMEOUT_S = 10.0
STATE = "telegram_pairing"  # attribute on app.state holding {"code": str, "bot": str, "expires": float} or None


def _bad(message: str, kind: str = "bad_request") -> UserDataError:
    return UserDataError(kind, message)


def new_code() -> str:
    """`OT-` plus six random digits (secrets, not random: the code is a short-lived credential)."""
    return f"OT-{secrets.randbelow(1_000_000):06d}"


def _token(app) -> str:
    values = app.state.keys.get("telegram")
    if values is None:
        raise _bad("KEY REQUIRED: set TELEGRAM_BOT_TOKEN in APIKEYS", "key_required")
    # Fixture mode never talks to Telegram (the shared client would answer from recordings and fake a pairing).
    if app.state.settings.openterm_fixtures and "telegram" not in getattr(app.state, "delivery_senders", {}):
        raise _bad("FIXTURE MODE: PAIRING NEEDS THE REAL TELEGRAM API", "unavailable")
    return values["TELEGRAM_BOT_TOKEN"]


async def _call(app, method: str, payload: dict | None = None) -> dict:
    """One Bot API call. Returns the `result` field; raises a UserDataError whose text holds no token."""
    http: httpx.AsyncClient = app.state.keys_http
    url = f"https://api.telegram.org/bot{_token(app)}/{method}"
    try:
        r = await http.post(url, json=payload or {}, timeout=TIMEOUT_S)
    except httpx.HTTPError as e:
        # str(e) can contain the URL and therefore the token: name only the kind of failure.
        raise _bad(f"TELEGRAM UNREACHABLE ({type(e).__name__})", "unavailable") from None
    if r.status_code == 401:
        raise _bad("TELEGRAM REJECTED THE BOT TOKEN: CHECK IT IN APIKEYS", "unavailable")
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code != 200 or not body.get("ok"):
        why = redact(str(body.get("description") or "")[:120])
        raise _bad(f"TELEGRAM {method.upper()} FAILED (HTTP {r.status_code}){': ' + why if why else ''}", "unavailable")
    return body.get("result")


async def start(app) -> dict:
    """Begins a pairing: returns the bot's link and a fresh one-time code."""
    me = await _call(app, "getMe")
    bot = (me or {}).get("username") if isinstance(me, dict) else None
    if not bot:
        raise _bad("TELEGRAM DID NOT NAME THE BOT", "unavailable")
    state = {"code": new_code(), "bot": bot, "expires": _delivery.now() + CODE_TTL_S}
    setattr(app.state, STATE, state)  # replaces any earlier code, which stops working at once
    return {"bot": bot, "link": f"https://t.me/{bot}", "code": state["code"], "expires_in": int(CODE_TTL_S)}


def _chat_with_code(updates, code: str) -> str | None:
    """The chat id (as text) of the newest message that contains `code`, or None.

    The code must stand alone (not glued to other letters or digits), so `OT-1234567` never matches `OT-123456`.
    """
    pattern = re.compile(rf"(?<![A-Z0-9-]){re.escape(code)}(?!\d)")
    found = None
    for upd in updates if isinstance(updates, list) else []:
        msg = upd.get("message") if isinstance(upd, dict) else None
        if not isinstance(msg, dict) or not isinstance(msg.get("text"), str):
            continue
        chat = msg.get("chat")
        chat_id = chat.get("id") if isinstance(chat, dict) else None
        if isinstance(chat_id, int) and not isinstance(chat_id, bool) and pattern.search(msg["text"].upper()):
            found = str(chat_id)  # updates arrive oldest first, so the last match is the newest
    return found


async def check(app) -> dict:
    """Looks once for the code. {paired: True} on success, {paired: False, expires_in} while still waiting."""
    state = getattr(app.state, STATE, None)
    if state is None:
        raise _bad("NO PAIRING IN PROGRESS: PRESS P TO START ONE")
    remaining = state["expires"] - _delivery.now()
    if remaining <= 0:
        setattr(app.state, STATE, None)
        raise _bad("PAIRING CODE EXPIRED: PRESS P FOR A NEW ONE")
    # offset=-100 = "the last 100 updates", so a busy bot's old chatter cannot hide the newest message.
    updates = await _call(app, "getUpdates", {"offset": -100, "timeout": 0, "allowed_updates": ["message"]})
    chat_id = _chat_with_code(updates, state["code"])
    if chat_id is None:
        return {"paired": False, "expires_in": int(remaining)}
    # One use only: if a second check already consumed this code while we were waiting for Telegram, stop here.
    if getattr(app.state, STATE, None) is not state:
        raise _bad("NO PAIRING IN PROGRESS: PRESS P TO START ONE")
    setattr(app.state, STATE, None)
    await dsettings.put(app.state.userdata.db, {"telegram_chat_id": chat_id})
    return {"paired": True}  # the chat id stays in the backend
