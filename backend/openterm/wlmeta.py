"""Watchlist colour flags and section headers (Phase 22), the pure part: what may be stored and how it is cleaned up.

A watchlist is stored as a plain list of symbols (table `watchlists`). Flags and sections are EXTRA information about that list,
kept apart in the `kv` table under the key `wlmeta:<LIST NAME>` so no schema migration is needed and the list itself is untouched.
The stored value is JSON:

    {"flags": {"AAPL": "RED", "JPM": "GREEN"},            one colour per symbol (a symbol with no flag is simply absent)
     "sections": [{"before": "JPM", "title": "Banks"}]}   a header row shown just above the symbol `before`

This module has no database code (that lives in `userdata.py`, next to the other watchlist methods) so that it can be unit tested
without one, and so `userdata.py` can import it without a circular import. Errors are `WlMetaError`; the caller turns them into the
API's `bad_request` answer. The frontend keeps its own copy of the colour list (`functions/wlFlags.ts`), pinned equal by
`tests/test_ts_mirrors.py`.
"""

from __future__ import annotations

from .idents import STORED_SYMBOL_RE
from .symbols import resolve


class WlMetaError(Exception):
    """The document is not storable (the message is shown to the user as the API's `bad_request` text)."""


COLORS = ("RED", "ORANGE", "YELLOW", "GREEN", "BLUE", "PURPLE", "GREY")
MAX_SECTIONS = 50  # a list is at most 500 symbols (userdata.MAX_WATCHLIST); 50 headers is already a header per ten rows
MAX_TITLE = 40  # characters of a section title
FIELDS = {"flags", "sections"}  # anything else in the document is refused, never silently dropped


def _symbol(raw: object, what: str) -> str:
    """A canonical stored symbol (aliases resolved like the command line does), or a WlMetaError naming the field."""
    if not isinstance(raw, str):
        raise WlMetaError(f"{what}: SYMBOL MUST BE TEXT")
    sym = resolve(raw)
    if not STORED_SYMBOL_RE.match(sym):
        raise WlMetaError(f"{what}: BAD SYMBOL {raw[:24]}")
    return sym


def validate(raw: object) -> dict:
    """The cleaned document `{"flags": {...}, "sections": [...]}`, or a WlMetaError saying what is wrong. Strict on purpose:
    an unknown field, colour or key is an error (a typo like `colour` would otherwise be lost without a word)."""
    if not isinstance(raw, dict):
        raise WlMetaError("META MUST BE AN OBJECT")
    extra = sorted(set(raw) - FIELDS)
    if extra:
        raise WlMetaError(f"UNKNOWN FIELD {extra[0]}: ONLY flags AND sections")
    flags_in, sections_in = raw.get("flags", {}), raw.get("sections", [])
    if not isinstance(flags_in, dict):
        raise WlMetaError("flags MUST BE AN OBJECT OF SYMBOL: COLOUR")
    if not isinstance(sections_in, list):
        raise WlMetaError("sections MUST BE A LIST")

    flags: dict[str, str] = {}
    for key, colour in flags_in.items():
        sym = _symbol(key, "flags")
        if colour not in COLORS:
            raise WlMetaError(f"flags: BAD COLOUR {str(colour)[:12]} FOR {sym}: USE {' '.join(COLORS)}")
        flags[sym] = colour

    if len(sections_in) > MAX_SECTIONS:
        raise WlMetaError(f"AT MOST {MAX_SECTIONS} SECTIONS")
    sections: list[dict] = []
    for item in sections_in:
        if not isinstance(item, dict) or set(item) != {"before", "title"}:
            raise WlMetaError('EACH SECTION IS {"before": SYMBOL, "title": TEXT}')
        before = _symbol(item["before"], "sections")
        title = item["title"]
        if not isinstance(title, str) or not title.strip() or len(title.strip()) > MAX_TITLE or not title.isprintable():
            raise WlMetaError(f"SECTION TITLE: 1-{MAX_TITLE} PRINTABLE CHARACTERS")
        title = title.strip()
        if any(s["before"] == before for s in sections):
            raise WlMetaError(f"TWO SECTIONS BEFORE {before}")
        if any(s["title"].casefold() == title.casefold() for s in sections):
            raise WlMetaError(f"TWO SECTIONS TITLED {title}")
        sections.append({"before": before, "title": title})
    return {"flags": flags, "sections": sections}


def members_error(meta: dict, symbols: list[str]) -> str | None:
    """The first symbol that `meta` names but the list does not hold (the flag or section would point at nothing), else None."""
    have = set(symbols)
    for sym in [*meta["flags"], *(s["before"] for s in meta["sections"])]:
        if sym not in have:
            return sym
    return None


def prune(meta: dict, symbols: list[str]) -> dict:
    """`meta` without the flags and sections of symbols that have left the list since it was saved (a removed symbol must not
    leave a flag or a header floating). Nothing is deleted from storage: undoing the removal brings them back."""
    have = set(symbols)
    return {
        "flags": {s: c for s, c in meta["flags"].items() if s in have},
        "sections": [s for s in meta["sections"] if s["before"] in have],
    }


def is_empty(meta: dict) -> bool:
    return not meta["flags"] and not meta["sections"]
