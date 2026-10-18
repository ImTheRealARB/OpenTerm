"""Phase 13 step 6: keyed sources (Finnhub, Alpaca), CN scoring, N merging, ANR / EEO fallbacks.

Finnhub and Alpaca answers are documented shapes (fixtures labelled `doc_shaped`): these tests prove the plumbing and the
parsers, not that the live services answer exactly this way.
"""

import json
from pathlib import Path

import httpx
import pytest

from openterm.providers.alpaca import AlpacaProvider
from openterm.providers.base import ProviderError
from openterm.providers.finnhub import FinnhubProvider
from openterm.research import cn, keyed_parse, sentiment

FIX = Path(__file__).parent / "fixtures"


def body(name: str):
    return json.loads((FIX / f"{name}.json").read_bytes().decode("utf-8"))["body"]


# --- sentiment ---------------------------------------------------------------------------------------------------------

def test_score_counts_whole_words_only():
    assert sentiment.score("Apple beats estimates, shares surge") == 2
    assert sentiment.score("Apple faces probe, shares fall") == -2
    assert sentiment.score("Apple schedules its next event") == 0
    assert sentiment.score("Rising rates") == 0  # "rising" is not in the list: no stemming, no guessing
    assert sentiment.score("RECORD profit but lawsuit risk") == 0  # +record +profit -lawsuit -risk
    assert sentiment.score(None) == 0


def test_labels():
    assert [sentiment.label(v) for v in (3, 0, -1)] == ["POS", "NEU", "NEG"]


# --- parsers ---------------------------------------------------------------------------------------------------------------

def test_finnhub_news_skips_rows_without_link_or_headline():
    rows = [*body("finnhub_company_news_aapl"), {"headline": "no link", "url": ""}, {"url": "https://x.test/a"}, "junk"]
    items = keyed_parse.finnhub_news(rows, "finnhub")
    assert items[0].url =="https://example.com/fixture/finnhub/aapl-1"  # newest first
    assert len(items) == 3 and all(i.source == "finnhub" for i in items)
    assert items[0].published == 1792300000.0 and items[0].publisher == "Fixture Wire"


def test_finnhub_news_rejects_a_non_list():
    with pytest.raises(ProviderError):
        keyed_parse.finnhub_news({"error": "x"}, "finnhub")


def test_alpaca_news_reads_iso_times_and_ignores_content():
    b = body("alpaca_news_aapl")
    b["news"][0]["content"] = "<p>FULL ARTICLE BODY</p>"
    items = keyed_parse.alpaca_news(b, "alpaca")
    assert [i.title.startswith("FIXTURE") for i in items] == [True, True]
    assert items[0].published == 1792315800.0  # 2026-10-18T09:30:00Z
    assert "ARTICLE BODY" not in json.dumps([i.model_dump() for i in items])


def test_finnhub_ratings_payload_computes_mean_and_says_what_is_missing():
    p = keyed_parse.finnhub_ratings("AAPL", body("finnhub_recommendation_aapl"), "finnhub")
    row = p["sections"][0]["rows"][0]
    assert row["period"] == "2026-10-01" and row["strong_buy"] == 12
    n = 12 + 22 + 14 + 2 + 1
    mean = (12 * 1 + 22 * 2 + 14 * 3 + 2 * 4 + 1 * 5) / n
    assert next(h for h in p["headline"] if h["label"] == "MEAN RATING")["value"] == f"{mean:.2f}"
    assert any("PRICE TARGETS" in n for n in p["notes"])


def test_finnhub_surprises_percent_becomes_ratio():
    p = keyed_parse.finnhub_surprises("AAPL", body("finnhub_earnings_aapl"), "finnhub")
    rows = p["sections"][0]["rows"]
    assert [r["quarter"] for r in rows] == ["2026-09-30", "2026-06-30", "2026-03-31"]
    assert rows[0]["surprise"] == pytest.approx(0.125)
    assert p["headline"][0]["value"] == "2 OF 3"


def test_empty_answers_are_not_found():
    for fn in (keyed_parse.finnhub_ratings, keyed_parse.finnhub_surprises):
        with pytest.raises(ProviderError) as e:
            fn("AAPL", [], "finnhub")
        assert e.value.kind == "not_found"


def test_cn_payload_scores_dedupes_and_hides_nothing():
    items = keyed_parse.finnhub_news(body("finnhub_company_news_aapl"), "finnhub:fixture")
    items += keyed_parse.alpaca_news(body("alpaca_news_aapl"), "alpaca:fixture")
    p = cn.cn_payload("AAPL", items, ["gdelt"], [{"key": "X", "what": "y"}], ["finnhub", "alpaca"])
    rows = p["sections"][0]["rows"]
    assert len(rows) == 5 and {r["source"] for r in rows} == {"finnhub", "alpaca"}
    by = {r["headline"]: r["label"] for r in rows}
    assert by["FIXTURE: Apple beats profit estimates as services growth hits a record"] == "POS"
    assert by["FIXTURE: Apple faces probe over app store fees, shares fall"] == "NEG"
    assert by["FIXTURE: Apple schedules its next product event"] == "NEU"
    assert any("NOT A MODEL" in n for n in p["notes"]) and any("GDELT" in n for n in p["notes"])
    assert p["key_required"] == [{"key": "X", "what": "y"}]


