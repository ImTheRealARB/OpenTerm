"""Phase 19 step 8: PRED parsers on the recorded Polymarket and Kalshi answers, probability normalisation, the label, filters, the two adapters,
failure handling (one source down / both down) and `/api/world/pred[/detail]`. No network; no order surface."""

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from openterm.providers.base import ProviderError
from openterm.providers.kalshi import KalshiMarketsProvider
from openterm.providers.polymarket import PolymarketProvider
from openterm.world import pred

FIX = Path(__file__).parent / "fixtures"
LABEL = "MARKET-IMPLIED PROBABILITY, NOT A FORECAST"
POLY_ID, KALSHI_ID = "665374", "KXOAIANTH-40-ANTH"


def rec(name: str):
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))["body"]


POLY = rec("polymarket_markets")
POLY_CLOSED = rec("polymarket_markets_closed")
KALSHI = rec("kalshi_markets")


# --- Polymarket parser ---------------------------------------------------------------------------------------------------
def test_recording_really_has_json_string_outcomes_and_prices():
    m = POLY[0]
    assert isinstance(m["outcomes"], str) and isinstance(m["outcomePrices"], str)
    assert json.loads(m["outcomes"]) == ["Yes", "No"]


def test_polymarket_prices_are_parsed_from_json_strings_into_a_probability():
    rows = pred.parse_polymarket(POLY)
    first = rows[0]
    want = float(json.loads(POLY[0]["outcomePrices"])[0])
    assert first["prob"] == want and first["pct"] == round(want * 100, 1)
    assert first["outcome"] == "Yes" and first["source"] == "polymarket" and first["vol_unit"] == "USD"
    assert len(rows) == len(POLY) == 100


def test_polymarket_probability_is_normalised_to_zero_one_and_shown_as_percent():
    for r in pred.parse_polymarket(POLY):
        assert 0.0 <= r["prob"] <= 1.0
        assert r["pct"] == round(r["prob"] * 100, 1)


def test_polymarket_shows_the_yes_outcome_even_when_it_is_listed_second():
    m = {"id": "1", "question": "Q?", "outcomes": '["No", "Yes"]', "outcomePrices": '["0.7", "0.3"]', "active": True, "closed": False, "volume": "10"}
    r = pred.poly_row(m)
    assert r["outcome"] == "Yes" and r["prob"] == 0.3


def test_polymarket_multi_outcome_market_shows_the_first_outcome_by_name():
    m = {"id": "2", "question": "Who wins?", "outcomes": '["Lakers", "Celtics"]', "outcomePrices": '["0.41", "0.59"]', "active": True, "closed": False}
    r = pred.poly_row(m)
    assert (r["outcome"], r["prob"]) == ("Lakers", 0.41)


@pytest.mark.parametrize("prices", ['["1.4", "-0.4"]', '["abc", "0.5"]', '["0.5"]', "not json", "[]"])
def test_polymarket_prices_out_of_range_or_malformed_drop_the_row_not_clamp_it(prices):
    m = {"id": "3", "question": "Q?", "outcomes": '["Yes", "No"]', "outcomePrices": prices, "active": True, "closed": False}
    assert pred.poly_row(m) is None


def test_polymarket_closed_inactive_and_archived_markets_are_filtered():
    assert pred.parse_polymarket(POLY_CLOSED) == []  # real resolved markets: they still say active=true, closed=true
    assert all(m["active"] is True and m["closed"] is True for m in POLY_CLOSED)
    base = dict(POLY[0])
    assert pred.poly_row(base) is not None
    assert pred.poly_row({**base, "active": False}) is None
    assert pred.poly_row({**base, "closed": True}) is None
    assert pred.poly_row({**base, "archived": True}) is None


def test_polymarket_non_list_answer_is_an_error_not_an_empty_table():
    with pytest.raises(ValueError):
        pred.parse_polymarket({"error": "rate limited"})


