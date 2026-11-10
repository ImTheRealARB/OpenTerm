"""SDK tests. No network and no server: `httpx.MockTransport` plays OpenTerm.

Every payload below is TEST DATA shaped like OpenTerm's envelopes. NOT A RECORDING of any real provider answer.
"""

import json

import httpx
import pandas as pd
import pytest

from openterm_sdk import (
    BackendDown,
    BadRequest,
    KeyRequired,
    NoData,
    OpenTerm,
    OpenTermError,
    ProviderDown,
    StaleData,
)

NOW = 1_700_000_000.0


def env(data, source="testsrc", stale=False, age=1.5, fallback=()):
    return {"data": data, "source": source, "as_of": NOW, "age_s": age, "stale": stale, "fallback_from": list(fallback)}


def make(handler, **kw):
    calls = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    return OpenTerm("http://127.0.0.1:9", transport=httpx.MockTransport(wrapped), **kw), calls


def reply(body, status=200):
    return lambda request: httpx.Response(status, json=body)


BARS = {"symbol": "TEST", "range": "1M", "interval": "1d", "currency": "USD", "exchange": "TESTX", "tz": "UTC",
        "t": [NOW, NOW + 86400], "o": [1.0, None], "h": [2.0, 2.5], "l": [0.5, 0.6], "c": [1.5, 2.0], "v": [10, None],
        "adj": None, "source": "testsrc", "as_of": NOW}


def test_history_is_a_dataframe_with_provenance_and_keeps_missing_values_missing():
    ot, calls = make(reply(env(BARS, fallback=["other"])))
    df = ot.history("TEST", "1M", "1d")
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.index.tz is not None and df.index[0] == pd.Timestamp(NOW, unit="s", tz="UTC")
    assert pd.isna(df["open"].iloc[1])  # never filled
    assert df.attrs["source"] == "testsrc" and df.attrs["as_of"] == NOW and df.attrs["stale"] is False
    assert df.attrs["age_s"] == 1.5 and df.attrs["fallback_from"] == ["other"] and df.attrs["as_of_iso"].startswith("2023-11-14")
    assert df.attrs["interval"] == "1d" and df.attrs["currency"] == "USD"
    assert calls[0].url.path == "/api/history" and dict(calls[0].url.params) == {"symbol": "TEST", "range": "1M", "interval": "1d"}


def test_source_pin_goes_on_the_query_per_call_and_per_client():
    ot, calls = make(reply(env(BARS)), source="Nasdaq")
    ot.history("TEST")
    assert calls[-1].url.params["source"] == "nasdaq"
    ot.history("TEST", source="yahoo")
    assert calls[-1].url.params["source"] == "yahoo"
    plain, calls = make(reply(env(BARS)))
    plain.history("TEST")
    assert "source" not in calls[-1].url.params


def test_a_bad_source_name_is_refused_before_any_request():
    ot, calls = make(reply(env(BARS)))
    with pytest.raises(BadRequest) as e:
        ot.history("TEST", source="a b")
    assert str(e.value).startswith("SRC=A B") and calls == []


def test_a_pinned_source_that_fails_raises_with_the_servers_message_and_no_other_data():
    ot, _ = make(reply({"error": "SRC=NASDAQ: PROVIDER DOWN", "kind": "unavailable", "detail": "nasdaq: HTTP 503"}, 503))
    with pytest.raises(ProviderDown) as e:
        ot.history("TEST", source="nasdaq")
    assert e.value.source == "nasdaq" and e.value.status == 503 and str(e.value).startswith("SRC=NASDAQ: PROVIDER DOWN")


def test_unknown_source_is_a_bad_request_with_the_servers_words():
    ot, _ = make(reply({"error": "SRC=NOSUCH: UNKNOWN SOURCE (SEE /api/sources)", "kind": "bad_request"}, 400))
    with pytest.raises(BadRequest, match="UNKNOWN SOURCE"):
        ot.quote("AAPL", source="nosuch")


