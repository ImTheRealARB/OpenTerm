"""Kite follow-ups (2026-11-05), pinned on REAL recordings made against the live service the same day (scripts/record_kite_live.py).

The `*_real.json` fixtures hold real Kite Connect answers (NFO / BFO / MCX / CDS futures, an option, BSE and NSE equity, the WebSocket frames).
Expected numbers are read back out of those files, never typed here, so a re-recording on another day keeps the tests valid.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from openterm.kite.instruments import Instruments, parse
from openterm.kite.symbols import to_kite, to_yahoo
from openterm.kite.ws import KiteTicker, decode, default_segment
from openterm.providers.base import ProviderError
from openterm.providers.kite import KiteProvider
from openterm.streaming.hub import Hub
from openterm.streaming.tick import Tick

FIX = Path(__file__).parent / "fixtures"


def rec(name: str) -> dict:
    return json.loads((FIX / f"{name}.json").read_bytes().decode("utf-8"))


SUBSET = rec("kite_instruments_real_subset")
QUOTES = rec("kite_quote_derivs_real")["body"]["data"]
KEYS = SUBSET["keys"]  # role -> Kite key, as picked on the recording day


class FakeSession:
    state = "OK"
    logged_in = True
    has_key = True

    def message(self):
        return None


class FakeClient:
    """Answers from the recordings and remembers what was asked."""

    def __init__(self):
        self.asked_quotes: list[list[str]] = []

    async def get_text(self, path):
        assert path == "/instruments"
        return SUBSET["text"]

    async def quote(self, keys):
        self.asked_quotes.append(list(keys))
        return {k: QUOTES[k] for k in keys if k in QUOTES}

    async def candles(self, token, interval, start, end):
        for name in ("reliance", "nifty_fut", "gold_fut", "usdinr_fut"):
            r = rec(f"kite_historical_{name}_day_real")
            if r["token"] == token:
                return r["body"]["data"]["candles"]
        return []


def provider() -> tuple[KiteProvider, FakeClient]:
    p = KiteProvider(None)  # type: ignore[arg-type]
    c = FakeClient()
    p.session, p.client, p.instruments = FakeSession(), c, Instruments(c, None)  # type: ignore[assignment]
    return p, c


def yahoo_of(key: str) -> str:
    sym = to_yahoo(key)
    assert sym is not None, key
    return sym


# --- symbols of every segment resolve to the instrument Kite recorded --------------------------------------------------------------------

@pytest.mark.parametrize("role", ["nifty_fut", "sensex_fut", "gold_fut", "crude_fut", "usdinr_fut", "reliance", "reliance_bse", "nifty_ce"])
def test_every_segment_round_trips_between_our_symbol_and_the_kite_key(role):
    key = KEYS[role]
    sym = yahoo_of(key)
    assert to_kite(sym) == key
    assert parse(SUBSET["text"], 0.0).find(key) is not None, key  # and the recorded dump really holds that instrument


def test_a_bse_scrip_code_resolves_to_the_same_instrument_as_the_name():
    """Yahoo writes BSE tickers as numbers (`500325.BO`); Kite's trading symbol is the name (`RELIANCE`) and the number is its exchange_token."""
    dump = parse(SUBSET["text"], 0.0)
    by_name = dump.find("BSE:RELIANCE")
    assert by_name is not None and dump.find(f"BSE:{by_name['exchange_token']}") == by_name
    assert dump.find("BSE:999999") is None  # an unknown code stays unknown
    assert dump.find("NSE:2885") is None  # NSE has no such alias: only BSE scrip codes are numbers in the Yahoo convention


async def test_quotes_ask_kite_for_the_name_when_given_a_bse_scrip_code():
    p, c = provider()
    code = parse(SUBSET["text"], 0.0).find("BSE:RELIANCE")["exchange_token"]
    (q,) = await p.quotes([f"{code}.BO"])
    assert c.asked_quotes == [["BSE:RELIANCE"]]  # Kite's /quote knows no numeric trading symbol
    assert q.symbol == f"{code}.BO" and q.exchange == "BSE" and q.price == QUOTES["BSE:RELIANCE"]["last_price"]


# --- quotes: every derivative segment is parsed with its real fields -----------------------------------------------------------------------

