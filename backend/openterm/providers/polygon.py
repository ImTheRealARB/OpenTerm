"""Polygon.io, now Massive (free key): US quotes (the previous session's close), daily and minute candles, symbol search.

Free plan (per provider docs, not verified here): 5 requests a minute, end-of-day data, about 2 years of history. So the quote is the
PREVIOUS SESSION'S bar, not a live price: `market_time` is that session's start and the panel shows its age. The key travels in the
`Authorization: Bearer` header, never the URL. The host is api.massive.com (the rebranded Polygon API; the old api.polygon.io host is
documented to keep working, but only the new one was recorded). Errors are HTTP 401 `{"status": "ERROR", "error": "Unknown API Key"}`
(a real recording), 403 `NOT_AUTHORIZED` for data outside the plan, 429 for the minute limit.

Minute candles include pre-market and after-hours bars (04:00 to 20:00 New York), unlike Yahoo's regular-session bars.

Fixtures: keytest_polygon_401 is a REAL answer to a made-up key (no account). There is no public demo key, so every success shape
(`polygon_docshape_*`) is built from the documentation and says NOT A RECORDING inside the file.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

from .. import errkinds as K
from ..models import Bars, Quote, SearchHit
from ..ranges import range_days
from .base import HISTORY, QUOTES, SEARCH, ProviderError
from .keyed import KeyedProvider
from .keyed_market import SESSIONS, depth_days, fnum, inum, trim_sessions

BASE = "https://api.massive.com"
HISTORY_DAYS = 730  # the free plan's two years
MAX_BARS = 50000
SPANS = {"1m": (1, "minute"), "5m": (5, "minute"), "15m": (15, "minute"), "30m": (30, "minute"), "60m": (60, "minute"),
         "1d": (1, "day"), "1wk": (1, "week"), "1mo": (1, "month")}
# Bars in one 04:00-20:00 New York day (pre-market and after-hours included), to size a request and declare `intraday_days`.
BARS_EXTENDED = {"1m": 960, "5m": 192, "15m": 64, "30m": 32, "60m": 16}
NY = ZoneInfo("America/New_York")
_US = re.compile(r"^[A-Z]{1,5}(-[A-Z])?$")
_US_EXCHANGES = {"XNAS", "XNYS", "ARCX", "XASE", "BATS", "IEXG", "XNGS", "XNMS", "XNCM"}


def pg_symbol(symbol: str) -> str | None:
    """US tickers; a share class BRK-B is written BRK.B by Polygon. Anything with an exchange suffix is not requested."""
    s = symbol.strip().upper()
    if not _US.match(s):
        return None
    return s.replace("-", ".")


class PolygonProvider(KeyedProvider):
    name = "polygon"
    label = "Polygon / Massive (free key)"
    capabilities = frozenset({QUOTES, HISTORY, SEARCH})
    markets = "US shares and ETFs: previous-session quote, daily to minute candles (about 2 years), symbol search"
    terms = ("Free key (POLYGON_API_KEY): 5 requests a minute, end-of-day data, about 2 years of history (per provider docs, not verified here). "
             "The quote is the previous session's bar. Real-time and snapshots need a paid plan.")
    rate = (5 / 60, 2)  # 5 requests a minute
    max_wait = 2.0
    timeout = 10.0
    key_name = "POLYGON_API_KEY"
    headers: ClassVar[dict[str, str]] = {"User-Agent": "OpenTerm/0.1", "Accept": "application/json"}
    intraday_days: ClassVar[dict[str, int]] = {i: min(HISTORY_DAYS, depth_days(n, MAX_BARS)) for i, n in BARS_EXTENDED.items()}
    msg_rate_limited = "Polygon request limit reached (5 a minute on a free key)"
    msg_refused = "Polygon refused the key ({code})"

    def supports(self, capability: str, symbol: str | None = None) -> bool:
        return super().supports(capability, symbol) and (symbol is None or capability == SEARCH or pg_symbol(symbol) is not None)

    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._key}"}  # a header, never the URL

    def _check_status(self, r: Any) -> None:
        if r.status_code == 403:  # NOT_AUTHORIZED: the key is fine, the data is not in its plan (not a strike, not a key error)
            raise ProviderError(K.UNSUPPORTED, "KEY PLAN: this data needs a paid Polygon plan")
        if r.status_code == 404:
            raise ProviderError(K.NOT_FOUND, "Polygon has no such symbol")
        super()._check_status(r)

    async def _api(self, path: str, params: dict[str, Any] | None = None) -> dict:
        body = await self.get_json(f"{BASE}{path}", params or {})
        if not isinstance(body, dict):
            raise ProviderError(K.UNAVAILABLE, "Polygon sent an unexpected answer")
        if str(body.get("status", "")).upper() == "ERROR":
            raise ProviderError(K.UNAVAILABLE, "Polygon reported an error")  # fixed text: the body is not copied
        return body

    # --- quotes ---------------------------------------------------------------------------------------------------------------
    async def quotes(self, symbols: list[str]) -> list[Quote]:
        out: list[Quote] = []
        first: ProviderError | None = None
        for s in symbols[:5]:  # one request each, 5 a minute
            sym = pg_symbol(s)
            if sym is None:
                continue
            try:
                body = await self._api(f"/v2/aggs/ticker/{sym}/prev", {"adjusted": "true"})
            except ProviderError as e:
                if e.kind != K.NOT_FOUND:
                    first = first or e
                continue
            rows = body.get("results") or []
            if not rows or fnum(rows[0].get("c")) is None:
                continue
            b = rows[0]
            t = fnum(b.get("t"))
            out.append(Quote(symbol=s, currency="USD", price=fnum(b.get("c")), open=fnum(b.get("o")), high=fnum(b.get("h")),
                             low=fnum(b.get("l")), volume=inum(b.get("v")), market_time=int(t / 1000) if t else None,
                             source=self.source, as_of=self.now()))
        if not out:
            raise first or ProviderError(K.NOT_FOUND, "no quote")
        return out

    # --- history --------------------------------------------------------------------------------------------------------------
    async def history(self, symbol: str, range_: str, interval: str) -> Bars:
        sym = pg_symbol(symbol)
        span = SPANS.get(interval)
        if sym is None or span is None:
            raise ProviderError(K.UNSUPPORTED, f"polygon: no {interval} candles for {symbol}")
        days = range_days(range_)
        intraday = interval in BARS_EXTENDED
        limit = self.intraday_days[interval] if intraday else HISTORY_DAYS
        if days > limit:
            raise ProviderError(K.DEPTH, f"{interval} candles reach back {limit} days on a free Polygon key")
        today = datetime.now(UTC).date()
        window = {"1d": 5, "5d": 12}.get(range_, days)  # a few spare days, cut to N sessions below
        start = today - timedelta(days=window)
        body = await self._api(f"/v2/aggs/ticker/{sym}/range/{span[0]}/{span[1]}/{start.isoformat()}/{today.isoformat()}",
                               {"adjusted": "true", "sort": "asc", "limit": MAX_BARS})
        rows = [r for r in body.get("results") or [] if fnum(r.get("t")) is not None]
        if not rows:
            raise ProviderError(K.NOT_FOUND, "no rows")
        if intraday and range_ in SESSIONS:
            pairs = [(int(r["t"] // 1000), datetime.fromtimestamp(r["t"] / 1000, NY).date().isoformat()) for r in rows]
            rows = rows[trim_sessions(pairs, SESSIONS[range_]):]
        return Bars.model_construct(
            symbol=symbol, range=range_, interval=interval, currency="USD", exchange=None, tz="America/New_York" if intraday else None,
            t=[int(r["t"] // 1000) for r in rows], o=[fnum(r.get("o")) for r in rows], h=[fnum(r.get("h")) for r in rows],
            l=[fnum(r.get("l")) for r in rows], c=[fnum(r.get("c")) for r in rows], v=[inum(r.get("v")) for r in rows],
            source=self.source, as_of=self.now(),
        )

    # --- search ---------------------------------------------------------------------------------------------------------------
    async def search(self, query: str) -> list[SearchHit]:
        body = await self._api("/v3/reference/tickers", {"search": query.strip(), "market": "stocks", "active": "true", "limit": 15})
        hits = []
        for d in body.get("results") or []:
            if d.get("primary_exchange") not in _US_EXCHANGES or not d.get("ticker"):
                continue  # an exchange OpenTerm has no Yahoo suffix for would resolve to the wrong market
            hits.append(SearchHit(symbol=str(d["ticker"]).replace(".", "-"), name=d.get("name"), exchange=d.get("primary_exchange"),
                                  type=d.get("type"), source=self.source))
        if not hits:
            raise ProviderError(K.NOT_FOUND, "no matches")
        return hits

    async def probe(self) -> None:
        await self._api("/v2/aggs/ticker/AAPL/prev", {"adjusted": "true"})
