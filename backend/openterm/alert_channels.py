"""Per-alert delivery channels (Phase 20): `ALRT AAPL > 200 VIA TG,EMAIL`.

An alert row stores `channels`: NULL = "every channel switched on in DELIVERY" (today's behaviour, the default),
or a JSON list such as `["telegram", "email"]` = "only these".

Why this is its own small module and not part of `delivery/`: `delivery` decides HOW a message is sent; this file only
decides WHICH channels an alert asked for, and records the ones that cannot be used. It calls `delivery.dispatch`
with a channel list and does not change how delivery works.

An alert may ask for a channel that is switched off in DELIVERY settings. That must not vanish silently, so
`route` writes a `skipped` row with the reason `CHANNEL OFF` to the same delivery log the panel shows.
"""

from __future__ import annotations

import asyncio
import json
import logging

from .userdata import UserDataError

log = logging.getLogger("openterm.alert_channels")

# The three channels the backend can push on (same names as delivery.settings.PUSH; "desktop" lives in the browser).
CANONICAL = ("email", "telegram", "webhook")
# What a user may type after VIA (case-insensitive) -> the canonical name. TG is the short form of telegram.
ALIASES = {"EMAIL": "email", "TELEGRAM": "telegram", "TG": "telegram", "WEBHOOK": "webhook"}


def parse(raw) -> list[str] | None:
    """Validates the `channels` field of a create request. None (or missing) = all enabled channels.

    Anything else must be a non-empty list of known channel names; an unknown name is a 400, never ignored, so a typo
    such as `VIA TELEGRM` cannot quietly turn into "send nowhere" or "send everywhere".
    """
    if raw is None:
        return None
    if not isinstance(raw, list) or not raw or not all(isinstance(c, str) for c in raw):
        raise UserDataError("bad_request", "CHANNELS MUST BE A LIST OF: " + ", ".join(sorted(ALIASES)))
    out: list[str] = []
    for c in raw:
        name = ALIASES.get(c.strip().upper())
        if name is None:
            raise UserDataError("bad_request", f"UNKNOWN CHANNEL {c.strip()[:20].upper()}: USE " + ", ".join(sorted(ALIASES)))
        if name not in out:  # "TG,TELEGRAM" is one channel
            out.append(name)
    return out


def dump(channels: list[str] | None) -> str | None:
    """The TEXT stored in the column (NULL stays NULL)."""
    return None if channels is None else json.dumps(channels)


def load(text: str | None) -> list[str] | None:
    """The reverse of `dump`, for rows read back from the database."""
    return None if text is None else json.loads(text)


async def route(app, kind: str, ref, subject: str, text: str, extra: dict | None, channels: list[str]) -> list[dict]:
    """Sends to the requested channels that are switched on and logs `CHANNEL OFF` for the ones that are not."""
    from . import delivery
    from .delivery import log as dlog
    from .delivery import settings as dsettings

    db = app.state.userdata.db
    cfg = await dsettings.get(db)
    on = [c for c in channels if cfg["channels"].get(c)]
    for c in channels:
        if c in on:
            continue
        try:
            await dlog.add(db, kind, str(ref), c, "skipped", "CHANNEL OFF")
        except Exception:  # noqa: BLE001 - the database may be closing at shutdown
            log.warning("could not log CHANNEL OFF for %s", c)
    # `channels=[]` makes dispatch return at once, so "everything asked for is off" sends nothing at all.
    return await delivery.dispatch(app, kind, ref, subject, text, extra, channels=on)


def spawn(app, kind: str, ref, subject: str, text: str, extra: dict | None = None,
          channels: list[str] | None = None) -> asyncio.Task:
    """Background version, the drop-in for `delivery.spawn` that both fire paths use.

    No channel list = exactly the old behaviour (`delivery.spawn`, all enabled channels).
    """
    from . import delivery

    if channels is None:
        return delivery.spawn(app, kind, ref, subject, text, extra)
    task = asyncio.create_task(route(app, kind, ref, subject, text, extra, channels))
    delivery._track(app, task)  # the same keep-alive set delivery uses, so the task is not garbage collected
    return task
