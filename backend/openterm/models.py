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


class Profile(BaseModel):
    """Company / instrument description for DES. Numbers stay None when the source lacks them."""

    symbol: str
    name: str | None = None
    exchange: str | None = None
    currency: str | None = None
    quote_type: str | None = None
    sector: str | None = None
    industry: str | None = None
    country: str | None = None
    website: str | None = None
    employees: int | None = None
    description: str | None = None
    market_cap: float | None = None
    enterprise_value: float | None = None
    pe: float | None = None
    forward_pe: float | None = None
    eps: float | None = None
    forward_eps: float | None = None
    dividend_yield: float | None = None
    beta: float | None = None
    shares_out: float | None = None
    float_shares: float | None = None
    high_52w: float | None = None
    low_52w: float | None = None
    avg_volume: float | None = None
    price_to_book: float | None = None
    delay_min: int | None = None
    """Exchange data delay in minutes, as reported by the source."""
    source: str
    as_of: float
