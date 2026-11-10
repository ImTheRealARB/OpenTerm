# Ported from HKUDS/Vibe-Trading @ 8b8e083, agent/src/factors/zoo/qlib158/corr10.py (MIT; see THIRD_PARTY.md).
# Changes: imports only; a per-file `ruff: noqa` header covers lint (unused imports, import order, style).
# ruff: noqa
# Adapted from microsoft/qlib@d5379c520f66a39953bad76234a7019a72796fd0:qlib/contrib/data/handler.py
# (Apache-2.0). Copyright (c) Microsoft Corporation.
# ============================================================
# 中文名称: 价量相关性 10日
# 简要说明: ts_corr(close, log(volume+1), 10)，10日收盘价与成交量的相关系数。
# 典型用途: 衡量10日价格与成交量的同步性，正相关表示价涨量增的健康走势。
# ============================================================
"""qlib158 CORR10: formula = \\mathrm{ts\\_corr}(\\mathrm{close}, \\log(\\mathrm{volume}+1), 10)."""
from __future__ import annotations

import numpy as np
import pandas as pd
from openterm.quantlib.alpha.base import ts_corr

__alpha_meta__ = {
    'id': 'qlib158_corr10',
    'theme': ['volume', 'microstructure'],
    'formula_latex': '\\\\mathrm{ts\\\\_corr}(\\\\mathrm{close}, \\\\log(\\\\mathrm{volume}+1), 10)',
    'columns_required': ['close', 'volume'],
    'universe': ['equity_us', 'equity_cn', 'equity_hk', 'equity_in', 'equity_kr'],
    'frequency': ['1d'],
    'decay_horizon': 10,
    'min_warmup_bars': 10,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return qlib158 CORR10 on the supplied OHLCV panel."""
    c = panel['close']
    v = panel['volume']
    logv = np.log1p(v)
    return ts_corr(c, logv, 10)
