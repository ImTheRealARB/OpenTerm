"""The one spreadsheet-formula guard for every CSV the server writes (audit H-14).

Excel and Sheets run a cell that starts with = + - @ TAB or CR as a formula, so text from a provider (a company
name, a label) could run code on the reader's machine. The frontend has the same rule in `frontend/src/csvText.ts`.

Rule: a TEXT cell starting with one of those characters gets a leading apostrophe, unless the whole cell is a strict
plain number (so "-1.5" and "+3.4%" stay numbers). A real int / float is never touched. The old check only looked
one character after + or -, so "+1+cmd|..." passed.
"""

from __future__ import annotations

import re

_TRIGGER = ("=", "+", "-", "@", "\t", "\r")
# sign? digits with an optional fraction (or a bare fraction), optional exponent, optional percent sign. Nothing else.
_PLAIN_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?%?")


def neutralize(v):
    """Return `v`, with a leading apostrophe when it is text a spreadsheet would run as a formula."""
    if isinstance(v, str) and v.startswith(_TRIGGER) and _PLAIN_NUMBER.fullmatch(v) is None:
        return "'" + v
    return v
