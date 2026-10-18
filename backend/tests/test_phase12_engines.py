"""Phase 12 step 5 additions: composite symbol classification, fail-closed markets, Binance candles (no network)."""

import asyncio
import importlib
import json
from pathlib import Path

import httpx
import pytest

FIX = Path(__file__).parent / "fixtures"


def mod(name: str):
    return importlib.import_module(name)


@pytest.mark.parametrize(("symbol", "market"), [
    ("AAPL", "us_equity"), ("BRK-B", "us_equity"), ("^GSPC", "us_equity"), ("RELIANCE.NS", "india_equity"),
    ("^NSEI", "india_equity"), ("VOD.L", "uk_equity"), ("0700.HK", "hk_equity"), ("TD.TO", "ca_equity"),
    ("BTCUSDT.P", "crypto"), ("BTC-USD", "crypto"), ("EURUSD=X", "forex"), ("ES=F", "futures"),
])
def test_market_of_reads_yahoo_style_symbols(symbol, market):
    assert mod("openterm.bt.engines.composite").market_of(symbol) == market


@pytest.mark.parametrize("symbol", ["7203.T", "SAP.DE", "600519.SH", "^N225"])
def test_market_of_refuses_markets_that_are_not_built(symbol):
    with pytest.raises(ValueError, match="CANNOT PLACE|UNKNOWN INDEX"):
        mod("openterm.bt.engines.composite").market_of(symbol)


def test_composite_refuses_a_mixed_currency_basket():
    engine = mod("openterm.bt.engines.composite")
    with pytest.raises(ValueError, match="one settlement currency"):
        engine._reject_mixed_currency(["AAPL", "RELIANCE.NS"])
    engine._reject_mixed_currency(["AAPL", "BTCUSDT.P", "ES=F"])  # all USD-settled: allowed


def test_composite_refuses_china_futures_and_unbuilt_markets():
    engine = mod("openterm.bt.engines.composite")
    with pytest.raises(ValueError, match="CHINA FUTURES"):
        engine.CompositeEngine({}, ["IF2406.CFFEX"])
    with pytest.raises(ValueError, match="CANNOT PLACE"):
        engine.CompositeEngine({}, ["AAPL", "7203.T"])


def test_crypto_engine_refuses_perpetual_strict():
    with pytest.raises(ValueError, match="PERPETUAL_STRICT"):
        mod("openterm.bt.engines.crypto").CryptoEngine({"perpetual_strict": True})


def test_unknown_engine_names_the_ones_that_exist():
    with pytest.raises(ValueError, match="UNKNOWN ENGINE CHINA_A"):
        mod("openterm.bt.engine").make_engine("china_a", {}, [])


def test_bars_per_year_by_engine_and_interval():
    cat = mod("openterm.bt.catalog")
    assert (cat.bars_per_year("us", "1D"), cat.bars_per_year("crypto", "1D"), cat.bars_per_year("crypto", "1W")) == (252, 365, 52)


def _provider():
    prov = mod("openterm.providers.crypto").BinanceKlinesProvider
    fixtures = mod("openterm.providers.fixtures")
    return prov(httpx.AsyncClient(transport=fixtures.fixture_transport()), source="binance_klines:fixture")


def test_binance_klines_supports_only_usdt_pairs():
    p = _provider()
    assert all(p.supports("history", s) for s in ("BTCUSDT", "BTC-USDT", "BTCUSDT.P", "ethusdt.p"))
    assert not any(p.supports("history", s) for s in ("AAPL", "BTC-USD", "EURUSD=X", "RELIANCE.NS"))
    assert not p.supports("quotes", "BTCUSDT")


def test_binance_perp_candles_carry_the_daily_mean_funding_rate():
    bars = asyncio.run(_provider().history("BTCUSDT.P", "MAX", "1d"))
    assert bars.exchange == "Binance USD-M Futures" and bars.source == "binance_klines:fixture"
    assert len(bars.fund) == len(bars.t) and any(f is not None for f in bars.fund)
    funding = json.loads((FIX / "binance_perp_funding_btcusdt.json").read_bytes().decode("utf-8"))["body"]
    first_day = funding[0]["fundingTime"] // 86_400_000 * 86_400
    day = [float(x["fundingRate"]) for x in funding if x["fundingTime"] // 86_400_000 * 86_400 == first_day]
    assert bars.fund[bars.t.index(first_day)] == pytest.approx(sum(day) / len(day))
    assert all(f is None for f in bars.fund[: bars.t.index(first_day)])  # no funding data before the recording


def test_binance_spot_candles_have_no_funding():
    bars = asyncio.run(_provider().history("BTC-USDT", "1Y", "1d"))
    assert bars.fund is None and bars.exchange == "Binance" and len(bars.t) == 367  # 1Y = 366 days + the open bar


def test_binance_unknown_symbol_is_not_found_not_an_outage():
    provider = mod("openterm.providers.base").ProviderError
    with pytest.raises(provider) as err:
        asyncio.run(_provider().history("DOGEUSDT", "1Y", "1d"))
    assert err.value.kind == "not_found"


def test_forex_run_refuses_slip(client):
    r = client.post("/api/bt/run", json={"rule": "CLOSE>SMA20", "symbols": ["EURUSD=X"], "options": {"slip_bps": 5}})
    assert r.status_code == 400 and "FOREX" in r.json()["error"]
