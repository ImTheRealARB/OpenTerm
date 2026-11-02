"""Telegram channel: Bot API `sendMessage`, plain text (Phase 17 B)."""

from __future__ import annotations

import httpx

from . import DeliveryError


async def send(app, values: dict, cfg: dict, subject: str, text: str, extra: dict) -> None:
    # Reuse the app's shared HTTP client (fixture transport in fixture mode, the real one otherwise).
    http: httpx.AsyncClient = app.state.keys_http
    url = f"https://api.telegram.org/bot{values['TELEGRAM_BOT_TOKEN']}/sendMessage"
    r = await http.post(url, json={"chat_id": cfg["telegram_chat_id"], "text": f"{subject}\n\n{text}"[:4000],
                                   "disable_web_page_preview": True}, timeout=10.0)
    if r.status_code != 200:
        # Telegram's error body is JSON with a human description; it does not contain the token.
        raise DeliveryError(f"TELEGRAM HTTP {r.status_code}: {r.text[:160]}")
