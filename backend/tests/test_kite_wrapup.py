"""Kite wrap-up (2026-11-05): OMON / CT for BFO and CDS, the Kite `1D` range, and the ticker's reconnect after a dropped socket.

Dump rows for the root tests come from the REAL recorded subset (`kite_instruments_real_subset`); the option rows are written here, labelled,
because the recording holds no BFO or CDS option. Nothing in this file talks to the network: websockets.connect is replaced by a fake.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from openterm.kite import chain as kc
from openterm.kite.instruments import Instruments
from openterm.kite.symbols import derivative_root
from openterm.kite.ws import KiteTicker
from openterm.streaming.hub import Hub
from openterm.streaming.tick import Tick

FIX = Path(__file__).parent / "fixtures"


def rec(name: str) -> dict:
    return json.loads((FIX / f"{name}.json").read_bytes().decode("utf-8"))


SUBSET = rec("kite_instruments_real_subset")
QUOTES = rec("kite_quote_derivs_real")["body"]["data"]
WS = rec("kite_ws_packets_real")
NOW = datetime(2026, 11, 5, 6, 0, tzinfo=UTC).timestamp()  # 11:30 IST on the recording day

# --- (a) the root of a BFO / CDS symbol --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("symbol", "want"), [
    ("NIFTY.NFO", ("NFO", "NIFTY")), ("crudeoil.mcx", ("MCX", "CRUDEOIL")),
    ("SENSEX.BFO", ("BFO", "SENSEX")), ("USDINR.CDS", ("CDS", "USDINR")),
    ("RELIANCE.NS", None), ("^NSEI", None), (".CDS", None), ("AAPL", None),
])
def test_derivative_root_knows_every_derivative_exchange(symbol, want):
    assert derivative_root(symbol) == want


class Session:
    state = "OK"
    logged_in = True
    has_key = True

    def auth(self):
        return "key", "token"  # fake values: the fake socket below never looks at them


# A BFO / CDS option chain written for this test (NOT a recording). Same column layout as the real dump.
OPTION_ROWS = (
    "9000001,9001,SENSEX26N1180000CE,SENSEX,0,2026-11-12,80000,0.05,20,CE,BFO-OPT,BFO\n"
    "9000002,9002,SENSEX26N1180000PE,SENSEX,0,2026-11-12,80000,0.05,20,PE,BFO-OPT,BFO\n"
    "9000003,9003,USDINR26N1396CE,USDINR,0,2026-11-13,96,0.0025,1,CE,CDS-OPT,CDS\n"
    "9000004,9004,USDINR26N1396PE,USDINR,0,2026-11-13,96,0.0025,1,PE,CDS-OPT,CDS"
)


class Client:
    def __init__(self):
        self.asked: list[list[str]] = []

    async def get_text(self, path):
        assert path == "/instruments"
        return SUBSET["text"] + "\n" + OPTION_ROWS

    async def quote(self, keys):
        self.asked.append(list(keys))
        fake = {
            "BSE:SENSEX": {"last_price": 80100.0},
            "BFO:SENSEX26N1180000CE": {"last_price": 300.0, "oi": 5, "depth": {"buy": [{"price": 299.0}], "sell": [{"price": 301.0}]}},
            "BFO:SENSEX26N1180000PE": {"last_price": 250.0, "oi": 7},
            "CDS:USDINR26N13FUT": {"last_price": 95.5},  # the future that expires with the option: the spot stand-in
            "CDS:USDINR26N1396CE": {"last_price": 0.5, "oi": 11},
            "CDS:USDINR26N1396PE": {"last_price": 0.4, "oi": 13},
        }
        return {k: (fake.get(k) or QUOTES.get(k)) for k in keys if k in fake or k in QUOTES}


async def test_ct_lists_the_cds_futures_of_usdinr():
    c = Client()
    d = await kc.futures(Session(), c, Instruments(c, None), "USDINR.CDS", NOW, True)
    rows = d["sections"][0]["rows"]
    assert len(rows) >= 20 and all(r["symbol"].endswith(".CDS") for r in rows)
    assert rows[0]["contract"] == "USDINR26N06FUT" and rows[0]["price"] == QUOTES["CDS:USDINR26N06FUT"]["last_price"]


async def test_ct_lists_the_bfo_futures_of_sensex():
    c = Client()
    d = await kc.futures(Session(), c, Instruments(c, None), "SENSEX.BFO", NOW, True)
    rows = d["sections"][0]["rows"]
    assert [r["contract"] for r in rows] == ["SENSEX26NOVFUT"] and rows[0]["price"] == QUOTES["BFO:SENSEX26NOVFUT"]["last_price"]


async def test_omon_for_sensex_options_uses_the_bse_index_as_spot():
    c = Client()
    d = await kc.omon(Session(), c, Instruments(c, None), "SENSEX.BFO", NOW, True)
    assert any("BSE:SENSEX" in n for n in d["notes"])  # the spot basis names the index it quoted
    assert ["BSE:SENSEX"] == [k for k in c.asked[0] if k.startswith("BSE:")]
    calls = d["sections"][0]["rows"]
    assert calls and calls[0]["strike"] == 80000 and calls[0]["oi"] == 5


async def test_omon_for_usdinr_options_takes_the_spot_from_the_same_month_future():
    c = Client()
    d = await kc.omon(Session(), c, Instruments(c, None), "USDINR.CDS", NOW, True)
    assert any("UNDERLYING = USDINR26N13FUT" in n for n in d["notes"]), d["notes"]
    spot = next(h for h in d["headline"] if h["label"] == "SPOT")
    assert spot["raw"] == 95.5  # the future's price (no index exists for CDS)


async def test_omon_on_an_unknown_bfo_root_says_what_is_missing():
    c = Client()
    with pytest.raises(Exception, match="NO ZZZ OPTIONS ON BFO"):
        await kc.omon(Session(), c, Instruments(c, None), "ZZZ.BFO", NOW, True)


# --- (c) the ticker reconnects after a dropped socket -------------------------------------------------------------------------------------

class FakeSocket:
    """Stands in for a websockets connection: sends are remembered, frames are replayed, then it either drops or stays open."""

    def __init__(self, frames: list[bytes], drop_after: bool):
        self.frames, self.drop_after, self.sent = frames, drop_after, []

    async def send(self, text):
        self.sent.append(json.loads(text))

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for f in self.frames:
            yield f
        if self.drop_after:
            return  # the server closes the connection: `async for` ends
        await asyncio.Event().wait()  # stays open until the ticker is stopped


class FakeConnect:
    """One entry per connection attempt: an exception to raise, or a FakeSocket to hand over."""

    def __init__(self, plan):
        self.plan, self.calls = list(plan), 0

    def __call__(self, url, **_):
        self.calls += 1
        step = self.plan.pop(0)
        outer = self

        class Ctx:
            async def __aenter__(self):
                if isinstance(step, Exception):
                    raise step
                outer.current = step
                return step

            async def __aexit__(self, *a):
                return False

        return Ctx()


async def run_ticker(monkeypatch, plan, until, backoff_seen=None):
    """Run the real `_run` loop against the fake connect until `until(ticker)` is true; returns (ticker, connect, delays, states)."""
    import websockets

    connect = FakeConnect(plan)
    monkeypatch.setattr(websockets, "connect", connect)
    emitted: list[Tick] = []
    c = Client()
    ticker = KiteTicker(emitted.append, Session(), Instruments(c, None), lambda s: None)  # type: ignore[arg-type]
    delays: list[float] = []
    states: list[str] = []

    async def fast_sleep(seconds):  # records the wait the ticker asked for, and yields without really waiting
        delays.append(seconds)
        states.append(ticker.status)  # what the screen would see during the backoff
        await asyncio.sleep(0)

    ticker._sleep = fast_sleep
    await ticker.set_symbols({"RELIANCE.NS", "^NSEI"})
    ticker.start()
    try:
        async with asyncio.timeout(5):
            while not until(ticker, connect):
                await asyncio.sleep(0.01)
    finally:
        await ticker.stop()
    ticker.emitted = emitted  # type: ignore[attr-defined]
    return ticker, connect, delays, states


def frames() -> list[bytes]:
    return [bytes.fromhex(f["data"]) for f in WS["frames"][:2]]


async def test_a_dropped_socket_goes_down_at_once_backs_off_and_reconnects(monkeypatch):
    plan = [FakeSocket(frames(), drop_after=True), FakeSocket(frames(), drop_after=False)]
    ticker, connect, delays, states = await run_ticker(monkeypatch, plan, lambda t, c: c.calls >= 2 and t.status == "OK")
    assert connect.calls == 2
    assert delays == [1.0] and states == ["DOWN"]  # between the two connections the status was DOWN, so `covers` was false
    assert ticker.status == "OK" or ticker._task is not None
    for sock in plan:  # every connection subscribed to both instruments and asked for quote mode
        assert [m["a"] for m in sock.sent] == ["subscribe", "mode"]
        assert len(sock.sent[0]["v"]) == 2


async def test_failed_connects_back_off_doubling_and_a_good_connection_resets_it(monkeypatch):
    plan = [OSError("refused"), OSError("refused"), OSError("refused"), FakeSocket(frames(), drop_after=True),
            FakeSocket(frames(), drop_after=False)]
    _, _, delays, _ = await run_ticker(monkeypatch, plan, lambda t, c: c.calls >= 5 and t.status == "OK")
    assert delays == [1.0, 2.0, 4.0, 1.0]  # 1, 2, 4 while refused; the success resets it, so the next drop waits 1 again


async def test_the_backoff_stops_doubling_at_sixty_seconds(monkeypatch):
    plan = [OSError("refused")] * 8 + [FakeSocket([], drop_after=False)]
    _, _, delays, _ = await run_ticker(monkeypatch, plan, lambda t, c: c.calls >= 9 and t.status == "OK")
    assert delays == [1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 60.0, 60.0]


async def test_ticks_label_falls_back_to_stream_while_down_and_returns_to_rt_kite_after(monkeypatch):
    """Through the real hub: while the socket is gone Yahoo's tick passes (source y = STREAM); after the reconnect it is dropped again and
    Kite's own ticks (source k = RT KITE) come through."""
    plan = [FakeSocket(frames(), drop_after=True), FakeSocket(frames(), drop_after=False)]
    seen: dict[str, Tick] = {}
    hub_box: dict[str, Hub] = {}
    late = Tick("RELIANCE.NS", 1300.0, None, None, None, None, None, 1, "y")  # Yahoo's delayed stream tick

    import websockets

    connect = FakeConnect(plan)
    monkeypatch.setattr(websockets, "connect", connect)
    c = Client()
    ticker = KiteTicker(lambda t: hub_box["h"].emit(t), Session(), Instruments(c, None), lambda s: None)  # type: ignore[arg-type]
    hub = Hub(yahoo=type("Y", (), {"status": "OK", "messages": 0})(), poller=None, kite=ticker)
    hub_box["h"] = hub

    async def sleeper(seconds):
        hub.emit(late)  # a Yahoo tick arrives while the Kite socket is down
        seen["down"] = hub._pending.pop("RELIANCE.NS")
        await asyncio.sleep(0)

    ticker._sleep = sleeper
    await ticker.set_symbols({"RELIANCE.NS", "^NSEI"})
    ticker.start()
    try:
        async with asyncio.timeout(5):
            while not (connect.calls >= 2 and ticker.status == "OK" and "RELIANCE.NS" in hub._pending):
                await asyncio.sleep(0.01)
        hub.emit(late)  # Yahoo again, now that Kite is back: dropped
        seen["up"] = hub._pending["RELIANCE.NS"]
    finally:
        await ticker.stop()
    assert seen["down"].source == "y"  # STREAM while Kite was down
    assert seen["up"].source == "k" and seen["up"].price != 1300.0  # RT KITE after


