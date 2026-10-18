"""CN: company news merged from every keyless-or-keyed source, one row per headline with a keyword score (spec E, K, L).

Pure: the service passes in the items each source returned, the sources that failed and the keyed sources that lack a key.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ..models import NewsItem
from ..providers.news import merge
from . import sentiment
from .table import col, head, payload, section


def stamp(epoch: float | None) -> str | None:
    return datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%d %H:%M") if epoch else None


def short_source(source: str) -> str:
    """`yahoo_rss:fixture` -> `yahoo_rss`. The envelope keeps the fixture tag; a row only names its feed."""
    return source.split(":", 1)[0]


def cn_payload(symbol: str, items: list[NewsItem], failed: list[str], key_required: list[dict], answered: list[str]) -> dict:
    rows = []
    for i in merge(items):
        s = sentiment.score(i.title)
        rows.append({"time": stamp(i.published), "label": sentiment.label(s), "score": s, "source": short_source(i.source),
                     "publisher": i.publisher, "headline": i.title, "url": i.url})
    pos, neg = sum(r["label"] == "POS" for r in rows), sum(r["label"] == "NEG" for r in rows)
    net = sum(r["score"] for r in rows)
    notes = [sentiment.NOTE, "HEADLINES AND LINKS ONLY; ARTICLES OPEN ON THE PUBLISHER'S SITE",
             "GDELT IS LEFT OUT (SLOW, ONE CALL PER 5 S): USE N <SECURITY> FOR IT"]
    if failed:
        notes.append("DID NOT ANSWER: " + ", ".join(n.upper() for n in failed))
    return payload(
        symbol, f"CN {symbol} · COMPANY NEWS",
        [head("HEADLINES", str(len(rows)), len(rows)), head("POS / NEG", f"{pos} / {neg}"),
         head("NET KEYWORD SCORE", f"{net:+d}", net), head("SOURCES", ", ".join(sorted(answered)) or None)],
        [section("news", "HEADLINES",
                 [col("time", "TIME (UTC)", "text", 16), col("label", "SCORE", "text", 5), col("source", "FEED", "text", 10),
                  col("publisher", "PUBLISHER", "text", 16), col("headline", "HEADLINE", "text", 90)], rows,
                 "KEYWORD SCORE, NOT A MODEL")],
        notes, ", ".join(sorted(answered)) or None, key_required)
