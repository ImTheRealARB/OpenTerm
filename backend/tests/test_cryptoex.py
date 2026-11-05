"""Kraken and Coinbase Exchange: the keyless second crypto exchanges (board, candles, order book).

The parsers run on REAL recorded answers (tests/fixtures/kraken_*.json, coinbase_*.json, recorded 2026-11-05 by hand from the public APIs,
long answers trimmed to their newest rows). The providers run over the fixture transport, so no test touches the network.
What these tests pin down:
  - Kraken's odd names (XBT / XDG, the X..Z.. result keys) and Coinbase's reordered candle rows are read correctly;
  - a USD pair is never passed off as a USDT pair (the quote is on every result);
  - the depth rules: Kraken keeps 720 candles, Coinbase pages to 4,000, and a longer request raises `depth` for the router;
  - the fallback order when Binance is blocked: CoinGecko / Binance fail -> Kraken -> Coinbase; Binance fails -> Coinbase -> Kraken.
"""

import asyncio
import json
import math
import time
from pathlib import Path

import httpx
import pytest

from openterm.providers import ADAPTERS, fixtures
from openterm.providers import cryptoex_parse as px
from openterm.providers.base import CRYPTO, HISTORY, Provider, ProviderError
from openterm.providers.coinbase import MAX_BARS as CB_MAX
from openterm.providers.coinbase import CoinbaseProvider
from openterm.providers.crypto import BINANCE_BASES
from openterm.providers.hierarchy import HIERARCHY, order_for, rank_of
from openterm.providers.kraken import KrakenProvider
from openterm.router import AllFailed, Router
from openterm.world import cryptodepth as cd

FIX = Path(__file__).parent / "fixtures"


def rec(name: str):
    return json.loads((FIX / f"{name}.json").read_bytes().decode("utf-8"))["body"]


def run(coro):
    return asyncio.run(coro)


def provider(cls, calls: list | None = None):
    """A provider wired to the recorded answers; `calls` (a list) collects every request it makes."""
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        return fixtures._route(request)

    return cls(httpx.AsyncClient(transport=httpx.MockTransport(handler)), source=f"{cls.name}:fixture")


# --- pair names ---------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text,want", [("BTC-USD", ("BTC", "USD")), ("btc-usdt", ("BTC", "USDT")), ("SOL-EUR", ("SOL", "EUR")), ("ETH-GBP", ("ETH", "GBP"))])
def test_split_pair_reads_the_apps_crypto_spelling(text, want):
    assert px.split_pair(text) == want


@pytest.mark.parametrize("text", ["AAPL", "BTCUSD", "BTCUSDT", "BTC-INR", "BRK-B", "BTCUSDT.P", "^GSPC", "EURUSD=X", "X-USD", ""])
def test_split_pair_refuses_everything_else(text):
    # No dash = could be a share (ABUSD); a share must never reach a crypto exchange. Perpetuals stay with Binance.
    assert px.split_pair(text) is None


def test_kraken_pair_names_use_xbt_and_xdg():
    assert px.kraken_pair("BTC", "USD") == "XBTUSD" and px.kraken_pair("DOGE", "USDT") == "XDGUSDT"
    assert px.kraken_pair("ETH", "BTC") == "ETHXBT"  # the quote is renamed too
    assert px.kraken_pair("SOL", "EUR") == "SOLEUR"


# --- Kraken parsers on the recorded answers ---------------------------------------------------------------------------------
def test_kraken_board_reads_the_legacy_result_keys():
    coins = px.parse_kraken_ticker(rec("kraken_ticker_usd"), BINANCE_BASES, "USD", "kraken", 1.0)
    assert [c.symbol for c in coins] == list(BINANCE_BASES)  # BTC (key XXBTZUSD), DOGE (XDGUSD), XRP (XXRPZUSD) all found, in board order
    btc = coins[0]
    assert btc.quote == "USD" and btc.price and btc.price > 1000 and btc.low_24h <= btc.price <= btc.high_24h
    raw = rec("kraken_ticker_usd")["result"]["XXBTZUSD"]
    assert btc.volume_24h == pytest.approx(float(raw["v"][1]) * float(raw["p"][1]))  # coins x 24h VWAP = quote value
    assert all(c.change_pct_24h is None for c in coins)  # Kraken has no 24h change: left empty, never faked from today's open


