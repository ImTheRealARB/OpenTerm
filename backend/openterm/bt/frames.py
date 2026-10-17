"""Bar frames for the engine (worker-side, pandas). One rule everywhere, so recorded fixtures, the router's `Bars`
and Vibe's cross-check script all give the identical input:

- one row per exchange-local trading day (tz-naive DatetimeIndex at midnight), sorted, duplicates keep the last;
- columns open, high, low, close, volume, and adj_close when the source has it;
- rows with any missing open/high/low/close are dropped (never filled).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

COLUMNS = ["open", "high", "low", "close", "volume"]


def _finish(df: pd.DataFrame) -> pd.DataFrame:
    df = df.dropna(subset=["open", "high", "low", "close"])
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df.index.name = None
    return df


def from_yahoo_chart(body: dict) -> pd.DataFrame:
    """Raw Yahoo v8 chart JSON (as recorded): local day = UTC timestamp + meta.gmtoffset."""
    res = body["chart"]["result"][0]
    off = res["meta"].get("gmtoffset", 0) or 0
    q = res["indicators"]["quote"][0]
    idx = pd.to_datetime(np.asarray(res["timestamp"], dtype="int64") + off, unit="s").floor("D")
    df = pd.DataFrame({k: q.get(k) for k in COLUMNS}, index=idx, dtype=float)
    adj = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose")
    if adj is not None:
        df["adj_close"] = np.asarray(adj, dtype=float)
    return _finish(df)


def from_bars(bars: dict) -> pd.DataFrame:
    """The router's `Bars` dict (t = UTC epoch seconds, tz = exchange zone): local day from the zone."""
    t = pd.to_datetime(np.asarray(bars["t"], dtype="int64"), unit="s", utc=True)
    if bars.get("tz"):
        t = t.tz_convert(bars["tz"])
    idx = t.tz_localize(None).floor("D")
    df = pd.DataFrame({"open": bars["o"], "high": bars["h"], "low": bars["l"], "close": bars["c"],
                       "volume": bars["v"]}, index=idx, dtype=float)
    if bars.get("adj") is not None:
        df["adj_close"] = np.asarray(bars["adj"], dtype=float)
    return _finish(df)


def adjusted(df: pd.DataFrame) -> pd.DataFrame:
    """OHLC scaled by adj_close / close (dividends and splits); unchanged when the source has no adj_close."""
    if "adj_close" not in df.columns or df["adj_close"].isna().all():
        return df
    ratio = (df["adj_close"] / df["close"]).fillna(1.0)
    out = df.copy()
    for c in ("open", "high", "low", "close"):
        out[c] = df[c] * ratio
    return out


def from_binance_perp(klines: list, funding: list) -> pd.DataFrame:
    """Binance USD-M klines (UTC days) with `funding_rate` = mean of that day's settlements; days without funding
    data are dropped (the engine would otherwise charge its fixed default rate)."""
    df = pd.DataFrame([[float(x) for x in r[1:6]] for r in klines], columns=COLUMNS,
                      index=pd.to_datetime([r[0] for r in klines], unit="ms").floor("D"))
    fr = pd.Series([float(x["fundingRate"]) for x in funding],
                   index=pd.to_datetime([x["fundingTime"] for x in funding], unit="ms"))
    daily = fr.groupby(fr.index.floor("D")).mean()
    df = df.loc[(df.index >= daily.index.min()) & (df.index <= daily.index.max())].copy()
    df["funding_rate"] = daily.reindex(df.index)
    return _finish(df.dropna(subset=["funding_rate"]))
