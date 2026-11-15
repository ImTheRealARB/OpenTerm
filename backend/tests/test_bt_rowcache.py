"""The per-bar row fast path (`BaseEngine._row_from_values`) must return exactly what `frame.loc[ts]` returns.

Why: the backtest engine reads one row per bar per symbol. `frame.loc[ts]` was ~45% of a 10-year daily run, so the
engine now builds the same Series from a numpy copy of the frame (made once per run). These tests pin "same Series":
values, dtype, index and name, plus the cases where the copy must be rebuilt or `.loc` must still be used.
"""

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pandas.testing as pdt

from openterm.bt.engines.base import BaseEngine

# The helper only needs an object with a __dict__ to keep its cache on, so a bare namespace stands in for an engine.
row_of = BaseEngine._row_from_values


def _frame(n: int = 5) -> pd.DataFrame:
    idx = pd.date_range("2020-01-01", periods=n, freq="D")
    return pd.DataFrame({"open": np.arange(n, dtype=float), "close": np.arange(n) + 0.5,
                         "volume": np.arange(n, dtype="int64") * 100}, index=idx)


def test_numeric_row_matches_loc() -> None:
    eng, f = SimpleNamespace(), _frame()
    for ts in f.index:
        pdt.assert_series_equal(row_of(eng, f, ts), f.loc[ts])  # int + float columns upcast to float64 in both


def test_mixed_dtype_row_matches_loc() -> None:
    eng, f = SimpleNamespace(), _frame()
    f["note"] = ["a", "b", None, "d", "e"]  # object column: both paths give an object Series
    ts = f.index[2]
    pdt.assert_series_equal(row_of(eng, f, ts), f.loc[ts])


def test_missing_timestamp_is_none() -> None:
    assert row_of(SimpleNamespace(), _frame(), pd.Timestamp("1999-01-01")) is None


def test_copy_rebuilt_when_columns_change() -> None:
    eng, f = SimpleNamespace(), _frame()
    ts = f.index[1]
    row_of(eng, f, ts)  # builds the cached copy
    f["sma"] = f["close"].rolling(2).mean()  # a new column makes a new columns Index, so the copy is stale
    pdt.assert_series_equal(row_of(eng, f, ts), f.loc[ts])


def test_duplicate_index_keeps_loc() -> None:
    f = _frame(3)
    f.index = pd.DatetimeIndex([f.index[0], f.index[0], f.index[2]])  # .loc returns a DataFrame for a repeated stamp
    pdt.assert_frame_equal(row_of(SimpleNamespace(), f, f.index[0]), f.loc[f.index[0]])
