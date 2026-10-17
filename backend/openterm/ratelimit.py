import asyncio
import time


class RateLimited(Exception):
    def __init__(self, wait_s: float):
        super().__init__(f"rate limited, next slot in {wait_s:.1f}s")
        self.wait_s = wait_s


class TokenBucket:
    """Per-provider token bucket. Callers never wait longer than `max_wait`:
    past that we raise so the router can fall back instead of stalling the UI."""

    def __init__(self, rate: float, burst: int):
        self.rate = rate
        self.burst = burst
        self.tokens = float(burst)
        self._t = time.monotonic()

    def _refill(self) -> None:
        now = time.monotonic()
        self.tokens = min(self.burst, self.tokens + (now - self._t) * self.rate)
        self._t = now

    @property
    def remaining(self) -> float:
        self._refill()
        return max(0.0, self.tokens)

    async def acquire(self, max_wait: float = 0.25) -> None:
        self._refill()
        self.tokens -= 1
        if self.tokens >= 0:
            return
        wait = -self.tokens / self.rate
        if wait > max_wait:
            self.tokens += 1
            raise RateLimited(wait)
        await asyncio.sleep(wait)
