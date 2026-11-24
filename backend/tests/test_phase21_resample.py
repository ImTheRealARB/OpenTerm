"""Phase 21: the longer candle lengths (2h..12h, 2d, 3d, 2wk, quarterly, yearly) built by openterm/resample.py, and Binance 1 second candles.

Pure unit tests on hand-made bars (so every expected number can be checked by eye), plus the 1 second recording and the service wiring.
No network: the 1 second candles replay `binance_spot_klines_btcusdt_1s_real.json`, a real answer recorded on 2026-11-24.
"""

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from openterm.models import Bars
from openterm.providers.base import ProviderError
from openterm.providers.crypto import BinanceKlinesProvider
from openterm.providers.fixtures import fixture_transport
from openterm.providers.yahoo import YahooProvider
from openterm.ranges import INTERVALS, RANGES, normalize
from openterm.resample import RESAMPLED, ResampleError, resample


def _ts(tz: str, y: int, mo: int, d: int, h: int, mi: int = 0) -> int:
    """Epoch seconds of a wall-clock time in an exchange time zone."""
    return int(datetime(y, mo, d, h, mi, tzinfo=ZoneInfo(tz)).timestamp())


def _bars(t: list[int], interval: str, tz: str, **extra) -> Bars:
    """Hand-made candles: bar i opens at 100+i, high open+2, low open-1, close open+0.5, volume 10*(i+1)."""
    o = [100.0 + i for i in range(len(t))]
    return Bars.model_construct(
        symbol="TEST", range="1y", interval=interval, currency="USD", exchange="X", tz=tz, t=t, o=o,
        h=[x + 2 for x in o], l=[x - 1 for x in o], c=[x + 0.5 for x in o], v=[10 * (i + 1) for i in range(len(t))],
        source="fake", as_of=1.0, **extra,
    )


def _local(t: int, tz: str) -> str:
    return datetime.fromtimestamp(t, ZoneInfo(tz)).strftime("%m-%d %H:%M")


def test_us_hours_are_cut_from_the_session_open_and_never_cross_a_day():
    tz = "America/New_York"
    # Two sessions of seven hourly candles (09:30 .. 15:30), the way Yahoo sends them.
    t = [_ts(tz, 2024, 3, d, 9 + h, 30) for d in (4, 5) for h in range(7)]
    out = resample(_bars(t, "60m", tz), "4h")
    # Each day: 09:30-13:30 holds 4 candles, 13:30-17:30 holds the last 3. The second day starts a new bucket on its own.
    assert [_local(x, tz) for x in out.t] == ["03-04 09:30", "03-04 13:30", "03-05 09:30", "03-05 13:30"]
    assert out.interval == "4h" and out.source == "fake" and out.tz == tz
    assert out.o[0] == 100.0 and out.c[0] == 103.5 and out.h[0] == 105.0 and out.l[0] == 99.0  # first open, last close, max high, min low
    assert out.v == [10 + 20 + 30 + 40, 50 + 60 + 70, 80 + 90 + 100 + 110, 120 + 130 + 140]


def test_india_hours_are_cut_from_09_15():
    tz = "Asia/Kolkata"
    t = [_ts(tz, 2024, 3, 4, 9 + h, 15) for h in range(7)]  # 09:15 .. 15:15
    out = resample(_bars(t, "60m", tz), "2h")
    assert [_local(x, tz) for x in out.t] == ["03-04 09:15", "03-04 11:15", "03-04 13:15", "03-04 15:15"]
    assert out.v == [10 + 20, 30 + 40, 50 + 60, 70]  # the last candle of the day stands alone


def test_quarters_and_years_come_from_calendar_months():
    tz = "America/New_York"
    # Nov 2022 .. Jun 2023: the series opens on a half quarter and a half year, and those buckets hold only what exists.
    months = [(2022, 11), (2022, 12), *[(2023, m) for m in range(1, 7)]]
    t = [_ts(tz, y, m, 3, 9, 30) for y, m in months]
    base = _bars(t, "1mo", tz, adj=[1.0 * i for i in range(len(t))])
    q = resample(base, "3mo")
    # Quarters: [Nov, Dec] [Jan, Feb, Mar] [Apr, May, Jun] (calendar quarters, not "every 3 candles")
    assert [_local(x, tz)[:5] for x in q.t] == ["11-03", "01-03", "04-03"]
    assert q.v == [10 + 20, 30 + 40 + 50, 60 + 70 + 80]
    assert q.c == [101.5, 104.5, 107.5] and q.adj == [1.0, 4.0, 7.0]  # the last close and last adjusted close of each quarter
    y = resample(base, "12mo")
    assert [_local(x, tz)[:5] for x in y.t] == ["11-03", "01-03"] and y.v == [10 + 20, 30 + 40 + 50 + 60 + 70 + 80]


