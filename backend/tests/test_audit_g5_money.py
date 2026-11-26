"""Audit group 5 "money math": numbers that were wrong by a hand-checkable amount.

Every expected value is worked out next to the assertion. pandas is a worker-only dependency, so it is imported inside
the tests (never at module level), like the other BT tests.
"""

import importlib

import pytest


def mod(name: str):
    return importlib.import_module(name)


# --- C-08: forex engine with Yahoo `=X` tickers -----------------------------------------------------------------------

def test_c08_yahoo_fx_ticker_normalises_to_a_pair():
    hooks = mod("openterm.bt.engines.hooks")
    assert hooks._normalize_symbol("USDJPY=X") == "USD/JPY"
    assert hooks._normalize_symbol("EURUSD=X") == "EUR/USD"
    assert hooks._normalize_symbol("eurusd.fx") == "EUR/USD"  # the old forms still work


def _fx(cfg=None):
    return mod("openterm.bt.engines.forex").ForexEngine({"initial_cash": 100_000, **(cfg or {})})


def test_c08_usdjpy_ticker_gets_the_usdjpy_spread_not_the_default():
    e = _fx()
    # USD/JPY spread is 1.0 pip (default would be 2.0): half-spread 0.5 + slippage 0.3 = 0.8 pip = 0.8 * 0.01 = 0.008.
    assert e.apply_slippage_for_symbol("USDJPY=X", 150.0, 1) == pytest.approx(150.008)
    # USD/TRY is 15.0 pips: (7.5 + 0.3) * 0.0001 = 0.00078 on a 30.0 price.
    assert e.apply_slippage_for_symbol("USDTRY=X", 30.0, -1) == pytest.approx(30.0 - 0.00078)


def test_c08_usdjpy_ticker_earns_the_usdjpy_swap():
    pd = mod("pandas")
    hooks = mod("openterm.bt.engines.hooks")
    models = mod("openterm.bt.models")
    # 0.1 lot long USD/JPY = 10,000 units; swap +8.0 per lot -> +0.8 on a Tuesday (no triple swap).
    pos = models.Position(symbol="USDJPY=X", direction=1, entry_price=150.0, entry_time=pd.Timestamp("2024-01-01"),
                          size=10_000.0)
    swap = hooks.calc_forex_swap("USDJPY=X", pd.Timestamp("2024-01-02"), {"USDJPY=X": pos}, 100_000.0, {})
    assert swap == pytest.approx(0.8)


def test_c08_usd_base_pnl_is_converted_from_quote_currency_at_the_exit_rate():
    e = _fx()
    # Long 10,000 USD from 150 to 151: +1.0 JPY per USD = 10,000 JPY = 10,000 / 151 USD = 66.2252 (the bug booked 10,000).
    assert e._calc_pnl("USDJPY=X", 1, 10_000.0, 150.0, 151.0) == pytest.approx(10_000.0 / 151.0)
    assert e._calc_pnl("USD/JPY", -1, 10_000.0, 150.0, 151.0) == pytest.approx(-10_000.0 / 151.0)


def test_c08_usd_quote_pairs_and_metals_need_no_conversion():
    e = _fx()
    # EUR/USD: 100,000 EUR from 1.10 to 1.11 = +1,000 USD already. Gold: 100 oz from 2000 to 2010 = +1,000 USD.
    assert e._calc_pnl("EURUSD=X", 1, 100_000.0, 1.10, 1.11) == pytest.approx(1_000.0)
    assert e._calc_pnl("XAUUSD=X", 1, 100.0, 2000.0, 2010.0) == pytest.approx(1_000.0)


def test_c08_usd_base_margin_and_size_are_in_usd_units():
    e = _fx()
    # The base of USD/JPY is the dollar: $50,000 of exposure is 50,000 units (not 50,000 / 150), and at 100:1 it needs
    # $500 of margin (not 50,000 * 150 / 100 = 75,000 yen booked as dollars).
    assert e._calc_raw_size("USDJPY=X", 50_000.0, 150.0) == pytest.approx(50_000.0)
    assert e._calc_margin("USDJPY=X", 50_000.0, 150.0, 100.0) == pytest.approx(500.0)
    # EUR/USD keeps the generic maths: $55,000 at 1.10 = 50,000 EUR; margin 50,000 * 1.10 / 100 = $550.
    assert e._calc_raw_size("EURUSD=X", 55_000.0, 1.10) == pytest.approx(50_000.0)
    assert e._calc_margin("EURUSD=X", 50_000.0, 1.10, 100.0) == pytest.approx(550.0)


