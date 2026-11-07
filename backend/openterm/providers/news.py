"""News headlines: publisher RSS feeds (market top stories), Yahoo's per-symbol headline RSS, and the
GDELT DOC API (keyword search). Headlines and links only; articles open on the publisher's site.

XML is parsed with the stdlib: Python 3.12 bundles Expat >= 2.6, which is not vulnerable to the
billion-laughs and quadratic-blowup attacks, and ElementTree never fetches external entities.
"""

import asyncio
import hashlib
import html
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import ClassVar
from urllib.parse import urlsplit

import orjson

from ..config import load_yaml
from ..models import NewsItem
from ..news_tags import feed_selected, normalize_title
from .base import NEWS_KEYWORD, NEWS_POOL, NEWS_SYMBOL, NEWS_TOP, Provider, ProviderError
from .http import UA
from .news_feeds import FEEDS as FEED_TABLE
from .news_feeds import Feed

log = logging.getLogger("openterm.news")

# The built-in top-stories feeds as {name, url} dicts (the full curated table is news_feeds.FEEDS).
FEEDS: list[dict[str, str]] = [{"name": f.name, "url": f.url} for f in FEED_TABLE if f.core]
MAX_ITEMS = 200
FEED_TIMEOUT = 6.0  # seconds per feed: a slow feed is reported as not answering, it never holds the others up
CACHE_S, FAST_CACHE_S = 60.0, 30.0  # per-feed cache; tech / breaking feeds (Feed.fast) refresh sooner
MAX_PER_FEED = 50
SUMMARY_LEN = 300
RSS_ACCEPT = "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.5"

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_GDELT_PUNCT = re.compile(r"\s+([:?!,;.])")


def clean(text: str | None, limit: int = SUMMARY_LEN) -> str:
    """Plain text from a feed field: tags dropped, entities decoded, whitespace collapsed, capped."""
    if not text:
        return ""
    s = _WS.sub(" ", html.unescape(_TAG.sub(" ", text))).strip()
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def item_id(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


def rfc822(s: str | None) -> float | None:
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s.strip())
    except (TypeError, ValueError):
        try:  # SEBI sends "05 Nov 2026 18:00:02 +0530" (no weekday), which the email parser refuses
            d = datetime.strptime(s.strip(), "%d %b %Y %H:%M:%S %z")
        except ValueError:
            return None
    # A date with no zone is read as UTC; a feed that meant local time (RBI, IST) would land in the future, so cap at "now".
    return min((d if d.tzinfo else d.replace(tzinfo=UTC)).timestamp(), time.time())


def domain(url: str) -> str | None:
    host = urlsplit(url).hostname or ""
    return host.removeprefix("www.") or None


ATOM = "{http://www.w3.org/2005/Atom}"
DC_DATE = "{http://purl.org/dc/elements/1.1/}date"


def iso8601(s: str | None) -> float | None:
    """Atom / Dublin Core dates ("2026-11-05T11:39:42+00:00", also with a trailing Z)."""
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.strip())
    except ValueError:
        return None
    return (d if d.tzinfo else d.replace(tzinfo=UTC)).timestamp()


def _entries(root: ET.Element):
    """(title, url, date text, summary) for each RSS <item> or Atom <entry>."""
    for it in root.iter("item"):
        yield it.findtext("title"), (it.findtext("link") or "").strip(), (it.findtext("pubDate") or it.findtext(DC_DATE)), it.findtext("description")
    for en in root.iter(ATOM + "entry"):
        # Atom puts the URL in an attribute; prefer the rel="alternate" (or unlabelled) link.
        link = next((lk.get("href", "") for lk in en.findall(ATOM + "link") if lk.get("rel", "alternate") == "alternate"), "")
        yield (en.findtext(ATOM + "title"), link.strip(), en.findtext(ATOM + "published") or en.findtext(ATOM + "updated"),
               en.findtext(ATOM + "summary"))


