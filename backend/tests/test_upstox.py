"""Upstox adapter (READ-ONLY, free Analytics Token).

Every answer below is DOC-SHAPED: written from the Upstox developer docs with invented numbers, not recorded from the live
service (no token was available). These tests prove the plumbing and the parsers; the first live call is the real test.
"""

import gzip
import itertools
import json
from datetime import date, datetime

import httpx
import pytest

from openterm.providers import upstox_parse as up
from openterm.providers.base import ProviderError
from openterm.providers.upstox import UpstoxProvider
from openterm.router import Router

TOKEN = "docshape_analytics_token"
RELIANCE = {"segment": "NSE_EQ", "instrument_key": "NSE_EQ|INE002A01018", "trading_symbol": "RELIANCE", "name": "RELIANCE INDUSTRIES LTD",
            "isin": "INE002A01018", "instrument_type": "EQ", "exchange_token": "2885"}
RELIANCE_BE = {**RELIANCE, "instrument_key": "NSE_EQ|INE002A01018X", "instrument_type": "BE"}  # a duplicate name in another series
BSE_RELIANCE = {"segment": "BSE_EQ", "instrument_key": "BSE_EQ|INE002A01018", "trading_symbol": "RELIANCE", "name": "RELIANCE INDUSTRIES LTD",
                "isin": "INE002A01018", "instrument_type": "A", "exchange_token": "500325"}
OPTION = {"segment": "NSE_FO", "instrument_key": "NSE_FO|51834", "trading_symbol": "NIFTY25APR21600PE", "instrument_type": "PE"}


def instruments_file(*rows) -> bytes:
    return gzip.compress(json.dumps(list(rows)).encode())


def candle(day: str, close: float, vol: int = 1000, oi: int = 0):
    return [f"{day}T00:00:00+05:30", close - 2, close + 3, close - 4, close, vol, oi]


