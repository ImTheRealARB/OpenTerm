"""MA deal values: the amount a deal filing STATES in its own text. Pure.

Nothing here estimates a deal's size. A value is returned only when the filing prints one next to a deal word, and the sentence it came from is returned
with it, so the reader can check it. Two shapes are read:
  * a Schedule TO cover page: "Transaction Valuation ... $12,345,678" (the amount the offer is priced at, used to compute the SEC filing fee);
  * a sentence about the transaction that gives an amount in millions, billions or trillions beside a value word ("an all-cash transaction with an enterprise
    value of approximately $605 million", "aggregate consideration of approximately $4.3 billion").
A price per share ("$37.50 per share") is never a deal value. The first matching sentence wins: a filing with several figures (an enterprise value and an
equity value) shows the first, and the quote says which. Most filings state nothing: the answer is then None and the panel says NOT STATED.
"""

from __future__ import annotations

import html
import re
from typing import Any

MAX_TEXT = 1_500_000  # characters read from one filing; the value sentence is near the top of a press release or cover page
_SCALE = {"million": 1e6, "billion": 1e9, "trillion": 1e12}
_AMOUNT = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)\s*(million|billion|trillion)\b", re.IGNORECASE)
_VALUE_WORD = re.compile(
    r"(?:enterprise value|equity value|transaction value|aggregate (?:equity |cash |stock )?(?:value|consideration|purchase price)|total (?:transaction )?"
    r"(?:value|consideration)|purchase price|valued at|values [\w .&,'-]{1,60} at|consideration of)", re.IGNORECASE)
_DEAL_WORD = re.compile(r"transaction|acqui|merger|business combination|tender offer|purchase|takeover|buyout", re.IGNORECASE)
_NOT_A_DEAL = re.compile(r"\baverage\b|\bindustry\b|\bmarket (?:size|opportunity)\b", re.IGNORECASE)
_COVER = re.compile(r"transaction\s+valuation[^$]{0,120}\$\s?(\d[\d,]{3,}(?:\.\d+)?)", re.IGNORECASE)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"(])")


def to_text(raw: bytes | str) -> str:
    """An HTML (or plain) filing as one line of text: scripts and styles dropped, tags removed, entities decoded, spaces collapsed."""
    s = raw if isinstance(raw, str) else raw.decode("utf-8", "replace")
    s = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", s)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()[:MAX_TEXT]


def extract(text: str) -> dict[str, Any] | None:
    """{"usd", "quote", "kind"} for the first stated deal value in `text`, or None."""
    m = _COVER.search(text)
    if m:
        usd = float(m.group(1).replace(",", ""))
        if usd > 0:
            return {"usd": usd, "quote": text[max(0, m.start() - 20): m.end() + 40].strip(), "kind": "cover page"}
    for sentence in _SENTENCE_END.split(text):
        if len(sentence) > 1200 or not _DEAL_WORD.search(sentence) or _NOT_A_DEAL.search(sentence):
            continue
        for a in _AMOUNT.finditer(sentence):
            if _VALUE_WORD.search(sentence[max(0, a.start() - 90): a.start()]):
                usd = float(a.group(1).replace(",", "")) * _SCALE[a.group(2).lower()]
                return {"usd": usd, "quote": sentence.strip()[:300], "kind": "sentence"}
    return None


def money(usd: float | None) -> str | None:
    """605000000 -> '$605M', 4.3e9 -> '$4.30B'."""
    if usd is None:
        return None
    if usd >= 1e12:
        return f"${usd / 1e12:.2f}T"
    if usd >= 1e9:
        return f"${usd / 1e9:.2f}B"
    if usd >= 1e6:
        return f"${usd / 1e6:.0f}M"
    return f"${usd:,.0f}"


ALLOWED_PREFIX = "https://www.sec.gov/Archives/edgar/data/"


def check_url(url: str) -> str:
    """Only SEC filing documents may be fetched on a client's word (no other host, no path tricks). Raises ValueError otherwise."""
    if not url.startswith(ALLOWED_PREFIX) or ".." in url or "#" in url or len(url) > 300 or any(c.isspace() for c in url):
        raise ValueError("ONLY A SEC FILING DOCUMENT (WWW.SEC.GOV/ARCHIVES/EDGAR/DATA/...) CAN BE READ")
    return url
