"""Alert delivery (Phase 17 B, extended in Phase 20): push a fired alert to email, Telegram or a webhook, and log every attempt.

Flow: a route that fires an alert calls `spawn(...)` (a background task, so the HTTP answer is never
delayed) -> `dispatch` reads the settings, runs each enabled channel on its own and writes one row per
channel to the `deliveries` table. Nothing here raises to the caller: a failure is a log row.

Phase 20 additions:
- Retry with backoff. The FIRST attempt runs inline. If it fails for a temporary reason (network blip, HTTP 429,
  HTTP 5xx, SMTP 4xx) the row is logged as `retrying` and a background task tries again after 30 s, 2 min and
  10 min, then rewrites the same row to `sent` or `failed`. A failing channel therefore never keeps the caller
  waiting. The retry queue lives in memory: a restart forgets pending retries (the row is left as `retrying`).
- A daily cap per channel (`daily_cap` in the delivery settings, default 50). The over-cap send is logged as
  `skipped` with the reason, never dropped silently.
- Configured recipients and chat ids are blanked out of every stored or returned error text.

Testing hooks: `app.state.delivery_senders` is an optional dict {channel: async sender}. A sender in
it replaces the real one (and is used even in fixture mode, which otherwise never sends). `sleep` and `now`
below are module globals so tests can fake the clock instead of waiting minutes.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import smtplib
import time

import httpx

logger = logging.getLogger("openterm.delivery")

TIMEOUT_S = 10.0  # one attempt, per channel
# Wait before retry 1, 2 and 3. After the third retry fails the row becomes `failed` (4 attempts in all).
BACKOFF_S = (30.0, 120.0, 600.0)

# Injectable clock and sleeper (tests replace these; production uses the real ones).
sleep = asyncio.sleep
now = time.time


class DeliveryError(Exception):
    """A send failed for a reason retrying will not fix (bad URL, no TLS, HTTP 4xx). The text is shown in the log."""


class RetryableError(DeliveryError):
    """A send failed for a temporary reason (HTTP 429 / 5xx). `retry_after` = seconds the server asked us to wait."""

    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


# Errors worth a retry: the network blinked. Everything else (bad credentials, refused TLS) fails at once.
NETWORK_ERRORS = (OSError, httpx.TransportError, smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError)


def is_retryable(e: BaseException) -> bool:
    """Temporary failure? Network errors, a RetryableError (429 / 5xx), or an SMTP 4xx 'try again later' answer.

    smtplib's errors are all OSErrors, so they must be sorted BEFORE the generic OSError rule: a 535 (bad password)
    or 550 (no such mailbox) will never succeed later, while 4xx codes and a dropped connection might.
    """
    if isinstance(e, smtplib.SMTPResponseException):
        return 400 <= e.smtp_code < 500
    if isinstance(e, smtplib.SMTPServerDisconnected):
        return True
    if isinstance(e, smtplib.SMTPException):  # recipients refused, auth failed, no STARTTLS support, ...
        return False
    return isinstance(e, (*NETWORK_ERRORS, RetryableError))


# channel -> (key name in the key store or None, fields shown in the KEY REQUIRED message, setting that must be filled)
NEEDS = {
    "email": ("smtp", "SMTP_HOST/PORT/USER/PASSWORD", "email_to"),
    "telegram": ("telegram", "TELEGRAM_BOT_TOKEN", "telegram_chat_id"),
    "webhook": ("webhook", "ALERT_WEBHOOK_URL", None),
}

# Key-store fields that are secret (or reveal who we write to). Their VALUES are scrubbed from stored error text.
_SECRET_FIELD_HINTS = ("TOKEN", "PASSWORD", "URL", "USER")


def _default_senders() -> dict:
    # imported here, not at the top: the submodules import DeliveryError from this file
    from . import email, telegram, webhook

    return {"email": email.send, "telegram": telegram.send, "webhook": webhook.send}


def _secrets(app, cfg: dict) -> list[str]:
    """Values that must never reach a log row or an API answer: recipient, chat id, tokens, passwords, webhook URL.

    Taken from EVERY channel's keys, not just the one that failed: a proxy or relay error can quote anything.
    """
    out = [cfg.get("email_to") or "", cfg.get("telegram_chat_id") or ""]
    for key_name, _label, _needed in NEEDS.values():
        values = app.state.keys.get(key_name)
        if isinstance(values, dict):
            out += [str(v) for k, v in values.items() if any(h in k.upper() for h in _SECRET_FIELD_HINTS)]
    return [s for s in out if s]


def _describe(e: BaseException) -> str:
    """One line for the log. A DeliveryError carries its own readable text; others get their class name."""
    if isinstance(e, TimeoutError):
        return f"TIMED OUT AFTER {TIMEOUT_S:g} s"
    return str(e) if isinstance(e, DeliveryError) else f"{type(e).__name__}: {e}"


async def _once(sender, app, values, cfg, subject, text, extra) -> None:
    """One send attempt with a timeout. Raises whatever the sender raises."""
    await asyncio.wait_for(sender(app, values, cfg, subject, text, extra), TIMEOUT_S)


# --- daily cap -------------------------------------------------------------------------------------------------


def _today() -> str:
    return dt.datetime.fromtimestamp(now()).date().isoformat()  # the machine's local day


async def _take_slot(app, channel: str, cap: int) -> bool:
    """Counts one send against today's cap for `channel`. False = the cap is used up (nothing is counted).

    The counter lives in kv (`delivery_sent:<channel>` = {day, n}) and not in the deliveries log, because the log
    keeps only 500 rows: a flood of skipped rows would push old `sent` rows out and quietly reset the count.
    A lock makes read-then-write atomic for two alerts firing at the same moment.
    """
    lock = getattr(app.state, "delivery_cap_lock", None)
    if lock is None:
        lock = app.state.delivery_cap_lock = asyncio.Lock()
    db = app.state.userdata.db
    key = f"delivery_sent:{channel}"
    async with lock:
        async with db.execute("SELECT value FROM kv WHERE key=?", (key,)) as cur:
            row = await cur.fetchone()
        today = _today()
        state = json.loads(row[0]) if row else {}
        n = state["n"] if state.get("day") == today else 0  # a new day starts again at 0
        if n >= cap:
            return False
        await db.execute("INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                         (key, json.dumps({"day": today, "n": n + 1})))
        await db.commit()
        return True


# --- retry in the background -----------------------------------------------------------------------------------


def _track(app, task: asyncio.Task) -> None:
    """Keeps a reference so the task is not garbage collected while it sleeps."""
    tasks = getattr(app.state, "delivery_tasks", None)
    if tasks is None:
        tasks = app.state.delivery_tasks = set()
    tasks.add(task)
    task.add_done_callback(tasks.discard)


async def _retry_later(app, row_id: int, secrets: list[str], sender, values, cfg, subject, text, extra,
                       first_error: BaseException) -> None:
    """Retries after each BACKOFF_S step, updating the one log row. Never raises."""
    from . import log as dlog

    db = app.state.userdata.db
    err = first_error
    status, detail = "failed", None
    try:
        for n, step in enumerate(BACKOFF_S, start=1):
            # a 429 can ask for longer than the schedule: honour whichever is longer
            wait = max(step, float(getattr(err, "retry_after", None) or 0))
            await sleep(wait)
            try:
                await _once(sender, app, values, cfg, subject, text, extra)
                status, detail = "sent", None
                break
            except Exception as e:  # noqa: BLE001 - becomes a log row
                err = e
                if not is_retryable(e):
                    status, detail = "failed", _describe(e)
                    break
                if n < len(BACKOFF_S):
                    status, detail = "retrying", f"{_describe(e)}; RETRY {n + 1} OF {len(BACKOFF_S)} NEXT"
                    await dlog.update(db, row_id, status, detail, secrets)
                else:
                    status, detail = "failed", f"GAVE UP AFTER {len(BACKOFF_S) + 1} ATTEMPTS: {_describe(e)}"
        await dlog.update(db, row_id, status, detail, secrets)
    except asyncio.CancelledError:  # shutdown: say so in the row, then let the cancellation through
        try:
            await dlog.update(db, row_id, "failed", "INTERRUPTED BY SHUTDOWN", secrets)
        except Exception:  # noqa: BLE001, S110 - the database may already be closed
            pass
        raise
    except Exception:  # noqa: BLE001 - e.g. the database closed under us
        logger.warning("delivery retry bookkeeping failed for row %s", row_id)


async def _run_channel(app, channel: str, cfg: dict, kind: str, ref: str, subject: str, text: str, extra: dict) -> dict:
    """Runs one channel and logs it. Returns {channel, status, detail}; never raises."""
    from . import log as dlog

    key_name, key_label, needed = NEEDS[channel]
    override = getattr(app.state, "delivery_senders", {}).get(channel)
    values = None
    sender = None
    retry_error: BaseException | None = None
    # A per-channel copy, so a sender may keep progress notes in it (Telegram remembers which parts were sent,
    # so a retry does not post part 1 twice) without leaking them into another channel's payload.
    ch_extra = dict(extra)
    try:
        if app.state.keys.get(key_name) is None:
            status, detail = "skipped", f"KEY REQUIRED: set {key_label} in APIKEYS"
        elif needed and not cfg.get(needed):
            status, detail = "skipped", f"SET {needed} IN DELIVERY SETTINGS"
        elif override is None and app.state.settings.openterm_fixtures:
            status, detail = "skipped", "FIXTURE MODE"
        else:
            values = app.state.keys.get(key_name)
            cap = int(cfg.get("daily_cap", 50))
            if not await _take_slot(app, channel, cap):
                status, detail = "skipped", f"DAILY CAP OF {cap} REACHED FOR {channel.upper()}; RESETS AT MIDNIGHT"
            else:
                sender = override or _default_senders()[channel]
                try:
                    await _once(sender, app, values, cfg, subject, text, ch_extra)
                    status, detail = "sent", None
                except Exception as e:  # classified just below: retryable or re-raised
                    if not is_retryable(e):
                        raise
                    retry_error = e
                    status, detail = "retrying", f"{_describe(e)}; RETRY 1 OF {len(BACKOFF_S)} IN {BACKOFF_S[0]:g} s"
    except Exception as e:  # noqa: BLE001 - a delivery failure must become a log row, never an exception in the caller
        status, detail = "failed", _describe(e)
    secrets = _secrets(app, cfg)
    row_id = None
    try:
        row_id = await dlog.add(app.state.userdata.db, kind, ref, channel, status, detail, secrets)
    except Exception:  # noqa: BLE001 - the database may be closing at shutdown
        logger.warning("delivery log write failed for %s", channel)
    if retry_error is not None and row_id is not None:
        _track(app, asyncio.create_task(
            _retry_later(app, row_id, secrets, sender, values, cfg, subject, text, ch_extra, retry_error)))
    return {"channel": channel, "status": status, "detail": dlog.clean(detail, secrets)}


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
    task = asyncio.create_task(dispatch(app, kind, ref, subject, text, extra))
    _track(app, task)
    return task
