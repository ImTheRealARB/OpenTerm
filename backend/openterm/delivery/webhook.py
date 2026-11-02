"""Webhook channel (Slack / Discord style) (Phase 17 B). The URL is a secret, so it is a key."""

from __future__ import annotations

from urllib.parse import urlparse

import httpx

from . import DeliveryError

LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def check_url(url: str) -> str:
    """https only; plain http is allowed just for this machine (a local test receiver)."""
    u = urlparse(url)
    if u.scheme == "https" and u.hostname:
        return url
    if u.scheme == "http" and u.hostname in LOOPBACK_HOSTS:
        return url
    raise DeliveryError("WEBHOOK URL MUST BE https (http ONLY FOR LOOPBACK)")


async def send(app, values: dict, cfg: dict, subject: str, text: str, extra: dict) -> None:
    url = check_url(values["ALERT_WEBHOOK_URL"])
    http: httpx.AsyncClient = app.state.keys_http
    # "text" is Slack's field, "content" is Discord's; sending both works for either.
    body = {**extra, "text": f"{subject}\n{text}", "content": f"{subject}\n{text}", "subject": subject}
    r = await http.post(url, json=body, timeout=10.0)
    if not 200 <= r.status_code < 300:
        raise DeliveryError(f"WEBHOOK HTTP {r.status_code}")
