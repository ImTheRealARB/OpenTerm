"""Errors the SDK raises. They carry the words OpenTerm itself uses (`KEY REQUIRED`, `PROVIDER DOWN`), never made-up data.

Every error is an `OpenTermError`, so `except OpenTermError` catches all of them. A pinned source that cannot answer
(`source="nasdaq"`) raises one of these with `.source` set, and its text starts with `SRC=NASDAQ:`.
"""

from __future__ import annotations

import re


class OpenTermError(Exception):
    """kind: OpenTerm's error word (not_found, unavailable, key_required, bad_request, login_expired ...); status: HTTP status or 0."""

    def __init__(self, message: str, *, kind: str = "error", status: int = 0, detail: str | None = None,
                 key: str | None = None, source: str | None = None):
        super().__init__(message)
        self.message = message
        self.kind = kind
        self.status = status
        self.detail = detail
        self.key = key
        self.source = source  # the pinned source the message names (SRC=NAME), if any

    def __str__(self) -> str:
        return f"{self.message} ({self.detail})" if self.detail else self.message


class KeyRequired(OpenTermError):
    """The source needs an API key. `.key` names it; set it in OpenTerm's APIKEYS screen (the SDK never sees or sends keys)."""


class ProviderDown(OpenTermError):
    """The source (or every source that could answer) is down or blocked. Retry later; nothing was made up."""


class NoData(OpenTermError):
    """The source is up but has nothing for this symbol or series."""


class BadRequest(OpenTermError):
    """The request cannot be served as asked (bad symbol, unknown source, a source that does not serve this data, bad filter)."""


class LoginRequired(OpenTermError):
    """A broker login (Kite) is missing or expired. Run KITE LOGIN in OpenTerm."""


class BackendDown(OpenTermError):
    """No OpenTerm answered at the address. Start it first (`openterm`, or the desktop app)."""


_BY_KIND: dict[str, type[OpenTermError]] = {
    "key_required": KeyRequired,
    "unavailable": ProviderDown,
    "not_found": NoData,
    "bad_request": BadRequest,
    "login_expired": LoginRequired,
    "login_required": LoginRequired,
}
_SRC = re.compile(r"^SRC=([A-Z0-9_]+)", re.IGNORECASE)


def from_reply(status: int, body: object) -> OpenTermError:
    """The right error for an OpenTerm error answer `{"error", "kind", "detail", "key"}` (any other body becomes a plain error)."""
    if not isinstance(body, dict):
        return OpenTermError(f"HTTP {status}", status=status)
    message = str(body.get("error") or f"HTTP {status}")
    kind = str(body.get("kind") or "error")
    key = body.get("key")
    detail = body.get("detail")
    if kind == "key_required":
        message = f"KEY REQUIRED: set {key} in APIKEYS" if key else "KEY REQUIRED"
        detail = None
    m = _SRC.match(message)
    return _BY_KIND.get(kind, OpenTermError)(
        message, kind=kind, status=status, detail=str(detail) if detail else None,
        key=str(key) if key else None, source=m.group(1).lower() if m else None,
    )


class StaleData(OpenTermError):
    """Raised only when the client was built with `raise_on_stale=True` and OpenTerm answered from its stale cache.

    The default is to return the data and set `df.attrs["stale"] = True` (with `age_s`): OpenTerm refreshes in the
    background, and a stale answer is always labelled, never dressed up as fresh.
    """
