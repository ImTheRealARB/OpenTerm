# Ported from HKUDS/Vibe-Trading @ 8b8e083, agent/src/factors/zoo/qlib158/imxd10.py (MIT; see THIRD_PARTY.md).
# Changes: imports only; a per-file `ruff: noqa` header covers lint (unused imports, import order, style).
# ruff: noqa
# Adapted from microsoft/qlib@d5379c520f66a39953bad76234a7019a72796fd0:qlib/contrib/data/handler.py
# (Apache-2.0). Copyright (c) Microsoft Corporation.
# ============================================================
# 中文名称: 极值跨度 10日
# 简要说明: (ts_argmax(high, 10) - ts_argmin(low, 10)) / 10，最高与最低出现位置的时间差。
# 典型用途: 衡量10日内从最低点到最高点所需的时间，反映趋势持续性。
# ============================================================
"""qlib158 IMXD10: formula = (\\mathrm{ts\\_argmax}(\\mathrm{high}, 10) - \\mathrm{ts\\_argmin}(\\mathrm{low}, 10)) / 10."""
from __future__ import annotations

import pandas as pd
from openterm.quantlib.alpha.base import ts_argmax, ts_argmin

__alpha_meta__ = {
    'id': 'qlib158_imxd10',
    'theme': ['momentum'],
    'formula_latex': '(\\\\mathrm{ts\\\\_argmax}(\\\\mathrm{high}, 10) - \\\\mathrm{ts\\\\_argmin}(\\\\mathrm{low}, 10)) / 10',
    'columns_required': ['high', 'low'],
    'universe': ['equity_us', 'equity_cn', 'equity_hk', 'equity_in', 'equity_kr'],
    'frequency': ['1d'],
    'decay_horizon': 10,
    'min_warmup_bars': 10,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return qlib158 IMXD10 on the supplied OHLCV panel."""
    h = panel['high']
    lo = panel['low']
    return (ts_argmax(h, 10) - ts_argmin(lo, 10)) / float(10)
