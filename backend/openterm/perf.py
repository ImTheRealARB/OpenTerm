"""Request latency ring buffer, exposed at /api/perf. Pure ASGI middleware (no BaseHTTPMiddleware overhead)."""

import time
from collections import deque

_SAMPLES: deque[tuple[str, float]] = deque(maxlen=4096)


def record(path: str, ms: float) -> None:
    _SAMPLES.append((path, ms))


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = min(len(s) - 1, max(0, round(p / 100 * (len(s) - 1))))
    return s[k]


def summary() -> dict:
    by_path: dict[str, list[float]] = {}
    for path, ms in _SAMPLES:
        by_path.setdefault(path, []).append(ms)
    return {
        path: {"n": len(v), "p50": percentile(v, 50), "p95": percentile(v, 95)}
        for path, v in by_path.items()
    }


class TimingMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        t0 = time.perf_counter()

        async def wrapped_send(message):
            if message["type"] == "http.response.start":
                ms = (time.perf_counter() - t0) * 1000
                headers = list(message.get("headers", []))
                headers.append((b"server-timing", f"app;dur={ms:.2f}".encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, wrapped_send)
        finally:
            record(scope["path"], (time.perf_counter() - t0) * 1000)
