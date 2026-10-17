"""SYNxxxx test instruments for load testing (OPENTERM_SYNTHETIC=1 only). Every value is tagged
source="SYNTHETIC" and the UI labels it; these symbols never resolve to real securities."""

import random
import time

from ..models import Bars, Quote
from ..symbols import SYNTHETIC_RE
from .base import HISTORY, QUOTES, Provider


class SyntheticProvider(Provider):
    name = "synthetic"
    label = "SYNTHETIC test data"
    capabilities = frozenset({QUOTES, HISTORY})
    markets = "SYN0000-SYN9999 only (load testing)"
    terms = "Generated locally. Not market data."
    rate = (10_000.0, 10_000)

    def __init__(self, http=None, source: str | None = None):
        super().__init__(http, source="SYNTHETIC")  # type: ignore[arg-type]

    def supports(self, capability: str, symbol: str | None = None) -> bool:
        return capability in self.capabilities and (symbol is None or bool(SYNTHETIC_RE.match(symbol)))

    async def quotes(self, symbols: list[str]) -> list[Quote]:
        now = time.time()
        return [
            Quote(symbol=s, name=f"SYNTHETIC {s[3:]}", currency="XXX", exchange="SYNTHETIC", tz="UTC",
                  price=100.0, prev_close=100.0, change=0.0, change_pct=0.0, source=self.source, as_of=now)
            for s in symbols
            if SYNTHETIC_RE.match(s)
        ]

    async def history(self, symbol: str, range_: str, interval: str) -> Bars:
        rnd = random.Random(symbol)
        n, t0, px = 250, int(time.time()) - 250 * 86400, 100.0
        t, o, h, lo, c, v = [], [], [], [], [], []
        for i in range(n):
            op = px
            px = max(0.01, px * (1 + rnd.gauss(0, 0.01)))
            t.append(t0 + i * 86400)
            o.append(round(op, 2))
            c.append(round(px, 2))
            h.append(round(max(op, px) * 1.003, 2))
            lo.append(round(min(op, px) * 0.997, 2))
            v.append(1000)
        return Bars.model_construct(
            symbol=symbol, range=range_, interval="1d", currency="XXX", exchange="SYNTHETIC", tz="UTC",
            t=t, o=o, h=h, l=lo, c=c, v=v, source=self.source, as_of=time.time(),
        )

    async def probe(self) -> None:
        return None