def parse_rss(content: bytes, publisher: str | None, source: str) -> list[NewsItem]:
    """RSS 2.0 items or Atom entries. `publisher` None means "use each link's domain" (aggregated feeds)."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        # Some feeds declare UTF-8 but contain stray cp1252 bytes: keep what decodes.
        try:
            root = ET.fromstring(content.decode("utf-8", errors="replace"))
        except ET.ParseError as e:
            raise ProviderError("unavailable", "feed is not XML (bot check or outage?)") from e
    out: list[NewsItem] = []
    for raw_title, url, date, summary in _entries(root):
        title = clean(raw_title)
        if not title or not url.startswith(("https://", "http://")):
            continue
        out.append(NewsItem(
            id=item_id(url), title=title, url=url, publisher=publisher or domain(url),
            published=rfc822(date) or iso8601(date), summary=clean(summary) or None,
            source=source,
        ))
        if len(out) >= MAX_PER_FEED:
            break
    return out


def merge(items: list[NewsItem]) -> list[NewsItem]:
    """Newest first, one entry per URL (and per identical headline), capped."""
    seen: set[str] = set()
    out = []
    for i in sorted(items, key=lambda x: x.published or 0, reverse=True):
        title_key = normalize_title(i.title)  # case / punctuation differences do not make a new story
        if i.url in seen or title_key in seen:
            continue
        seen.update((i.url, title_key))
        out.append(i)
    return out[:MAX_ITEMS]


def configured_feeds() -> list[Feed]:
    """The feed table, or the user's own list when config.yaml has `news: feeds:` (those all count as top stories)."""
    custom = (load_yaml().get("news") or {}).get("feeds")
    if not custom:
        return list(FEED_TABLE)
    return [Feed(str(f["name"]).upper(), str(f["url"]), ("markets",), "WORLD", (), False) for f in custom if f.get("name") and f.get("url")]


class RssProvider(Provider):
    name = "rss"
    label = "Publisher RSS feeds"
    capabilities = frozenset({NEWS_TOP, NEWS_POOL})
    terms = "Headlines, teasers and links from each publisher's public RSS feed. Articles open on the publisher's site."
    rate = (100.0, 100)  # dozens of feeds fetched at once, each on its own host: a shared 5/s bucket would starve them
    headers: ClassVar[dict[str, str]] = {"User-Agent": UA, "Accept": RSS_ACCEPT}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.feeds = configured_feeds()
        # config.yaml feeds are all "top"; with the built-in table only the five original (core) feeds are.
        custom = bool((load_yaml().get("news") or {}).get("feeds"))
        self.top = self.feeds if custom else [f for f in self.feeds if f.core]
        self.markets = f"{len(self.feeds)} curated feeds (tech, markets, India, official, commodities, crypto); top stories: " + ", ".join(f.name for f in self.top)
        self._cache: dict[str, tuple[float, list[NewsItem]]] = {}  # url -> (fetched at, items)

    async def _feed(self, feed: Feed) -> list[NewsItem]:
        """One feed's items, through a short per-feed cache (30 s for fast feeds, 60 s otherwise)."""
        hit = self._cache.get(feed.url)
        if hit and time.time() - hit[0] < (FAST_CACHE_S if feed.fast else CACHE_S):
            return hit[1]
        items = parse_rss(await self.get_bytes(feed.url, timeout=FEED_TIMEOUT), feed.name, self.source)
        self._cache[feed.url] = (time.time(), items)
        return items

    async def _fetch_all(self, feeds: list[Feed]) -> tuple[list[tuple[Feed, list[NewsItem]]], list[str]]:
        """All feeds at once. A dead feed is recorded by name and never stops the others."""
        results = await asyncio.gather(*(self._feed(f) for f in feeds), return_exceptions=True)
        ok: list[tuple[Feed, list[NewsItem]]] = []
        failed: list[str] = []
        for feed, r in zip(feeds, results):
            if isinstance(r, BaseException):
                failed.append(feed.name)
                log.warning("feed %s failed: %s", feed.name, r)
            else:
                ok.append((feed, r))
        return ok, failed

    async def news_top(self) -> dict:
        ok, failed = await self._fetch_all(self.top)
        items = [i for _, found in ok for i in found]
        if not items:
            raise ProviderError("unavailable", f"no feed answered ({', '.join(failed) or 'none configured'})")
        return {"items": merge(items), "failed": failed}

    async def news_pool(self, section: str | None) -> dict:
        """Every feed of the section (all feeds when None), kept with its feed so the caller can filter on feed tags."""
        feeds = [f for f in self.feeds if feed_selected(f, section)]
        ok, failed = await self._fetch_all(feeds)
        if not any(found for _, found in ok):
            raise ProviderError("unavailable", f"no feed answered ({', '.join(failed) or 'none matched'})")
        return {"pool": ok, "failed": failed, "total": len(feeds)}

    async def probe(self) -> None:
        await self._feed(self.top[0])


