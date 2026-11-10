# Ported from HKUDS/Vibe-Trading @ 8b8e083, agent/src/factors/zoo/qlib158/beta30.py (MIT; see THIRD_PARTY.md).
# Changes: imports only; a per-file `ruff: noqa` header covers lint (unused imports, import order, style).
# ruff: noqa
# Adapted from microsoft/qlib@d5379c520f66a39953bad76234a7019a72796fd0:qlib/contrib/data/handler.py
# (Apache-2.0). Copyright (c) Microsoft Corporation.
# ============================================================
# 中文名称: Beta系数 30日
# 简要说明: Slope(close, 30) / close，收盘价对时间的30日线性回归斜率，按最新收盘价归一化。
# 典型用途: 衡量30日价格趋势的速度和方向，正值表示上涨趋势。
# ============================================================
"""qlib158 BETA30: formula = \\mathrm{Slope}(\\mathrm{close}, 30) / \\mathrm{close}."""
from __future__ import annotations

import pandas as pd
from openterm.quantlib.alpha.base import safe_div, ts_slope

__alpha_meta__ = {
    'id': 'qlib158_beta30',
    'theme': ['momentum'],
    'formula_latex': '\\\\mathrm{Slope}(\\\\mathrm{close}, 30) / \\\\mathrm{close}',
    'columns_required': ['close'],
    'universe': ['equity_us', 'equity_cn', 'equity_hk', 'equity_in', 'equity_kr'],
    'frequency': ['1d'],
    'decay_horizon': 30,
    'min_warmup_bars': 30,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return qlib158 BETA30 on the supplied OHLCV panel."""
    c = panel['close']
    return safe_div(ts_slope(c, 30), c)
