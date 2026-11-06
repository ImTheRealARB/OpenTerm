"""Audit B-3, B-4, B-5: options runs validate, an OR rule works before its first cross, crypto vol uses 365 days, YAS rejects a nonsense yield."""

import math

import numpy as np
import pandas as pd
import pytest

from openterm.bt import rules, validate_job
from openterm.options import hivg


def test_validators_accept_options_trades_with_no_prices():
    """_run_options records entry_price / exit_price / costs as None; BT MC and BT WF used to crash on them (B-3)."""
    trade = {"symbol": "AAPL", "direction": 1, "entry_price": None, "exit_price": None, "entry_time": "2024-01-02",
             "exit_time": "2024-02-02", "size": 1.0, "pnl": 12.5, "pnl_pct": None, "commission": None,
             "holding_bars": None, "exit_reason": "expiry"}
    equity = [[1_704_153_600 + 86_400 * i, 100_000.0 + i] for i in range(5)]
    _eq, trades = validate_job._inputs({"equity": equity, "trades": [trade]})
    assert trades[0].entry_price == 0.0 and trades[0].pnl == 12.5


def _frame(close):
    idx = pd.date_range("2024-01-01", periods=len(close))
    c = pd.Series(close, index=idx, dtype=float)
    return pd.DataFrame({"open": c, "high": c, "low": c, "close": c, "volume": 1.0}, index=idx)


def test_or_rule_is_not_silenced_before_the_first_cross():
    """SMA2 never crosses above SMA3 here, but CLOSE < 50 is true on every bar: the OR must be true (B-4)."""
    df = _frame([40, 39, 38, 37, 36, 35, 34, 33, 32, 31, 30, 29])
    sig = rules.signals(rules.parse("SMA2 CROSS> SMA3 OR CLOSE < 50"), {"X": df})["X"]
    assert (sig.iloc[3:] == 1.0).all()
    plain = rules.signals(rules.parse("SMA2 CROSS> SMA3"), {"X": df})["X"]
    assert (plain == 0.0).all()  # nothing crossed: still no position


def test_cross_still_holds_after_a_cross():
    df = _frame([10, 9, 8, 7, 8, 9, 10, 11, 12, 13, 12, 11, 10, 9, 8])
    sig = rules.signals(rules.parse("SMA2 CROSS> SMA4"), {"X": df})["X"]
    assert sig.max() == 1.0 and sig.iloc[-1] == 0.0  # long after the up-cross, flat after the down-cross


def test_crypto_realized_vol_uses_365_days():
    rets = [0.01, -0.02, 0.015, -0.01, 0.02, -0.015, 0.01, -0.005, 0.012, -0.011]
    eq = hivg.cc_vol(rets, 10)
    crypto = hivg.cc_vol(rets, 10, hivg.CRYPTO_TRADING_DAYS)
    assert crypto / eq == pytest.approx(math.sqrt(365 / 252))
    highs, lows = [101.0, 102.0, 103.0], [99.0, 100.0, 100.5]
    assert hivg.parkinson_vol(highs, lows, 3, 365.0) / hivg.parkinson_vol(highs, lows, 3) == pytest.approx(math.sqrt(365 / 252))
    assert np.isfinite(hivg.rolling_cc(rets, 5, 365.0)[-1])


@pytest.mark.parametrize("yld", ["-100", "-150", "-50", "-200"])
def test_yas_rejects_a_yield_that_cannot_be_discounted(client, yld):
    r = client.get("/api/deriv/yas", params={"CPN": "5", "MAT": "2030-11-06", "YLD": yld, "FREQ": "1"})
    assert r.status_code == 400 and "YLD" in r.text


# --- B-1: a holding added without a currency takes its bars' currency ---------------------------------------------------------
class _FakeService:
    """Only what quant_routes._fx needs: history() for the FX pair."""

    def __init__(self):
        self.asked: list[str] = []

    async def history(self, symbol, range_, interval):
        self.asked.append(symbol)
        return {"data": {"c": [None, 0.0118, 0.0119]}}  # INRUSD=X: ~84 rupees to the dollar


def _request(service):
    from types import SimpleNamespace
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(service=service)))


async def test_holding_without_a_currency_uses_its_bars_currency():
    from openterm import quant_routes as qr

    pf = {"base": "USD", "positions": [{"symbol": "AAPL", "qty": 10}, {"symbol": "RELIANCE.NS", "qty": 10, "currency": None}]}
    envs = {"AAPL": {"data": {"currency": "USD"}}, "RELIANCE.NS": {"data": {"currency": "INR"}}}
    pos, why = qr._holdings(pf)
    fake = _FakeService()
    fx, mixed, why = await qr._fx(_request(fake), pf, pos, envs)
    assert why is None and mixed is True
    assert [p["ccy"] for p in pos] == ["USD", "INR"]  # the job values RELIANCE.NS in rupees, converted
    assert fx == {"INR": pytest.approx(0.0119)} and fake.asked == ["INRUSD=X"]


async def test_typed_currency_wins_and_unknown_currency_stays_base():
    from openterm import quant_routes as qr

    pf = {"base": "USD", "positions": [{"symbol": "SYN0001", "qty": 1}, {"symbol": "X", "qty": 1, "currency": "USD"}]}
    envs = {"SYN0001": {"data": {"currency": "XXX"}}, "X": {"data": {"currency": "EUR"}}}  # XXX = ISO "no currency"
    pos, _ = qr._holdings(pf)
    fx, mixed, why = await qr._fx(_request(_FakeService()), pf, pos, envs)
    assert (fx, mixed, why) == ({}, False, None) and pos[1]["ccy"] == "USD"


def test_empty_portfolio_is_not_runnable():
    from openterm import quant_routes as qr

    assert qr._holdings({"base": "USD", "positions": []})[1] == "NOT RUNNABLE: THE PORTFOLIO HAS NO POSITIONS"