@pytest.mark.parametrize("role", ["nifty_fut", "sensex_fut", "gold_fut", "usdinr_fut", "nifty_ce", "reliance_bse"])
async def test_quotes_for_derivative_segments_use_the_real_fields(role):
    p, _ = provider()
    key = KEYS[role]
    (q,) = await p.quotes([yahoo_of(key)])
    raw = QUOTES[key]
    assert q.exchange == key.partition(":")[0] and q.currency == "INR" and q.price == raw["last_price"]
    assert q.prev_close == (raw["ohlc"]["close"] or None) and q.high == (raw["ohlc"]["high"] or None) and q.open == (raw["ohlc"]["open"] or None) and q.volume == (raw["volume"] or None)
    assert q.market_time is not None and q.market_time > 1_700_000_000  # the "YYYY-MM-DD HH:MM:SS" IST stamp parsed


# --- history: open interest only where it exists ------------------------------------------------------------------------------------------

async def test_futures_bars_carry_open_interest_and_cash_bars_do_not():
    p, _ = provider()
    fut = await p.history(yahoo_of(KEYS["nifty_fut"]), "1mo", "1d")
    want = rec("kite_historical_nifty_fut_day_real")["body"]["data"]["candles"]
    assert fut.oi == [float(c[6]) for c in want] and any(x > 0 for x in fut.oi) and fut.exchange == "NFO"
    cash = await p.history("RELIANCE.NS", "1mo", "1d")
    assert cash.oi is None  # Kite answers 0 for every bar of a share: that is "no open interest", not a line at zero
    assert len(cash.t) == len(rec("kite_historical_reliance_day_real")["body"]["data"]["candles"])


@pytest.mark.parametrize("role", ["gold_fut", "usdinr_fut"])
async def test_mcx_and_cds_daily_bars_keep_their_prices(role):
    p, _ = provider()
    bars = await p.history(yahoo_of(KEYS[role]), "1mo", "1d")
    want = rec(f"kite_historical_{role}_day_real")["body"]["data"]["candles"]
    assert bars.c == [float(c[4]) for c in want] and bars.exchange == KEYS[role].partition(":")[0]


async def test_a_contract_that_is_not_in_the_dump_says_which_contracts_exist():
    p, _ = provider()
    with pytest.raises(ProviderError) as e:
        await p.history("NIFTY26OCTFUT.NFO", "1mo", "1d")  # expired contracts are not in Kite's dump
    msg = str(e.value)
    assert e.value.kind == "not_found" and "NIFTY26OCTFUT" in msg and KEYS["nifty_fut"].partition(":")[2] in msg
    with pytest.raises(ProviderError) as e:
        await p.history("NIFTY.NFO", "1mo", "1d")  # a bare underlying is not a contract
    assert KEYS["nifty_fut"].partition(":")[2] in str(e.value)
    with pytest.raises(ProviderError) as e:
        await p.history("ZZZNOPE.NS", "1mo", "1d")  # a share: no contract list, just the plain message
    assert "CONTRACTS" not in str(e.value).upper()


# --- the WebSocket ticker, on real frames -------------------------------------------------------------------------------------------------

WS = rec("kite_ws_packets_real")


def segments() -> dict[int, str | None]:
    return {int(t): {"CDS": "cds", "BCD": "bcd"}.get(v["exchange"]) for t, v in WS["tokens"].items()}


def real_ticks() -> list[dict]:
    seg = segments()
    return [d for f in WS["frames"] for d in decode(bytes.fromhex(f["data"]), lambda t: seg.get(t) or default_segment(t))]


def test_the_decoder_reads_every_real_frame_into_prices_that_match_the_rest_answer():
    ticks = real_ticks()
    assert len(ticks) >= 6 and {t["token"] for t in ticks} <= {int(k) for k in WS["tokens"]}
    quote_by_token = {v["instrument_token"]: (k, v) for k, v in QUOTES.items()}
    checked = 0
    for t in ticks:
        if t["token"] not in quote_by_token:
            continue
        key, raw = quote_by_token[t["token"]]
        # a live price moves between two recordings minutes apart, but it stays within a few percent: a wrong divisor would be off by 100x
        assert t["ltp"] == pytest.approx(raw["last_price"], rel=0.05), key
        checked += 1
    assert checked >= 4  # the equity, the futures and the option were all cross-checked


def test_full_mode_frames_carry_open_interest_and_five_depth_levels_and_quote_frames_do_not():
    by_token: dict[int, dict] = {}
    for t in real_ticks():
        by_token.setdefault(t["token"], t)
    full = [by_token[int(k)] for k, v in WS["tokens"].items() if v["mode"] == "full" and int(k) in by_token]
    assert full and all(f["oi"] > 0 and len(f["depth_buy"]) == 5 and len(f["depth_sell"]) == 5 for f in full)
    equity = by_token[int(next(k for k, v in WS["tokens"].items() if v["key"] == "NSE:RELIANCE"))]
    assert "oi" not in equity and equity["volume"] > 0


