"""Pure parsers for Marketaux (`GET https://api.marketaux.com/v1/news/all`). No network.

Shapes come from the official docs (marketaux.com/documentation), NOT from a recording (no API key was available):
  success: {"meta": {"found": int, "returned": int, "limit": int, "page": int},
            "data": [{"uuid", "title", "description", "keywords", "snippet", "url", "image_url", "language",
                      "published_at" (UTC ISO text), "source" (a domain), "relevance_score" (number or null),
                      "entities": [{"symbol", "name", "exchange", "country", "type", "industry", "match_score",
                                    "sentiment_score" (-1 to +1), "highlights": [...]}], "similar": []}]}
  error:   {"error": {"code": "invalid_api_token", "message": "..."}} with HTTP 400/401/402/403/404/429/500/503.
Article bodies are never read or kept: headline, teaser, link and the sentiment number only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ..models import NewsItem
from .base import ProviderError
from .news import clean, item_id, merge

MAX_ITEMS = 80

# error code in the body -> ProviderError kind. 402 is "plan usage limit reached", 429 is "too many requests in 60 seconds".
ERROR_KINDS = {
    "invalid_api_token": "key_required",
    "endpoint_access_restricted": "key_required",
    "usage_limit_reached": "rate_limited",
    "rate_limit_reached": "rate_limited",
    "resource_not_found": "not_found",
    "malformed_parameters": "unavailable",
}


def error_of(status: int, body: Any) -> ProviderError | None:
    """The ProviderError for a failed answer (HTTP status plus the documented error body), or None when the answer is a success."""
    if status < 400:
        return None
    err = body.get("error") if isinstance(body, dict) else None
    code = err.get("code") if isinstance(err, dict) else None
    kind = ERROR_KINDS.get(code or "")
    if kind is None:  # an HTTP status without a recognised body: go by the status
        kind = {401: "key_required", 402: "rate_limited", 429: "rate_limited", 404: "not_found"}.get(status, "unavailable")
    return ProviderError(kind, f"Marketaux {code or 'HTTP ' + str(status)}")


def _https(url: Any) -> bool:
    return isinstance(url, str) and url.startswith(("https://", "http://"))


def _published(text: Any) -> float | None:
    if not isinstance(text, str):
        return None
    try:
        return datetime.fromisoformat(text).astimezone(UTC).timestamp()  # "...Z" parses on Python 3.11+
    except ValueError:
        return None


def sentiment_of(entities: Any, symbol: str | None) -> float | None:
    """Mean sentiment_score (-1 to +1) of the entities the article is about, 3 decimals; None when the article has none.

    With a symbol, only that company's score counts (an article about Tesla and Ford has a different tone for each).
    Without one (market news), every identified entity counts.
    """
    if not isinstance(entities, list):
        return None
    scores = [e["sentiment_score"] for e in entities
              if isinstance(e, dict) and isinstance(e.get("sentiment_score"), (int, float))
              and (symbol is None or str(e.get("symbol", "")).upper() == symbol.upper())]
    return round(sum(scores) / len(scores), 3) if scores else None


def parse_news(body: Any, source: str, symbol: str | None = None) -> list[NewsItem]:
    if not isinstance(body, dict) or not isinstance(body.get("data"), list):
        raise ProviderError("unavailable", "unexpected Marketaux news shape")
    out = [
        NewsItem(id=item_id(r["url"]), title=clean(r.get("title")), url=r["url"], publisher=r.get("source") or None,
                 published=_published(r.get("published_at")), summary=clean(r.get("description") or r.get("snippet")) or None,
                 sentiment=sentiment_of(r.get("entities"), symbol), source=source)
        for r in body["data"] if isinstance(r, dict) and _https(r.get("url")) and r.get("title")
    ]
    return merge(out)[:MAX_ITEMS]
