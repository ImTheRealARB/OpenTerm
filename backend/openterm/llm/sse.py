"""Server-sent events parser (pure). Yields each event's `data` payload; comments and other fields are skipped.

Chunks may split anywhere, even inside a UTF-8 character, so bytes are buffered until a full line arrives.
"""

from __future__ import annotations

from collections.abc import Iterable


class SSEParser:
    def __init__(self) -> None:
        self._buf = b""
        self._data: list[str] = []

    def feed(self, chunk: bytes) -> list[str]:
        self._buf += chunk
        out = []
        while (i := self._buf.find(b"\n")) >= 0:
            line = self._buf[:i].rstrip(b"\r").decode("utf-8", errors="replace")
            self._buf = self._buf[i + 1:]
            if not line:
                if self._data:
                    out.append("\n".join(self._data))
                    self._data = []
            elif line.startswith("data:"):
                self._data.append(line[5:].removeprefix(" "))
        return out

    def close(self) -> list[str]:
        """Flushes an event that ended without a blank line."""
        out = self.feed(b"\n") if self._buf else []
        if self._data:
            out.append("\n".join(self._data))
            self._data = []
        return out


def parse_sse(chunks: Iterable[bytes]) -> list[str]:
    p = SSEParser()
    out = [d for c in chunks for d in p.feed(c)]
    return out + p.close()