# --- providers over a mock transport -----------------------------------------------------------------------------------

def mock(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_finnhub_sends_the_key_in_a_header_never_the_url():
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=body("finnhub_news_general"))

    p = FinnhubProvider(mock(handler), api_key="SECRETKEY123")
    out = await p.news_top()
    assert len(out["items"]) == 2
    assert seen[0].headers["x-finnhub-token"] == "SECRETKEY123"
    assert "SECRETKEY123" not in str(seen[0].url) and "token" not in seen[0].url.query.decode()


async def test_keyless_providers_support_nothing_and_say_key_required():
    f, a = FinnhubProvider(mock(lambda r: httpx.Response(500)), api_key=""), AlpacaProvider(mock(lambda r: httpx.Response(500)))
    assert not f.supports("news_symbol") and not a.supports("news_symbol")
    for call in (f.news_top(), a.news_top()):
        with pytest.raises(ProviderError) as e:
            await call
        assert e.value.kind == "key_required"


async def test_a_refused_key_is_key_required_and_never_echoed():
    p = FinnhubProvider(mock(lambda r: httpx.Response(401, json={"error": "Invalid API key"})), api_key="SECRETKEY123")
    with pytest.raises(ProviderError) as e:
        await p.news_top()
    assert e.value.kind == "key_required" and "SECRETKEY123" not in str(e.value)
    a = AlpacaProvider(mock(lambda r: httpx.Response(403)), key_id="IDID", secret="SSSS")
    a.set_keys({"ALPACA_KEY_ID": "IDID", "ALPACA_SECRET_KEY": "SSSS"})
    with pytest.raises(ProviderError) as e2:
        await a.news_top()
    assert e2.value.kind == "key_required"


async def test_alpaca_needs_both_keys():
    a = AlpacaProvider(mock(lambda r: httpx.Response(500)))
    a.set_keys({"ALPACA_KEY_ID": "only-id"})
    assert not a.has_key
    a.set_keys({"ALPACA_KEY_ID": "i", "ALPACA_SECRET_KEY": "s"})
    assert a.has_key and a.supports("news_symbol") and not a.supports("quotes")


# --- API: N merges keyed sources, ANR / EEO fall back, SOURCES shows both -------------------------------------------------

def put_keys(client):
    assert client.put("/api/keys/finnhub", json={"fields": {"FINNHUB_API_KEY": "f" * 24}}).status_code == 200
    r = client.put("/api/keys/alpaca", json={"fields": {"ALPACA_KEY_ID": "a" * 20, "ALPACA_SECRET_KEY": "s" * 40}})
    assert r.status_code == 200


def test_news_merges_keyed_sources_into_the_keyless_answer(client):
    put_keys(client)  # before the first fetch: the server caches a news answer for 120 s
    d = client.get("/api/news", params={"symbol": "AAPL"}).json()
    srcs = {i["source"].split(":")[0] for i in d["data"]["items"]}
    assert {"yahoo_rss", "finnhub", "alpaca"} <= srcs
    assert d["source"] == "+".join(sorted(srcs))
    assert d["data"]["failed"] == []
    times = [i["published"] or 0 for i in d["data"]["items"]]
    assert times == sorted(times, reverse=True)  # merged newest first
    top = client.get("/api/news").json()
    assert {"finnhub", "alpaca"} <= {i["source"].split(":")[0] for i in top["data"]["items"]}


def test_keyed_sources_listed_on_sources_and_inert_until_keyed(client):
    s = client.get("/api/sources").json()
    row = {p["name"]: p for p in s["providers"]}
    assert "news_symbol" in row["finnhub"]["capabilities"] and "news_top" in row["alpaca"]["capabilities"]
    assert row["finnhub"]["calls"] == 0  # not called while keyless


def test_ratings_and_surprises_fall_back_to_finnhub_only_when_yahoo_fails(client):
    import time

    d = client.get("/api/research/anr", params={"symbol": "AAPL"}).json()
    assert d["source"].startswith("yahoo_research")  # Yahoo answers: Finnhub is never asked
    put_keys(client)
    router = client.app.state.service.router
    router.health["yahoo_research"].down_until = time.time() + 600  # Yahoo tripped: the keyed source takes over
    r = client.get("/api/research/eeo", params={"symbol": "AAPL"}).json()
    assert r["source"].startswith("finnhub") and r["fallback_from"] == []
    assert [s["id"] for s in r["data"]["sections"]] == ["surprises"]  # only what Finnhub has, said so in the notes
    assert any("YAHOO" in n for n in r["data"]["notes"])
    # a symbol Finnhub's fixture has no row for is not found, never an invented table
    assert client.get("/api/research/anr", params={"symbol": "ZZZZNOPE"}).status_code == 404
