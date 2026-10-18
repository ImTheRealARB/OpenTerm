"""Pure parsers for the keyed Phase 13 sources (Finnhub, Alpaca): JSON -> NewsItem lists and ANR / EEO payloads.

Finnhub and Alpaca answers are documented shapes; no key was available to record them, so the fixtures are labelled
doc-shaped. Article bodies are never read or kept: headline, teaser and link only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ..models import NewsItem
from ..providers.base import ProviderError
from ..providers.news import clean, item_id, merge
from .table import col, head, payload, section

MAX_ITEMS = 80


def _https(url: Any) -> bool:
    return isinstance(url, str) and url.startswith(("https://", "http://"))


def finnhub_news(rows: Any, source: str) -> list[NewsItem]:
    """Finnhub /company-news and /news: [{headline, url, source, datetime (epoch s), summary, related}]."""
    if not isinstance(rows, list):
        raise ProviderError("unavailable", "unexpected Finnhub news shape")
    out = [
        NewsItem(id=item_id(r["url"]), title=clean(r.get("headline")), url=r["url"], publisher=r.get("source") or None,
                 published=float(r["datetime"]) if r.get("datetime") else None, summary=clean(r.get("summary")) or None,
                 source=source)
        for r in rows if isinstance(r, dict) and _https(r.get("url")) and r.get("headline")
    ]
    return merge(out)[:MAX_ITEMS]


def _iso(s: str | None) -> float | None:
    try:
        return datetime.fromisoformat(s or "").astimezone(UTC).timestamp()
    except ValueError:
        return None


def alpaca_news(body: Any, source: str) -> list[NewsItem]:
    """Alpaca /v1beta1/news: {"news": [{headline, url, source, created_at (ISO), summary, symbols}]}. `content` is ignored."""
    if not isinstance(body, dict) or not isinstance(body.get("news"), list):
        raise ProviderError("unavailable", "unexpected Alpaca news shape")
    out = [
        NewsItem(id=item_id(r["url"]), title=clean(r.get("headline")), url=r["url"], publisher=r.get("source") or None,
                 published=_iso(r.get("created_at")), summary=clean(r.get("summary")) or None, source=source)
        for r in body["news"] if isinstance(r, dict) and _https(r.get("url")) and r.get("headline")
    ]
    return merge(out)[:MAX_ITEMS]


def finnhub_ratings(symbol: str, rows: Any, source: str) -> dict:
    """ANR fallback: Finnhub /stock/recommendation (monthly analyst counts). No targets or firm-level changes."""
    if not isinstance(rows, list) or not rows:
        raise ProviderError("not_found", "no recommendation trend")
    rows = sorted((r for r in rows if isinstance(r, dict)), key=lambda r: r.get("period") or "", reverse=True)
    mix = [{"period": r.get("period"), "strong_buy": r.get("strongBuy"), "buy": r.get("buy"), "hold": r.get("hold"),
            "sell": r.get("sell"), "strong_sell": r.get("strongSell")} for r in rows[:6]]
    cur = mix[0]
    counts = [cur[k] or 0 for k in ("strong_buy", "buy", "hold", "sell", "strong_sell")]
    n = sum(counts)
    mean = sum(c * w for c, w in zip(counts, (1, 2, 3, 4, 5))) / n if n else None
    return payload(
        symbol, f"ANR {symbol} · ANALYST RATINGS",
        [head("ANALYSTS", str(n) if n else None, n or None),
         head("MEAN RATING", f"{mean:.2f}" if mean is not None else None, mean)],
        [section("trend", "RECOMMENDATION MIX (ANALYSTS)",
                 [col("period", "MONTH", "date", 10), col("strong_buy", "STRONG BUY", "int"), col("buy", "BUY", "int"),
                  col("hold", "HOLD", "int"), col("sell", "SELL", "int"), col("strong_sell", "STRONG SELL", "int")], mix)],
        ["FINNHUB RECOMMENDATION TREND ONLY: PRICE TARGETS AND FIRM-LEVEL CHANGES NEED YAHOO, WHICH DID NOT ANSWER",
         "MEAN RATING: 1 STRONG BUY TO 5 STRONG SELL, COMPUTED HERE FROM THE LATEST MONTH'S COUNTS"], source)


def finnhub_surprises(symbol: str, rows: Any, source: str) -> dict:
    """EEO fallback: Finnhub /stock/earnings (last four quarters, actual vs estimate). No estimate trend or revisions."""
    if not isinstance(rows, list) or not rows:
        raise ProviderError("not_found", "no earnings surprises")
    sur = []
    for r in sorted((r for r in rows if isinstance(r, dict)), key=lambda r: r.get("period") or "", reverse=True):
        pct = r.get("surprisePercent")
        sur.append({"quarter": r.get("period"), "actual": r.get("actual"), "estimate": r.get("estimate"),
                    "diff": r.get("surprise"), "surprise": pct / 100 if isinstance(pct, (int, float)) else None})
    beats = sum(1 for r in sur if (r["diff"] or 0) > 0)
    return payload(
        symbol, f"EEO {symbol} · REVISIONS AND SURPRISES",
        [head("BEATS IN LAST QUARTERS", f"{beats} OF {len(sur)}", beats)],
        [section("surprises", "EPS SURPRISES",
                 [col("quarter", "QUARTER", "date", 10), col("actual", "ACTUAL", "num"), col("estimate", "ESTIMATE", "num"),
                  col("diff", "DIFF", "num"), col("surprise", "SURPRISE", "pct")], sur)],
        ["FINNHUB EPS SURPRISES ONLY: THE ESTIMATE TREND AND REVISION COUNTS NEED YAHOO, WHICH DID NOT ANSWER"], source)
