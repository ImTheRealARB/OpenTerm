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
    """Short source code on the wire (one letter, see `SOURCES` below for the full table)."""

    def wire(self) -> list:
        return [self.symbol, self.price, self.change, self.change_pct, self.volume, self.high, self.low,
                self.time_ms, self.source]


@dataclass(frozen=True, slots=True)
class TickSource:
    """One tick source. The same one-letter code is shown under three names, because three places print it in three styles."""

    code: str
    quote_source: str | None
    """What a quote's `source` field says once this tick has updated it (DataService.apply_tick). None = the tick does not change the
    quote's source: the REST poller's ticks are the same snapshot the quote already came from."""
    alert_name: str
    """Lower-case words inside the text of a server-fired alert (alerts_engine)."""
    tick_label: str
    """Upper-case label on the GIP tick chart (world/tickbuf)."""


# THE table of tick sources. Add a new source here and the three maps below pick it up.
SOURCES: tuple[TickSource, ...] = (
    TickSource("y", "yahoo:stream", "yahoo stream", "YAHOO STREAM"),  # Yahoo's protobuf WebSocket stream
    TickSource("p", None, "yahoo poll", "YAHOO POLL"),                # REST poll of Yahoo (the fallback when the stream is down)
    TickSource("a", "alpaca:iex", "alpaca iex", "RT IEX"),            # Alpaca's latest IEX trades
    TickSource("k", "kite:ticker", "kite", "RT KITE"),                # Zerodha Kite ticker
    TickSource("s", "synthetic", "synthetic", "SYNTHETIC"),           # SYN0000-SYN9999 test data, always labelled on screen
)

# The three maps, derived from the table (code -> text). Each module imports the one it needs.
QUOTE_SOURCES: dict[str, str] = {s.code: s.quote_source for s in SOURCES if s.quote_source is not None}
ALERT_NAMES: dict[str, str] = {s.code: s.alert_name for s in SOURCES}
TICK_LABELS: dict[str, str] = {s.code: s.tick_label for s in SOURCES}