def test_currency_futures_are_scaled_by_ten_million_from_the_instrument_segment():
    token = int(next(k for k, v in WS["tokens"].items() if v["exchange"] == "CDS"))
    t = next(t for t in real_ticks() if t["token"] == token)
    assert 50 < t["ltp"] < 150  # USDINR in rupees; unscaled it would be about 962 million
    raw = next(d for f in WS["frames"] for d in decode(bytes.fromhex(f["data"]), lambda _t: "cds") if d["token"] == token)
    assert raw["ltp"] == t["ltp"]


class Capture:
    def __init__(self):
        self.ticks = []

    def __call__(self, tick):
        self.ticks.append(tick)


async def ticker_with_real_frames() -> tuple[KiteTicker, Capture]:
    cap = Capture()
    ticker = KiteTicker(cap, FakeSession(), Instruments(FakeClient(), None), lambda s: None)  # type: ignore[arg-type]
    await ticker.set_symbols({yahoo_of(v["key"]) for v in WS["tokens"].values()})
    ticker._wanted = await ticker._tokens()
    return ticker, cap


async def test_ticker_turns_real_frames_into_hub_ticks_tagged_k():
    ticker, cap = await ticker_with_real_frames()
    for f in WS["frames"]:
        ticker.on_message(bytes.fromhex(f["data"]))
    assert cap.ticks and {t.source for t in cap.ticks} == {"k"}
    symbols = {t.symbol for t in cap.ticks}
    assert yahoo_of("NSE:RELIANCE") in symbols and yahoo_of("NSE:NIFTY 50") in symbols
    rel = next(t for t in cap.ticks if t.symbol == "RELIANCE.NS")
    assert rel.change is not None and rel.change_pct is not None and rel.volume and rel.time_ms > 1_700_000_000_000


async def test_kite_keeps_a_symbol_while_connected_even_if_it_goes_quiet_for_a_while():
    """An illiquid option can be silent for minutes. If Yahoo's delayed tick got through then, the price would jump back 15 minutes."""
    ticker, _ = await ticker_with_real_frames()
    sym = "RELIANCE.NS"
    assert not ticker.covers(sym)  # nothing connected yet: Yahoo / the poller serve it
    ticker.status = "OK"
    assert ticker.covers(sym) and not ticker.covers("AAPL")  # connected and subscribed: Kite owns it
    ticker.symbols = set()  # the wanted set only changes when the loop re-reads it: quiet time alone never lapses the cover
    assert ticker.covers(sym)  # quiet for an hour, still ours
    ticker.status = "DOWN"
    assert not ticker.covers(sym)  # the socket is gone: Yahoo / the poller take over at once (their label is STREAM / POLL)


async def test_hub_hands_an_indian_symbol_back_to_yahoo_and_the_poller_when_the_kite_socket_drops():
    ticker, _ = await ticker_with_real_frames()
    hub = Hub(yahoo=type("Y", (), {"status": "OK", "messages": 0})(), poller=None, kite=ticker)
    late = Tick("RELIANCE.NS", 1300.0, None, None, None, None, None, 1, "y")  # Yahoo's delayed stream
    polled = Tick("RELIANCE.NS", 1299.0, None, None, None, None, None, 2, "p")
    ticker.status = "OK"
    hub.emit(late)
    assert hub.ticks_in == 0 and not hub._pending  # Kite owns the symbol: the delayed tick is dropped
    ticker.status = "DOWN"
    hub.emit(late)
    assert hub._pending["RELIANCE.NS"].source == "y"  # fallback: the screen then labels it STREAM
    hub.emit(polled)
    assert hub._pending["RELIANCE.NS"].source == "p"  # and POLL for the REST poller
    assert hub.stats()["kite"] == "DOWN"


def test_the_hub_label_for_kite_ticks_is_rt_kite():
    """The wire code `k` must have a name on screen (it showed as the bare letter before)."""
    src = (Path(__file__).parents[2] / "frontend" / "src" / "state" / "ticks.ts").read_bytes().decode("utf-8")
    assert 'k: "RT KITE"' in src and "RT KITE" in src.split("export function srcLabel")[1]


def test_packet_helper_still_rejects_noise():
    assert decode(struct.pack(">HH", 1, 99) + b"\x00" * 3) == []