def test_kraken_ohlc_rows_are_read_in_order_with_numbers():
    rows = px.parse_kraken_ohlc(rec("kraken_ohlc_xbtusd_1440"))
    assert len(rows) == 400 and [r[0] for r in rows] == sorted(r[0] for r in rows)
    t, o, h, lo, c, v = rows[-1]
    assert h >= max(o, c) and lo <= min(o, c) and v > 0 and t % 86400 == 0  # daily candles open at 00:00 UTC


def test_kraken_errors_are_read_from_the_http_200_answer():
    for name, kind in (("kraken_error_unknown_pair", "not_found"), ("kraken_error_invalid_args", "unavailable")):
        with pytest.raises(ProviderError) as e:
            px.parse_kraken_ohlc(rec(name))
        assert e.value.kind == kind
    with pytest.raises(ProviderError) as e:
        px.kraken_unwrap({"error": ["EAPI:Rate limit exceeded"]}, "TICKER")
    assert e.value.kind == "rate_limited"
    with pytest.raises(ProviderError) as e:
        px.kraken_unwrap({"error": [], "result": {}}, "TICKER")  # a 200 with nothing in it is not data
    assert e.value.kind == "unavailable"


# --- Coinbase parsers on the recorded answers ------------------------------------------------------------------------------
def test_coinbase_candle_rows_are_low_high_open_close():
    raw = rec("coinbase_candles_btcusd_86400")
    rows = px.parse_coinbase_candles(raw)
    assert len(rows) == len(raw) and [r[0] for r in rows] == sorted(r[0] for r in rows)  # newest-first on the wire, oldest-first here
    first = next(r for r in raw if int(r[0]) == rows[0][0])
    _, o, h, lo, c, _ = rows[0]
    assert (lo, h, o, c) == (first[1], first[2], first[3], first[4])
    assert all(h >= max(o, c) and lo <= min(o, c) for _, o, h, lo, c, _ in rows)  # would fail if the columns were read in the wrong order


def test_coinbase_error_answer_is_not_a_candle_list():
    with pytest.raises(ProviderError) as e:
        px.parse_coinbase_candles({"message": "Unsupported granularity"})
    assert e.value.kind == "unavailable" and "Unsupported granularity" in str(e.value)


def test_coinbase_stats_give_an_exact_24h_change_and_no_invented_volume():
    s = rec("coinbase_stats_usd")["BTC-USD"]
    coin = px.parse_coinbase_stats(s, "BTC", "USD", "coinbase", 1.0)
    assert coin.quote == "USD" and coin.price == float(s["last"])
    assert coin.change_pct_24h == pytest.approx((float(s["last"]) - float(s["open"])) / float(s["open"]) * 100)
    assert coin.volume_24h is None  # Coinbase volume is in coins; no price is guessed to turn it into dollars


# --- order books ------------------------------------------------------------------------------------------------------------
def test_recorded_kraken_and_coinbase_books_parse_and_summarise():
    bids, asks, ts = cd.parse_kraken_book(rec("kraken_depth_xbtusd"))
    assert len(bids) == len(asks) == 100 and ts and ts > 1_700_000_000_000  # level stamps are seconds; the book time is in ms
    s = cd.depth_summary(bids, asks, "USD")
    assert s["best_ask"] > s["best_bid"] and 0 < s["spread_pct"] < 0.1 and s["usd"] is True and s["quote"] == "USD"
    bids, asks, ts = cd.parse_coinbase_book(rec("coinbase_book_btcusd"))
    assert len(bids) == len(asks) == 100 and ts and ts > 1_700_000_000_000
    assert bids[0][0] > bids[-1][0] and asks[0][0] < asks[-1][0]


def test_coinbase_book_is_cut_to_the_best_levels():
    deep = {"bids": [[str(100 - i), "1", 1] for i in range(500)], "asks": [[str(101 + i), "1", 1] for i in range(500)], "time": "2026-11-05T06:47:30.3Z"}
    bids, asks, _ = cd.parse_coinbase_book(deep)
    assert len(bids) == len(asks) == cd.COINBASE_LEVELS and bids[0][0] == 100 and asks[0][0] == 101


