"""Cache-key namespaces for the data service (untangle B12).

`DataService` keeps every answer in one cache (`cache.mem` in memory, SQLite behind it), keyed by a short string. The prefix says
what kind of answer it is, so two kinds can never collide. The strings used to be built by hand in `service.py` (seven places for
the quote key alone), in `main.py` and in `quant_routes.py`. They are built here, so a prefix or a format changes in ONE file.

Prefixes in use elsewhere (still built next to the code that owns the data, listed so nobody reuses one):
  p: profile   n: news   c: crypto board   s: search   fa: fil: own: hds: SEC facts, filings, insiders, holders
  fred: macro:q:  FRED series and search   ern: earnings day   peers: peers   w: world functions   <name>: others in their own modules
"""

from __future__ import annotations

from collections.abc import Iterable


def quote(symbol: str) -> str:
    """The latest quote for a resolved symbol. Ticks are folded into this entry (`DataService.apply_tick`)."""
    return f"q:{symbol}"


def history(symbol: str, range_: str, interval: str, gated: Iterable[str] = ()) -> str:
    """Price bars. `gated` names the key-gated sources that can answer right now (e.g. `["kite"]`); each adds `:<first letter>`,
    so adding a key (which changes who answers Indian symbols) never serves bars cached from the other source."""
    return f"h:{symbol}:{range_}:{interval}" + "".join(f":{name[0]}" for name in gated)


def quant(*parts: str) -> str:
    """Quant-route answers (`q:fundsectors:SPY`, `q:kenfrench`). Shares the `q:` prefix with quotes, as it always did; safe because
    `resolve()` upper-cases every symbol and these names are lower case, so the two can never meet."""
    return "q:" + ":".join(parts)