def make(handler) -> UpstoxProvider:
    p = UpstoxProvider(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    p.set_keys({"UPSTOX_ANALYTICS_TOKEN": TOKEN})
    return p


# --- pure helpers -------------------------------------------------------------------------------------------------------

def test_symbol_mapping():
    assert up.classify("RELIANCE.NS") == ("equity", "NSE_EQ", "NSE", "RELIANCE")
    assert up.classify("500325.bo") == ("equity", "BSE_EQ", "BSE", "500325")
    assert up.classify("^NSEI")[1] == "NSE_INDEX|Nifty 50" and up.classify("^BSESN")[1] == "BSE_INDEX|SENSEX"
    assert up.classify("AAPL") is None and up.classify(".NS") is None and up.classify("NIFTY.NFO") is None


def test_candle_path_escapes_the_pipe_and_follows_the_documented_route():
    path = up.candle_path("NSE_EQ|INE002A01018", "minutes", 5, date(2025, 1, 1), date(2025, 1, 31))
    assert path == "/v3/historical-candle/NSE_EQ%7CINE002A01018/minutes/5/2025-01-31/2025-01-01"  # .../{to_date}/{from_date}


def test_windows_are_contiguous_within_the_request_limit_and_stop_at_the_data_start():
    end = date(2026, 11, 5)
    wins = up.windows(end, 365, "minutes", 5)  # 5 minute candles: at most about a month per request
    assert wins[-1][1] == end and wins[0][0] == date(2025, 11, 5)
    assert all((b - a).days <= 28 for a, b in wins)
    assert all((nxt[0] - cur[1]).days == 1 for cur, nxt in itertools.pairwise(wins)), "gap or overlap between windows"
    assert up.windows(end, 100_000, "minutes", 5)[0][0] == date(2022, 1, 1)  # never earlier than January 2022
    assert up.windows(end, 100_000, "days", 1)[0][0] == date(2000, 1, 1)
    assert len(up.windows(end, 100_000, "weeks", 1)) == 1  # no limit: one request
    assert len(up.windows(end, 30, "minutes", 30)) == 1
    assert up.depth_days(date(2022, 1, 31)) == 30


def test_parse_candles_sorts_drops_duplicates_and_rejects_a_bad_shape():
    rows = [candle("2025-01-03", 103), candle("2025-01-01", 101), candle("2025-01-02", 102), candle("2025-01-02", 102)]
    out = up.parse_candles(rows)
    assert [r[4] for r in out] == [101.0, 102.0, 103.0] and out[0][0] < out[1][0]
    assert out[0][0] == int(datetime.fromisoformat("2025-01-01T00:00:00+05:30").timestamp())  # epoch seconds, offset honoured
    with pytest.raises(ProviderError) as e:
        up.parse_candles([["not a time", 1, 2, 3, 4, 5, 0]])
    assert e.value.kind == "unavailable"
    with pytest.raises(ProviderError):
        up.parse_candles({"candles": []})


def test_parse_quotes_matches_on_instrument_token_not_on_the_response_key():
    data = {"NSE_EQ:RELIANCE": {"last_price": 1500.5, "instrument_token": "NSE_EQ|INE002A01018",
                                 "prev_ohlc": {"close": 1490.0}, "live_ohlc": {"open": 1495.0, "high": 1510.0, "low": 1488.0, "volume": 12345}},
            "NSE_EQ:OTHER": {"last_price": 5.0, "instrument_token": "NSE_EQ|INE999"},
            "NSE_EQ:NOPRICE": {"instrument_token": "NSE_EQ|INE002A01018"}}
    got = up.parse_quotes(data, {"NSE_EQ|INE002A01018": "RELIANCE.NS"})
    assert got == [{"symbol": "RELIANCE.NS", "price": 1500.5, "prev_close": 1490.0, "open": 1495.0, "high": 1510.0, "low": 1488.0, "volume": 12345}]


def test_parse_instruments_keeps_cash_equities_prefers_eq_and_indexes_bse_by_scrip_code():
    table = up.parse_instruments(instruments_file(RELIANCE_BE, RELIANCE, BSE_RELIANCE, OPTION))
    assert table["NSE_EQ:RELIANCE"]["key"] == "NSE_EQ|INE002A01018"  # the EQ series beat the later BE row
    assert table["BSE_EQ:500325"]["key"] == "BSE_EQ|INE002A01018" and table["BSE_EQ:RELIANCE"]["name"] == "RELIANCE INDUSTRIES LTD"
    assert not any("NIFTY" in k for k in table)  # options are dropped
    plain = up.parse_instruments(json.dumps([RELIANCE]).encode())  # a server may have un-gzipped the body already
    assert "NSE_EQ:RELIANCE" in plain


def test_parse_instruments_with_no_equities_is_an_error_not_an_empty_table():
    with pytest.raises(ProviderError):
        up.parse_instruments(instruments_file(OPTION))
    with pytest.raises(ProviderError):
        up.parse_instruments(b"<html>blocked</html>")


# --- switching on -------------------------------------------------------------------------------------------------------

def test_inert_without_a_token_and_for_symbols_it_does_not_cover():
    p = UpstoxProvider(httpx.AsyncClient())
    assert not p.supports("history", "RELIANCE.NS") and not p.supports("quotes")
    p.set_keys({"UPSTOX_ANALYTICS_TOKEN": TOKEN})
    assert p.supports("history", "RELIANCE.NS") and p.supports("quotes", "^NSEI") and p.supports("quotes")
    assert not p.supports("history", "AAPL") and not p.supports("search", "RELIANCE.NS")
    p.set_keys({})
    assert not p.has_key


def test_declares_its_intraday_depth_for_the_limits_report():
    p = UpstoxProvider(httpx.AsyncClient())
    assert p.intraday_days["5m"] > 1000 and set(p.intraday_days) >= {"1m", "5m", "15m", "30m", "60m"}


# --- history and quotes through a fake transport ------------------------------------------------------------------------

async def test_history_sends_the_token_in_a_header_and_builds_bars():
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.url.host == "assets.upstox.com":
            return httpx.Response(200, content=instruments_file(RELIANCE) if "NSE" in req.url.path else instruments_file(BSE_RELIANCE))
        return httpx.Response(200, json={"status": "success", "data": {"candles": [candle("2025-01-02", 102, 50, 7), candle("2025-01-01", 101)]}})

    bars = await make(handler).history("RELIANCE.NS", "1mo", "1d")
    api = [r for r in seen if r.url.host == "api.upstox.com"]
    assert len(api) == 1 and api[0].headers["authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in str(api[0].url), "the token must never travel in a URL"
    assert "/v3/historical-candle/NSE_EQ%7CINE002A01018/days/1/" in str(api[0].url)
    assert bars.c == [101.0, 102.0] and bars.v == [1000, 50] and bars.currency == "INR" and bars.tz == "Asia/Kolkata"
    assert bars.oi == [0.0, 7.0] and "doc-shaped" not in bars.source  # not a fixture client, so no fixture label


async def test_a_long_intraday_range_is_fetched_in_windows_and_merged():
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "assets.upstox.com":
            return httpx.Response(200, content=instruments_file(RELIANCE, BSE_RELIANCE))
        calls.append(str(req.url))
        day = f"2025-01-{len(calls):02d}"
        return httpx.Response(200, json={"status": "success", "data": {"candles": [candle(day, 100 + len(calls))]}})

    bars = await make(handler).history("RELIANCE.NS", "1y", "5m")
    assert 12 <= len(calls) <= 14 and len(bars.t) == len(calls) and bars.t == sorted(bars.t)


async def test_the_instruments_table_is_downloaded_once():
    downloads = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "assets.upstox.com":
            downloads.append(req.url.path)
            return httpx.Response(200, content=instruments_file(RELIANCE, BSE_RELIANCE))
        return httpx.Response(200, json={"status": "success", "data": {"candles": [candle("2025-01-01", 101)]}})

    p = make(handler)
    await p.history("RELIANCE.NS", "1mo", "1d")
    await p.history("RELIANCE.BO", "1mo", "1d")
    assert len(downloads) == 2  # NSE + BSE files, once


async def test_an_index_needs_no_instruments_file():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.host == "api.upstox.com", "an index must not trigger a download"
        return httpx.Response(200, json={"status": "success", "data": {"candles": [candle("2025-01-01", 23000)]}})

    bars = await make(handler).history("^NSEI", "1mo", "1d")
    assert bars.c == [23000.0] and bars.exchange == "NSE"


async def test_an_unknown_share_is_not_found_so_the_next_source_answers():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=instruments_file(RELIANCE, BSE_RELIANCE))

    with pytest.raises(ProviderError) as e:
        await make(handler).history("NOSUCHCO.NS", "1mo", "1d")
    assert e.value.kind == "not_found"


@pytest.mark.parametrize(("status", "body", "kind"), [
    (401, {"status": "error", "errors": [{"error_code": "UDAPI100050", "message": f"Invalid token {TOKEN}"}]}, "key_required"),
    (429, {}, "rate_limited"),
    (400, {"status": "error", "errors": [{"error_code": "UDAPI1021", "message": "bad instrument key"}]}, "not_found"),
    (400, {"status": "error", "errors": [{"error_code": "UDAPI1148", "message": "Invalid date range"}]}, "depth"),
    (500, {"status": "error", "errors": [{"error_code": "UDAPI9", "message": "boom"}]}, "unavailable"),
])
async def test_upstox_errors_map_to_router_kinds_and_never_echo_the_token(status, body, kind):
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body)

    with pytest.raises(ProviderError) as e:
        await make(handler).history("^NSEI", "1mo", "1d")
    assert e.value.kind == kind and TOKEN not in str(e.value)


