"""Phase 22 (minimal test bar): TRA maths, BETA least squares, and the watchlist flag / section validator. 1-3 cases each."""

from datetime import UTC, datetime

import pytest

from openterm import wlmeta
from openterm.world import returns as R


def _bars(dates: list[str], close: list[float], adj: list[float] | None = None, tz: str = "UTC") -> dict:
    """Daily bars in the shape `/api/history` gives (columnar, epoch seconds), one per ISO date at 00:00 UTC."""
    t = [int(datetime.fromisoformat(d).replace(tzinfo=UTC).timestamp()) for d in dates]
    return {"t": t, "c": close, "adj": adj, "tz": tz}


# --- TRA ---------------------------------------------------------------------------------------------------------------
def test_tra_price_total_and_dividend_part():
    """Close 100 -> 121 is +21 % price. The adjusted close starts lower (90 -> 121): +34.44 % total, so dividends added 13.44 points.
    Exactly 365 days apart, so the annualised figure is 1.3444 ^ (365.25 / 365) - 1."""
    s = R.series_from_bars("AAA", _bars(["2023-01-02", "2023-07-01", "2024-01-02"], [100, 110, 121], [90, 100, 121]))
    w = R.window_return(s, "2023-01-02", "2024-01-02")
    assert w["price_return"] == pytest.approx(0.21)
    assert w["total_return"] == pytest.approx(121 / 90 - 1)
    assert w["dividend_part"] == pytest.approx(121 / 90 - 1 - 0.21)
    assert w["days"] == 365 and w["basis"] == "TOTAL"
    assert w["annualised"] == pytest.approx((121 / 90) ** (365.25 / 365) - 1)


def test_tra_without_adj_is_price_only_and_excess_uses_the_same_dates():
    """No adjusted close (or a ^ index) means PRICE only, never a made-up total. The benchmark is read over the security's own dates."""
    sec = R.series_from_bars("AAA", _bars(["2024-01-02", "2024-01-03", "2024-01-04"], [10, 11, 12]))
    bench = R.series_from_bars("^IDX", _bars(["2023-12-29", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"], [50, 100, 101, 110, 500], [50, 100, 101, 110, 500]))
    assert R.window_return(sec, "2024-01-02", "2024-01-04")["total_return"] is None
    rows, bench_row, warnings = R.tra_table([(sec, "yahoo")], (bench, "yahoo"))
    # AAA +20 % over its 3 bars; the index +10 % over the SAME 3 days (not its own wider range): excess +10 points, PRICE basis.
    assert rows[0]["price_return_pct"] == pytest.approx(20) and rows[0]["bench_return_pct"] == pytest.approx(10)
    assert rows[0]["excess_pct"] == pytest.approx(10) and rows[0]["excess_basis"] == "PRICE"
    assert bench_row["basis"] == "PRICE" and any("PRICE ONLY" in w for w in warnings)


# --- BETA --------------------------------------------------------------------------------------------------------------
def test_ols_hand_checked_five_points():
    """x = 1..5, y = 2 4 5 4 5: mean x 3, mean y 4, Sxx 10, Sxy 6 -> beta 0.6, alpha 2.2, leftover squares 2.4 of 6 -> R2 0.6,
    standard error sqrt(2.4 / 3 / 10) = sqrt(0.08)."""
    fit = R.ols([1, 2, 3, 4, 5], [2, 4, 5, 4, 5])
    assert fit["beta"] == pytest.approx(0.6) and fit["alpha"] == pytest.approx(2.2)
    assert fit["r2"] == pytest.approx(0.6) and fit["se_beta"] == pytest.approx(0.08**0.5) and fit["n"] == 5


def test_ols_perfect_fit_and_rolling_matches_a_plain_regression():
    x = [0.01, -0.02, 0.03, 0.00, -0.01, 0.02, 0.015]
    y = [2 * v + 0.001 for v in x]
    fit = R.ols(x, y)
    assert fit["beta"] == pytest.approx(2) and fit["alpha"] == pytest.approx(0.001) and fit["r2"] == pytest.approx(1)
    # The running-sum rolling beta must equal a fresh regression on the same trailing window.
    y2 = [0.5 * v + 0.01 * ((-1) ** i) for i, v in enumerate(x)]
    roll = R.rolling_beta(x, y2, 4)
    assert roll[:3] == [None, None, None]
    assert roll[5] == pytest.approx(R.ols(x[2:6], y2[2:6])["beta"])


# --- watchlist flags and sections --------------------------------------------------------------------------------------
def test_wlmeta_validate_accepts_a_good_document_and_refuses_the_rest():
    ok = wlmeta.validate({"flags": {"aapl": "RED"}, "sections": [{"before": "JPM", "title": "  Banks "}]})
    assert ok == {"flags": {"AAPL": "RED"}, "sections": [{"before": "JPM", "title": "Banks"}]}
    for bad in (
        {"colour": {}},  # unknown field
        {"flags": {"AAPL": "PINK"}},  # not one of the 7 colours
        {"sections": [{"before": "JPM", "title": "A"}, {"before": "JPM", "title": "B"}]},  # two headers on one row
        {"sections": [{"before": "JPM", "title": "x" * 41}]},  # title too long
        {"sections": [{"before": "JPM"}]},  # missing title
    ):
        with pytest.raises(wlmeta.WlMetaError):
            wlmeta.validate(bad)


def test_wlmeta_prune_drops_symbols_that_left_the_list():
    meta = {"flags": {"AAPL": "RED", "MSFT": "BLUE"}, "sections": [{"before": "MSFT", "title": "Big"}]}
    assert wlmeta.prune(meta, ["AAPL"]) == {"flags": {"AAPL": "RED"}, "sections": []}
    assert wlmeta.members_error(meta, ["AAPL"]) == "MSFT"
