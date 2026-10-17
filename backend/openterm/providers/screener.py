"""Phase 9: the US equity universe for EQS (Nasdaq.com stock screener) and peer lists for COMP (Yahoo).

The screener answers the whole US-listed universe (about 7,000 rows, 2.2 MB JSON) in one call, so it is fetched
once per TTL and filtered in the browser. The payload is columnar with sector / industry / country tables to keep
it small: each row is [symbol, name, last, chg, pct, volume, mcap, country_i, ipo_year, sector_i, industry_i].
"""

from typing import Any, ClassVar

from .base import Provider, ProviderError
from .nasdaq import num
from .yahoo import UA

SCREENER = "screener"
PEERS = "peers"

COLUMNS = ["symbol", "name", "last", "chg", "pct", "volume", "mcap", "country", "ipo", "sector", "industry"]


def _index(table: list[str], lookup: dict[str, int], value: str | None) -> int:
    v = (value or "").strip()
    i = lookup.get(v)
    if i is None:
        i = lookup[v] = len(table)
        table.append(v)
    return i


def screener_from_body(body: Any, source: str, as_of: float) -> dict:
    data = (body or {}).get("data") if isinstance(body, dict) else None
    raw = (data or {}).get("rows") or []
    sectors: list[str] = [""]
    industries: list[str] = [""]
    countries: list[str] = [""]
    lk_s, lk_i, lk_c = {"": 0}, {"": 0}, {"": 0}
    rows = []
    for r in raw:
        sym = (r.get("symbol") or "").strip().upper()
        if not sym:
            continue
        vol, cap, ipo = num(r.get("volume")), num(r.get("marketCap")), num(r.get("ipoyear"))
        rows.append([
            sym,
            " ".join((r.get("name") or "").split()),
            num(r.get("lastsale")),
            num(r.get("netchange")),
            num(r.get("pctchange")),
            int(vol) if vol is not None else None,
            # Nasdaq reports 0.00 for instruments without a market cap (funds, units, warrants).
            cap if cap else None,
            _index(countries, lk_c, r.get("country")),
            int(ipo) if ipo else None,
            _index(sectors, lk_s, r.get("sector")),
            _index(industries, lk_i, r.get("industry")),
        ])
    if not rows:
        raise ProviderError("not_found", "screener returned no rows")
    return {
        "columns": COLUMNS, "rows": rows, "sectors": sectors, "industries": industries, "countries": countries,
        "count": len(rows), "as_of_text": (data or {}).get("asOf"), "market": "US", "source": source, "as_of": as_of,
    }


class NasdaqScreenerProvider(Provider):
    name = "nasdaq_screener"
    label = "Nasdaq.com stock screener"
    capabilities = frozenset({SCREENER})
    markets = "US-listed stocks only (NASDAQ, NYSE, AMEX); one snapshot of the whole universe per fetch"
    terms = "Public website API; personal use. Prices delayed. Undocumented: may change."
    rate = (0.2, 2)
    max_wait = 1.0
    timeout = 20.0  # 2.2 MB answer, about 2-3 s measured from India
    headers: ClassVar[dict[str, str]] = {"User-Agent": UA, "Accept": "application/json, text/plain, */*"}

    async def screener(self) -> dict:
        body = await self.get_json(
            "https://api.nasdaq.com/api/screener/stocks", {"tableonly": "true", "download": "true"}
        )
        return screener_from_body(body, self.source, self.now())

    async def probe(self) -> None:
        # One row instead of the 2.2 MB universe (the scheduler probes a tripped provider every 30 s).
        body = await self.get_json("https://api.nasdaq.com/api/screener/stocks", {"tableonly": "true", "limit": 1})
        if not isinstance(body, dict) or not body.get("data"):
            raise ProviderError("unavailable", "probe returned no data")


def peers_from_body(body: Any, symbol: str) -> list[dict]:
    result = ((body or {}).get("finance") or {}).get("result") if isinstance(body, dict) else None
    for r in result or []:
        if str(r.get("symbol", "")).upper() != symbol.upper():
            continue
        return [
            {"symbol": str(p["symbol"]).upper(), "score": p.get("score")}
            for p in r.get("recommendedSymbols") or []
            if p.get("symbol")
        ]
    return []


class YahooPeersProvider(Provider):
    name = "yahoo_peers"
    label = "Yahoo Finance recommended symbols"
    capabilities = frozenset({PEERS})
    markets = "Global (any Yahoo symbol); about 5 'people also watch' symbols, not a strict industry peer set"
    terms = "Unofficial Yahoo Finance endpoint; personal use. May change without notice."
    rate = (2.0, 4)
    headers: ClassVar[dict[str, str]] = {"User-Agent": UA, "Accept": "application/json"}

    async def peers(self, symbol: str) -> dict:
        body = await self.get_json(f"https://query2.finance.yahoo.com/v6/finance/recommendationsbysymbol/{symbol}")
        out = peers_from_body(body, symbol)
        if not out:
            raise ProviderError("not_found", "no recommended symbols")
        return {"peers": out, "source": self.source}

    async def probe(self) -> None:
        await self.peers("AAPL")
