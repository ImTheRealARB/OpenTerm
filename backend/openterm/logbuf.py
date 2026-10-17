"""Structured log ring buffer behind the LOG panel (/api/log)."""

import logging
from collections import deque
from itertools import count

_seq = count(1)
RECORDS: deque[dict] = deque(maxlen=1000)


class RingHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            RECORDS.append({
                "seq": next(_seq),
                "t": record.created,
                "level": record.levelname,
                "logger": record.name,
                "msg": record.getMessage(),
            })
        except Exception:  # noqa: BLE001 - a logging handler must never raise
            self.handleError(record)


def install(level: int = logging.INFO) -> None:
    root = logging.getLogger("openterm")
    root.setLevel(level)
    if not any(isinstance(h, RingHandler) for h in root.handlers):
        root.addHandler(RingHandler())


def since(seq: int) -> list[dict]:
    return [r for r in RECORDS if r["seq"] > seq]
