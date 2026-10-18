"""Secret redaction for logs, error text and API responses (Phase 11).

`redact(text)` masks every known secret value (registered by the key store) and common key shapes in URLs and
headers, so a key never reaches /api/log, an error body, SOURCES or stderr.
"""

import logging
import re

MIN_SECRET = 8
_SECRETS: set[str] = set()

_PATTERNS = [
    (re.compile(r"(?i)\b(token|apikey|api_key|access_token|key|secret)=([^&\s\"']+)"), r"\1=***"),
    (re.compile(r"(?i)(authorization:\s*bearer\s+)\S+"), r"\1***"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"), "***"),
]


def register(values) -> None:
    """Adds secret values to the global set (values shorter than MIN_SECRET are ignored)."""
    _SECRETS.update(v for v in values if v and len(v) >= MIN_SECRET)


def unregister(values) -> None:
    _SECRETS.difference_update(values)


def redact(text: str, secrets=None) -> str:
    if not text:
        return text
    pool = _SECRETS if secrets is None else {s for s in secrets if s and len(s) >= MIN_SECRET}
    for s in sorted(pool, key=len, reverse=True):
        if s in text:
            text = text.replace(s, "***")
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001 - a bad format string is the logger's problem, not ours
            return True
        clean = redact(msg)
        if clean != msg:
            record.msg, record.args = clean, None
        return True


_FILTER = RedactFilter()


def install() -> None:
    """Filters the ring buffer, every root handler and the HTTP client loggers (which log full URLs)."""
    from . import logbuf

    targets: list[logging.Filterer] = [logging.getLogger(n) for n in ("openterm", "httpx", "httpcore")]
    targets += logging.getLogger().handlers
    targets += [h for h in logging.getLogger("openterm").handlers if isinstance(h, logbuf.RingHandler)]
    for t in targets:
        if _FILTER not in t.filters:
            t.addFilter(_FILTER)
