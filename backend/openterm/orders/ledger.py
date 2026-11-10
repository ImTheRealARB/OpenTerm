"""Every order event goes into the hash-chained audit ledger (ai/audit.py, table `ai_ledger`) as kind `order`.

Entry: ref = our client order id (or the event name for account-level events), model = `<broker>:<mode>`, manifest = {event, app, broker, mode,
account tail}, meta = the event's facts (order fields, check results, broker order id, error text). Never a key, token or confirm token.
Error text is redacted. A ledger failure is logged and re-raised only for the events that must not happen unrecorded (see service.submit).
"""

from __future__ import annotations

import logging

from .. import __version__
from ..ai.audit import AuditLog
from ..redact import redact

log = logging.getLogger("openterm.orders.ledger")
KIND = "order"
EVENTS = ("confirm_issued", "refused", "submitted", "accepted", "failed", "cancel", "cancel_failed", "replace", "kill_on", "kill_off", "kill_cancel_all",
          "live_on", "live_off", "mandate_changed", "import_fills")


def clean(v):
    """Strings are redacted and clipped; containers are cleaned recursively."""
    if isinstance(v, str):
        return redact(v)[:400]
    if isinstance(v, dict):
        return {str(k): clean(x) for k, x in v.items()}
    if isinstance(v, list | tuple):
        return [clean(x) for x in v[:100]]
    return v


class OrderLedger:
    def __init__(self, audit: AuditLog):
        self.audit = audit

    async def event(self, event: str, broker: str = "-", mode: str = "-", ref: str | None = None, account: str = "", **meta) -> dict:
        assert event in EVENTS, event
        mf = {"event": event, "app": __version__, "broker": broker, "mode": mode, "account": ("…" + account[-4:]) if account else ""}
        return await self.audit.append(KIND, ref or event, f"{broker}:{mode}", mf, clean(meta))
