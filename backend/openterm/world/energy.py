"""NRG: the energy board from FRED's keyless CSV (series FRED republishes from EIA and the Fed). Pure code: catalogue, rows, spread.

EIA's weekly stocks and production series (WCESTUS1, WCRFPUS2, ...) answer 404 on fredgraph.csv (probed 2026-10-18), so this board is prices only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime


@dataclass(frozen=True)
class Series:
    id: str
    alias: str
    label: str
    group: str
    unit: str
    freq: str
    stale_days: int  # older than this at the last observation = flagged STALE


DAILY, WEEKLY = "DAILY", "WEEKLY"
SERIES: tuple[Series, ...] = (
    Series("DCOILWTICO", "WTI", "WTI CRUDE, CUSHING", "CRUDE", "$/BBL", DAILY, 7),
    Series("DCOILBRENTEU", "BRENT", "BRENT CRUDE, EUROPE", "CRUDE", "$/BBL", DAILY, 7),
    Series("DHHNGSP", "HH", "HENRY HUB NATURAL GAS", "GAS", "$/MMBTU", DAILY, 7),
    Series("DGASNYH", "GASNY", "NY HARBOR CONVENTIONAL GASOLINE", "PRODUCTS", "$/GAL", DAILY, 7),
    Series("DGASUSGULF", "GASGC", "US GULF COAST CONVENTIONAL GASOLINE", "PRODUCTS", "$/GAL", DAILY, 7),
    Series("DDFUELNYH", "ULSD", "NY HARBOR ULTRA-LOW SULFUR DIESEL", "PRODUCTS", "$/GAL", DAILY, 7),
    Series("DHOILNYH", "HEAT", "NY HARBOR NO.2 HEATING OIL", "PRODUCTS", "$/GAL", DAILY, 7),
    Series("DJFUELUSGULF", "JET", "US GULF COAST KEROSENE JET FUEL", "PRODUCTS", "$/GAL", DAILY, 7),
    Series("DPROPANEMBTX", "PROPANE", "MONT BELVIEU PROPANE", "PRODUCTS", "$/GAL", DAILY, 7),
    Series("GASREGW", "GASRET", "US REGULAR GASOLINE, RETAIL", "RETAIL", "$/GAL", WEEKLY, 14),
    Series("GASDESW", "DIESELRET", "US DIESEL, RETAIL", "RETAIL", "$/GAL", WEEKLY, 14),
)
BY_KEY: dict[str, Series] = {k: s for s in SERIES for k in (s.alias, s.id)}
GROUPS = ("CRUDE", "GAS", "PRODUCTS", "RETAIL")
YEAR_DAYS = 366


def resolve(text: str) -> Series:
    key = text.strip().upper()
    s = BY_KEY.get(key)
    if s is None:
        raise ValueError(f"UNKNOWN ENERGY SERIES {key[:24]}. USE: {' '.join(x.alias for x in SERIES)}")
    return s


def _iso(epoch_s: float) -> str:
    return datetime.fromtimestamp(epoch_s, UTC).date().isoformat()


def _d(text: str) -> date:
    return date.fromisoformat(text[:10])


def make_row(s: Series, data: dict | None, today: date, error: str | None = None) -> dict:
    """One board row from a FRED series answer (`t` epoch seconds, `v` with None for missing days, `last_date`)."""
    row = {"id": s.id, "alias": s.alias, "label": s.label, "group": s.group, "unit": s.unit, "freq": s.freq,
           "last": None, "date": None, "chg": None, "pct": None, "lo": None, "hi": None, "pos": None, "n": 0, "stale": False, "error": error}
    if not data:
        row["error"] = error or "NO DATA"
        return row
    obs = [(t, v) for t, v in zip(data["t"], data["v"], strict=False) if v is not None]
    if not obs:
        row["error"] = "NO OBSERVATIONS IN RANGE"
        return row
    last_t, last = obs[-1]
    last_date = data.get("last_date") or _iso(last_t)
    window = [v for t, v in obs if last_t - t <= YEAR_DAYS * 86400]
    lo, hi = min(window), max(window)
    prev = obs[-2][1] if len(obs) > 1 else None
    row.update(last=last, date=last_date, n=len(window), lo=lo, hi=hi,
               chg=None if prev is None else last - prev,
               pct=None if not prev else (last - prev) / abs(prev) * 100.0,
               pos=None if hi <= lo else (last - lo) / (hi - lo) * 100.0,
               stale=(today - _d(last_date)).days > s.stale_days)
    return row


def spread(wti: dict | None, brent: dict | None) -> dict | None:
    """Brent minus WTI on the latest date both have a value (daily series skip different holidays)."""
    if not wti or not brent:
        return None
    a = {t: v for t, v in zip(wti["t"], wti["v"], strict=False) if v is not None}
    b = {t: v for t, v in zip(brent["t"], brent["v"], strict=False) if v is not None}
    common = sorted(set(a) & set(b))
    if not common:
        return None
    t = common[-1]
    return {"value": b[t] - a[t], "date": _iso(t), "label": "BRENT - WTI", "unit": "$/BBL"}
