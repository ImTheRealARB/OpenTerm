"""Normalized data models. Every provider maps into these; every datum carries source + as_of."""

from pydantic import BaseModel


class Quote(BaseModel):
    symbol: str
    name: str | None = None
    currency: str | None = None
    exchange: str | None = None
    tz: str | None = None
    price: float | None = None
    prev_close: float | None = None
    change: float | None = None
    change_pct: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    volume: int | None = None
    high_52w: float | None = None
    low_52w: float | None = None
    market_time: int | None = None
    """Epoch seconds (UTC) of the last trade."""
    source: str
    as_of: float
    """Epoch seconds (UTC) when we fetched it."""


class Bars(BaseModel):
    """Columnar OHLCV: compact on the wire and maps straight onto Float64Arrays in the browser."""

    symbol: str
    range: str
    interval: str
    currency: str | None = None
    exchange: str | None = None
    tz: str | None = None
    t: list[int]
    o: list[float | None]
    h: list[float | None]
    l: list[float | None]
    c: list[float | None]
    v: list[int | None]
    source: str
    as_of: float


class SearchHit(BaseModel):
    symbol: str
    name: str | None = None
    exchange: str | None = None
    type: str | None = None
    source: str
