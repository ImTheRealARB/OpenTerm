"""Webhook channel (Slack / Discord style) (Phase 17 B). The URL is a secret, so it is a key."""

from __future__ import annotations

import ipaddress
import os
from urllib.parse import urlparse

import httpx

from . import DeliveryError, RetryableError

LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}
APP_PORT = 8000  # this app's own port: a webhook must never point back at it
ALLOW_LOCAL_ENV = "OPENTERM_ALLOW_LOCAL_WEBHOOK"


def _private_host(host: str) -> bool:
    """A name or address that points inside this machine or its network (audit D-4: server-side request forgery,
    where the backend is tricked into calling a service the outside world cannot reach). Checks address literals
    and well-known names only; a public DNS name that secretly resolves to a private address is not caught, because
    resolving names here would add network calls to a pure check."""
    if host == "localhost" or host.endswith((".localhost", ".internal", ".local")):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return not ip.is_global  # loopback, 10/8, 172.16/12, 192.168/16, 169.254/16 (cloud metadata), unspecified, reserved


def check_url(url: str) -> str:
    """https to a public host only. A receiver on this machine (http://127.0.0.1:<port>) needs OPENTERM_ALLOW_LOCAL_WEBHOOK=1
    and is never allowed to be this app's own port."""
    u = urlparse(url)
    host = (u.hostname or "").lower()
    if not host or u.scheme not in ("http", "https"):
        raise DeliveryError("WEBHOOK URL MUST BE https")
    if _private_host(host):
        if u.scheme == "http" and host in LOOPBACK_HOSTS and os.environ.get(ALLOW_LOCAL_ENV) == "1":
            if (u.port or 80) == APP_PORT:
                raise DeliveryError(f"WEBHOOK MUST NOT POINT AT OPENTERM ITSELF (PORT {APP_PORT})")
            return url
        raise DeliveryError(f"WEBHOOK MUST BE A PUBLIC https HOST (local receivers need {ALLOW_LOCAL_ENV}=1)")
    if u.scheme != "https":
        raise DeliveryError("WEBHOOK URL MUST BE https")
    return url


async def send(app, values: dict, cfg: dict, subject: str, text: str, extra: dict) -> None:
    url = check_url(values["ALERT_WEBHOOK_URL"])
    http: httpx.AsyncClient = app.state.keys_http
    # "text" is Slack's field, "content" is Discord's; sending both works for either.
    body = {**extra, "text": f"{subject}\n{text}", "content": f"{subject}\n{text}", "subject": subject}
    r = await http.post(url, json=body, timeout=10.0)
    if r.status_code == 429 or r.status_code >= 500:  # temporary: the retry loop tries again later
        try:
            wait = float(r.headers.get("retry-after", ""))  # seconds form only; a date form falls back to the schedule
        except ValueError:
            wait = None
        raise RetryableError(f"WEBHOOK HTTP {r.status_code}", retry_after=wait)
    if not 200 <= r.status_code < 300:
        raise DeliveryError(f"WEBHOOK HTTP {r.status_code}")