def test_c08_a_usdjpy_backtest_books_dollars_not_yen():
    pd = mod("pandas")
    engine = mod("openterm.bt.engine")
    idx = pd.bdate_range("2024-01-02", periods=5)
    # Flat 150 until the exit bar, then 151: one long trade, entered on bar 1's open, closed on the last bar.
    px = [150.0, 150.0, 150.0, 150.0, 151.0]
    df = pd.DataFrame({"open": px, "high": px, "low": px, "close": px, "volume": 0.0}, index=idx)
    sig = pd.Series([0.0, 1.0, 1.0, 1.0, 0.0], index=idx)
    res = engine.backtest({"USDJPY=X": df}, {"USDJPY=X": sig}, {"initial_cash": 100_000}, engine="forex")
    assert len(res.trades) == 1
    t = res.trades[0]
    # Dollar PnL of a long from entry to exit is size * (exit - entry) / exit, never size * (exit - entry).
    assert t.pnl == pytest.approx(t.size * (t.exit_price - t.entry_price) / t.exit_price, rel=1e-9)
    # A one-yen move on a dollar position is well under 1% of its size: the old yen-as-dollars bug booked all of it.
    assert abs(t.pnl) < t.size * 0.01
    # Sizing is the 100:1 leverage on $100,000 = $10,000,000 of dollars (it was 10M / 150 units before the fix) and
    # its margin is $100,000.
    assert t.size == pytest.approx(10_000_000.0) and t.entry_margin == pytest.approx(100_000.0)
    # Final equity = cash + dollar PnL + USD/JPY long swap: 10M / 100,000 = 100 lots x +8.0 x 3 swap days = +2,400
    # (it was 100,000 + 9.8 million yen booked as dollars, with a -1.0 default swap, before the fix).
    assert float(res.equity.iloc[-1]) == pytest.approx(100_000.0 + t.pnl + 2_400.0)


# --- H-22: BT LIVE paper book ---------------------------------------------------------------------------------------

DAY = 86_400


def test_h22_a_wiped_out_short_book_is_closed_flat_not_flipped_into_a_negative_long():
    from openterm.bt import fwd

    t = [i * DAY for i in range(5)]
    o = [100.0, 100.0, 250.0, 250.0, 250.0]
    st = fwd.new_state("x", "AAPL", "s", "1D", 10_000.0, now=0)
    # bar 0 and 1 say short: filled at bar 1's open 100 -> qty -100, cash 10,000 + 100 * 100 = 20,000.
    # bar 2 says long, filled at bar 3's open 250: equity = 20,000 - 100 * 250 = -5,000. The old code set qty = +1 * -5,000 /
    # 250 = -20 (still short) while saying pos = long.
    fwd.step(st, t[:5], o, [-1, -1, 1, 1], now=1)
    assert st["qty"] == 0.0 and st["pos"] == 0 and st["cash"] == 0.0  # closed at 250 and the debt is not carried
    assert st["fills"][-1] == [t[3], "BUY", pytest.approx(100.0), 250.0]  # the cover of the 100 short shares
    assert st["status"] == "stopped" and "EQUITY" in st["error"]  # the book is halted and says why


def test_h22_a_flip_with_no_open_yet_is_decided_again_on_the_next_step_not_lost():
    from openterm.bt import fwd

    t = [i * DAY for i in range(5)]
    st = fwd.new_state("x", "AAPL", "s", "1D", 1000.0, now=0)
    # the forming bar's open is not known yet: the long decided on bar 2 cannot fill
    fwd.step(st, t[:4], [100.0, 100.0, 100.0, None], [0, 0, 1], now=1)
    assert st["pos"] == 0 and st["fills"] == [] and st["last_t"] == t[1]  # bar 2 is NOT marked as decided
    assert [d[0] for d in st["decisions"]] == [t[0], t[1]]
    # next step the open exists: the same decision fills there, once
    fwd.step(st, t, [100.0, 100.0, 100.0, 105.0, 106.0], [0, 0, 1, 1], now=2)
    assert st["pos"] == 1 and st["fills"] == [[t[3], "BUY", pytest.approx(1000.0 / 105.0), 105.0]]
    assert [d[0] for d in st["decisions"]] == [t[0], t[1], t[2], t[3]]


