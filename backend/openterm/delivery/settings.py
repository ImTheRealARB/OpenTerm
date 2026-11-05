"""Delivery settings: one JSON document in kv key `delivery` (Phase 17 B/C). Everything is off by default.

Secrets are NOT here: the SMTP password, bot token and webhook URL are keys (APIKEYS). The recipient address and
chat id ARE stored here (the senders need them) but they are private: the browser never receives them. Every
route answers with `public(cfg)`, which swaps them for `recipients: {channel: {configured, hint}}` (Phase 20 rule 5).
"""

from __future__ import annotations

import json
import re
import zoneinfo

from ..userdata import UserDataError

KEY = "delivery"
CHANNELS = ("email", "telegram", "webhook", "desktop")
PUSH = ("email", "telegram", "webhook")  # channels the backend sends on; desktop lives in the browser
DAYS = ("mon-fri", "daily")
EMAIL_RE = re.compile(r"^[^@\s,;<>]{1,64}@[^@\s,;<>]{1,255}$")
CHAT_RE = re.compile(r"^(-?\d{1,20}|@[A-Za-z][A-Za-z0-9_]{4,31})$")
DEFAULT_DAILY_CAP = 50  # sends per push channel per local day (Phase 20)
MAX_DAILY_CAP = 1000
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def defaults() -> dict:
    return {
        "channels": dict.fromkeys(CHANNELS, False),
        "email_to": "",
        "telegram_chat_id": "",
        # most sends per channel per local day; the over-cap send is logged as skipped, never dropped silently
        "daily_cap": DEFAULT_DAILY_CAP,
        # tz "" = the machine's own time zone (the brief scheduler resolves it)
        "brief": {"enabled": False, "time": "08:30", "days": "mon-fri", "tz": ""},
    }


def _bad(msg: str) -> UserDataError:
    return UserDataError("bad_request", msg)


def validate(raw, current: dict | None = None) -> dict:
    """Merges `raw` over `current` (or defaults) and checks every field. Unknown fields are errors."""
    if not isinstance(raw, dict):
        raise _bad("DELIVERY SETTINGS MUST BE A JSON OBJECT")
    unknown = set(raw) - set(defaults())
    if unknown:
        raise _bad(f"UNKNOWN DELIVERY SETTING: {min(unknown)}")
    out = json.loads(json.dumps(current if current is not None else defaults()))  # deep copy
    if "channels" in raw:
        ch = raw["channels"]
        if not isinstance(ch, dict) or set(ch) - set(CHANNELS) or not all(isinstance(v, bool) for v in ch.values()):
            raise _bad("channels MUST MAP email, telegram, webhook, desktop TO true OR false")
        out["channels"].update(ch)
    if "email_to" in raw:
        v = raw["email_to"]
        if not isinstance(v, str) or (v.strip() and not EMAIL_RE.match(v.strip())):
            raise _bad("email_to MUST BE ONE EMAIL ADDRESS")
        out["email_to"] = v.strip()
    if "telegram_chat_id" in raw:
        v = raw["telegram_chat_id"]
        if not isinstance(v, str) or (v.strip() and not CHAT_RE.match(v.strip())):
            raise _bad("telegram_chat_id MUST BE A NUMBER OR @channelname")
        out["telegram_chat_id"] = v.strip()
    if "daily_cap" in raw:
        v = raw["daily_cap"]
        # bool is an int subclass in Python: reject it explicitly
        if isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= MAX_DAILY_CAP:
            raise _bad(f"daily_cap MUST BE A WHOLE NUMBER FROM 1 TO {MAX_DAILY_CAP}")
        out["daily_cap"] = v
    if "brief" in raw:
        b = raw["brief"]
        if not isinstance(b, dict) or set(b) - set(out["brief"]):
            raise _bad("brief ACCEPTS enabled, time, days, tz")
        if "enabled" in b and not isinstance(b["enabled"], bool):
            raise _bad("brief.enabled MUST BE true OR false")
        if "time" in b and not (isinstance(b["time"], str) and TIME_RE.match(b["time"])):
            raise _bad("brief.time MUST BE HH:MM (24 HOUR)")
        if "days" in b and b["days"] not in DAYS:
            raise _bad("brief.days MUST BE mon-fri OR daily")
        if "tz" in b:
            tz = b["tz"]
            if not isinstance(tz, str):
                raise _bad("brief.tz MUST BE A TIME ZONE NAME")
            if tz:
                try:
                    zoneinfo.ZoneInfo(tz)
                except (zoneinfo.ZoneInfoNotFoundError, ValueError, OSError):
                    raise _bad(f"brief.tz UNKNOWN TIME ZONE: {tz[:40]}") from None
        out["brief"].update(b)
    return out


async def get(db) -> dict:
    async with db.execute("SELECT value FROM kv WHERE key=?", (KEY,)) as cur:
        row = await cur.fetchone()
    if row is None:
        return defaults()
    return validate(json.loads(row[0]))  # a corrupt stored document fails loudly rather than being replaced


async def put(db, raw) -> dict:
    merged = validate(raw, await get(db))
    await db.execute("INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                     (KEY, json.dumps(merged)))
    await db.commit()
    return merged


# --- what the browser may see (Phase 20, rule 5) ----------------------------------------------------------------


def mask_email(addr: str) -> str:
    """`alice@gmail.com` -> `a•••@gmail.com`. Enough to recognise your own address, not enough to harvest it."""
    local, _, domain = addr.partition("@")
    return f"{local[:1]}•••@{domain}" if local and domain else "•••"


def public(cfg: dict) -> dict:
    """A copy of the settings that is safe to send to the browser.

    `email_to` and `telegram_chat_id` are removed and replaced by `recipients`, one entry per channel:
    `configured` (is there a value) and `hint` (a masked email, or a plain word for Telegram; the chat id itself,
    even partly, is never shown). To change a recipient the panel PUTs a new value; the stored one is never read back.
    """
    out = json.loads(json.dumps(cfg))  # deep copy: never mutate the stored document
    email = out.pop("email_to", "") or ""
    chat = out.pop("telegram_chat_id", "") or ""
    out["recipients"] = {
        "email": {"configured": bool(email), "hint": mask_email(email) if email else ""},
        "telegram": {"configured": bool(chat), "hint": "chat linked" if chat else ""},
    }
    return out
