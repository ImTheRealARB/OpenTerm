"""Webhook channel (Slack / Discord style) (Phase 17 B). The URL is a secret, so it is a key."""

from __future__ import annotations

import os
from urllib.parse import urlparse

import httpx

from .. import netguard
from . import DeliveryError, RetryableError

LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}
ALLOW_LOCAL_ENV = "OPENTERM_ALLOW_LOCAL_WEBHOOK"
RESOLVER: netguard.Resolver | None = None  # tests replace this so no test touches DNS; None = the system resolver


def _app_port() -> int:
    """This app's own port (a webhook must never point back at it), from the same setting the server was started with."""
    from ..config import get_settings

    return get_settings().openterm_port


def _private_host(host: str) -> bool:
    """A name or address that points inside this machine or its network (audit D-4: server-side request forgery,
    where the backend is tricked into calling a service the outside world cannot reach). This pure check covers address
    literals and local names; `send` also resolves the name and checks every address (audit C-03)."""
    return netguard.private_host(host)  # shared with the AI web tools: loopback, private, link-local (cloud metadata), CGNAT, mapped IPv4, odd spellings


def check_url(url: str) -> str:
    """https to a public host only. A receiver on this machine (http://127.0.0.1:<port>) needs OPENTERM_ALLOW_LOCAL_WEBHOOK=1
    and is never allowed to be this app's own port."""
    u = urlparse(url)
    host = (u.hostname or "").lower()
    if not host or u.scheme not in ("http", "https"):
        raise DeliveryError("WEBHOOK URL MUST BE https")
    if _private_host(host):
        if u.scheme == "http" and host in LOOPBACK_HOSTS and os.environ.get(ALLOW_LOCAL_ENV) == "1":
            if (u.port or 80) == _app_port():
                raise DeliveryError(f"WEBHOOK MUST NOT POINT AT OPENTERM ITSELF (PORT {_app_port()})")
            return url
        raise DeliveryError(f"WEBHOOK MUST BE A PUBLIC https HOST (local receivers need {ALLOW_LOCAL_ENV}=1)")
    if u.scheme != "https":
        raise DeliveryError("WEBHOOK URL MUST BE https")
    return url


async def send(app, values: dict, cfg: dict, subject: str, text: str, extra: dict) -> None:
    url = check_url(values["ALERT_WEBHOOK_URL"])
    u = urlparse(url)
    # A local receiver already passed the explicit opt-in in check_url. Anything else must RESOLVE to public addresses only:
    # `127.0.0.1.nip.io` is a public-looking name that answers 127.0.0.1. (The HTTP client resolves again when it connects, so a
    # name that changes its answer between the two lookups is not stopped here; webfetch pins the address, a webhook cannot because of TLS.)
    if (u.hostname or "").lower() not in LOOPBACK_HOSTS:
        try:
            await netguard.public_addresses(u.hostname or "", u.port or (443 if u.scheme == "https" else 80), RESOLVER)
        except netguard.Blocked as e:
            raise DeliveryError(f"WEBHOOK HOST REFUSED: {e}") from None
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