def test_h22_fills_are_capped():
    from openterm.bt import fwd

    book = fwd.new_state("x", "AAPL", "s", "1D", 1000.0, now=0)
    for i in range(fwd.MAX_FILLS + 50):
        fwd._trade(book, 1 if i % 2 == 0 else 0, 10.0, i)
    assert len(book["fills"]) == fwd.MAX_FILLS and book["fills"][-1][0] == fwd.MAX_FILLS + 49


def test_h22_a_stale_bar_set_does_not_step_the_paper_book():
    import asyncio
    from types import SimpleNamespace

    from openterm import bt_lab_routes as routes
    from openterm.errors import DataError

    class Svc:
        async def history(self, *a, **k):
            return {"data": {"t": [0], "c": [1.0]}, "stale": True, "age_s": 9_999, "source": "yahoo"}

    class Bt:
        async def strategy(self, name):
            return {"kind": "rule", "code": "SMA20>SMA50"}

    app = SimpleNamespace(state=SimpleNamespace(jobs=SimpleNamespace(on_done={"bt.fwdsig": object()})))
    orig = (routes.svc, routes.bt_of)
    routes.svc, routes.bt_of = (lambda req: Svc()), (lambda req: Bt())
    try:
        with pytest.raises(DataError) as e:
            asyncio.run(routes._submit_step(app, {"symbol": "AAPL", "strategy": "s", "interval": "1D", "id": "x"}))
    finally:
        routes.svc, routes.bt_of = orig
    assert "STALE" in str(e.value)


def test_h22_stop_and_the_signal_job_finishing_at_once_leave_the_book_stopped():
    import asyncio
    from types import SimpleNamespace

    import aiosqlite

    from openterm import bt_lab_routes as routes
    from openterm.bt import fwd

    async def go():
        async with aiosqlite.connect(":memory:") as db:
            await db.execute("CREATE TABLE kv (key TEXT PRIMARY KEY, value BLOB)")
            st = fwd.new_state("abc", "AAPL", "s", "1D", 1000.0, now=0)
            await routes._save(db, st)
            app = SimpleNamespace(state=SimpleNamespace(userdata=SimpleNamespace(db=db), jobs=SimpleNamespace(on_done={})))
            routes._hook(app)
            result = {"fwd_id": "abc", "t": [0, DAY], "o": [10.0, 10.0], "c": [10.0, 10.0], "signal": [1]}
            # stop first, the finishing job second: the job read the book before the stop was saved
            await asyncio.gather(routes.fwd_stop(SimpleNamespace(app=app), "abc"),
                                 app.state.jobs.on_done["bt.fwdsig"]({}, result))
            return (await routes._load(db, "abc"))["status"]

    assert asyncio.run(go()) == "stopped"


# --- H-23: BT OPT walk-forward efficiency, empty windows, no-downside Sortino ------------------------------------------

def test_h23_walk_forward_efficiency_is_none_when_the_in_sample_return_was_a_loss():
    import numpy as np

    from openterm.bt import overfit

    # One parameter set, two halves, 10 bars a year. In sample: 10 bars of -1% = 0.99^10 - 1 = -9.56% a year. Out of
    # sample: 10 bars of -2% = 0.98^10 - 1 = -18.29%. -18.29 / -9.56 = +1.91: a losing strategy reported 191% "efficiency".
    r = np.array([[-0.01]] * 10 + [[-0.02]] * 10)
    wf = overfit.walk_forward(r, list(range(20)), 1, False, "RETURN", 10, 100_000.0)
    assert wf["is_annual_mean"] == pytest.approx(0.99**10 - 1) and wf["oos_annual"] == pytest.approx(0.98**10 - 1)
    assert wf["wfe"] is None


def test_h23_a_window_where_no_parameter_set_has_a_fitness_is_skipped_not_given_column_zero():
    import numpy as np

    from openterm.bt import overfit

    rng = np.random.default_rng(1)
    r = np.zeros((30, 2))
    r[10:] = rng.normal(0.001, 0.01, (20, 2))   # window 1 learns from 10 flat bars (Sharpe undefined for both columns)
    wf = overfit.walk_forward(r, list(range(30)), 2, False, "SHARPE", 252, 100_000.0)
    assert [w["window"] for w in wf["windows"]] == [2]          # window 1 has nothing to choose from: dropped
    assert len(wf["equity"]) == 10                              # only window 2's out-of-sample bars are stitched


