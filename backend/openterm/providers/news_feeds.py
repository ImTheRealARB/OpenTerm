"""The curated list of free, keyless RSS / Atom news feeds, as ONE data table.

Adding a feed = adding one line to `_ROWS`; there is no code per feed. Each row is
    (name, url, sections, region, sectors, fast)
  sections : what the feed covers, from SECTIONS ("markets", "tech", ...). A feed may have several.
  region   : country / area code (US, IN, CN, UK, EU, JP, WORLD). Filters `region=`.
  sectors  : industry tags ("tech", "banks", "energy", ...). Filters `sector=` (together with keywords).
  fast     : True = tech / breaking feeds, cached 30 s instead of 60 s.
Every URL below answered with items on 2026-11-05 (one polite request each). The feeds that did not are listed with
the reason in docs/DATA_SOURCES.md "News feeds". Feed URLs change: re-check one when it starts showing in NOT ANSWERING.
"""

from typing import NamedTuple

SECTIONS = ("markets", "economy", "companies", "commodities", "crypto", "tech", "india", "world")
REGIONS = ("US", "IN", "CN", "UK", "EU", "JP", "WORLD")

# Short names for rows below, so the table stays one line per feed.
M, E, C, CM, CR, T, IN, W = "markets", "economy", "companies", "commodities", "crypto", "tech", "india", "world"

# The five feeds behind the plain "top stories" view. They are the feeds this app shipped with, so the unfiltered
# NEWS output (and the news alerts that read it) keeps behaving exactly as before.
CORE = {"CNBC", "MARKETWATCH", "BBC BUSINESS", "ECONOMIC TIMES", "MINT"}

_CNBC = "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id="

_ROWS: list[tuple] = [
    # name, url, sections, region, sectors, fast
    # --- the original five ---
    ("CNBC", _CNBC + "100003114", (M,), "US", (), False),
    ("MARKETWATCH", "https://feeds.content.dowjones.io/public/rss/mw_topstories", (M,), "US", (), False),
    ("BBC BUSINESS", "https://feeds.bbci.co.uk/news/business/rss.xml", (E, C), "UK", (), False),
    ("ECONOMIC TIMES", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms", (M, IN), "IN", (), False),
    ("MINT", "https://www.livemint.com/rss/markets", (M, IN), "IN", (), False),
    # --- tech (fast) ---
    ("TECHCRUNCH", "https://techcrunch.com/feed/", (T, C), "US", ("tech",), True),
    ("THE VERGE", "https://www.theverge.com/rss/index.xml", (T,), "US", ("tech",), True),
    ("ARS TECHNICA", "https://feeds.arstechnica.com/arstechnica/index", (T,), "US", ("tech",), True),
    ("WIRED", "https://www.wired.com/feed/rss", (T,), "US", ("tech",), True),
    ("HACKER NEWS", "https://news.ycombinator.com/rss", (T,), "WORLD", ("tech",), True),
    ("MIT TECH REVIEW", "https://www.technologyreview.com/feed/", (T,), "US", ("tech",), True),
    ("ENGADGET", "https://www.engadget.com/rss.xml", (T,), "US", ("tech",), True),
    ("THE REGISTER", "https://www.theregister.com/headlines.atom", (T,), "UK", ("tech",), True),
    ("CNBC TECH", _CNBC + "19854910", (T, M), "US", ("tech",), True),
    ("BBC TECH", "https://feeds.bbci.co.uk/news/technology/rss.xml", (T,), "UK", ("tech",), True),
    ("GUARDIAN TECH", "https://www.theguardian.com/technology/rss", (T,), "UK", ("tech",), True),
    ("ET TECH", "https://economictimes.indiatimes.com/tech/rssfeeds/13357270.cms", (T, IN), "IN", ("tech",), True),
    ("MINT TECH", "https://www.livemint.com/rss/technology", (T, IN), "IN", ("tech",), True),
    # --- global business and markets ---
    ("CNBC ECONOMY", _CNBC + "20910258", (E,), "US", (), False),
    ("CNBC FINANCE", _CNBC + "10000664", (M, C), "US", ("banks",), False),
    ("CNBC INVESTING", _CNBC + "15839069", (M,), "US", (), False),
    ("GUARDIAN BUSINESS", "https://www.theguardian.com/uk/business/rss", (E, C), "UK", (), False),
    ("AL JAZEERA", "https://www.aljazeera.com/xml/rss/all.xml", (W,), "WORLD", (), False),
    ("BBC WORLD", "https://feeds.bbci.co.uk/news/world/rss.xml", (W,), "WORLD", (), False),
    ("FINANCIAL TIMES", "https://www.ft.com/rss/home", (M, E, W), "UK", (), False),
    ("SEEKING ALPHA", "https://seekingalpha.com/market_currents.xml", (M, C), "US", (), True),
    ("INVESTING.COM", "https://www.investing.com/rss/news.rss", (M,), "WORLD", (), True),
    # --- India ---
    ("ET ECONOMY", "https://economictimes.indiatimes.com/news/economy/rssfeeds/1373380680.cms", (E, IN), "IN", (), False),
    ("ET COMPANIES", "https://economictimes.indiatimes.com/industry/rssfeeds/13352306.cms", (C, IN), "IN", (), False),
    ("MINT COMPANIES", "https://www.livemint.com/rss/companies", (C, IN), "IN", (), False),
    ("MINT ECONOMY", "https://www.livemint.com/rss/economy", (E, IN), "IN", (), False),
    ("BUSINESS STANDARD", "https://www.business-standard.com/rss/markets-106.rss", (M, IN), "IN", (), False),
    ("BS ECONOMY", "https://www.business-standard.com/rss/economy-102.rss", (E, IN), "IN", (), False),
    ("BUSINESSLINE", "https://www.thehindubusinessline.com/feeder/default.rss", (M, C, IN), "IN", (), False),
    ("BUSINESSLINE MARKETS", "https://www.thehindubusinessline.com/markets/feeder/default.rss", (M, IN), "IN", (), False),
    ("NDTV PROFIT", "https://feeds.feedburner.com/ndtvprofit-latest", (M, C, IN), "IN", (), False),
    ("RBI", "https://www.rbi.org.in/pressreleases_rss.xml", (E, IN), "IN", ("banks",), False),
    ("SEBI", "https://www.sebi.gov.in/sebirss.xml", (M, IN), "IN", ("banks",), False),
    # --- official ---
    ("FED", "https://www.federalreserve.gov/feeds/press_all.xml", (E,), "US", ("banks",), False),
    ("ECB", "https://www.ecb.europa.eu/rss/press.html", (E,), "EU", ("banks",), False),
    ("SEC", "https://www.sec.gov/news/pressreleases.rss", (M, C), "US", (), False),
    # --- commodities, energy, crypto ---
    ("OILPRICE", "https://oilprice.com/rss/main", (CM,), "WORLD", ("energy",), False),
    ("COINDESK", "https://www.coindesk.com/arc/outboundfeeds/rss/", (CR,), "WORLD", (), True),
    ("COINTELEGRAPH", "https://cointelegraph.com/rss", (CR,), "WORLD", (), True),
    ("THE BLOCK", "https://www.theblock.co/rss.xml", (CR,), "WORLD", (), True),
]


class Feed(NamedTuple):
    name: str
    url: str
    sections: tuple[str, ...]
    region: str
    sectors: tuple[str, ...]
    fast: bool

    @property
    def core(self) -> bool:
        return self.name in CORE


FEEDS: list[Feed] = [Feed(*row) for row in _ROWS]
