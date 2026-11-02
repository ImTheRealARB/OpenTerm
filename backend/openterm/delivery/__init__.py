"""Alert delivery (Phase 17 B): push a fired alert to email, Telegram or a webhook, and log every attempt.

Flow: a route that fires an alert calls `spawn(...)` (a background task, so the HTTP answer is never
delayed) -> `dispatch` reads the settings, runs each enabled channel on its own and writes one row per
channel to the `deliveries` table. Nothing here raises to the caller: a failure is a log row.

Testing hook: `app.state.delivery_senders` is an optional dict {channel: async sender}. A sender in
it replaces the real one (and is used even in fixture mode, which otherwise never sends).
"""

from __future__ import annotations

import asyncio
import logging
import smtplib

import httpx

logger = logging.getLogger("openterm.delivery")

TIMEOUT_S = 10.0  # one attempt, per channel
RETRY_DELAY_S = 2.0  # wait before the single retry; tests patch this to 0


class DeliveryError(Exception):
    """A send failed for a reason retrying will not fix (bad URL, no TLS, HTTP 4xx). The text is shown in the log."""


# Errors worth ONE retry: the network blinked. Everything else (bad credentials, refused TLS) fails at once.
NETWORK_ERRORS = (OSError, httpx.TransportError, smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError)

# channel -> (key name in the key store or None, fields shown in the KEY REQUIRED message, setting that must be filled)
NEEDS = {
    "email": ("smtp", "SMTP_HOST/PORT/USER/PASSWORD", "email_to"),
    "telegram": ("telegram", "TELEGRAM_BOT_TOKEN", "telegram_chat_id"),
    "webhook": ("webhook", "ALERT_WEBHOOK_URL", None),
}


def _default_senders() -> dict:
    # imported here, not at the top: the submodules import DeliveryError from this file
    from . import email, telegram, webhook

    return {"email": email.send, "telegram": telegram.send, "webhook": webhook.send}


async def _attempt(sender, app, values, cfg, subject, text, extra) -> None:
    """One send with a timeout, plus one retry after RETRY_DELAY_S when the failure was a network error."""
    for attempt in (1, 2):
        try:
            await asyncio.wait_for(sender(app, values, cfg, subject, text, extra), TIMEOUT_S)
            return
        except NETWORK_ERRORS:
            if attempt == 2:
                raise
            await asyncio.sleep(RETRY_DELAY_S)


async def _run_channel(app, channel: str, cfg: dict, kind: str, ref: str, subject: str, text: str, extra: dict) -> dict:
    """Runs one channel and logs it. Returns {channel, status, detail}; never raises."""
    from . import log as dlog

    key_name, key_label, needed = NEEDS[channel]
    override = getattr(app.state, "delivery_senders", {}).get(channel)
    values = None
    try:
        if app.state.keys.get(key_name) is None:
            status, detail = "skipped", f"KEY REQUIRED: set {key_label} in APIKEYS"
        elif needed and not cfg.get(needed):
            status, detail = "skipped", f"SET {needed} IN DELIVERY SETTINGS"
        elif override is None and app.state.settings.openterm_fixtures:
            status, detail = "skipped", "FIXTURE MODE"
        else:
            values = app.state.keys.get(key_name)
            await _attempt(override or _default_senders()[channel], app, values, cfg, subject, text, extra)
            status, detail = "sent", None
    except TimeoutError:
        status, detail = "failed", f"TIMED OUT AFTER {TIMEOUT_S:g} s"
    except Exception as e:  # noqa: BLE001 - a delivery failure must become a log row, never an exception in the caller
        status, detail = "failed", f"{type(e).__name__}: {e}" if not isinstance(e, DeliveryError) else str(e)
    try:
        await dlog.add(app.state.userdata.db, kind, ref, channel, status, detail)
    except Exception:  # noqa: BLE001 - the database may be closing at shutdown
        logger.warning("delivery log write failed for %s", channel)
    return {"channel": channel, "status": status, "detail": dlog.clean(detail)}


async def dispatch(app, kind: str, ref, subject: str, text: str, extra: dict | None = None,
                   channels: list[str] | None = None) -> list[dict]:
    """Sends to every enabled push channel (or just `channels`, used by the test route) and logs each one."""
    from . import settings as dsettings

    cfg = await dsettings.get(app.state.userdata.db)
    chosen = channels if channels is not None else [c for c in dsettings.PUSH if cfg["channels"].get(c)]
    if not chosen:
        return []
    return list(await asyncio.gather(*(
        _run_channel(app, c, cfg, kind, str(ref), subject, text, extra or {}) for c in chosen)))


def spawn(app, kind: str, ref, subject: str, text: str, extra: dict | None = None) -> asyncio.Task:
    """Runs `dispatch` in the background. The task is kept in a set on app.state so it is not garbage collected."""
    tasks = getattr(app.state, "delivery_tasks", None)
    if tasks is None:
        tasks = app.state.delivery_tasks = set()
    task = asyncio.create_task(dispatch(app, kind, ref, subject, text, extra))
    tasks.add(task)
    task.add_done_callback(tasks.discard)
    return task