def test_h23_no_downside_bar_means_no_sortino_not_a_huge_number():
    pd = mod("pandas")
    metrics = mod("openterm.bt.metrics")
    idx = pd.bdate_range("2024-01-01", periods=5)
    up = pd.Series([100_000.0, 101_000.0, 102_000.0, 103_000.0, 104_000.0], index=idx)
    job = mod("openterm.bt.job")
    raw = metrics.calc_metrics(up, [], 100_000.0, 252)
    assert raw["sortino"] > 1e6  # Vibe's own number (divides by 1e-10): the cross-check fixtures hold it, so it stays
    assert job.drop_undefined_sortino(dict(raw), up, 100_000.0)["sortino"] is None  # what BT OPT and the run card see
    # With one losing bar the ratio is defined. Equity 101k, 100k, 101k, 102k, 102k from a 100k start gives the bar
    # returns +1%, -1000/101000, +1%, +1000/101000, 0: mean 0.004; zero-target downside RMS over all five bars
    # = (1000/101000) / sqrt(5) = 0.0044280; Sortino = 0.004 / 0.0044280 * sqrt(252) = 14.34.
    import math

    mixed = pd.Series([101_000.0, 100_000.0, 101_000.0, 102_000.0, 102_000.0], index=idx)
    dsd = (1000 / 101_000) / math.sqrt(5)
    want = 0.004 / dsd * math.sqrt(252)
    kept = job.drop_undefined_sortino(metrics.calc_metrics(mixed, [], 100_000.0, 252), mixed, 100_000.0)
    assert kept["sortino"] == pytest.approx(want, rel=1e-4)


# --- H-24: QRY ratio filters and India short-side charges ---------------------------------------------------------------

def test_h24_a_bare_number_on_a_ratio_field_is_a_percent_on_both_sides_of_one():
    from datetime import date

    from openterm.query import lang as L

    today = date(2026, 1, 1)
    for text, want in (("1", 0.01), ("1.01", 0.0101), ("0.5", 0.005), ("3", 0.03), ("3%", 0.03), ("-2", -0.02)):
        got = L.parse(f"divy FOR SPX WHERE divy>{text}", today).where[0].value
        assert got == pytest.approx(want), text  # "1" was read as 100% and "1.01" as 1.01%: a jump at 1.0


def test_h24_india_stamp_duty_is_for_buys_and_the_dp_charge_for_sells_also_on_the_short_side():
    e = mod("openterm.bt.engines.india_equity").IndiaEquityEngine({"in_dp_charge": 15.93})
    # notional 100,000: exchange 2.97 + SEBI 0.10 + GST 0.5526 + STT 100 = 103.6226 before side charges (stamp 15 on a BUY
    # = 0.015%; the DP charge 15.93 on a SELL).
    base = 103.6226
    assert e.calc_commission(40, 2500.0, 1, True) == pytest.approx(base + 15.0)       # buy to open a long
    assert e.calc_commission(40, 2500.0, 1, False) == pytest.approx(base + 15.93)     # sell to close a long
    assert e.calc_commission(40, 2500.0, -1, True) == pytest.approx(base + 15.93)     # sell to open a short (was +15 stamp)
    assert e.calc_commission(40, 2500.0, -1, False) == pytest.approx(base + 15.0)     # buy to cover (was +15.93 DP)


# --- M-10: stop exits and CROSS rules ------------------------------------------------------------------------------------

def test_m10_cross_holds_through_a_touch_and_exits_only_on_a_strict_cross_back():
    pd = mod("pandas")
    rules = mod("openterm.bt.rules")
    close = [99.0, 101.0, 100.0, 99.0, 100.0, 101.0]
    df = pd.DataFrame({"open": close, "high": close, "low": close, "close": close, "volume": 1.0},
                      index=pd.bdate_range("2024-01-01", periods=6))
    sig = rules.signals(rules.parse("CLOSE CROSS> 100"), {"X": df})["X"].tolist()
    # bar 1 crosses above 100 -> on. Bar 2 only TOUCHES 100 (Pine's crossunder needs a strict fall): still on. Bar 3 is
    # below: off. Bar 4 touches again: stays off. Bar 5 is above and bar 4 was not above: a new cross-over -> on.
    assert sig == [0.0, 1.0, 1.0, 0.0, 0.0, 1.0]


