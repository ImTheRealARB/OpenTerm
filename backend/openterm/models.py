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


class NewsItem(BaseModel):
    """A headline and a link. OpenTerm never stores or shows article bodies."""

    id: str
    title: str
    url: str
    publisher: str | None = None
    published: float | None = None
    """Epoch seconds (UTC) as given by the feed."""
    summary: str | None = None
    """The feed's own teaser, tags stripped, at most 300 characters."""
    source: str


class Mover(BaseModel):
    symbol: str
    name: str | None = None
    price: float | None = None
    change: float | None = None
    change_pct: float | None = None
    volume: float | None = None


class Movers(BaseModel):
    tables: dict[str, list[Mover]]
    """GAINERS, LOSERS, ACTIVE (share volume), DOLLAR (dollar volume), NDX100."""
    table_as_of: dict[str, str | None] = {}
    """The source's own "data as of" text per table (tables can be from different sessions)."""
    as_of_text: str | None = None
    market_time: int | None = None
    """Epoch seconds of as_of_text, when it parses."""
    source: str
    as_of: float


class Coin(BaseModel):
    symbol: str
    name: str | None = None
    rank: int | None = None
    quote: str
    """Currency the prices are in (USD, INR, ... or USDT on Binance)."""
    price: float | None = None
    change_pct_1h: float | None = None
    change_pct_24h: float | None = None
    change_pct_7d: float | None = None
    high_24h: float | None = None
    low_24h: float | None = None
    volume_24h: float | None = None
    """24 h traded value in the quote currency."""
    market_cap: float | None = None
    updated: float | None = None
    """Epoch seconds of the source's last update."""
    source: str
    as_of: float