# --- providers over the recorded answers -------------------------------------------------------------------------------------
def test_supports_matches_what_each_exchange_can_serve():
    k, c = provider(KrakenProvider), provider(CoinbaseProvider)
    for p in (k, c):
        assert p.supports(HISTORY, "BTC-USD") and p.supports(HISTORY, "ETH-USDT") and p.supports("crypto_depth", "BTCUSDT")
        assert not p.supports(HISTORY, "AAPL") and not p.supports(HISTORY, "BTCUSDT.P") and not p.supports(HISTORY, "RELIANCE.NS")
        assert not p.supports("quotes", "BTC-USD")  # no quote capability: nothing in the app asks for it from Binance either
    assert k.supports(CRYPTO, "USD") and k.supports(CRYPTO, "eur") and not k.supports(CRYPTO, "INR")
    assert c.supports(CRYPTO, "USD") and not c.supports(CRYPTO, "EUR")  # Coinbase lists too few EUR products for a board


def test_kraken_candles_keep_the_pairs_real_quote():
    usd = run(provider(KrakenProvider).history("BTC-USD", "1y", "1d"))
    assert (usd.currency, usd.exchange, usd.source, usd.interval) == ("USD", "Kraken", "kraken:fixture", "1d")
    assert len(usd.t) == len(usd.o) == len(usd.v) == 367  # 1Y = 366 days + the forming bar, cut from the 400 recorded rows
    usdt = run(provider(KrakenProvider).history("BTC-USDT", "6mo", "1d"))
    assert usdt.currency == "USDT" and usdt.symbol == "BTC-USDT"  # a USDT pair is labelled USDT, never USD


def test_kraken_refuses_what_it_cannot_reach_with_a_depth_error():
    k = provider(KrakenProvider)
    for rng, iv, text in (("2y", "1d", "LAST 720 DAYS"), ("1mo", "60m", "LAST 30 DAYS"), ("1mo", "15m", "LAST 7 DAYS"), ("1d", "1m", "LAST 12 HOURS")):
        with pytest.raises(ProviderError) as e:
            run(k.history("BTC-USD", rng, iv))
        assert e.value.kind == "depth" and f"INTERVAL {iv} ONLY AVAILABLE FOR THE {text}" in str(e.value)


@pytest.mark.parametrize("iv", ["2m", "90m", "1mo"])
def test_kraken_has_no_such_candle_length(iv):
    with pytest.raises(ProviderError) as e:
        run(provider(KrakenProvider).history("BTC-USD", "1mo", iv))
    assert e.value.kind == "unsupported"


def test_kraken_weekly_candles_are_never_a_depth_error():
    # Weekly candles reach back to 2013, so even MAX is one answer. No weekly recording exists, so the daily one stands in for the rows.
    k = provider(KrakenProvider)

    async def get(path, params):
        assert (path, params["interval"]) == ("OHLC", 10080)
        return rec("kraken_ohlc_xbtusd_1440")

    k._get = get
    bars = run(k.history("BTC-USD", "max", "1wk"))
    assert len(bars.t) == 400


def test_kraken_unknown_pair_is_not_found_not_an_outage():
    with pytest.raises(ProviderError) as e:
        run(provider(KrakenProvider).history("NOPE-USD", "1y", "1d"))
    assert e.value.kind == "not_found"


def test_coinbase_candles_are_fetched_in_legal_contiguous_windows():
    calls: list = []
    bars = run(provider(CoinbaseProvider, calls).history("BTC-USD", "1y", "1d"))
    assert (bars.currency, bars.exchange, bars.source) == ("USD", "Coinbase", "coinbase:fixture")
    assert len(calls) == math.ceil(367 / 299) == 2
    spans = []
    for r in calls:
        a, b = (datetime_ts(r.url.params[k]) for k in ("start", "end"))
        assert b - a == 299 * 86400  # one under Coinbase's 300-candle limit, or the request is refused
        spans.append((a, b))
    spans.sort()
    assert spans[0][1] == spans[1][0]  # windows share a boundary: no candle can fall in a gap
    assert bars.t == sorted(set(bars.t)) and len(bars.t) == 298  # the fixture repeats the same rows per window: they are de-duplicated


def datetime_ts(iso: str) -> int:
    from datetime import datetime
    return int(datetime.fromisoformat(iso).timestamp())


def test_coinbase_usdt_pair_is_labelled_usdt():
    bars = run(provider(CoinbaseProvider).history("BTC-USDT", "6mo", "1d"))
    assert bars.currency == "USDT" and bars.symbol == "BTC-USDT"


