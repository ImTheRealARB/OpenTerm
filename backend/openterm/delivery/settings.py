"""Delivery settings: one JSON document in kv key `delivery` (Phase 17 B/C). Everything is off by default.

Secrets are NOT here: the SMTP password, bot token and webhook URL are keys (APIKEYS). Only the
recipient address and chat id are settings, because they are not secret.
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
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def defaults() -> dict:
    return {
        "channels": dict.fromkeys(CHANNELS, False),
        "email_to": "",
        "telegram_chat_id": "",
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
