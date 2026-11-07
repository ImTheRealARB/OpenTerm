"""Identifier validation: the one place that says what a symbol, a stored name or a run id may look like (untangle B9).

Before this, `ai/routes.py`, `ai/routes_run.py` and `ai/store.py` each held an identical symbol regex, and `userdata.py` held the
stored-data pair that five modules imported from it. Two symbol rules exist ON PURPOSE, so they have two names:

  AI_SYMBOL_RE      what an AI/thesis/filing API ARGUMENT may be: any case, 1-12 characters. The caller upper-cases it or the
                    data layer resolves it. NOTE: it ends in `$`, which also lets one trailing newline through ("AAPL\\n").
                    That is how it has always behaved and is kept as is; the stored pair below uses `\\Z`, which does not.
  STORED_SYMBOL_RE  what may be SAVED in the user database (portfolios, drawings, news alerts, world routes): upper case only,
                    up to 24 characters, starts with a letter, digit or ^.

Keep this file free of imports from the app: it is imported by the data layer, the AI layer and the store layer alike.
Python's `re` is the only dependency.
"""

import re

AI_SYMBOL_RE = re.compile(r"^[A-Za-z0-9.^=\-]{1,12}$")
STORED_SYMBOL_RE = re.compile(r"^[A-Z0-9^][A-Z0-9^=.&-]{0,23}\Z")
# A stored name (layout, portfolio, watchlist): upper case letters and digits, `_ . -`, up to 32 characters.
STORED_NAME_RE = re.compile(r"^[A-Z0-9][A-Z0-9_.-]{0,31}\Z")
# An AI run or thesis id: 12 lowercase hex characters (BT run ids are 16 and are checked elsewhere).
RUN_ID_RE = re.compile(r"^[0-9a-f]{12}$")