def test_coinbase_intraday_beyond_the_paging_budget_is_a_depth_error():
    c = provider(CoinbaseProvider)
    with pytest.raises(ProviderError) as e:
        run(c.history("BTC-USD", "5d", "1m"))  # 7,200 one-minute candles > 4,000
    assert e.value.kind == "depth" and "INTERVAL 1m ONLY AVAILABLE FOR THE LAST 2 DAYS" in str(e.value)
    with pytest.raises(ProviderError) as e:
        run(c.history("BTC-USD", "1y", "60m"))
    assert e.value.kind == "depth" and "LAST 166 DAYS" in str(e.value)
    assert (CB_MAX, KrakenProvider.intraday_days["60m"], CoinbaseProvider.intraday_days["1m"]) == (4000, 30, 2)  # declared depth matches the rules


def test_coinbase_long_daily_range_is_capped_not_refused():
    calls: list = []
    bars = run(provider(CoinbaseProvider, calls).history("BTC-USD", "max", "1d"))
    assert len(calls) == math.ceil((CB_MAX + 1) / 299) == 14 and bars.interval == "1d"


@pytest.mark.parametrize("iv", ["2m", "30m", "90m", "1wk", "1mo"])
def test_coinbase_has_no_such_candle_length(iv):
    with pytest.raises(ProviderError) as e:
        run(provider(CoinbaseProvider).history("BTC-USD", "1mo", iv))
    assert e.value.kind == "unsupported"


def test_coinbase_unknown_product_is_not_found():
    with pytest.raises(ProviderError) as e:
        run(provider(CoinbaseProvider).history("NOPE-USD", "1y", "1d"))
    assert e.value.kind == "not_found"


def test_boards_label_their_quote_and_leave_unknowns_empty():
    kb = run(provider(KrakenProvider).crypto("USD"))
    assert len(kb) == 22 and {c.quote for c in kb} == {"USD"} and kb[0].source == "kraken:fixture"
    cb = run(provider(CoinbaseProvider).crypto("USD"))
    assert len(cb) == 21 and "TRX" not in {c.symbol for c in cb} and {c.quote for c in cb} == {"USD"}
    assert all(c.change_pct_24h is not None and c.volume_24h is None for c in cb)
    for p in (provider(KrakenProvider), provider(CoinbaseProvider)):
        with pytest.raises(ProviderError) as e:
            run(p.crypto("INR"))
        assert e.value.kind == "unsupported"


def test_depth_for_a_quote_the_exchange_lacks_is_not_found():
    for cls in (KrakenProvider, CoinbaseProvider):
        out = run(provider(cls).crypto_depth("BTC", "USD"))
        assert out["quote"] == "USD" and out["venue"].endswith("SPOT") and out["levels"] == [100, 100]
        with pytest.raises(ProviderError) as e:
            run(provider(cls).crypto_depth("BTC", "EUR"))  # not recorded = the exchange does not know it
        assert e.value.kind == "not_found"


# --- hierarchy and fallback order ----------------------------------------------------------------------------------------------
def test_hierarchy_places_both_below_binance_and_yahoo_with_reasons():
    hist = order_for("history")
    assert hist.index("binance_klines") < hist.index("yahoo") < hist.index("coinbase") < hist.index("kraken") < hist.index("frankfurter")
    for name in ("coinbase", "kraken"):
        assert name in ADAPTERS
        r = rank_of(name)["history"]
        assert all(r[f].strip() for f in ("covers", "depth", "freshness", "limits", "why"))
    assert {r.provider for r in HIERARCHY["history"]} >= {"coinbase", "kraken"}


class Down(Provider):
    """A source that is blocked (Binance answers HTTP 451 in some countries)."""
    capabilities = frozenset({CRYPTO, HISTORY})

    def __init__(self, name, kind="unavailable", msg="HTTP 451"):
        super().__init__(httpx.AsyncClient())
        self.name, self._err = name, ProviderError(kind, msg)

    async def crypto(self, vs):
        raise self._err

    async def history(self, symbol, range_, interval):
        raise self._err


def test_board_falls_back_coingecko_binance_kraken():
    router = Router({"coingecko": Down("coingecko", "rate_limited", "429"), "binance": Down("binance"), "kraken": provider(KrakenProvider),
                     "coinbase": provider(CoinbaseProvider)}, {"crypto": ["coingecko", "binance", "kraken", "coinbase"]})
    coins, failed = run(router.call("crypto", lambda p: p.crypto("USD"), "USD"))
    assert coins[0].source == "kraken:fixture" and failed == ["coingecko", "binance"]


