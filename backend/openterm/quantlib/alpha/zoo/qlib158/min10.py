# Ported from HKUDS/Vibe-Trading @ 8b8e083, agent/src/factors/zoo/qlib158/min10.py (MIT; see THIRD_PARTY.md).
# Changes: imports only; a per-file `ruff: noqa` header covers lint (unused imports, import order, style).
# ruff: noqa
# Adapted from microsoft/qlib@d5379c520f66a39953bad76234a7019a72796fd0:qlib/contrib/data/handler.py
# (Apache-2.0). Copyright (c) Microsoft Corporation.
# ============================================================
# 中文名称: 最小价 10日
# 简要说明: ts_min(low, 10) / close，10日最低价与当前收盘价的比率。
# 典型用途: 衡量当前价格相对于10日最低点的位置，接近1表示接近近期低点。
# ============================================================
"""qlib158 MIN10: formula = \\mathrm{ts\\_min}(\\mathrm{low}, 10) / \\mathrm{close}."""
from __future__ import annotations

import pandas as pd
from openterm.quantlib.alpha.base import safe_div, ts_min

__alpha_meta__ = {
    'id': 'qlib158_min10',
    'theme': ['momentum'],
    'formula_latex': '\\\\mathrm{ts\\\\_min}(\\\\mathrm{low}, 10) / \\\\mathrm{close}',
    'columns_required': ['low', 'close'],
    'universe': ['equity_us', 'equity_cn', 'equity_hk', 'equity_in', 'equity_kr'],
    'frequency': ['1d'],
    'decay_horizon': 10,
    'min_warmup_bars': 10,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return qlib158 MIN10 on the supplied OHLCV panel."""
    lo = panel['low']
    c = panel['close']
    return safe_div(ts_min(lo, 10), c)
