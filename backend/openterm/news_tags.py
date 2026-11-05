"""News filters (region / sector / commodity / section / free text): PURE, no network, no database.

A headline matches a filter in one of two ways:
  1. its FEED carries the tag (TechCrunch is tagged sector "tech", so every TechCrunch headline is tech), or
  2. a KEYWORD from the tables below appears in its title or teaser ("crude" means commodity "oil").
All the keyword tables live here, in one place, so a new sector or commodity is one dictionary entry.
Matching is on whole words (regex word boundaries), so "oil" does not match "toil" and "gas" not "Vegas".
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:  # type only: importing it for real would be circular (providers/__init__ imports news, which imports this)
    from .providers.news_feeds import Feed

# --- keyword tables. Keys are the filter values users type (case-insensitive); values are the words that count. ---
SECTOR_WORDS: dict[str, tuple[str, ...]] = {
    "tech": ("software", "chip", "chips", "semiconductor", "ai", "artificial intelligence", "cloud", "cyber", "startup",
             "nvidia", "apple", "microsoft", "google", "alphabet", "meta", "amazon", "tesla", "openai", "intel", "amd"),
    "banks": ("bank", "banks", "banking", "lender", "lenders", "central bank", "fed", "rbi", "ecb", "credit", "loan",
              "loans", "jpmorgan", "goldman", "hdfc", "sbi", "icici"),
    "energy": ("oil", "gas", "crude", "opec", "lng", "refinery", "renewable", "solar", "wind", "power", "coal", "energy"),
    "pharma": ("pharma", "drug", "drugs", "fda", "vaccine", "biotech", "clinical", "trial", "therapy", "medicine"),
    "autos": ("auto", "autos", "car", "cars", "ev", "evs", "electric vehicle", "carmaker", "automaker", "tesla", "tata motors"),
    "retail": ("retail", "retailer", "retailers", "consumer", "walmart", "amazon", "e-commerce", "shopping"),
    "realestate": ("real estate", "property", "housing", "mortgage", "reit", "homebuilder"),
    "telecom": ("telecom", "5g", "broadband", "spectrum", "jio", "airtel", "verizon"),
    "metals": ("steel", "aluminium", "aluminum", "copper", "mining", "miner", "iron ore", "zinc", "nickel"),
}
COMMODITY_WORDS: dict[str, tuple[str, ...]] = {
    "oil": ("oil", "crude", "brent", "wti", "opec", "petroleum"),
    "gold": ("gold", "bullion"),
    "silver": ("silver",),
    "copper": ("copper",),
    "gas": ("natural gas", "lng", "gas prices", "henry hub"),
    "wheat": ("wheat", "grain", "grains"),
    "corn": ("corn", "maize"),
    "coffee": ("coffee",),
    "lithium": ("lithium",),
}
REGION_WORDS: dict[str, tuple[str, ...]] = {
    "US": ("wall street", "united states", "washington", "federal reserve", "nasdaq", "s&p 500", "dow jones", "treasury"),
    "IN": ("india", "indian", "rbi", "sebi", "nifty", "sensex", "rupee", "mumbai", "delhi", "modi"),
    "CN": ("china", "chinese", "beijing", "yuan", "shanghai", "hong kong"),
    "UK": ("uk", "britain", "british", "london", "bank of england", "sterling", "ftse"),
    "EU": ("eurozone", "euro zone", "europe", "european", "ecb", "brussels", "germany", "france"),
    "JP": ("japan", "japanese", "tokyo", "yen", "boj", "nikkei"),
}


def _word_regex(words: tuple[str, ...]) -> re.Pattern[str]:
    """One compiled pattern: any of `words`, as whole words, case-insensitive."""
    return re.compile(r"(?<![\w])(?:" + "|".join(re.escape(w) for w in words) + r")(?![\w])", re.IGNORECASE)


# Compiled once at import so filtering 1,000 headlines is a handful of regex scans.
_SECTOR_RE = {k: _word_regex(v) for k, v in SECTOR_WORDS.items()}
_COMMODITY_RE = {k: _word_regex(v) for k, v in COMMODITY_WORDS.items()}
_REGION_RE = {k: _word_regex(v) for k, v in REGION_WORDS.items()}


class Filters(NamedTuple):
    """What the user asked for. A None field is not filtered on; all given fields must match (AND)."""

    region: str | None = None
    sector: str | None = None
    commodity: str | None = None
    section: str | None = None
    q: str | None = None

    @property
    def active(self) -> bool:
        return any(self)


def clean_filters(region: str | None, sector: str | None, commodity: str | None, section: str | None, q: str | None) -> Filters:
    """Trim and normalise raw query-string values: codes upper/lower-cased, blanks become None."""
    def one(v: str | None, upper: bool = False) -> str | None:
        v = " ".join((v or "").split())
        return (v.upper() if upper else v.lower()) or None

    return Filters(one(region, True), one(sector), one(commodity), one(section), " ".join((q or "").split()) or None)


def normalize_title(title: str) -> str:
    """Key for near-duplicate detection: lower case, punctuation dropped, spaces collapsed.

    "Fed holds rates steady!" and "Fed Holds Rates Steady" give the same key, so the same story from two feeds shows once.
    """
    return " ".join(re.sub(r"[^\w\s]", " ", title.lower()).split())


def feed_selected(feed: Feed, section: str | None) -> bool:
    """Does this feed belong to the section? `india` also takes every Indian-region feed; None / `all` takes every feed."""
    if not section or section == "all":
        return True
    return section in feed.sections or (section == "india" and feed.region == "IN")


def _hit(table: dict[str, re.Pattern[str]], key: str, text: str) -> bool:
    pattern = table.get(key)
    return bool(pattern and pattern.search(text))


def item_matches(title: str, summary: str | None, feed: Feed, f: Filters) -> bool:
    """Does one headline (from `feed`) pass every given filter?"""
    text = f"{title} {summary or ''}"
    if f.section and not feed_selected(feed, f.section):
        return False
    if f.region and not (feed.region == f.region or _hit(_REGION_RE, f.region, text)):
        return False
    if f.sector and not (f.sector in feed.sectors or _hit(_SECTOR_RE, f.sector, text)):
        return False
    if f.commodity and not _hit(_COMMODITY_RE, f.commodity, text):
        return False
    if f.q:
        low = text.lower()
        # Every typed word must appear somewhere (substring, so "rates" finds "interest rates").
        if not all(w in low for w in f.q.lower().split()):
            return False
    return True


def known_values() -> dict[str, list[str]]:
    """The legal values for each filter, for error messages and the panel's help line."""
    from .providers.news_feeds import REGIONS, SECTIONS

    return {"region": list(REGIONS), "sector": sorted(SECTOR_WORDS), "commodity": sorted(COMMODITY_WORDS), "section": [*SECTIONS, "all"]}


def validate(f: Filters) -> str | None:
    """A message when a filter value is not one we know (so a typo says so instead of returning nothing), else None."""
    known = known_values()
    for name in ("region", "sector", "commodity", "section"):
        value = getattr(f, name)
        if value and value not in known[name]:
            return f"UNKNOWN {name.upper()} {value.upper()}. TRY: {', '.join(v.upper() for v in known[name])}"
    return None