def test_key_required_names_the_key_never_a_value():
    ot, _ = make(reply({"error": "KEY REQUIRED", "kind": "key_required", "key": "FOO_KEY", "detail": "KEY REQUIRED: set FOO_KEY in APIKEYS"}, 401))
    with pytest.raises(KeyRequired) as e:
        ot.news("AAPL", source="foo")
    assert e.value.key == "FOO_KEY" and "FOO_KEY" in str(e.value)


def test_not_found_and_other_kinds_map_to_types_and_all_are_openterm_errors():
    ot, _ = make(reply({"error": "NO DATA FOR SYMBOL", "kind": "not_found"}, 404))
    with pytest.raises(NoData):
        ot.profile("ZZZ")
    ot, _ = make(reply("<html>", 502))
    with pytest.raises(OpenTermError):
        ot.profile("ZZZ")


def test_backend_not_running_is_its_own_error():
    def boom(request):
        raise httpx.ConnectError("refused")

    ot, _ = make(boom)
    with pytest.raises(BackendDown, match="START IT FIRST"):
        ot.history("TEST")


def test_stale_is_flagged_by_default_and_raises_when_asked():
    stale = env(BARS, stale=True, age=7200)
    df = make(reply(stale))[0].history("TEST")
    assert df.attrs["stale"] is True and df.attrs["age_s"] == 7200
    with pytest.raises(StaleData):
        make(reply(stale), raise_on_stale=True)[0].history("TEST")


def q(sym, price, source="testsrc", stale=False):
    return env({"symbol": sym, "price": price, "currency": "USD", "source": source, "as_of": NOW}, source=source, stale=stale)


def test_quote_many_keeps_failures_out_of_the_frame_and_names_them():
    body = {"results": {"AAA": q("AAA", 1.0), "BBB": {"error": "SRC=TESTSRC: NO DATA FOR SYMBOL", "kind": "not_found"}, "CCC": q("CCC", 3.0, "other")}}
    df = make(reply(body))[0].quote(["AAA", "BBB", "CCC"])
    assert list(df.index) == ["AAA", "CCC"] and list(df["source"]) == ["testsrc", "other"]
    assert df.attrs["source"] == "mixed" and df.attrs["errors"] == {"BBB": "SRC=TESTSRC: NO DATA FOR SYMBOL"}
    assert df.attrs["as_of"] == NOW


def test_quote_single_failure_raises_and_all_failed_raises():
    err = {"error": "KEY REQUIRED", "kind": "key_required", "key": "K"}
    with pytest.raises(KeyRequired):
        make(reply({"results": {"AAA": err}}))[0].quote("AAA")
    with pytest.raises(OpenTermError):
        make(reply({"results": {"AAA": err, "BBB": err}}))[0].quote(["AAA", "BBB"])


def test_quote_stale_row_sets_the_summary_flag():
    df = make(reply({"results": {"AAA": q("AAA", 1.0, stale=True), "BBB": q("BBB", 2.0)}}))[0].quote(["AAA", "BBB"])
    assert df.attrs["stale"] is True and list(df["stale"]) == [True, False]


def test_news_search_and_profile():
    items = [{"id": "1", "title": "T", "url": "u", "publisher": "P", "published": NOW, "summary": None, "source": "rss", "sentiment": None},
             {"id": "2", "title": "U", "url": "v", "publisher": None, "published": None, "summary": None, "source": "rss", "sentiment": None}]
    ot, calls = make(reply(env({"kind": "pool", "items": items, "failed": ["feed1"]}, source="rss")))
    df = ot.news(section="tech", limit=5)
    assert df.attrs["source"] == "rss" and df.attrs["failed_feeds"] == ["feed1"] and pd.isna(df["published"].iloc[1])
    assert dict(calls[0].url.params) == {"section": "tech", "limit": "5"}
    hits = make(reply(env([{"symbol": "AAA", "name": "A", "source": "testsrc"}])))[0].search("aa")
    assert list(hits["symbol"]) == ["AAA"] and hits.attrs["source"] == "testsrc"
    prof = make(reply(env({"symbol": "AAA", "name": "A", "pe": None, "source": "testsrc", "as_of": NOW})))[0].profile("AAA")
    assert prof["pe"] is None and prof["_meta"]["source"] == "testsrc"


