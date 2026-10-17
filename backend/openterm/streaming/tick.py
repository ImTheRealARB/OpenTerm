from dataclasses import dataclass


@dataclass(slots=True)
class Tick:
    symbol: str
    price: float
    change: float | None
    change_pct: float | None
    volume: int | None
    high: float | None
    low: float | None
    time_ms: int
    source: str
    """Short source code on the wire: y = Yahoo stream, p = REST poll, s = SYNTHETIC test data."""

    def wire(self) -> list:
        return [self.symbol, self.price, self.change, self.change_pct, self.volume, self.high, self.low,
                self.time_ms, self.source]