def test_two_day_bars_count_from_the_start_and_skip_missing_values():
    t = [1_700_000_000 + i * 86_400 for i in range(5)]
    base = _bars(t, "1d", "UTC", adj=[1.0, 2.0, 3.0, 4.0, 5.0])
    base.o[0], base.v[1], base.c[3] = None, None, None  # a source may leave a value out
    out = resample(base, "2d")
    assert out.t == [t[0], t[2], t[4]] and out.v == [10, 30 + 40, 50]  # chunks of 2 from the start; the last chunk holds 1
    assert out.o[0] == 101.0  # the first open that exists
    assert out.c == [101.5, 102.5, 104.5]  # the second chunk's last close is missing, so the one before it counts
    assert out.adj == [2.0, 4.0, 5.0]  # the last adjusted close of each chunk
    with pytest.raises(ResampleError, match="NOT THE 60m"):  # daily bars cannot be folded into hours
        resample(base, "4h")


def test_new_interval_words_normalize_and_never_collide_with_a_range():
    for word, want in {"4H": "4h", "4h": "4h", "Q": "3mo", "quarterly": "3mo", "3mo": "3mo", "12MO": "12mo", "yearly": "12mo",
                       "2W": "2wk", "2d": "2d", "1s": "1s", "1sec": "1s"}.items():
        assert normalize("1Y", word) == ("1y", want), word
    assert set(RESAMPLED) <= set(INTERVALS.values())
    assert not (set(INTERVALS) - {"1D"}) & set(RANGES), "an interval alias must not also be a range id"  # "1D" has always been both


def _binance():
    return BinanceKlinesProvider(httpx.AsyncClient(transport=fixture_transport()), source="binance_klines:fixture")


def test_binance_one_second_candles_replay_the_recording_and_say_how_much_they_hold():
    bars = asyncio.run(_binance().history("BTCUSDT", "1D", "1s"))
    assert bars.interval == "1s" and len(bars.t) == 120 and bars.t[0] == 1_795_508_296
    assert all(b - a == 1 for a, b in zip(bars.t, bars.t[1:], strict=False))  # one candle per second
    assert bars.range == "2min"  # 1D was asked, 120 seconds are held: the label says what is held, not what was asked
    with pytest.raises(ProviderError) as err:  # the perpetual host has no 1 second candles
        asyncio.run(_binance().history("BTCUSDT.P", "1D", "1s"))
    assert err.value.kind == "unsupported"
    with pytest.raises(ProviderError) as err:  # and Yahoo must not forward the length (its error would count as an outage)
        asyncio.run(YahooProvider(httpx.AsyncClient(transport=fixture_transport())).history("AAPL", "1d", "1s"))
    assert err.value.kind == "unsupported"


def test_service_builds_two_day_candles_from_daily_ones_and_reports_the_base_envelope(client):
    daily = client.get("/api/history", params={"symbol": "AAPL", "range": "1Y", "interval": "1d"}).json()
    two = client.get("/api/history", params={"symbol": "AAPL", "range": "1Y", "interval": "2d"})
    assert two.status_code == 200
    body = two.json()
    n = len(daily["data"]["t"])
    assert body["data"]["interval"] == "2d" and len(body["data"]["t"]) == (n + 1) // 2
    assert body["data"]["t"][:2] == daily["data"]["t"][:4:2]
    assert body["source"] == daily["source"] and body["as_of"] == daily["as_of"]  # the envelope is the base answer's
    # A second call is served from the entry cached under the 2d key and gives the same bars.
    assert client.get("/api/history", params={"symbol": "AAPL", "range": "1Y", "interval": "2d"}).json()["data"] == body["data"]
    limits = client.get("/api/history/limits", params={"symbol": "AAPL"}).json()["intraday_days"]
    assert limits["4h"] == limits["60m"] and "2d" not in limits  # hours reach as far as 60m; daily-based lengths are not limited


def test_service_one_second_candles_are_binance_only(client):
    ok = client.get("/api/history", params={"symbol": "BTCUSDT", "range": "1D", "interval": "1s"})
    assert ok.status_code == 200 and ok.json()["data"]["interval"] == "1s" and len(ok.json()["data"]["t"]) == 120
    bad = client.get("/api/history", params={"symbol": "AAPL", "range": "1D", "interval": "1s"})
    assert bad.status_code == 400 and "BINANCE" in bad.json()["error"]