def test_m10_a_stop_exit_slips_with_its_own_symbols_pip_size():
    pd = mod("pandas")
    engine = mod("openterm.bt.engine")
    idx = pd.bdate_range("2024-01-02", periods=6)
    n = len(idx)

    def frame(px, low):
        return pd.DataFrame({"open": px, "high": px, "low": low, "close": px, "volume": 0.0}, index=idx)

    flat_jpy, flat_eur = [150.0] * n, [1.10] * n
    # USD/JPY trades last, so _active_symbol is still USD/JPY (pip 0.01) when EUR/USD's stop closes: the EUR/USD exit
    # was slipped by a JPY pip (0.01 = 100 EUR/USD pips) instead of 0.8 pips * 0.0001.
    eur_low = [1.10, 1.10, 1.10, 1.10, 1.0, 1.0]  # bar 4's low reaches a 5% stop (1.045)
    sig = {"EURUSD=X": pd.Series([0.0, 0.5, 0.5, 0.5, 0.5, 0.5], index=idx),
           "USDJPY=X": pd.Series([0.0, 0.5, 0.5, 0.5, 0.5, 0.5], index=idx)}
    data = {"EURUSD=X": frame(flat_eur, eur_low), "USDJPY=X": frame(flat_jpy, flat_jpy)}
    res = engine.backtest(data, sig, {"initial_cash": 100_000}, engine="forex", stops={"stop": 5.0, "target": None})
    stop_trade = next(t for t in res.trades if t.symbol == "EURUSD=X" and t.exit_reason == "stop")
    # EUR/USD is 1.0 pip spread -> half 0.5 + 0.3 slippage = 0.8 pip = 0.00008; a sell exit at the 1.045 level
    assert stop_trade.exit_price == pytest.approx(stop_trade.entry_price * 0.95 - 0.00008, abs=1e-9)


# --- H-25: quant bars by exchange date, parametric VaR drift -------------------------------------------------------------

def test_h25_asx_bars_land_on_their_local_trading_day_so_they_pair_with_us_bars():
    from openterm.quantjobs import common as cm

    day = 86_400
    # ASX daily bars are stamped at the 10:00 open = 23:00 UTC the DAY BEFORE in summer (AEDT, UTC+11).
    ax = {"t": [1704236400, 1704236400 + day], "c": [10.0, 11.0], "tz": "Australia/Sydney"}   # 2024-01-02 23:00Z, 01-03 23:00Z
    # SPY: 09:30 New York = 14:30 UTC the same day.
    spy = {"t": [1704292200, 1704292200 + day], "c": [470.0, 471.0], "tz": "America/New_York"}  # 2024-01-03 14:30Z, 01-04 14:30Z
    d_ax, _ = cm.series(ax)
    assert [cm.iso(int(x)) for x in d_ax] == ["2024-01-03", "2024-01-04"]      # was 01-02 and 01-03 (the UTC day)
    days, mat = cm.align({"AX": cm.series(ax), "SPY": cm.series(spy)})
    assert [cm.iso(int(x)) for x in days] == ["2024-01-03", "2024-01-04"]      # the pairs share a date, not a shifted one
    assert mat.tolist() == [[10.0, 470.0], [11.0, 471.0]]
    # no zone (crypto, synthetic): the UTC day, as before
    assert [cm.iso(int(x)) for x in cm.series({"t": [1704236400], "c": [1.0]})[0]] == ["2024-01-02"]


def test_h25_parametric_var_scales_the_mean_by_the_horizon_and_the_spread_by_its_root():
    from openterm.quantjobs import common as cm
    from openterm.quantlib import risk

    # returns 1% and 3%: mean 0.02, sample sd 0.0141421. z(5%) = -1.644854. Over 4 periods the mean grows 4x and the
    # spread 2x: VaR = -(0.02 * 4 + (-1.644854) * 0.0141421 * 2) = -(0.08 - 0.0465229) = -0.0334771 (a gain).
    # The ported function scales the mean by sqrt(4) as well: -(0.02 - 0.0232614) * 2 = +0.006523 (kept: Vibe's number).
    assert cm.parametric_var([0.01, 0.03], 0.95, 4) == pytest.approx(-0.0334771, abs=1e-6)
    assert risk.parametric_var([0.01, 0.03], 0.95, 4) == pytest.approx(0.006523, abs=1e-6)
    assert cm.parametric_var([0.01, 0.03], 0.95, 1) == pytest.approx(-(0.02 - 1.644854 * 0.0141421), abs=1e-6)