# --- Kalshi parser -------------------------------------------------------------------------------------------------------
def test_recording_prices_are_dollar_strings():
    m = KALSHI["markets"][0]
    assert isinstance(m["last_price_dollars"], str) and "yes_bid" not in m


def test_kalshi_dollar_prices_become_probabilities():
    rows = pred.parse_kalshi(KALSHI)
    by_id = {r["id"]: r for r in rows}
    m = next(x for x in KALSHI["markets"] if x["ticker"] == KALSHI_ID)
    r = by_id[KALSHI_ID]
    assert r["prob"] == float(m["last_price_dollars"]) and r["basis"] == "last"
    assert r["source"] == "kalshi" and r["vol_unit"] == "contracts" and r["volume"] == float(m["volume_fp"])
    assert all(0.0 <= x["prob"] <= 1.0 and x["pct"] == round(x["prob"] * 100, 1) for x in rows)


def test_kalshi_cent_prices_are_divided_by_a_hundred():
    m = {"ticker": "T-1", "title": "Will it?", "status": "active", "yes_bid": 45, "yes_ask": 47, "last_price": 46, "volume": 1200, "close_time": "2026-12-31T00:00:00Z"}
    r = pred.kalshi_row(m)
    assert r["prob"] == 0.46 and r["pct"] == 46.0 and r["volume"] == 1200 and r["close"] == "2026-12-31"
    no_trade = {**m, "last_price": 0}
    assert pred.kalshi_row(no_trade)["prob"] == pytest.approx(0.46) and pred.kalshi_row(no_trade)["basis"] == "mid"


def test_kalshi_dollars_win_over_cents_when_both_are_present():
    m = {"ticker": "T-2", "title": "Q", "status": "active", "last_price": 99, "last_price_dollars": "0.2500"}
    assert pred.kalshi_row(m)["prob"] == 0.25


def test_kalshi_empty_or_absurd_book_gives_no_probability():
    base = {"ticker": "T-3", "title": "Q", "status": "active", "last_price_dollars": "0.0000"}
    assert pred.kalshi_row({**base, "yes_bid_dollars": "0.0000", "yes_ask_dollars": "0.0000"}) is None
    assert pred.kalshi_row({**base, "yes_bid_dollars": "0.0000", "yes_ask_dollars": "1.0000"}) is None
    assert pred.kalshi_row({**base, "yes_bid_dollars": "0.4000", "yes_ask_dollars": "0.4400"})["prob"] == pytest.approx(0.42)


def test_kalshi_only_open_unresolved_markets_are_rows():
    m = KALSHI["markets"][0]
    assert pred.kalshi_row(m) is not None
    assert pred.kalshi_row({**m, "status": "closed"}) is None
    assert pred.kalshi_row({**m, "status": "settled", "result": "yes"}) is None
    assert pred.kalshi_row({**m, "result": "no"}) is None


def test_kalshi_question_names_the_yes_side_when_the_title_does_not():
    assert pred.kalshi_question({"title": "Who will win?", "yes_sub_title": "Anthropic"}) == "Who will win? (Anthropic)"
    assert pred.kalshi_question({"title": "Will Anthropic IPO?", "yes_sub_title": "Anthropic"}) == "Will Anthropic IPO?"
    assert pred.kalshi_question({"title": "Will it?", "yes_sub_title": "Yes"}) == "Will it?"


def test_kalshi_answer_without_markets_is_an_error():
    with pytest.raises(ValueError):
        pred.parse_kalshi({"cursor": ""})


# --- combine: sorting and the text filter -----------------------------------------------------------------------------------
def both():
    return [pred.parse_polymarket(POLY), pred.parse_kalshi(KALSHI)]


def test_rows_are_sorted_by_volume_descending():
    rows = pred.combine(both())
    vols = [r["volume"] for r in rows]
    assert vols == sorted(vols, reverse=True) and len(rows) == 200
    assert {r["source"] for r in rows} == {"polymarket", "kalshi"}


