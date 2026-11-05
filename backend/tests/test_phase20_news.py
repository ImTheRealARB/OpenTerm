"""Phase 20: news feeds and filters. No network: every XML string below is HAND-MADE (labelled test data, not a recording)."""

import time

import httpx
import pytest

from openterm.news_tags import (
    Filters,
    clean_filters,
    feed_selected,
    item_matches,
    normalize_title,
    validate,
)
from openterm.providers.news import RssProvider, iso8601, merge, parse_rss, rfc822
from openterm.providers.news_feeds import CORE, FEEDS, REGIONS, SECTIONS, Feed

# Small stand-in feeds for the matching tests (name, url, sections, region, sectors, fast).
TECH = Feed("TECHFEED", "https://t.invalid/rss", ("tech",), "US", ("tech",), True)
INDIA = Feed("INDIAFEED", "https://i.invalid/rss", ("markets", "india"), "IN", (), False)
WORLD = Feed("WORLDFEED", "https://w.invalid/rss", ("world",), "WORLD", (), False)


# --- the feed table itself ---------------------------------------------------------------------
def test_feed_table_is_well_formed():
    names = [f.name for f in FEEDS]
    assert len(names) == len(set(names)), "feed names must be unique"
    assert len({f.url for f in FEEDS}) == len(FEEDS), "feed URLs must be unique"
    assert all(f.url.startswith("https://") for f in FEEDS)
    assert all(set(f.sections) <= set(SECTIONS) and f.sections for f in FEEDS)
    assert all(f.region in REGIONS for f in FEEDS)
    assert {f.name for f in FEEDS if f.core} == CORE  # the original five stay the top-stories set
    assert sum(f.fast for f in FEEDS if "tech" in f.sections) >= 8  # tech is the fast lane


# --- pure filter logic, table-driven -----------------------------------------------------------
@pytest.mark.parametrize(
    ("title", "feed", "filters", "expected"),
    [
        # feed tags alone are enough
        ("Anything at all", TECH, Filters(sector="tech"), True),
        ("Anything at all", INDIA, Filters(region="IN"), True),
        ("Anything at all", INDIA, Filters(region="CN"), False),
        # keywords in a feed with no tag
        ("Nvidia unveils new chip", WORLD, Filters(sector="tech"), True),
        ("Nvidia unveils new chip", WORLD, Filters(sector="banks"), False),
        ("Sensex jumps as RBI holds rates", WORLD, Filters(region="IN"), True),
        ("Yen slides after BOJ meeting", WORLD, Filters(region="JP"), True),
        ("Brent crude climbs on OPEC cuts", WORLD, Filters(commodity="oil"), True),
        ("Gold hits a record", WORLD, Filters(commodity="gold"), True),
        ("Gold hits a record", WORLD, Filters(commodity="oil"), False),
        ("Spoil sport", WORLD, Filters(commodity="oil"), False),  # whole words only: 'oil' is not inside 'Spoil'
        ("Las Vegas trip", WORLD, Filters(commodity="gas"), False),
        # section = feed tag; india also takes every IN feed
        ("x", TECH, Filters(section="tech"), True),
        ("x", TECH, Filters(section="markets"), False),
        ("x", INDIA, Filters(section="india"), True),
        ("x", WORLD, Filters(section="all"), True),
        # free text: every word must appear, in title or teaser, any case
        ("Fed signals a rate cut in March", WORLD, Filters(q="rate cut"), True),
        ("Fed signals a rate cut in March", WORLD, Filters(q="rate hike"), False),
        ("Fed signals a rate cut in March", WORLD, Filters(q="FED march"), True),
        # filters combine with AND
        ("Nvidia unveils new chip", TECH, Filters(sector="tech", q="nvidia"), True),
        ("Nvidia unveils new chip", TECH, Filters(sector="tech", q="amd"), False),
        ("Nvidia unveils new chip", INDIA, Filters(region="IN", sector="tech"), True),
        ("Nvidia unveils new chip", WORLD, Filters(region="IN", sector="tech"), False),
    ],
)
def test_item_matches(title, feed, filters, expected):
    assert item_matches(title, None, feed, filters) is expected