# --- H-28: SCORE formulas on a company with a zero denominator ------------------------------------------------------------

def _filing(**over) -> dict:
    base = {"net_income": 10.0, "total_assets": 100.0, "operating_cf": 12.0, "long_term_debt": 20.0, "current_assets": 40.0,
            "current_liabilities": 20.0, "shares_diluted": 10.0, "gross_profit": 30.0, "revenue": 80.0, "receivables": 8.0,
            "ppe": 30.0, "da": 5.0, "sga": 10.0, "total_liabilities": 50.0, "retained_earnings": 15.0, "operating_income": 9.0,
            "equity": 50.0}
    return {**base, **over}


def test_h28_a_pre_revenue_company_is_not_computable_instead_of_crashing():
    from openterm.fund import scores

    cur, prev = _filing(revenue=0.0, gross_profit=0.0), _filing()
    for res in (scores.piotroski_f(cur, prev), scores.beneish_m(cur, prev), scores.piotroski_f(prev, cur)):
        assert res["score"] is None and res["zone"] is None
        assert any("ZERO" in m for m in res["missing"]), res["missing"]  # says why, so the panel prints NOT COMPUTABLE: ...
    # zero assets / zero liabilities break the Altman and Ohlson ratios the same way
    assert scores.altman_z(_filing(total_assets=0.0), 500.0)["score"] is None
    assert scores.altman_z2(_filing(total_liabilities=0.0))["score"] is None
    assert scores.ohlson_o(_filing(current_assets=0.0), _filing())["score"] is None


def test_h28_ohlson_probability_survives_a_hugely_negative_score():
    from openterm.fund import scores

    # net income 1e8 x total assets: -2.37 * 1e8 drives O to about -2.4e8, where exp(-O) overflows a float
    res = scores.ohlson_o(_filing(net_income=1e10), _filing())
    assert res["score"] < -1e6
    assert dict(res["inputs"])["PROBABILITY"] == 0.0


def test_h28_merton_says_so_when_it_cannot_solve_instead_of_crashing_or_returning_an_unconverged_number():
    from openterm.fund import scores

    # a near-default firm: equity 1,352 against 18.9 million of current liabilities and 216% equity vol. The fixed-point
    # iteration has not settled after 200 steps
    res = scores.merton_dd(1352.2115700124307, 2.16345564086947, 18937181.12909761, 0.0, 0.10664119296955922)
    assert res["score"] is None and any("CONVERGE" in m.upper() for m in res["missing"]), res
    # and one where N(d1) underflows to zero: a division by zero before the fix
    res = scores.merton_dd(1901.541303673125, 3.949860075478299, 53393806.91650316, 2211622567.5251994, 0.173338816056206)
    assert res["score"] is None and res["missing"]


# --- H-29: option expiry close in winter, 25-delta strike for long-dated / high-vol options ---------------------------

def test_h29_us_expiry_closes_at_1600_new_york_in_winter_too():
    from datetime import UTC, datetime

    from openterm.options import chain as ch

    # Friday 2026-12-18 (EST, UTC-5): the 16:00 close is 21:00 UTC. Yahoo stamps the expiry at 00:00 UTC of that date.
    exp = int(datetime(2026, 12, 18, tzinfo=UTC).timestamp())
    now = exp + 20.5 * 3600  # 15:30 New York: half an hour left
    assert ch.years_to_expiry(exp, now) == pytest.approx(0.5 * 3600 / (365 * 86400))  # was 0.0: the close was taken as 20:00 UTC
    # and in summer (EDT) it is still 20:00 UTC
    exp_s = int(datetime(2026, 7, 17, tzinfo=UTC).timestamp())
    assert ch.years_to_expiry(exp_s, exp_s + 19.5 * 3600) == pytest.approx(0.5 * 3600 / (365 * 86400))


