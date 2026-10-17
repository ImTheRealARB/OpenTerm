"""Phase 5: watchlists (SQLite), news (RSS / GDELT), movers, crypto, and the quote boards' symbols."""

import asyncio
import json
from datetime import UTC, datetime

import httpx
import pytest

from openterm.db import MIGRATIONS, open_db
from openterm.providers.base import ProviderError
from openterm.providers.crypto import BinanceProvider, CoinGeckoProvider
from openterm.providers.fixtures import FIXTURES, _route, fixture_transport
from openterm.providers.nasdaq import NasdaqProvider
from openterm.providers.news import FEEDS, GdeltProvider, RssProvider, YahooRssProvider, parse_rss
from openterm.router import AllFailed, Router
from openterm.userdata import MAX_WATCHLIST


@pytest.fixture
async def http():
    async with httpx.AsyncClient(transport=fixture_transport()) as c:
        yield c


def failing(hosts: set[str], status: int = 503) -> httpx.AsyncClient:
    """Fixture transport where the given hosts answer `status` (a provider or one feed being down)."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host in hosts:
            return httpx.Response(status, text="down")
        return _route(request)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def rss_text(name: str) -> bytes:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))["text"].encode("utf-8")


# --- watchlists ------------------------------------------------------------------------------
def test_migration_adds_watchlists(tmp_path):
    async def run():
        db = await open_db(tmp_path / "w.db")
        async with db.execute("PRAGMA user_version") as cur:
            version = (await cur.fetchone())[0]
        async with db.execute("SELECT name FROM sqlite_master WHERE type='table'") as cur:
            tables = {r[0] for r in await cur.fetchall()}
        await db.close()
        return version, tables

    version, tables = asyncio.run(run())
    assert version == len(MIGRATIONS) and "watchlists" in tables


def test_watchlist_crud(client):
    assert client.get("/api/watchlists").json() == {"watchlists": []}
    r = client.put("/api/watchlists/tech", json={"symbols": ["aapl", "MSFT", "aapl", " nvda "]})
    assert r.status_code == 200
    assert r.json()["name"] == "TECH" and r.json()["symbols"] == ["AAPL", "MSFT", "NVDA"]  # upper, deduped, in order

    r = client.patch("/api/watchlists/tech", json={"add": ["eurusd", "MSFT", "spx"], "remove": ["NVDA"]})
    assert r.json()["symbols"] == ["AAPL", "MSFT", "EURUSD=X", "^GSPC"]  # aliases resolved like the command line

    listed = client.get("/api/watchlists").json()["watchlists"]
    assert [(w["name"], w["count"]) for w in listed] == [("TECH", 4)]
    assert client.get("/api/watchlists/Tech").json()["symbols"] == ["AAPL", "MSFT", "EURUSD=X", "^GSPC"]

    # PATCH with add creates a missing list; PATCH with only remove on a missing list is a 404.
    assert client.patch("/api/watchlists/india", json={"add": ["RELIANCE.NS"]}).json()["symbols"] == ["RELIANCE.NS"]
    assert client.patch("/api/watchlists/nope", json={"remove": ["X"]}).status_code == 404

    assert client.delete("/api/watchlists/tech").json() == {"deleted": "TECH"}
    assert client.delete("/api/watchlists/tech").status_code == 404
    assert client.get("/api/watchlists/tech").status_code == 404
    assert [w["name"] for w in client.get("/api/watchlists").json()["watchlists"]] == ["INDIA"]


def test_watchlist_validation(client):
    assert client.put("/api/watchlists/my list", json={"symbols": ["AAPL"]}).status_code == 400
    assert client.put("/api/watchlists/X", json={"symbols": "AAPL"}).status_code == 400
    assert client.put("/api/watchlists/X", json={"symbols": ["AA PL"]}).status_code == 400
    assert client.put("/api/watchlists/X", json={"symbols": ["<script>"]}).status_code == 400
    too_many = [f"S{i}" for i in range(MAX_WATCHLIST + 1)]
    assert client.put("/api/watchlists/X", json={"symbols": too_many}).status_code == 413
    assert client.patch("/api/watchlists/X", json={"add": too_many}).status_code == 413
    assert client.patch("/api/watchlists/X", json={}).status_code == 400
    # An empty list is allowed (all symbols removed); the list itself stays until deleted.
    client.put("/api/watchlists/X", json={"symbols": ["AAPL"]})
    assert client.patch("/api/watchlists/X", json={"remove": ["AAPL"]}).json()["symbols"] == []


def test_watchlists_survive_restart(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from openterm.config import get_settings

    monkeypatch.setenv("OPENTERM_FIXTURES", "1")
    monkeypatch.setenv("OPENTERM_DB_PATH", str(tmp_path / "wl.db"))
    get_settings.cache_clear()
    from openterm.main import app

    with TestClient(app) as c:
        c.put("/api/watchlists/KEEP", json={"symbols": ["AAPL", "GC=F"]})
    with TestClient(app) as c:
        assert c.get("/api/watchlists/KEEP").json()["symbols"] == ["AAPL", "GC=F"]
    get_settings.cache_clear()


# --- news: parsing ---------------------------------------------------------------------------
def test_parse_rss_items():
    items = parse_rss(rss_text("rss_cnbc"), "CNBC", "rss")
    assert len(items) == 8
    first = items[0]
    assert first.title.startswith("Brent oil touches $110")
    assert first.url.startswith("https://www.cnbc.com/2026/10/16/")
    assert first.publisher == "CNBC" and first.source == "rss"
    assert first.published == datetime(2026, 10, 16, 20, 2, 21, tzinfo=UTC).timestamp()
    assert first.summary and first.summary.startswith("U.S. crude oil prices rose")
    assert len({i.id for i in items}) == 8  # stable ids, one per article


def test_parse_rss_timezones_and_html():
    et = parse_rss(rss_text("rss_et"), "ECONOMIC TIMES", "rss")
    # "Sat, 17 Oct 2026 14:16:40 +0530" is 08:46:40 UTC.
    assert et[0].published == datetime(2026, 10, 17, 8, 46, 40, tzinfo=UTC).timestamp()
    for i in et:
        assert "<" not in (i.summary or "") and len(i.summary or "") <= 300


def test_parse_rss_rejects_garbage():
    assert parse_rss(b"<html><body>bot check</body></html>", "X", "rss") == []
    with pytest.raises(ProviderError) as e:
        parse_rss(b"not xml at all", "X", "rss")
    assert e.value.kind == "unavailable"


# --- news: providers -------------------------------------------------------------------------
async def test_rss_top_merges_feeds_newest_first(http):
    out = await RssProvider(http).news_top()
    assert out["failed"] == []
    items = out["items"]
    assert {i.publisher for i in items} == {f["name"] for f in FEEDS}
    times = [i.published for i in items]
    assert times == sorted(times, reverse=True)
    assert len({i.url for i in items}) == len(items)


async def test_rss_top_partial_failure_is_reported():
    async with failing({"feeds.bbci.co.uk"}) as c:
        out = await RssProvider(c).news_top()
    assert out["failed"] == ["BBC BUSINESS"]
    assert out["items"] and "BBC BUSINESS" not in {i.publisher for i in out["items"]}
    async with failing({f["url"].split("/")[2] for f in FEEDS}) as c:
        with pytest.raises(ProviderError) as e:
            await RssProvider(c).news_top()
    assert e.value.kind == "unavailable"


async def test_yahoo_rss_symbol_news(http):
    p = YahooRssProvider(http)
    items = (await p.news_symbol("AAPL"))["items"]
    assert len(items) == 8 and items[0].title.startswith("Apple's iPhone Duo")
    assert items[0].publisher == "stocktwits.com"  # aggregated feed: the link's own site
    with pytest.raises(ProviderError) as e:
        await p.news_symbol("ZZZZ")  # not recorded: fixture mode never invents headlines
    assert e.value.kind == "not_found"


async def test_gdelt_keyword_news(http):
    items = (await GdeltProvider(http).news_keyword("NVIDIA"))["items"]
    assert len(items) == 5
    assert items[0].publisher == "aol.com" and items[0].source == "gdelt"
    assert items[0].published == datetime(2026, 10, 17, 9, 15, tzinfo=UTC).timestamp()


async def test_gdelt_throttle_text_is_rate_limited():
    rec = json.loads((FIXTURES / "gdelt_429.json").read_text(encoding="utf-8"))
    for status in (429, 200):  # GDELT also answers its throttle text with 200 at times

        def handler(request, status=status):
            return httpx.Response(status, text=rec["text"])

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            with pytest.raises(ProviderError) as e:
                await GdeltProvider(c).news_keyword("NVIDIA")
        assert e.value.kind == "rate_limited"


async def test_gdelt_short_symbols_are_not_queried(http):
    with pytest.raises(ProviderError) as e:
        await GdeltProvider(http).news_symbol("GE")
    assert e.value.kind == "not_found"


# --- news: API -------------------------------------------------------------------------------
def test_news_api(client):
    top = client.get("/api/news").json()
    assert top["source"] == "rss:fixture" and top["stale"] is False
    assert len(top["data"]["items"]) == 8 * len(FEEDS) and top["data"]["failed"] == []
    assert top["data"]["kind"] == "top"

    sym = client.get("/api/news", params={"symbol": "aapl"}).json()
    assert sym["source"] == "yahoo_rss:fixture" and sym["data"]["kind"] == "symbol"
    assert sym["data"]["query"] == "AAPL"

    kw = client.get("/api/news", params={"q": "nvidia"}).json()
    assert kw["source"] == "gdelt:fixture" and kw["data"]["query"] == "NVIDIA"
    assert client.get("/api/news", params={"q": "x" * 200}).status_code == 422


def test_news_unrecorded_search_is_404_with_detail(client):
    r = client.get("/api/news", params={"q": "zzzunrecorded"})
    assert r.status_code == 404
    assert r.json()["error"] == "NO HEADLINES FOUND" and "gdelt: not_found" in r.json()["detail"]


async def test_gdelt_waits_for_its_slot(http):
    from openterm.ratelimit import TokenBucket

    p = GdeltProvider(http)
    p.bucket = TokenBucket(2.0, 1)  # next slot in 0.5 s: longer than the default 0.25 s wait
    await p.news_keyword("NVIDIA")
    assert (await p.news_keyword("NVIDIA"))["items"]  # waited for the slot instead of failing


# --- movers ----------------------------------------------------------------------------------
async def test_nasdaq_movers(http):
    m = await NasdaqProvider(http).movers()
    assert set(m.tables) == {"GAINERS", "LOSERS", "ACTIVE", "DOLLAR", "NDX100"}
    g = m.tables["GAINERS"][0]
    assert (g.symbol, g.price, g.change, g.change_pct) == ("XLABW", 0.195, 0.1244, 176.204)
    active = m.tables["ACTIVE"][0]
    assert active.symbol == "HODO" and active.volume == pytest.approx(561_137_454.657995)
    # Percent change is derived from the reported last and change: 0.0253 / (0.0928 - 0.0253).
    assert active.change_pct == pytest.approx(0.0253 / (0.0928 - 0.0253) * 100)
    assert m.as_of_text == "Data as of Oct 16, 2026 4:15 PM ET"
    assert m.market_time == int(datetime(2026, 10, 16, 20, 15, tzinfo=UTC).timestamp())
    assert all(r.change_pct is not None and r.change_pct < 0 for r in m.tables["LOSERS"])


def test_movers_api(client):
    r = client.get("/api/movers").json()
    assert r["source"] == "nasdaq:fixture"
    assert len(r["data"]["tables"]["GAINERS"]) == 10


# --- crypto ----------------------------------------------------------------------------------
async def test_coingecko_markets(http):
    coins = await CoinGeckoProvider(http).crypto("USD")
    assert len(coins) == 50
    btc = coins[0]
    assert (btc.symbol, btc.name, btc.rank, btc.quote) == ("BTC", "Bitcoin", 1, "USD")
    assert btc.price == 81588 and btc.market_cap == 1639828032036
    assert btc.change_pct_7d == -1.35 and btc.change_pct_1h == 0.0213
    assert btc.updated == datetime(2026, 10, 17, 9, 50, 57, tzinfo=UTC).timestamp()


async def test_binance_fallback_rows(http):
    p = BinanceProvider(http)
    assert p.supports("crypto", "USD") and not p.supports("crypto", "INR")
    coins = await p.crypto("USD")
    assert len(coins) == 22 and coins[0].symbol == "BTC" and coins[0].quote == "USDT"
    assert coins[0].price == 81699.91 and coins[0].change_pct_24h == -0.572
    assert coins[0].market_cap is None and coins[0].rank is None  # Binance has no market cap: left blank


async def test_crypto_falls_back_to_binance():
    async with failing({"api.coingecko.com"}, status=429) as c:
        providers = {"coingecko": CoinGeckoProvider(c), "binance": BinanceProvider(c)}
        router = Router(providers, {"crypto": ["coingecko", "binance"]})
        coins, failed = await router.call("crypto", lambda p: p.crypto("USD"), "USD")
        assert failed == ["coingecko"] and coins[0].quote == "USDT"
        assert router.health["coingecko"].down  # 429 trips the breaker at once
        with pytest.raises(AllFailed):
            await router.call("crypto", lambda p: p.crypto("INR"), "INR")


def test_crypto_api(client):
    r = client.get("/api/crypto").json()
    assert r["source"] == "coingecko:fixture" and r["data"]["vs"] == "USD"
    assert r["data"]["coins"][0]["symbol"] == "BTC"
    assert client.get("/api/crypto", params={"vs": "inr"}).status_code == 404  # not recorded
    assert client.get("/api/crypto", params={"vs": "xx1"}).status_code == 400


# --- boards (WEI / FX / FXC / CMDTY use the existing quote path) -------------------------------
def test_board_symbols_quote_in_fixture_mode(client):
    syms = "^GSPC,^NSEI,000001.SS,GC=F,CL=F,USDINR=X,USDEUR=X,DX-Y.NYB,FTSEMIB.MI"
    res = client.get("/api/quote", params={"symbols": syms}).json()["results"]
    for s in syms.split(","):
        assert res[s]["data"]["price"] > 0, s


def test_sources_list_phase5_providers(client):
    names = {p["name"] for p in client.get("/api/sources").json()["providers"]}
    assert {"rss", "yahoo_rss", "gdelt", "coingecko", "binance"} <= names