def test_board_reaches_coinbase_when_kraken_is_down_too():
    router = Router({"coingecko": Down("coingecko"), "binance": Down("binance"), "kraken": Down("kraken"), "coinbase": provider(CoinbaseProvider)},
                    {"crypto": ["coingecko", "binance", "kraken", "coinbase"]})
    coins, failed = run(router.call("crypto", lambda p: p.crypto("USD"), "USD"))
    assert coins[0].source == "coinbase:fixture" and failed == ["coingecko", "binance", "kraken"]


def test_usdt_candles_fall_back_binance_yahoo_coinbase_kraken():
    yahoo_has_no_usdt = Down("yahoo", "not_found", "404")
    order = {"history": ["binance_klines", "yahoo", "coinbase", "kraken"]}
    router = Router({"binance_klines": Down("binance_klines"), "yahoo": yahoo_has_no_usdt, "coinbase": provider(CoinbaseProvider),
                     "kraken": provider(KrakenProvider)}, order)
    bars, failed = run(router.call("history", lambda p: p.history("BTC-USDT", "6mo", "1d"), "BTC-USDT"))
    assert (bars.exchange, bars.currency) == ("Coinbase", "USDT") and failed == ["binance_klines", "yahoo"]
    # Coinbase out as well: Kraken answers, still USDT
    router = Router({"binance_klines": Down("binance_klines"), "yahoo": yahoo_has_no_usdt, "coinbase": Down("coinbase"), "kraken": provider(KrakenProvider)}, order)
    bars, failed = run(router.call("history", lambda p: p.history("BTC-USDT", "6mo", "1d"), "BTC-USDT"))
    assert (bars.exchange, bars.currency) == ("Kraken", "USDT") and failed == ["binance_klines", "yahoo", "coinbase"]


def test_a_range_too_deep_for_every_source_is_a_bad_request_with_the_reason():
    router = Router({"coinbase": provider(CoinbaseProvider), "kraken": provider(KrakenProvider)}, {"history": ["coinbase", "kraken"]})
    with pytest.raises(AllFailed) as e:
        run(router.call("history", lambda p: p.history("BTC-USD", "1y", "1m"), "BTC-USD"))
    assert e.value.kind == "bad_request" and "ONLY AVAILABLE FOR THE LAST" in str(e.value.errors[0][1])
    assert router.health["coinbase"].errors == 0 and router.health["kraken"].errors == 0  # too deep is not an outage: no breaker strike


def test_history_limits_report_reflects_the_declared_depth():
    router = Router({"coinbase": provider(CoinbaseProvider), "kraken": provider(KrakenProvider)}, {"history": ["coinbase", "kraken"]})
    lim = router.history_limits("BTC-USD")["intraday_days"]
    assert lim == {"1m": 2, "5m": 13, "15m": 41, "60m": 166, "30m": 15}  # the deepest declared per length (Kraken alone has 30m)


# --- through the real app (fixture mode): Binance knocked out by hand ----------------------------------------------------------------
def _knock_out(client, *names):
    router = client.app.state.service.router
    for n in names:
        router.health[n].down_until = time.time() + 300


def test_cdep_falls_back_to_kraken_then_coinbase_and_names_the_venue(client):
    _knock_out(client, "binance_deriv", "okx")
    body = client.get("/api/world/cdep", params={"pair": "BTCUSDT"}).json()
    assert body["source"] == "kraken" and body["data"]["venue"] == "KRAKEN SPOT" and body["data"]["quote"] == "USDT"
    _knock_out(client, "kraken")
    body = client.get("/api/world/cdep", params={"pair": "BTCUSD"}).json()  # a different key: not served from the cache
    assert body["source"] == "coinbase" and body["data"]["venue"] == "COINBASE SPOT" and body["data"]["quote"] == "USD"


def test_crypto_board_falls_back_with_binance_and_coingecko_down(client):
    _knock_out(client, "coingecko", "binance")
    body = client.get("/api/crypto", params={"vs": "USD"}).json()
    # the two are tripped, so the router skips them without calling (that is why fallback_from is empty here)
    assert body["source"] == "kraken:fixture"
    assert len(body["data"]["coins"]) == 22 and body["data"]["coins"][0]["quote"] == "USD"


def test_usdt_chart_falls_back_to_coinbase_with_binance_down(client):
    _knock_out(client, "binance_klines")
    body = client.get("/api/history", params={"symbol": "BTC-USDT", "range": "6M", "interval": "1d"}).json()
    assert body["source"] == "coinbase:fixture" and body["data"]["currency"] == "USDT"