def test_teaser_text_counts():
    assert item_matches("Quarterly results", "Profit beat as copper prices rose", WORLD, Filters(commodity="copper"))


@pytest.mark.parametrize(
    ("a", "b"),
    [("Fed holds rates steady!", "FED HOLDS RATES STEADY"), ("Apple: new  iPhone", "apple new iphone"), ("A -- B", "a b")],
)
def test_normalize_title_collapses_near_duplicates(a, b):
    assert normalize_title(a) == normalize_title(b)


def test_clean_filters_and_validate():
    f = clean_filters(" in ", "TECH ", "", None, "  rate   cut ")
    assert f == Filters(region="IN", sector="tech", commodity=None, section=None, q="rate cut")
    assert f.active and not Filters().active
    assert validate(f) is None
    msg = validate(Filters(region="MARS"))
    assert msg and "UNKNOWN REGION MARS" in msg and "IN" in msg  # a typo names the legal values
    assert validate(Filters(sector="astrology"))
    assert validate(Filters(section="all")) is None


@pytest.mark.parametrize(("section", "feed", "expected"), [(None, TECH, True), ("all", TECH, True), ("tech", INDIA, False), ("india", INDIA, True)])
def test_feed_selected(section, feed, expected):
    assert feed_selected(feed, section) is expected


# --- parsing: RSS, Atom, odd dates -------------------------------------------------------------
ATOM = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry><title>Atom headline</title><link rel="alternate" href="https://a.invalid/1"/>
    <updated>2026-11-05T11:39:42+00:00</updated><summary>An atom teaser</summary></entry>
  <entry><title>Second</title><link href="https://a.invalid/2"/><published>2026-11-05T12:00:00Z</published></entry>