def test_fundamentals_rows_are_line_items_and_columns_period_ends():
    d = {"symbol": "AAA", "period": "A", "currency": "USD",
         "periods": [{"end": "2023-12-31", "derived": False}, {"end": "2022-12-31", "derived": True}],
         "statements": {"IS": [{"key": "revenue", "label": "Revenue", "unit": "USD", "values": [10.0, None]}], "BS": [], "CF": []}}
    ot, calls = make(reply(env(d, source="sec")), source="yahoo")
    df = ot.fundamentals("AAA")
    assert df.loc["revenue", "2023-12-31"] == 10.0 and pd.isna(df.loc["revenue", "2022-12-31"])
    assert df.attrs["source"] == "sec" and df.attrs["labels"]["revenue"] == "Revenue" and df.attrs["derived"]["2022-12-31"] is True
    assert "source" not in calls[0].url.params  # SEC is the only source: the client default pin is not sent
    with pytest.raises(BadRequest):
        ot.fundamentals("AAA", statement="XX")


def test_portfolios_and_backtests_are_read_only_views():
    def handler(request):
        p = request.url.path
        assert request.method == "GET"
        if p == "/api/portfolios":
            return httpx.Response(200, json={"portfolios": [{"name": "main", "base": "USD", "count": 1, "updated_at": NOW}]})
        if p == "/api/portfolios/main":
            return httpx.Response(200, json={"name": "main", "base": "USD", "updated_at": NOW, "positions": [{"symbol": "AAA", "qty": 2}]})
        if p == "/api/bt/runs":
            return httpx.Response(200, json={"runs": [{"id": "r1", "strategy": "s", "created_at": NOW, "metrics": {"sharpe": 1.0}}]})
        if p == "/api/bt/runs/r1":
            return httpx.Response(200, json={"id": "r1", "engine": "vec", "metrics": {"sharpe": 1.0}, "equity": [[NOW, 100.0], [NOW + 86400, 101.0]],
                                             "benchmark": [[NOW, 100.0], [NOW + 86400, 100.5]], "trades": [{"symbol": "AAA", "pnl": 1.0}], "config": {"initial_cash": 100}})
        return httpx.Response(404, json={"error": "NO RUN", "kind": "not_found"})

    ot, calls = make(handler, source="yahoo")
    assert list(ot.portfolios()["name"]) == ["main"]
    pf = ot.portfolio("main")
    assert pf.attrs["base"] == "USD" and "source" not in pf.attrs and pf.loc[0, "qty"] == 2
    assert ot.backtests()["id"].tolist() == ["r1"]
    run = ot.backtest("r1")
    assert run.metrics == {"sharpe": 1.0} and list(run.equity.columns) == ["equity", "benchmark"] and run.trades.loc[0, "pnl"] == 1.0
    with pytest.raises(NoData):
        ot.backtest("nope")
    assert all("source" not in c.url.params for c in calls)  # the pin means nothing for the user's own data


def test_the_client_has_no_write_methods():
    public = [n for n in dir(OpenTerm) if not n.startswith("_")]
    banned = ("order", "place", "buy", "sell", "put", "post", "delete", "write", "run_backtest", "submit", "cancel", "modify")
    assert not [n for n in public if any(b in n.lower() for b in banned)], public

    import inspect

    from openterm_sdk import client

    assert "self._http.get(" in inspect.getsource(client) and not any(
        f".{verb}(" in inspect.getsource(client) for verb in ("post", "put", "patch", "delete"))


def test_no_key_or_secret_is_ever_sent():
    ot, calls = make(reply(env(BARS)))
    ot.history("TEST")
    assert set(calls[0].headers) <= {"host", "accept", "accept-encoding", "connection", "user-agent"}
    assert json.dumps(dict(calls[0].url.params)).lower().find("key") == -1
