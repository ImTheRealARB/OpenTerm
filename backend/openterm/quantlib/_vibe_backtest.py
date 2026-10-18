"""Small helpers from Vibe-Trading's backtest package that OpenTerm has no equivalent for.

Ported from HKUDS/Vibe-Trading @ d0db2e3, agent/backtest/correlation.py and agent/backtest/validation.py (MIT; see THIRD_PARTY.md).
Changes: `_close_series` (correlation.py) and `_json_safe` (validation.py) are verbatim. `_fetch_price_series`
(correlation.py) walked Vibe's data-loader registry, which OpenTerm does not have: here it raises, so callers must pass
``price_series`` (OpenTerm jobs read stored bars).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


def _close_series(code: str, df: pd.DataFrame) -> pd.Series:
    """Extract the close-price series from a loader frame, date-indexed and sorted.

    Supports ``trade_date`` as the index name, as a column, or a plain
    DatetimeIndex — the shapes real loaders return.
    """
    if df.empty:
        raise ValueError(f"Price series for '{code}' is empty")
    if "close" not in df.columns and "close" not in df.index.names:
        raise ValueError(f"No 'close' column in price series for '{code}'")
    # Support trade_date as index name, column, or a plain DatetimeIndex.
    if "trade_date" in df.columns:
        ts = df.set_index("trade_date")["close"]
    elif "close" in df.columns and (
        "trade_date" in df.index.names
        or isinstance(df.index, pd.DatetimeIndex)
    ):
        ts = df["close"]
    else:
        raise ValueError(
            f"No trade_date index/column for price series '{code}'"
        )
    return ts.sort_index()


def _fetch_price_series(
    codes: list[str],
    start_date: str,
    end_date: str,
    diagnostics: dict | None = None,
) -> dict[str, pd.DataFrame]:
    """Not available in OpenTerm: pass ``price_series`` explicitly."""
    raise NotImplementedError("OpenTerm has no Vibe loader registry; pass price_series explicitly")


def _json_safe(value: Any) -> Any:
    """Return a JSON-strict copy of validation results."""
    if isinstance(value, np.ndarray):
        return [_json_safe(item) for item in value.tolist()]
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value