# --- (b) a Kite 1D range is the last session, like Yahoo's ----------------------------------------------------------------------------------

def session_candles(day: str, n: int = 3) -> list[list]:
    """`n` five-minute candles of one IST day in Kite's row layout [time, o, h, l, c, v]."""
    return [[f"{day}T09:{15 + 5 * i:02d}:00+0530", 100 + i, 101 + i, 99, 100.5 + i, 1000] for i in range(n)]


class CandleClient(Client):
    def __init__(self, candles):
        super().__init__()
        self.candles_out, self.window = candles, None

    async def candles(self, token, interval, start, end):
        self.window = (start, end)
        return self.candles_out


def kite_provider(candles):
    from openterm.providers.kite import KiteProvider

    p = KiteProvider(None)  # type: ignore[arg-type]
    c = CandleClient(candles)
    p.session, p.client, p.instruments = Session(), c, Instruments(c, None)  # type: ignore[assignment]
    return p, c


async def test_one_day_is_the_last_session_not_48_hours():
    # Kite answers with Wednesday's and Thursday's candles for a 2-day window: only Thursday (the latest IST date present) is one session
    p, c = kite_provider(session_candles("2026-11-04") + session_candles("2026-11-05"))
    bars = await p.history("RELIANCE.NS", "1d", "5m")
    days = {datetime.fromtimestamp(t, p_tz()).strftime("%Y-%m-%d") for t in bars.t}
    assert days == {"2026-11-05"} and len(bars.t) == 3 and bars.range == "1d"
    assert (c.window[1] - c.window[0]).days >= 4  # a weekend or a holiday before the last session must still find one


async def test_one_day_after_a_weekend_still_returns_the_friday_session():
    p, _ = kite_provider(session_candles("2026-10-29") + session_candles("2026-10-30"))  # nothing since Friday 30 Oct
    bars = await p.history("RELIANCE.NS", "1d", "5m")
    assert {datetime.fromtimestamp(t, p_tz()).strftime("%Y-%m-%d") for t in bars.t} == {"2026-10-30"}


async def test_longer_ranges_are_not_trimmed():
    p, _ = kite_provider(session_candles("2026-11-04") + session_candles("2026-11-05"))
    bars = await p.history("RELIANCE.NS", "5d", "5m")
    assert len(bars.t) == 6


def p_tz():
    from zoneinfo import ZoneInfo

    return ZoneInfo("Asia/Kolkata")
