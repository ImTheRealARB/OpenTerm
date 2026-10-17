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
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import ClassVar
from urllib.parse import urlsplit

import orjson

from ..config import load_yaml
from ..models import NewsItem
from .base import NEWS_KEYWORD, NEWS_SYMBOL, NEWS_TOP, Provider, ProviderError
from .yahoo import UA

log = logging.getLogger("openterm.news")

# Default market feeds (verified 2026-10-17). Override with `news: feeds:` in config.yaml.
FEEDS: list[dict[str, str]] = [
    {"name": "CNBC", "url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114"},
    {"name": "MARKETWATCH", "url": "https://feeds.content.dowjones.io/public/rss/mw_topstories"},
    {"name": "BBC BUSINESS", "url": "https://feeds.bbci.co.uk/news/business/rss.xml"},
    {"name": "ECONOMIC TIMES", "url": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"},
    {"name": "MINT", "url": "https://www.livemint.com/rss/markets"},
]
MAX_ITEMS = 200
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
        return None
    return (d if d.tzinfo else d.replace(tzinfo=UTC)).timestamp()


def domain(url: str) -> str | None:
    host = urlsplit(url).hostname or ""
    return host.removeprefix("www.") or None


def parse_rss(content: bytes, publisher: str | None, source: str) -> list[NewsItem]:
    """RSS 2.0 items. `publisher` None means "use each link's domain" (aggregated feeds)."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        # Some feeds declare UTF-8 but contain stray cp1252 bytes: keep what decodes.
        try:
            root = ET.fromstring(content.decode("utf-8", errors="replace"))
        except ET.ParseError as e:
            raise ProviderError("unavailable", "feed is not XML (bot check or outage?)") from e
    out: list[NewsItem] = []
    for it in root.iter("item"):
        title = clean(it.findtext("title"))
        url = (it.findtext("link") or "").strip()
        if not title or not url.startswith(("https://", "http://")):
            continue
        out.append(NewsItem(
            id=item_id(url), title=title, url=url, publisher=publisher or domain(url),
            published=rfc822(it.findtext("pubDate")), summary=clean(it.findtext("description")) or None,
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
        title_key = i.title.lower()
        if i.url in seen or title_key in seen:
            continue
        seen.update((i.url, title_key))
        out.append(i)
    return out[:MAX_ITEMS]


def configured_feeds() -> list[dict[str, str]]:
    feeds = ((load_yaml().get("news") or {}).get("feeds")) or FEEDS
    return [{"name": str(f["name"]).upper(), "url": str(f["url"])} for f in feeds if f.get("name") and f.get("url")]


class RssProvider(Provider):
    name = "rss"
    label = "Publisher RSS feeds"
    capabilities = frozenset({NEWS_TOP})
    terms = "Headlines, teasers and links from each publisher's public RSS feed. Articles open on the publisher's site."
    rate = (5.0, 10)
    headers: ClassVar[dict[str, str]] = {"User-Agent": UA, "Accept": RSS_ACCEPT}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.feeds = configured_feeds()
        self.markets = "Market top stories: " + ", ".join(f["name"] for f in self.feeds)

    async def _feed(self, feed: dict[str, str]) -> list[NewsItem]:
        return parse_rss(await self.get_bytes(feed["url"]), feed["name"], self.source)

    async def news_top(self) -> dict:
        results = await asyncio.gather(*(self._feed(f) for f in self.feeds), return_exceptions=True)
        items: list[NewsItem] = []
        failed: list[str] = []
        for feed, r in zip(self.feeds, results):
            if isinstance(r, BaseException):
                failed.append(feed["name"])
                log.warning("feed %s failed: %s", feed["name"], r)
            else:
                items.extend(r)
        if not items:
            raise ProviderError("unavailable", f"no feed answered ({', '.join(failed) or 'none configured'})")
        return {"items": merge(items), "failed": failed}

    async def probe(self) -> None:
        await self._feed(self.feeds[0])


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
