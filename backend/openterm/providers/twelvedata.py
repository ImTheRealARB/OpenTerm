"""Twelve Data (free key): quotes, daily and intraday history, symbol search, and some non-US exchanges.

Free plan (per provider docs, not verified here): 8 API credits a minute and 800 a day; every quote or time-series call costs 1 credit per symbol, so a quote
for N symbols is N credits. A time series returns at most 5000 bars per call, which is where `intraday_days` comes from. The key
travels in the `Authorization: apikey ...` header (documented, recommended), never in the URL. Errors arrive as JSON
{"code", "message", "status": "error"} and are mapped here whatever the HTTP status is. Non-US symbols are sent as the bare ticker plus
an ISO market code (RELIANCE.NS -> RELIANCE, mic_code XNSE). Indices, futures and crypto pairs are not requested (free-plan coverage
differs and the keyless sources serve them); FX pairs go as EUR/USD.

Fixtures: twelvedata_real_* are REAL answers recorded with Twelve Data's public `demo` key (scripts/record_providers.py).
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

import httpx

from .. import errkinds as K
from ..models import Bars, Quote, SearchHit
from ..ranges import range_days
from .base import HISTORY, QUOTES, SEARCH, ProviderError
from .keyed import KeyedProvider
from .keyed_market import (
    BARS_PER_SESSION,
    MIC_SUFFIX,
    SESSIONS,
    SUFFIX_MIC,
    US_MICS,
    depth_days,
    fnum,
    inum,
    trim_sessions,
)

BASE = "https://api.twelvedata.com"
MAX_BARS = 5000
MAX_QUOTE_SYMBOLS = 8  # one credit each and 8 credits a minute on the free plan
INTERVALS = {"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min", "60m": "1h", "1d": "1day", "1wk": "1week", "1mo": "1month"}
_SUFFIXED = re.compile(r"^([A-Z0-9&]{1,12})\.([A-Z]{1,2})$")
_CLASS = re.compile(r"^([A-Z]{1,4})-([A-Z])$")  # BRK-B (Yahoo) -> BRK.B (Twelve Data)
_US = re.compile(r"^[A-Z]{1,5}$")
_FX = re.compile(r"^([A-Z]{3})([A-Z]{3})=X$")


def td_symbol(symbol: str) -> tuple[str, dict[str, str]] | None:
    """OpenTerm (Yahoo-style) symbol -> (Twelve Data symbol, extra query params), or None when it is not requested from Twelve Data."""
    s = symbol.strip().upper()
    if m := _FX.match(s):
        return f"{m.group(1)}/{m.group(2)}", {}
    if m := _SUFFIXED.match(s):
        mic = SUFFIX_MIC.get(m.group(2))
        return (m.group(1), {"mic_code": mic}) if mic else None
    if m := _CLASS.match(s):
        return f"{m.group(1)}.{m.group(2)}", {}
    return (s, {}) if _US.match(s) else None


class TwelveDataProvider(KeyedProvider):
    name = "twelvedata"
    label = "Twelve Data (free key)"
    capabilities = frozenset({QUOTES, HISTORY, SEARCH})
    markets = "US shares and ETFs, FX pairs, and shares on NSE, BSE, LSE, TSX, HKEX, TSE, Xetra, Euronext and other non-US exchanges"
    terms = ("Free key (TWELVEDATA_API_KEY): 8 credits a minute, 800 a day, 1 credit per symbol per call; 5000 bars per call. "
             "Prices are as the plan delivers them (free plans can be delayed). Some data and exchanges need a paid plan.")
    rate = (8 / 60, 8)  # 8 credits a minute
    max_wait = 2.0
    timeout = 10.0
    key_name = "TWELVEDATA_API_KEY"
    headers: ClassVar[dict[str, str]] = {"User-Agent": "OpenTerm/0.1", "Accept": "application/json"}
    intraday_days: ClassVar[dict[str, int]] = {i: depth_days(BARS_PER_SESSION[i], MAX_BARS) for i in ("1m", "5m", "15m", "30m", "60m")}
    msg_rate_limited = "429 from Twelve Data"
    msg_refused = "Twelve Data refused the key ({code})"

    def supports(self, capability: str, symbol: str | None = None) -> bool:
        return super().supports(capability, symbol) and (symbol is None or capability == SEARCH or td_symbol(symbol) is not None)

    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"apikey {self._key}"}  # a header, never the URL

    def _check_status(self, r: httpx.Response) -> None:
        try:
            body = r.json()
        except ValueError:
            body = None
        if isinstance(body, dict) and body.get("status") == "error":
            raise self._error(int(fnum(body.get("code")) or r.status_code), str(body.get("message") or ""))
        super()._check_status(r)

    def _error(self, code: int, message: str) -> ProviderError:
        low = message.lower()
        if code == 401:
            return ProviderError(K.KEY_REQUIRED, "Twelve Data refused the key (401)")
        if code == 403:
            return ProviderError(K.UNSUPPORTED, "KEY PLAN: this data needs a paid Twelve Data plan")
        if code == 404 or (code == 400 and ("not found" in low or "symbol" in low)):
            return ProviderError(K.NOT_FOUND, "Twelve Data has no such symbol")
        if code == 429:
            return ProviderError(K.RATE_LIMITED, "Twelve Data credit limit reached (" + ("day" if "day" in low else "minute") + ")")
        return ProviderError(K.UNAVAILABLE, f"Twelve Data error {code}")

    async def _api(self, path: str, params: dict[str, Any]) -> Any:
        return await self.get_json(f"{BASE}/{path}", params)

    # --- quotes ---------------------------------------------------------------------------------------------------------------
    async def quotes(self, symbols: list[str]) -> list[Quote]:
        wanted = [(s, td_symbol(s)) for s in symbols[:MAX_QUOTE_SYMBOLS]]
        results = await asyncio.gather(*(self._quote(s, t) for s, t in wanted if t), return_exceptions=True)
        out = [r for r in results if isinstance(r, Quote)]
        if not out:
            errs = [r for r in results if isinstance(r, ProviderError) and r.kind != K.NOT_FOUND]
            if errs:
                raise errs[0]
            raise ProviderError(K.NOT_FOUND, "no quote")
        return out

    async def _quote(self, symbol: str, td: tuple[str, dict[str, str]]) -> Quote:
        d = await self._api("quote", {"symbol": td[0], **td[1]})
        price = fnum((d or {}).get("close"))
        if not isinstance(d, dict) or price is None:
            raise ProviderError(K.NOT_FOUND, "no quote")
        wk = d.get("fifty_two_week") or {}
        return Quote(
            symbol=symbol, name=d.get("name"), currency=d.get("currency"), exchange=d.get("exchange"), price=price,
            prev_close=fnum(d.get("previous_close")), change=fnum(d.get("change")), change_pct=fnum(d.get("percent_change")),
            open=fnum(d.get("open")), high=fnum(d.get("high")), low=fnum(d.get("low")), volume=inum(d.get("volume")),
            high_52w=fnum(wk.get("high")), low_52w=fnum(wk.get("low")), market_time=inum(d.get("timestamp")),
            source=self.source, as_of=self.now(),
        )

    # --- history --------------------------------------------------------------------------------------------------------------
    async def history(self, symbol: str, range_: str, interval: str) -> Bars:
        td = td_symbol(symbol)
        unit = INTERVALS.get(interval)
        if td is None or unit is None:
            raise ProviderError(K.UNSUPPORTED, f"twelvedata: no {interval} candles for {symbol}")
        days = range_days(range_)
        intraday = interval in BARS_PER_SESSION
        if intraday:
            limit = self.intraday_days.get(interval, 0)
            if days > limit:
                raise ProviderError(K.DEPTH, f"{interval} candles reach back {limit} days on Twelve Data (5000 bars per call)")
            sessions = SESSIONS.get(range_, 0)
            size = min(MAX_BARS, int((sessions + 2 if sessions else days * 5 / 7 + 2) * BARS_PER_SESSION[interval]) + 1)
        else:
            size = min(MAX_BARS, int(days * {"1d": 5 / 7, "1wk": 1 / 7, "1mo": 1 / 30}[interval]) + 5)
        params = {"symbol": td[0], "interval": unit, "outputsize": size, "order": "desc", **td[1]}
        if intraday:
            params["timezone"] = "UTC"
        body = await self._api("time_series", params)
        rows = (body or {}).get("values") if isinstance(body, dict) else None
        if not rows:
            raise ProviderError(K.NOT_FOUND, "no rows")
        meta = body.get("meta") or {}
        tzname = meta.get("exchange_timezone") or None
        pairs = []  # (epoch, session day, row), oldest first
        zone = ZoneInfo(tzname) if tzname else UTC
        for row in reversed(rows):
            t = _epoch(row.get("datetime"), intraday)
            if t is not None:
                pairs.append((t, datetime.fromtimestamp(t, zone).date().isoformat() if intraday else "", row))
        if intraday and range_ in SESSIONS:
            pairs = pairs[trim_sessions([(t, d) for t, d, _ in pairs], SESSIONS[range_]):]
        if not pairs:
            raise ProviderError(K.NOT_FOUND, "no rows")
        return Bars.model_construct(
            symbol=symbol, range=range_, interval=interval, currency=meta.get("currency"), exchange=meta.get("exchange"), tz=tzname,
            t=[t for t, _, _ in pairs], o=[fnum(r.get("open")) for _, _, r in pairs], h=[fnum(r.get("high")) for _, _, r in pairs],
            l=[fnum(r.get("low")) for _, _, r in pairs], c=[fnum(r.get("close")) for _, _, r in pairs],
            v=[inum(r.get("volume")) for _, _, r in pairs], source=self.source, as_of=self.now(),
        )

    # --- search ---------------------------------------------------------------------------------------------------------------
    async def search(self, query: str) -> list[SearchHit]:
        body = await self._api("symbol_search", {"symbol": query.strip(), "outputsize": 15})
        hits = []
        for d in (body or {}).get("data") or [] if isinstance(body, dict) else []:
            mic, sym = d.get("mic_code") or "", d.get("symbol")
            if not sym:
                continue
            if mic in US_MICS:
                out = str(sym).replace(".", "-")
            elif mic in MIC_SUFFIX:
                out = f"{sym}.{MIC_SUFFIX[mic]}"
            else:
                continue  # an exchange OpenTerm has no Yahoo suffix for: the symbol would resolve to the wrong market
            hits.append(SearchHit(symbol=out, name=d.get("instrument_name"), exchange=d.get("exchange"), type=d.get("instrument_type"),
                                  source=self.source))
        if not hits:
            raise ProviderError(K.NOT_FOUND, "no matches")
        return hits

    async def probe(self) -> None:
        await self._api("api_usage", {})


def _epoch(text: Any, intraday: bool) -> int | None:
    """'2026-11-10 15:15:00' (asked in UTC) or '2026-11-10' (midnight UTC, like the other daily sources) -> epoch seconds."""
    if not isinstance(text, str):
        return None
    try:
        dt = datetime.strptime(text, "%Y-%m-%d %H:%M:%S" if intraday else "%Y-%m-%d")
    except ValueError:
        try:
            dt = datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return None
    return int(dt.replace(tzinfo=UTC).timestamp())
