"""Audit 2026-11-04 #3: the Yahoo adapter must label bars with the interval Yahoo really answered with."""

from openterm.providers.yahoo import bars_from_chart


def _result(granularity: str | None) -> dict:
    meta = {"symbol": "AAPL", "currency": "USD", "exchangeTimezoneName": "America/New_York"}
    if granularity:
        meta["dataGranularity"] = granularity
    return {
        "meta": meta,
        "timestamp": [1_000_000, 3_600_000],
        "indicators": {"quote": [{"open": [1, 2], "high": [1, 2], "low": [1, 2], "close": [1, 2], "volume": [5, 6]}]},
    }


def test_monthly_bars_for_range_max_are_not_labelled_daily():
    # `range=max&interval=1d` is answered with monthly bars (CLAUDE.md "Yahoo range=max is monthly").
    bars = bars_from_chart(_result("1mo"), "max", "1d", "yahoo", 0.0)
    assert bars.interval == "1mo"


def test_matching_or_missing_granularity_keeps_requested_interval():
    assert bars_from_chart(_result("1d"), "1y", "1d", "yahoo", 0.0).interval == "1d"
    assert bars_from_chart(_result(None), "1y", "1d", "yahoo", 0.0).interval == "1d"
    # Yahoo names the hourly size "1h" even when asked for "60m": same thing, keep what was asked.
    assert bars_from_chart(_result("1h"), "1mo", "60m", "yahoo", 0.0).interval == "60m"