class YahooRssProvider(Provider):
    name = "yahoo_rss"
    label = "Yahoo Finance headline RSS (unofficial)"
    capabilities = frozenset({NEWS_SYMBOL})
    markets = "Per-symbol headlines, mostly US listings; sparse for other markets"
    terms = "Unofficial feed; personal use. Links go to the original publishers."
    rate = (4.0, 8)
    headers: ClassVar[dict[str, str]] = {"User-Agent": UA, "Accept": RSS_ACCEPT}

    async def news_symbol(self, symbol: str) -> dict:
        content = await self.get_bytes(
            "https://feeds.finance.yahoo.com/rss/2.0/headline", {"s": symbol, "region": "US", "lang": "en-US"}
        )
        items = parse_rss(content, None, self.source)
        if not items:
            raise ProviderError("not_found", "no headlines")
        return {"items": merge(items), "failed": []}

    async def probe(self) -> None:
        await self.news_symbol("SPY")


def gdelt_time(s: str | None) -> float | None:
    try:
        return datetime.strptime(s or "", "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC).timestamp()
    except ValueError:
        return None


class GdeltProvider(Provider):
    name = "gdelt"
    label = "GDELT DOC 2.0 API"
    capabilities = frozenset({NEWS_KEYWORD, NEWS_SYMBOL})
    markets = "Keyword search over worldwide online news, last 7 days, English"
    terms = "Free, no key. GDELT asks for at most one request every 5 s. Often slow (5-15 s)."
    rate = (0.2, 1)
    max_wait = 6.0  # a second search inside 5 s waits for its slot instead of failing
    timeout = 20.0
    headers: ClassVar[dict[str, str]] = {"User-Agent": UA, "Accept": "application/json"}

    async def _search(self, query: str) -> dict:
        content = await self.get_bytes("https://api.gdeltproject.org/api/v2/doc/doc", {
            "query": f"{query} sourcelang:english", "mode": "artlist", "maxrecords": 50, "format": "json",
            "sort": "datedesc", "timespan": "7d",
        })
        if content.lstrip()[:20].lower().startswith(b"please limit"):
            raise ProviderError("rate_limited", "GDELT: one request every 5 s")
        try:
            body = orjson.loads(content)
        except orjson.JSONDecodeError as e:
            raise ProviderError("unavailable", "non-JSON response") from e
        items = [
            NewsItem(
                id=item_id(a["url"]), title=_GDELT_PUNCT.sub(r"\1", clean(a.get("title"))), url=a["url"],
                publisher=a.get("domain") or domain(a["url"]), published=gdelt_time(a.get("seendate")),
                source=self.source,
            )
            for a in (body.get("articles") or [] if isinstance(body, dict) else [])
            if str(a.get("url", "")).startswith(("https://", "http://")) and a.get("title")
        ]
        if not items:
            raise ProviderError("not_found", "no articles")
        return {"items": merge(items), "failed": []}

    async def news_keyword(self, query: str) -> dict:
        return await self._search(query)

    async def news_symbol(self, symbol: str) -> dict:
        base = re.split(r"[.=\-]", symbol.lstrip("^"))[0]
        if len(base) < 3:  # GDELT rejects very short keywords, and they would match everything
            raise ProviderError("not_found", "symbol too short for a keyword search")
        return await self._search(f'"{base}"')

    async def probe(self) -> None:
        return None  # one request per 5 s: never spend it on a health check
