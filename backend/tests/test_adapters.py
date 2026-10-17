import httpx
import pytest

from openterm.providers.base import ProviderError
from openterm.providers.fixtures import fixture_transport
from openterm.providers.nasdaq import NasdaqProvider, num, parse_trade_time
from openterm.providers.yahoo import YahooProvider


@pytest.fixture
async def http():
    async with httpx.AsyncClient(transport=fixture_transport()) as c:
        yield c


async def test_yahoo_history_columnar(http):
    bars = await YahooProvider(http).history("AAPL", "1y", "1d")
    n = len(bars.t)
    assert n > 200
    assert len(bars.o) == len(bars.h) == len(bars.l) == len(bars.c) == len(bars.v) == n
    assert bars.t == sorted(bars.t)
    assert bars.currency == "USD" and bars.tz == "America/New_York"
    assert bars.source == "yahoo" and bars.as_of > 0
    assert all(lo <= hi for lo, hi in zip(bars.l, bars.h) if lo is not None and hi is not None)


async def test_yahoo_intraday_nse(http):
    bars = await YahooProvider(http).history("RELIANCE.NS", "1d", "5m")
    assert bars.currency == "INR" and bars.tz == "Asia/Kolkata" and len(bars.t) > 10


async def test_yahoo_unknown_symbol_is_not_found(http):
    with pytest.raises(ProviderError) as e:
        await YahooProvider(http).history("ZZZZNOTREAL", "1d", "1d")
    assert e.value.kind == "not_found"


async def test_yahoo_spark_quotes(http):
    qs = await YahooProvider(http).quotes(["AAPL", "RELIANCE.NS", "NOPE"])
    by = {q.symbol: q for q in qs}
    assert set(by) == {"AAPL", "RELIANCE.NS"}
    aapl = by["AAPL"]
    assert aapl.price and aapl.prev_close
    assert aapl.change == pytest.approx(aapl.price - aapl.prev_close)
    assert aapl.change_pct == pytest.approx(aapl.change / aapl.prev_close * 100)
    assert by["RELIANCE.NS"].currency == "INR"


async def test_yahoo_search(http):
    hits = await YahooProvider(http).search("RELIAN")
    assert hits[0].symbol == "RELIANCE.NS" and hits[0].exchange == "NSE"


async def test_nasdaq_quote(http):
    p = NasdaqProvider(http)
    assert p.supports("quotes", "AAPL") and not p.supports("quotes", "RELIANCE.NS")
    (q,) = await p.quotes(["AAPL"])
    assert q.price == 343.46 and q.change == 1.46 and q.change_pct == 0.43
    assert q.prev_close == pytest.approx(342.0)
    assert (q.low_52w, q.high_52w) == (243.42, 348.15)
    assert q.volume == 59946749


async def test_nasdaq_daily_only(http):
    with pytest.raises(ProviderError) as e:
        await NasdaqProvider(http).history("AAPL", "1d", "5m")
    assert e.value.kind == "unsupported"


def test_nasdaq_parsers():
    assert num("$1,234.50") == 1234.5 and num("N/A") is None and num("+0.43%") == 0.43
    assert parse_trade_time("Oct 15, 2026") is not None
    assert parse_trade_time("Oct 16, 2026 4:00 PM ET") is not None
    assert parse_trade_time("garbage") is None
