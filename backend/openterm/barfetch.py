"""Fetching daily bars for MANY symbols without tripping the data source's rate limit (untangle B8).

The quant routes (RISK, OPT, ATTR, FACT, ALPHA, ...) ask for the bars of a whole portfolio or universe at once. Yahoo, the source
most of those symbols come from, hands out about 4 requests a second in bursts of 8 (`YahooProvider.rate`, the provider's own
token bucket). A 429 opens its circuit breaker for 5 s, so firing 20 requests together fails the later ones. This module paces the
calls so they stay inside that budget; the numbers come from `YahooProvider.rate`, they are not restated here.

Why this lives outside `quant_routes.py`: it is about the data source, not about quant maths, and any other multi-symbol route
(a future screener or correlation board) needs the same pacing.
"""

from __future__ import annotations

import asyncio

from .errors import DataError
from .providers.yahoo import YahooProvider
from .symbols import SYNTHETIC_RE

# The single home of the Yahoo numbers: its own token bucket (requests per second, burst).
_RATE = YahooProvider.rate[0]  # requests per second (rate[1] is the burst size)
WIDTH = int(_RATE)  # at most this many requests in flight at once
START_GAP_S = 1 / _RATE + 0.01  # one request slot plus a 10 ms margin
FREE_STARTS = 5  # the first symbols (index 0..5) start at once; symbol number i after that waits (i - FREE_STARTS) * START_GAP_S
RETRIES = 4  # tries per symbol; only an "unavailable" answer (a rate-limited call) is tried again
RETRY_PAUSE_S = 0.6  # pause before asking again after a rate-limited ("unavailable") answer


async def fetch_bars(service, symbols: list[str], range_: str, tolerate: bool = False) -> tuple[dict, dict]:
    """(envelopes by symbol, DataErrors by symbol). Without `tolerate` the first failure is raised, named.

    `service` is the `DataService` (anything with `async history(symbol, range, interval)`). Bars are daily (`1d`).
    """
    gate = asyncio.Semaphore(WIDTH)

    async def one(sym: str, i: int) -> dict:
        if not SYNTHETIC_RE.match(sym):  # synthetic bars never touch the network: no pacing
            await asyncio.sleep(max(0, i - FREE_STARTS) * START_GAP_S)  # stagger the starts past the free ones
        async with gate:
            for attempt in range(RETRIES):
                try:
                    return await service.history(sym, range_, "1d")
                except DataError as e:
                    if e.kind != "unavailable" or attempt == RETRIES - 1:
                        raise
                    await asyncio.sleep(RETRY_PAUSE_S)
            raise AssertionError("unreachable")  # the loop either returns or raises

    res = await asyncio.gather(*(one(s, i) for i, s in enumerate(symbols)), return_exceptions=True)
    ok: dict = {}
    bad: dict = {}
    for sym, r in zip(symbols, res, strict=True):
        if isinstance(r, DataError):
            bad[sym] = r
        elif isinstance(r, BaseException):
            raise r
        else:
            ok[sym] = r
    if bad and not tolerate:
        sym, e = next(iter(bad.items()))
        raise DataError(e.kind, f"{sym}: {e}", getattr(e, "detail", None))
    return ok, bad
