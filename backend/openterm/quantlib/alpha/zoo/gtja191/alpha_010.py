# Ported from HKUDS/Vibe-Trading @ 8b8e083, agent/src/factors/zoo/gtja191/alpha_010.py (MIT; see THIRD_PARTY.md).
# Changes: imports and a warm-up NaN mask (see PATCHES in scripts/port_vibe_alphas.py); a per-file `ruff: noqa` header covers lint (unused imports, import order, style).
# ruff: noqa

# ============================================================
# 中文名称: GTJA #10 - 条件收益平方极值
# 简要说明: RANK(MAX(((RET<0)?STD(RET,20):CLOSE)^2,5))，条件收益平方的5日最大值。
# 典型用途: 识别短期剧烈波动后的潜在反转点。
# ============================================================
"""GTJA Alpha #10.

Formula: RANK(MAX(((RET<0)?STD(RET,20):CLOSE)^2,5))
Source: 国泰君安 191 alpha 研报 (2014), alpha 10."""

from __future__ import annotations

import numpy as np
import pandas as pd

from openterm.quantlib.alpha.base import (
    decay_linear,
    delta,
    rank,
    safe_div,
    signed_power,
    ts_argmax,
    ts_argmin,
    ts_corr,
    ts_cov,
    ts_max,
    ts_mean,
    ts_min,
    ts_rank,
    ts_std,
)

__alpha_meta__ = {
    "id": "gtja191_010",
    "theme": ['volatility', 'reversal'],
    "formula_latex": 'RANK(MAX(((RET<0)?STD(RET,20):CLOSE)^2,5))',
    "columns_required": ['close'],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 5,
    "min_warmup_bars": 25,
    "notes": 'Per-day return = pct_change(1) via (close - delay(close,1))/delay(close,1).',
}

def compute(panel: dict) -> pd.DataFrame:
    c = panel["close"]
    pc = c.shift(1)
    ret = safe_div(c - pc, pc)
    s20 = ts_std(ret, 20)
    pick = ret.copy()
    c = c.where(ret.notna())  # OpenTerm: a NaN RET is not `RET >= 0`; without a return the bar has no value
    pick = pick.where(ret < 0, c)
    pick = pick.where(~(ret < 0), s20)
    return rank(ts_max(pick * pick, 5))