def test_text_filter_takes_every_word_case_insensitively():
    rows = pred.combine(both(), "ANTHROPIC ipo")
    assert rows and all("anthropic" in r["question"].lower() and "ipo" in r["question"].lower() for r in rows)
    assert pred.combine(both(), "zzqqxx nothing like this") == []


def test_limit_caps_the_rows():
    assert len(pred.combine(both(), "", 10)) == 10


# --- detail parsers --------------------------------------------------------------------------------------------------------
def test_polymarket_history_is_ascending_and_inside_zero_one():
    h = pred.parse_poly_history(rec("polymarket_prices_history"))
    assert len(h["t"]) == len(h["p"]) > 50 and h["t"] == sorted(h["t"]) and all(0 <= p <= 1 for p in h["p"])
    assert pred.parse_poly_history({"history": [{"t": 2, "p": 0.5}, {"t": 1, "p": 1.7}, {"t": 0, "p": "x"}]}) == {"t": [2], "p": [0.5]}
    with pytest.raises(ValueError):
        pred.parse_poly_history({"error": "x"})


def test_kalshi_candles_use_the_close_price_and_skip_empty_periods():
    h = pred.parse_kalshi_candles(rec("kalshi_candlesticks"))
    assert len(h["t"]) == len(h["p"]) > 10 and h["t"] == sorted(h["t"]) and all(0 <= p <= 1 for p in h["p"])
    c = {"candlesticks": [{"end_period_ts": 10, "price": {"close_dollars": "0.5000"}}, {"end_period_ts": 20, "price": {}},
                          {"end_period_ts": 30, "price": {"close": 61}}, {"end_period_ts": 40}]}
    assert pred.parse_kalshi_candles(c) == {"t": [10, 30], "p": [0.5, 0.61]}


def test_polymarket_detail_has_the_label_and_an_outcome_table():
    d = pred.poly_detail(rec(f"polymarket_market_{POLY_ID}"), {"t": [1], "p": [0.1]}, None)
    assert d["label"] == LABEL and [o["name"] for o in d["outcomes"]] == ["Yes", "No"]
    assert d["outcomes"][0]["prob"] + d["outcomes"][1]["prob"] == pytest.approx(1.0)
    assert d["history"] == {"t": [1], "p": [0.1]} and d["vol_unit"] == "USD"


def test_kalshi_detail_shows_yes_and_no_with_the_book():
    d = pred.kalshi_detail(rec(f"kalshi_market_{KALSHI_ID}"), None, "NO PRICE HISTORY")
    yes, no = d["outcomes"]
    assert (yes["name"], no["name"]) == ("Yes", "No") and yes["prob"] + no["prob"] == pytest.approx(1.0)
    assert yes["bid"] <= yes["ask"] and d["label"] == LABEL and d["series"] == "KXOAIANTH" and d["history_note"] == "NO PRICE HISTORY"


