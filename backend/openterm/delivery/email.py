"""Email channel (SMTP) and the shared TLS helper (Phase 17 B).

`smtp_connect` is used by both the sender below and `keys._smtp_check`, so the key test and the real
send trust exactly the same things: certificates are always verified, and a server that cannot
encrypt is refused unless it is on this machine (a local relay such as MailHog).
"""

from __future__ import annotations

import asyncio
import smtplib
import ssl
from email.message import EmailMessage  # stdlib `email` (absolute import), not this module

from . import DeliveryError

LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def smtp_connect(host: str, port: int, user: str, password: str, timeout: float = 10) -> smtplib.SMTP:
    """Opens an encrypted, logged-in SMTP connection. The caller closes it."""
    ctx = ssl.create_default_context()  # verifies the certificate chain and the host name
    s = None
    try:
        if port == 465:  # implicit TLS: the connection is encrypted from the first byte
            s = smtplib.SMTP_SSL(host, port, timeout=timeout, context=ctx)
            s.ehlo()
        else:  # explicit TLS: plain connect, then upgrade with STARTTLS
            s = smtplib.SMTP(host, port, timeout=timeout)
            s.ehlo()
            if s.has_extn("starttls"):
                s.starttls(context=ctx)
                s.ehlo()
            elif host not in LOOPBACK_HOSTS:
                raise DeliveryError("SMTP SERVER OFFERS NO TLS")
        if user:
            s.login(user, password)
        return s
    except ssl.SSLCertVerificationError:
        _close(s)
        raise DeliveryError("SMTP TLS CERTIFICATE NOT TRUSTED") from None
    except BaseException:
        _close(s)
        raise


def _close(s) -> None:
    if s is not None:
        try:
            s.close()
        except Exception:  # noqa: BLE001, S110 - closing a half-open connection must never hide the real error
            pass


def build_message(sender: str, to: str, subject: str, text: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = sender, to, subject.replace("\n", " ")
    msg.set_content(text)
    return msg


def send_sync(values: dict, to: str, subject: str, text: str, connect=None) -> None:
    """Blocking send. `connect` is injectable so tests can pass a fake SMTP; default is `smtp_connect`."""
    connect = connect or smtp_connect
    s = connect(values["SMTP_HOST"], int(values["SMTP_PORT"]), values["SMTP_USER"], values["SMTP_PASSWORD"], 10)
    try:
        s.send_message(build_message(values["SMTP_USER"], to, subject, text))
    finally:
        _close(s)


async def send(app, values: dict, cfg: dict, subject: str, text: str, extra: dict) -> None:
    # smtplib blocks, so it runs in a worker thread and the event loop stays free
    await asyncio.to_thread(send_sync, values, cfg["email_to"], subject, text)
