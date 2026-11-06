"""User-facing ranges/intervals (1D, 5D, 1M, 6M, YTD, 1Y, 5Y, MAX; 1m..1mo) and validation."""

import datetime as dt

RANGES = {
    "1D": "1d", "5D": "5d", "1M": "1mo", "3M": "3mo", "6M": "6mo", "YTD": "ytd",
    "1Y": "1y", "2Y": "2y", "3Y": "3y", "5Y": "5y", "10Y": "10y", "20Y": "20y", "MAX": "max",
}
YAHOO_INTERVALS = {"1m", "2m", "5m", "15m", "30m", "60m", "90m", "1d", "1wk", "1mo"}
# Case-insensitive aliases. "1M" is deliberately absent: it is the one-month RANGE.
INTERVALS = {
    "1MIN": "1m", "2MIN": "2m", "5MIN": "5m", "15MIN": "15m", "30MIN": "30m",
    "1H": "60m", "60MIN": "60m", "90MIN": "90m",
    "D": "1d", "1D": "1d", "DAILY": "1d", "W": "1wk", "1W": "1wk", "1WK": "1wk", "WEEKLY": "1wk",
    "MO": "1mo", "1MO": "1mo", "MONTHLY": "1mo",
}
DEFAULT_INTERVAL = {
    "1d": "5m", "5d": "15m", "1mo": "60m", "3mo": "1d", "6mo": "1d", "ytd": "1d",
    "1y": "1d", "2y": "1d", "3y": "1d", "5y": "1wk", "10y": "1mo", "20y": "1d", "max": "1mo",
}
# How far back each intraday candle length reaches is NOT checked here: it depends on which source answers, so each provider
# declares `intraday_days` and the router reports it (Router.history_limits). Yahoo's is in providers/yahoo.py.
_RANGE_DAYS = {
    "1d": 1, "5d": 5, "1mo": 31, "3mo": 92, "6mo": 183, "ytd": 366,
    "1y": 366, "2y": 731, "3y": 1096, "5y": 1827, "10y": 3653, "20y": 7305, "max": 100_000,
}


def normalize(range_: str | None, interval: str | None) -> tuple[str, str]:
    r = RANGES.get((range_ or "1Y").upper())
    if r is None:
        raise ValueError(f"BAD RANGE: {range_}. USE {' '.join(RANGES)}")
    if interval:
        i = interval if interval in YAHOO_INTERVALS else INTERVALS.get(interval.upper())
        if i is None:
            raise ValueError(f"BAD INTERVAL: {interval}")
    else:
        i = DEFAULT_INTERVAL[r]
    return r, i


def range_days(r: str, today: dt.date | None = None) -> int:
    """Calendar days a range looks back. YTD is year to date: from 1 January of this year (audit A-4; it used to be a
    flat 366, which made YTD a one-year chart on every source that builds its own window)."""
    if r == "ytd":
        now = today or dt.date.today()
        return (now - dt.date(now.year, 1, 1)).days + 1
    return _RANGE_DAYS[r]