# --- adapters ---------------------------------------------------------------------------------------------------------------
def poly(handler) -> PolymarketProvider:
    return PolymarketProvider(httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def kalshi(handler) -> KalshiMarketsProvider:
    return KalshiMarketsProvider(httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def test_polymarket_asks_for_open_markets_by_volume_and_has_no_key_header():
    seen: list[httpx.Request] = []

    def h(req):
        seen.append(req)
        return httpx.Response(200, json=POLY)

    out = asyncio.run(poly(h).pred_markets())
    q = seen[0].url.params
    assert (q["active"], q["closed"], q["order"], q["ascending"]) == ("true", "false", "volumeNum", "false")
    assert seen[0].method == "GET" and out == POLY
    assert not {"authorization", "x-api-key"} & {k.lower() for k in seen[0].headers}


def test_kalshi_reads_two_pages_without_combos_and_merges_by_ticker():
    seen: list[httpx.Request] = []

    def h(req):
        seen.append(req)
        ms = KALSHI["markets"][:3] if "min_close_ts" not in req.url.params else KALSHI["markets"][1:5]
        return httpx.Response(200, json={"markets": ms})

    out = asyncio.run(kalshi(h).pred_markets())
    assert len(seen) == 2 and all(r.url.params["mve_filter"] == "exclude" and r.url.params["status"] == "open" and r.method == "GET" for r in seen)
    assert sum("min_close_ts" in r.url.params for r in seen) == 1
    assert [m["ticker"] for m in out["markets"]] == [m["ticker"] for m in KALSHI["markets"][:5]]


@pytest.mark.parametrize("status,kind", [(429, "rate_limited"), (503, "unavailable"), (404, "not_found")])
def test_upstream_errors_map_to_provider_error_kinds(status, kind):
    with pytest.raises(ProviderError) as e:
        asyncio.run(poly(lambda r: httpx.Response(status)).pred_markets())
    assert e.value.kind == kind


def test_a_wrong_shape_is_unavailable_not_a_crash():
    with pytest.raises(ProviderError) as e:
        asyncio.run(poly(lambda r: httpx.Response(200, json={"markets": []})).pred_markets())
    assert e.value.kind == "unavailable"
    with pytest.raises(ProviderError) as e2:
        asyncio.run(kalshi(lambda r: httpx.Response(200, json=[])).pred_markets())
    assert e2.value.kind == "unavailable"


def test_candlesticks_are_asked_for_by_series_over_seven_days():
    seen: list[httpx.Request] = []

    def h(req):
        seen.append(req)
        return httpx.Response(200, json=rec("kalshi_candlesticks"))

    asyncio.run(kalshi(h).pred_history("KXOAIANTH", KALSHI_ID))
    q = seen[0].url.params
    assert seen[0].url.path.endswith(f"/series/KXOAIANTH/markets/{KALSHI_ID}/candlesticks")
    assert int(q["end_ts"]) - int(q["start_ts"]) == 7 * 86400 and q["period_interval"] == "60"
    with pytest.raises(ProviderError):
        asyncio.run(kalshi(h).pred_history("", KALSHI_ID))


# --- routes (fixture mode) ---------------------------------------------------------------------------------------------------
def test_route_returns_both_sources_with_the_label_and_the_envelope(client):
    r = client.get("/api/world/pred").json()
    d = r["data"]
    assert d["label"] == LABEL and r["source"] == "polymarket + kalshi" and r["stale"] is False and "as_of" in r and "age_s" in r
    assert {x["source"] for x in d["rows"]} == {"polymarket", "kalshi"} and d["failed"] == [] and d["notes"] == []
    vols = [x["volume"] for x in d["rows"]]
    assert vols == sorted(vols, reverse=True)
    assert d["rows"][0]["question"] == POLY[0]["question"] and 0 <= d["rows"][0]["prob"] <= 1


def test_route_filters_by_text_and_a_miss_is_empty_with_the_label(client):
    d = client.get("/api/world/pred", params={"q": "iran"}).json()["data"]
    assert d["rows"] and all("iran" in x["question"].lower() for x in d["rows"]) and d["label"] == LABEL
    miss = client.get("/api/world/pred", params={"q": "zzqqxxvv"}).json()["data"]
    assert miss["rows"] == [] and miss["label"] == LABEL


def test_route_never_lists_a_closed_market(client):
    closed = {m["question"] for m in POLY_CLOSED}
    rows = client.get("/api/world/pred").json()["data"]["rows"]
    assert not closed & {x["question"] for x in rows}


def test_detail_polymarket_has_outcomes_and_history(client):
    r = client.get("/api/world/pred/detail", params={"source": "polymarket", "id": POLY_ID}).json()
    d = r["data"]
    assert d["label"] == LABEL and d["outcomes"][0]["name"] == "Yes" and len(d["history"]["t"]) > 50 and d["history_note"] is None
    assert r["source"] == "polymarket"


def test_detail_kalshi_has_outcomes_and_history(client):
    d = client.get("/api/world/pred/detail", params={"source": "kalshi", "id": KALSHI_ID}).json()["data"]
    assert d["label"] == LABEL and d["outcomes"][1]["name"] == "No" and len(d["history"]["t"]) > 10


def test_detail_of_an_unrecorded_market_is_not_found_never_invented(client):
    r = client.get("/api/world/pred/detail", params={"source": "polymarket", "id": "1"})
    assert r.status_code == 404 and "history" not in r.text and r.json()["kind"] == "not_found"


def test_detail_rejects_bad_source_and_id(client):
    assert client.get("/api/world/pred/detail", params={"source": "ftx", "id": "x"}).status_code == 400
    assert client.get("/api/world/pred/detail", params={"source": "kalshi", "id": "a/b"}).status_code == 400
    assert client.get("/api/world/pred/detail", params={"source": "kalshi", "id": "a b"}).status_code == 400


def test_a_missing_price_history_still_answers_the_outcome_table(client, monkeypatch):
    async def no_history(self, token):
        raise ProviderError("unavailable", "timeout")

    monkeypatch.setattr(PolymarketProvider, "pred_history", no_history)
    d = client.get("/api/world/pred/detail", params={"source": "polymarket", "id": POLY_ID}).json()["data"]
    assert d["history"] is None and "UNAVAILABLE" in d["history_note"] and d["outcomes"][0]["prob"] == 0.145


def _down(monkeypatch, cls, name="pred_markets"):
    async def boom(self, *a, **k):
        raise ProviderError("unavailable", "down for the test")

    monkeypatch.setattr(cls, name, boom)


def test_one_source_down_still_answers_with_the_other_and_says_which_failed(client, monkeypatch):
    _down(monkeypatch, KalshiMarketsProvider)
    r = client.get("/api/world/pred").json()
    d = r["data"]
    assert {x["source"] for x in d["rows"]} == {"polymarket"} and d["sources"] == ["polymarket"]
    assert [f["source"] for f in d["failed"]] == ["kalshi"] and "KALSHI FAILED" in d["notes"][0]
    assert d["label"] == LABEL and r["fallback_from"] == ["kalshi"]


def test_the_other_source_down_names_polymarket(client, monkeypatch):
    _down(monkeypatch, PolymarketProvider)
    d = client.get("/api/world/pred").json()["data"]
    assert {x["source"] for x in d["rows"]} == {"kalshi"} and [f["source"] for f in d["failed"]] == ["polymarket"]


def test_both_sources_down_is_an_error_not_an_empty_table(client, monkeypatch):
    _down(monkeypatch, PolymarketProvider)
    _down(monkeypatch, KalshiMarketsProvider)
    r = client.get("/api/world/pred")
    assert r.status_code >= 500 and r.json()["kind"] == "unavailable" and "rows" not in r.text
    assert "POLYMARKET" in r.json()["error"] and "KALSHI" in r.json()["error"]


def test_sources_screen_lists_both_adapters_as_keyless(client):
    names = {p["name"] for p in client.get("/api/sources").json()["providers"]}
    assert {"polymarket", "kalshi"} <= names


# --- read only ---------------------------------------------------------------------------------------------------------------
def test_no_trading_or_account_surface_exists(client):
    banned = ("order", "trade", "buy", "sell", "position", "balance", "portfolio", "wallet", "bet", "fill")
    paths = [p for p in client.app.openapi()["paths"] if p.startswith("/api/world/pred")]
    assert sorted(paths) == ["/api/world/pred", "/api/world/pred/detail"]
    assert not [p for p in paths if any(b in p.lower() for b in banned)]
    for cls in (PolymarketProvider, KalshiMarketsProvider):
        methods = [m for m in dir(cls) if not m.startswith("_")]
        assert not [m for m in methods if any(b in m.lower() for b in banned)], methods
    for cls in (PolymarketProvider, KalshiMarketsProvider):  # reads only: no POST/PUT/DELETE anywhere in the adapters
        src = Path(__import__(cls.__module__, fromlist=["x"]).__file__).read_text(encoding="utf-8")
        assert "post_json" not in src and ".post(" not in src and ".delete(" not in src
