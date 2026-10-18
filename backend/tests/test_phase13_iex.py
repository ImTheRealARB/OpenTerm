"""Phase 13 step 7: real-time IEX trades (Alpaca keys). Doc-shaped answers; the plumbing is what is tested."""

import asyncio

import httpx
import pytest

from openterm.providers.alpaca import AlpacaProvider
from openterm.providers.base import ProviderError
from openterm.research import keyed_parse
from openterm.streaming.hub import Hub
from openterm.streaming.iex import US_SYMBOL, IexPoller, alpaca_symbol
from openterm.streaming.tick import Tick

TRADES = {"trades": {
    "AAPL": {"t": "2026-10-18T14:30:00.123456Z", "x": "V", "p": 190.5, "s": 100, "c": ["@"], "i": 1, "z": "C"},
    "BRK.B": {"t": "2026-10-18T14:30:01Z", "p": 450.0, "s": 5},
    "BAD": {"t": "nope", "p": 10},
    "ZERO": {"t": "2026-10-18T14:30:01Z", "p": 0},
}}


def test_parse_keeps_good_rows_and_converts_time():
    out = keyed_parse.alpaca_trades(TRADES)
    assert set(out) == {"AAPL", "BRK.B"}
    price, size, ms = out["AAPL"]
    assert (price, size) == (190.5, 100) and ms == 1792333800123
    with pytest.raises(ProviderError):
        keyed_parse.alpaca_trades({"nope": 1})


def test_only_us_tickers_and_class_shares_are_asked_for():
    assert all(US_SYMBOL.match(s) for s in ("AAPL", "BRK-B", "F"))
    assert not any(US_SYMBOL.match(s) for s in ("RELIANCE.NS", "^GSPC", "EURUSD=X", "BTC-USD", "SYN0001", "TOOLONGX"))
    assert alpaca_symbol("BRK-B") == "BRK.B"


async def test_provider_sends_feed_iex_and_keys_in_headers():
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=TRADES)

    p = AlpacaProvider(httpx.AsyncClient(transport=httpx.MockTransport(handler)), key_id="KID", secret="SEC")
    out = await p.latest_trades(["AAPL", "BRK.B"])
    assert out["AAPL"][0] == 190.5
    q = seen[0].url.params
    assert q["feed"] == "iex" and q["symbols"] == "AAPL,BRK.B"
    assert seen[0].headers["apca-api-key-id"] == "KID" and "KID" not in str(seen[0].url) and "SEC" not in str(seen[0].url)


class FakeAlpaca:
    def __init__(self, has_key=True):
        self.has_key = has_key
        self.calls = []
        self.answer = keyed_parse.alpaca_trades(TRADES)
        self.error = None

    async def latest_trades(self, symbols):
        self.calls.append(symbols)
        if self.error:
            raise self.error
        return self.answer


async def run_poller(fake, symbols, prev=lambda s: 180.0, wait=0.12):
    ticks = []
    iex = IexPoller(ticks.append, fake, prev, interval_s=0.02)
    await iex.set_symbols(symbols)
    iex.start()
    await asyncio.sleep(wait)
    await iex.stop()
    return iex, ticks


async def test_poller_emits_rt_ticks_once_per_trade_with_change_from_prev_close():
    fake = FakeAlpaca()
    iex, ticks = await run_poller(fake, {"AAPL", "BRK-B", "RELIANCE.NS"})
    assert {t.symbol for t in ticks} == {"AAPL", "BRK-B"}  # non-US dropped, BRK.B mapped back to BRK-B
    assert len(ticks) == 2  # the same trades polled again are not new ticks
    t = next(t for t in ticks if t.symbol == "AAPL")
    assert (t.source, t.price, t.time_ms) == ("a", 190.5, 1792333800123)
    assert t.change == pytest.approx(10.5) and t.change_pct == pytest.approx(10.5 / 180 * 100)
    assert fake.calls[0] == ["AAPL", "BRK.B"] and iex.status == "OK"
    assert iex.covers("AAPL") and not iex.covers("MSFT")


async def test_poller_without_keys_does_nothing():
    fake = FakeAlpaca(has_key=False)
    iex, ticks = await run_poller(fake, {"AAPL"})
    assert ticks == [] and fake.calls == [] and iex.status == "OFF" and not iex.covers("AAPL")


async def test_poller_reports_a_refused_key_and_an_outage():
    fake = FakeAlpaca()
    fake.error = ProviderError("key_required", "refused")
    iex, ticks = await run_poller(fake, {"AAPL"})
    assert ticks == [] and iex.status == "KEY REQUIRED"
    fake.error = ProviderError("unavailable", "timeout")
    iex, ticks = await run_poller(fake, {"AAPL"})
    assert iex.status == "DOWN" and not iex.covers("AAPL")


async def test_no_prev_close_still_ticks_without_change():
    _iex, ticks = await run_poller(FakeAlpaca(), {"AAPL"}, prev=lambda s: None)
    assert ticks[0].change is None and ticks[0].change_pct is None


async def test_hub_drops_yahoo_ticks_only_while_iex_covers_the_symbol():
    fake = FakeAlpaca()
    iex, _ = await run_poller(fake, {"AAPL"})
    hub = Hub(yahoo=None, poller=None, iex=iex)
    yahoo = Tick("AAPL", 191.0, 1.0, 0.5, None, None, None, 1, "y")
    other = Tick("MSFT", 400.0, 1.0, 0.5, None, None, None, 1, "y")
    rt = Tick("AAPL", 190.5, None, None, None, None, None, 2, "a")
    hub.emit(yahoo)
    hub.emit(other)
    hub.emit(rt)
    assert hub._pending["AAPL"].source == "a" and hub._pending["MSFT"].source == "y"
    assert hub.ticks_in == 2
    iex._seen["AAPL"] -= 10  # IEX went quiet: Yahoo ticks pass again
    hub.emit(yahoo)
    assert hub._pending["AAPL"].source == "y"
    fake.has_key = False
    iex._seen["AAPL"] = iex._seen["AAPL"] + 100
    hub.emit(Tick("AAPL", 192.0, None, None, None, None, None, 3, "p"))
    assert hub._pending["AAPL"].price == 192.0  # keys removed: coverage ends at once


def test_stats_report_iex_state():
    assert Hub(yahoo=type("Y", (), {"status": "OK", "messages": 0})(), poller=None).stats()["iex"] == "OFF"
