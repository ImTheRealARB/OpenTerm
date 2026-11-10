# Ported from HKUDS/Vibe-Trading @ 8b8e083, agent/src/factors/zoo/qlib158/imin10.py (MIT; see THIRD_PARTY.md).
# Changes: imports only; a per-file `ruff: noqa` header covers lint (unused imports, import order, style).
# ruff: noqa
# Adapted from microsoft/qlib@d5379c520f66a39953bad76234a7019a72796fd0:qlib/contrib/data/handler.py
# (Apache-2.0). Copyright (c) Microsoft Corporation.
# ============================================================
# 中文名称: 最低价位置 10日
# 简要说明: ts_argmin(low, 10) / 10，10日内最低价出现位置的归一化指标。
# 典型用途: 值接近0表示最低价出现在近期，接近1表示出现在较早期。
# ============================================================
"""qlib158 IMIN10: formula = \\mathrm{ts\\_argmin}(\\mathrm{low}, 10) / 10."""
from __future__ import annotations

import pandas as pd
from openterm.quantlib.alpha.base import ts_argmin

__alpha_meta__ = {
    'id': 'qlib158_imin10',
    'theme': ['momentum'],
    'formula_latex': '\\\\mathrm{ts\\\\_argmin}(\\\\mathrm{low}, 10) / 10',
    'columns_required': ['low'],
    'universe': ['equity_us', 'equity_cn', 'equity_hk', 'equity_in', 'equity_kr'],
    'frequency': ['1d'],
    'decay_horizon': 10,
    'min_warmup_bars': 10,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return qlib158 IMIN10 on the supplied OHLCV panel."""
    lo = panel['low']
    return ts_argmin(lo, 10) / float(10)