def test_h29_25_delta_strike_is_found_when_vol_times_root_t_is_large():
    import math

    from openterm.options import surface as sf

    # flat 100% vol over 4 years: s sqrt(T) = 2. Forward 25-delta strikes: k = 0.5 x^2 -/+ 0.6744898 x for the call / put
    # = 2 + 1.3489796 = 3.3489796 and 2 - 1.3489796 = 0.6510204. The fixed (0, 1.5) and (-1.5, 0) brackets held neither.
    fit = sf.Fit(1.0, 0.0, 0.0, 0.0, 10, -5.0, 5.0)
    assert sf.delta_strike(fit, 4.0, True) == pytest.approx(3.3489796, abs=1e-6)
    assert sf.delta_strike(fit, 4.0, False) == pytest.approx(0.6510204, abs=1e-6)
    sk = sf.skew_metrics(fit, 4.0)
    assert sk["iv_c25"] == pytest.approx(1.0) and sk["rr25"] == pytest.approx(0.0) and not math.isnan(sk["bf25"])
    # the ordinary case keeps its answer: 20% vol, 1 year -> x = 0.2, call k = 0.02 + 0.1349 = 0.1549
    assert sf.delta_strike(sf.Fit(0.2, 0.0, 0.0, 0.0, 10, -1.0, 1.0), 1.0, True) == pytest.approx(0.5 * 0.04 + 0.6744898 * 0.2,
                                                                                               abs=1e-6)


def test_h29_a_negative_fitted_vol_is_not_reported_as_a_25_delta_vol():
    from openterm.options import surface as sf

    fit = sf.Fit(-0.05, 0.0, 0.0, 0.0, 10, -1.0, 1.0)  # a smile fit that went below zero
    sk = sf.skew_metrics(fit, 1.0)
    assert sk["iv_c25"] is None and sk["iv_p25"] is None and sk["rr25"] is None  # was -5.0% printed as an IV


# --- C-09: OSA P(PROFIT) with breakevens outside the spot grid -------------------------------------------------------

def _straddle_probability(sign: int) -> tuple[float, float]:
    """(model P(profit), hand value) for a 1Y ATM straddle: S = K = 100, r = 0, IV 60%. sign +1 long, -1 short."""
    import math

    from openterm.options import analytics as an
    from openterm.options.pricer import spot_grid

    S, K, T, iv = 100.0, 100.0, 1.0, 0.6
    # Hand maths. With r = 0 an ATM call and put cost the same: S * (2 N(iv sqrt(T) / 2) - 1) = 23.5823 each.
    leg = S * (2 * an.ncdf(iv * math.sqrt(T) / 2) - 1)
    prem = 2 * leg                                      # straddle = 47.1646
    lo_be, hi_be = K - prem, K + prem                   # breakevens 52.8354 and 147.1646: both OUTSIDE [80, 120]
    mu = math.log(S) - 0.5 * iv * iv * T                # lognormal location (r = 0)

    def cdf(x: float) -> float:
        return an.ncdf((math.log(x) - mu) / (iv * math.sqrt(T)))

    long_p = cdf(lo_be) + (1 - cdf(hi_be))              # P(S_T < 52.84) + P(S_T > 147.16) = 0.2227 + 0.1726
    legs = [{"qty": sign, "type": "C", "strike": K}, {"qty": sign, "type": "P", "strike": K}]
    curve = an.pl_curves(legs, [leg, leg], spot_grid([K, K], S, 200), T, 0.0, iv, 1.0, 0.0, 0.0)
    got = an.prob_profit(curve, S, T, 0.0, iv)
    return got, (long_p if sign > 0 else 1 - long_p)


def test_c09_long_straddle_with_far_breakevens_has_a_real_probability():
    got, want = _straddle_probability(+1)
    assert want == pytest.approx(0.3953, abs=1e-3)  # sanity of the hand maths itself
    assert got == pytest.approx(want, abs=1e-3)     # the bug said 0.0%


def test_c09_short_straddle_is_the_complement_not_100_percent():
    got, want = _straddle_probability(-1)
    assert want == pytest.approx(0.6047, abs=1e-3)
    assert got == pytest.approx(want, abs=1e-3)     # the bug said 100.0%


# ---------- M-11: an infinite NAV must be an error, not a number ----------


def test_m11_an_infinite_nav_is_rejected():
    mf = mod("openterm.world.mfund")
    body = {"meta": {"scheme_code": 1, "scheme_name": "X"}, "data": [{"date": "01-01-2026", "nav": "inf"}]}
    with pytest.raises(mf.MfundError):
        mf.parse_fund(body)