async def test_quotes_build_change_and_skip_symbols_upstox_lacks():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "assets.upstox.com":
            return httpx.Response(200, content=instruments_file(RELIANCE, BSE_RELIANCE))
        assert req.url.path == "/v3/market-quote/ohlc" and req.url.params["interval"] == "1d"
        assert set(req.url.params["instrument_key"].split(",")) == {"NSE_EQ|INE002A01018", "NSE_INDEX|Nifty 50"}
        return httpx.Response(200, json={"status": "success", "data": {
            "NSE_EQ:RELIANCE": {"last_price": 1500.0, "instrument_token": "NSE_EQ|INE002A01018", "prev_ohlc": {"close": 1480.0},
                                "live_ohlc": {"open": 1485.0, "high": 1505.0, "low": 1470.0, "volume": 999}},
            "NSE_INDEX:Nifty 50": {"last_price": 24000.0, "instrument_token": "NSE_INDEX|Nifty 50", "prev_ohlc": {"close": 24100.0},
                                   "live_ohlc": {"open": 24050.0, "high": 24100.0, "low": 23900.0, "volume": 0}}}})

    got = {q.symbol: q for q in await make(handler).quotes(["RELIANCE.NS", "^NSEI", "NOSUCHCO.NS"])}
    assert set(got) == {"RELIANCE.NS", "^NSEI"}
    r = got["RELIANCE.NS"]
    assert r.price == 1500.0 and r.change == 20.0 and r.change_pct == pytest.approx(20 / 1480 * 100) and r.volume == 999
    assert r.currency == "INR" and r.exchange == "NSE" and r.name == "RELIANCE INDUSTRIES LTD"
    assert got["^NSEI"].change == -100.0


# --- inside the router --------------------------------------------------------------------------------------------------

class YahooStub:
    name, capabilities, intraday_days = "yahoo", frozenset({"history", "quotes"}), {"5m": 60}

    def supports(self, capability, symbol=None):
        return True

    async def history(self, symbol, range_, interval):
        return "yahoo-bars"


async def test_in_the_router_upstox_answers_indian_symbols_and_yahoo_the_rest_and_removing_the_token_switches_it_off():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "success", "data": {"candles": [candle("2025-01-01", 24000)]}})

    upstox = make(handler)
    router = Router({"upstox": upstox, "yahoo": YahooStub()}, {"history": ["upstox", "yahoo"]})
    bars, failed = await router.call("history", lambda p: p.history("^NSEI", "1mo", "1d"), "^NSEI")
    assert bars.source == "upstox" and failed == []
    result, failed = await router.call("history", lambda p: p.history("AAPL", "1mo", "1d"), "AAPL")
    assert result == "yahoo-bars" and failed == []  # Upstox was never asked about AAPL
    upstox.set_keys({})  # token removed: Upstox switches itself off and Yahoo answers Indian symbols again
    result, _ = await router.call("history", lambda p: p.history("^NSEI", "1mo", "1d"), "^NSEI")
    assert result == "yahoo-bars"
