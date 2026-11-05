"""Shared bits of the four US government functions (USASP, FEDREG, FEC, CONGRESS). Pure: no network, no pandas.

Each function has its own parser module (`usaspending.py`, `fedreg.py`, `fec.py`, `congress.py`); they share one error class and a few tiny
helpers so the "answer is not the documented shape" failure looks the same everywhere (and is never turned into an empty table).
"""

from __future__ import annotations

from typing import Any

# The two api.data.gov keys (FEC, Congress.gov) come from the same signup page.
SIGNUP = "https://api.data.gov/signup/"


class UsGovError(Exception):
    """The user's words are unusable (`bad_request`) or the upstream answer is not the shape its documentation promises (`unavailable`)."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def clip(text: Any, limit: int) -> str:
    """One line of text: whitespace collapsed, cut to `limit` characters with an ellipsis. None / non-text becomes ''."""
    if not isinstance(text, str):
        return ""
    t = " ".join(text.split())
    return t if len(t) <= limit else t[: limit - 1].rstrip() + "…"


def num(v: Any) -> float | None:
    """A number from a JSON value, or None. Booleans are not numbers; text is not guessed at."""
    if isinstance(v, bool) or not isinstance(v, int | float):
        return None
    return float(v)


def text_or_none(v: Any) -> str | None:
    """A non-empty string, else None (JSON null and empty strings both mean 'not given')."""
    return v if isinstance(v, str) and v else None


def need_list(body: Any, key: str, what: str) -> list:
    """`body[key]` must be a list, else the answer is not what the docs say: fail loudly with `what` named."""
    if not isinstance(body, dict) or not isinstance(body.get(key), list):
        raise UsGovError("unavailable", f"{what}: UNEXPECTED ANSWER SHAPE (NO '{key}' LIST)")
    return body[key]
