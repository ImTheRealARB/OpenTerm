"""Telegram channel: Bot API `sendMessage` with MarkdownV2 (Phase 17 B, MarkdownV2 + splitting in Phase 20).

Three details Telegram forces on us:
- MarkdownV2 treats ~20 punctuation characters as formatting, so every one in our text must be escaped with a
  backslash (`escape_mdv2`), or Telegram answers HTTP 400 "can't parse entities" and the alert is lost.
- One message holds at most 4,096 characters, so long text is split into several messages, cutting between lines
  (`split_message`) and only inside a line when that single line is longer than the limit.
- HTTP 429 means "slow down" and says how long in `parameters.retry_after` seconds. That becomes a
  `RetryableError`, and the retry loop in `delivery/__init__.py` waits at least that long.
"""

from __future__ import annotations

import re
from collections.abc import Callable

import httpx

from . import DeliveryError, RetryableError

TG_LIMIT = 4096  # Telegram's maximum message length (characters, after parsing)

# Every character MarkdownV2 reserves, from the Bot API docs: _ * [ ] ( ) ~ ` > # + - = | { } . !  and the backslash.
_MDV2_SPECIAL = re.compile(r"([_*\[\]()~`>#+\-=|{}.!\\])")


def escape_mdv2(text: str) -> str:
    """Puts a backslash before every MarkdownV2 special character so Telegram shows the text literally."""
    return _MDV2_SPECIAL.sub(r"\\\1", text)  # "\\" = a literal backslash, "\1" = the matched character


def split_message(text: str, limit: int = TG_LIMIT, cost: Callable[[str], int] = len) -> list[str]:
    """Cuts `text` into pieces whose `cost` is at most `limit`, preferring to cut between lines.

    `cost` measures a piece as Telegram will see it; for MarkdownV2 that is the ESCAPED length, because each
    backslash counts. A line longer than the limit is cut character by character (never leaving a half escape,
    because we measure and cut the raw text and escape afterwards).
    """
    chunks: list[str] = []
    cur: list[str] = []
    cur_cost = 0
    for line in text.split("\n"):
        c = cost(line)
        if c > limit:  # one line alone does not fit: flush, then slice it
            if cur:
                chunks.append("\n".join(cur))
                cur, cur_cost = [], 0
            piece, piece_cost = "", 0
            for ch in line:
                cc = cost(ch)
                if piece_cost + cc > limit:
                    chunks.append(piece)
                    piece, piece_cost = "", 0
                piece += ch
                piece_cost += cc
            if piece:
                cur, cur_cost = [piece], piece_cost  # the tail may still share a message with the next lines
            continue
        joined = c + (1 if cur else 0)  # +1 for the newline between lines
        if cur_cost + joined > limit:
            chunks.append("\n".join(cur))
            cur, cur_cost = [line], c
        else:
            cur.append(line)
            cur_cost += joined
    if cur:
        chunks.append("\n".join(cur))
    return [c for c in chunks if c.strip()]


def build_messages(subject: str, text: str) -> list[str]:
    """Ready-to-send MarkdownV2 strings: the first starts with the subject in bold, all escaped, all <= 4,096."""
    header = f"*{escape_mdv2(subject.strip()[:200])}*\n\n"
    # Reserve the header's room in every part so the first one fits; a little unused room elsewhere is harmless.
    parts = split_message(text, TG_LIMIT - len(header), cost=lambda s: len(escape_mdv2(s))) or [""]
    out = [escape_mdv2(p) for p in parts]
    out[0] = header + out[0]
    return out


def _retry_after(r: httpx.Response) -> float | None:
    try:
        return float(r.json()["parameters"]["retry_after"])
    except (ValueError, KeyError, TypeError):
        return None


async def send(app, values: dict, cfg: dict, subject: str, text: str, extra: dict) -> None:
    # Reuse the app's shared HTTP client (fixture transport in fixture mode, the real one otherwise).
    http: httpx.AsyncClient = app.state.keys_http
    url = f"https://api.telegram.org/bot{values['TELEGRAM_BOT_TOKEN']}/sendMessage"
    parts = build_messages(subject, text)
    # `extra` is this channel's private copy and survives retries: remember how many parts already went out,
    # so a 429 on part 3 retries part 3 and does not post parts 1 and 2 again.
    for i in range(extra.get("_tg_sent", 0), len(parts)):
        r = await http.post(url, json={"chat_id": cfg["telegram_chat_id"], "text": parts[i],
                                       "parse_mode": "MarkdownV2", "disable_web_page_preview": True}, timeout=10.0)
        if r.status_code == 429:
            raise RetryableError("TELEGRAM HTTP 429: RATE LIMITED", retry_after=_retry_after(r))
        if r.status_code >= 500:
            raise RetryableError(f"TELEGRAM HTTP {r.status_code}: SERVER ERROR")
        if r.status_code != 200:
            # Telegram's error body is JSON with a human description; it does not contain the token.
            raise DeliveryError(f"TELEGRAM HTTP {r.status_code}: {r.text[:160]}")
        extra["_tg_sent"] = i + 1
