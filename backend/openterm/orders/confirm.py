"""One-time confirm tokens. `issue(fingerprint)` is called by the preview step after the mandate passed; `consume` is called by submit.

A token is bound to a fingerprint (the whole order plus mode and account), expires after TTL seconds, works once, and is burned by any
failed attempt (a wrong order presented with a right token cannot be retried with it). Held in memory only: a restart voids every token.
"""

from __future__ import annotations

import secrets
import time

from .errors import OrderError

TTL = 60.0
MAX_OPEN = 50


class ConfirmTokens:
    def __init__(self, clock=time.monotonic, ttl: float = TTL):
        self.clock = clock
        self.ttl = ttl
        self._open: dict[str, tuple[str, float]] = {}

    def _sweep(self) -> None:
        now = self.clock()
        for t in [t for t, (_, exp) in self._open.items() if exp <= now]:
            del self._open[t]
        while len(self._open) > MAX_OPEN:
            del self._open[next(iter(self._open))]

    def issue(self, fp: str) -> tuple[str, float]:
        self._sweep()
        token = secrets.token_urlsafe(24)
        self._open[token] = (fp, self.clock() + self.ttl)
        return token, self.ttl

    def consume(self, token, fp: str) -> None:
        self._sweep()
        if not isinstance(token, str) or not token:
            raise OrderError("confirm_required", "CONFIRM REQUIRED: PREVIEW THE ORDER AND CONFIRM IT (NO CONFIRM TOKEN)")
        got = self._open.pop(token, None)  # popped first: single use, and burned on a mismatch
        if got is None:
            raise OrderError("confirm_required", "CONFIRM TOKEN IS UNKNOWN, USED OR EXPIRED: PREVIEW AND CONFIRM AGAIN")
        if got[0] != fp:
            raise OrderError("confirm_required", "CONFIRM TOKEN WAS ISSUED FOR A DIFFERENT ORDER: PREVIEW AND CONFIRM AGAIN")

    def clear(self) -> None:
        self._open.clear()