</feed>"""


def test_atom_entries_are_parsed():
    items = parse_rss(ATOM, "ATOMFEED", "rss")
    assert [i.title for i in items] == ["Atom headline", "Second"]
    assert items[0].url == "https://a.invalid/1" and items[0].summary == "An atom teaser"
    assert items[1].published == iso8601("2026-11-05T12:00:00Z")


def test_odd_dates():
    assert rfc822("05 Nov 2026 18:00:02 +0530") == iso8601("2026-11-05T12:30:02+00:00")  # SEBI: no weekday
    assert rfc822("Thu, 05 Nov 2026 19:10:00") <= time.time()  # zone-less date from a feed that meant IST is never in the future
    assert rfc822(None) is None and rfc822("garbage") is None and iso8601("garbage") is None


def test_merge_drops_near_identical_headlines_across_feeds():
    a = parse_rss(b"<rss><channel><item><title>Fed holds rates steady!</title><link>https://x.invalid/1</link></item></channel></rss>", "A", "rss")
    b = parse_rss(b"<rss><channel><item><title>FED holds rates steady</title><link>https://y.invalid/2</link></item></channel></rss>", "B", "rss")
    assert len(merge(a + b)) == 1


# --- the provider: concurrency, failure isolation, caching -------------------------------------
def rss(*titles: str, day: str = "05") -> str:
    body = "".join(
        f"<item><title>{t}</title><link>https://story.invalid/{abs(hash(t))}</link><pubDate>Thu, {day} Nov 2026 1{n}:00:00 GMT</pubDate></item>"
        for n, t in enumerate(titles)
    )
    return f'<?xml version="1.0"?><rss version="2.0"><channel>{body}</channel></rss>'


class Fake:
    """A transport that answers by URL and counts the requests it saw."""

    def __init__(self, answers: dict[str, httpx.Response | None]):
        self.answers, self.calls = answers, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.calls.append(url)
        r = self.answers.get(url)
        if r is None:
            raise httpx.ConnectError("down")  # a dead host
        return r

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self))


def xml(text: str) -> httpx.Response:
    return httpx.Response(200, text=text, headers={"content-type": "application/rss+xml"})


@pytest.fixture
def three_feeds(monkeypatch):
    """The provider sees three tiny feeds instead of the real table."""
    feeds = [
        Feed("TECHFEED", "https://t.invalid/rss", ("tech",), "US", ("tech",), True),
        Feed("INDIAFEED", "https://i.invalid/rss", ("markets", "india"), "IN", (), False),
        Feed("DEADFEED", "https://dead.invalid/rss", ("markets",), "UK", (), False),
    ]
    monkeypatch.setattr("openterm.providers.news.configured_feeds", lambda: feeds)
    return feeds


async def test_one_dead_feed_never_blocks_the_others(three_feeds):
    fake = Fake({"https://t.invalid/rss": xml(rss("Chip news")), "https://i.invalid/rss": xml(rss("Sensex up"))})
    out = await RssProvider(fake.client()).news_pool(None)
    assert out["failed"] == ["DEADFEED"] and out["total"] == 3
    assert {f.name for f, _ in out["pool"]} == {"TECHFEED", "INDIAFEED"}


async def test_pool_section_fetches_only_that_sections_feeds(three_feeds):
    fake = Fake({"https://t.invalid/rss": xml(rss("Chip news"))})
    out = await RssProvider(fake.client()).news_pool("tech")
    assert fake.calls == ["https://t.invalid/rss"] and out["failed"] == [] and out["total"] == 1


async def test_all_feeds_dead_is_an_error(three_feeds):
    with pytest.raises(Exception, match="no feed answered"):
        await RssProvider(Fake({}).client()).news_pool(None)


async def test_per_feed_cache_and_fast_feeds_refresh_sooner(three_feeds, monkeypatch):
    fake = Fake({"https://t.invalid/rss": xml(rss("Chip news")), "https://i.invalid/rss": xml(rss("Sensex up"))})
    p = RssProvider(fake.client())
    await p.news_pool(None)
    await p.news_pool(None)
    assert fake.calls.count("https://t.invalid/rss") == 1  # second call came from the cache
    # 40 s later: the fast tech feed (30 s) is fetched again, the normal India feed (60 s) is not
    real = time.time
    monkeypatch.setattr("openterm.providers.news.time.time", lambda: real() + 40)
    await p.news_pool(None)
    assert fake.calls.count("https://t.invalid/rss") == 2
    assert fake.calls.count("https://i.invalid/rss") == 1


# --- the HTTP route (fixture mode: hand-made FIXTURE feeds for the new table entries) ----------
def test_route_section_returns_the_usual_item_shape(client):
    r = client.get("/api/news", params={"section": "tech", "limit": 5})
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["kind"] == "pool" and 0 < len(d["items"]) <= 5
    assert {"id", "title", "url", "publisher", "published", "summary", "source"} <= set(d["items"][0])  # same shape as today
    assert d["feeds_ok"] + len(d["failed"]) == d["feeds_total"] > 5
    assert all("FIXTURE" in i["title"] for i in d["items"])  # test data is labelled
    times = [i["published"] for i in d["items"]]
    assert times == sorted(times, reverse=True)


def test_route_filters_and_text(client):
    d = client.get("/api/news", params={"region": "IN", "section": "all"}).json()["data"]
    assert d["items"] and all(i["publisher"] in {f.name for f in FEEDS if f.region == "IN"} for i in d["items"])
    hit = client.get("/api/news", params={"section": "all", "q": "techcrunch"}).json()["data"]["items"]
    assert hit and all("TECHCRUNCH" in i["title"] for i in hit)
    assert client.get("/api/news", params={"section": "all", "q": "zzzznomatch"}).json()["data"]["items"] == []


def test_route_unknown_filter_value_says_so(client):
    r = client.get("/api/news", params={"region": "MARS"})
    assert r.status_code == 400 and "UNKNOWN REGION" in r.text


def test_plain_top_stories_still_use_only_the_original_feeds(client):
    d = client.get("/api/news").json()["data"]
    assert d["kind"] == "top" and {i["publisher"] for i in d["items"]} <= CORE
