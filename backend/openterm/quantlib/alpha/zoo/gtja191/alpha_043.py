# Ported from HKUDS/Vibe-Trading @ 8b8e083, agent/src/factors/zoo/gtja191/alpha_043.py (MIT; see THIRD_PARTY.md).
# Changes: imports only; a per-file `ruff: noqa` header covers lint (unused imports, import order, style).
# ruff: noqa

# ============================================================
# 中文名称: GTJA #43 - 收益递归平均
# 简要说明: SUM((CLOSE>DELAY(CLOSE,1)?VOLUME:0),26)/SUM((CLOSE<=DELAY(CLOSE,1)?VOLUME:0),26)*100，类似Alpha#40的变种。
# 典型用途: 上涨量与下跌量的比值，用于评估市场参与者的方向偏好。
# ============================================================
"""GTJA Alpha #43.

Formula: SUM((CLOSE>DELAY(CLOSE,1)?VOLUME:(CLOSE<DELAY(CLOSE,1)?-VOLUME:0)),6)
Source: 国泰君安 191 alpha 研报 (2014), alpha 43."""

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
    "id": "gtja191_043",
    "theme": ['volume', 'momentum'],
    "formula_latex": 'SUM((CLOSE>DELAY(CLOSE,1)?VOLUME:(CLOSE<DELAY(CLOSE,1)?-VOLUME:0)),6)',
    "columns_required": ['close', 'volume'],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 6,
    "min_warmup_bars": 7,
    "notes": 'Signed volume accumulation over 6 days.',
}

def compute(panel: dict) -> pd.DataFrame:
    c = panel["close"]
    v = panel["volume"]
    pc = c.shift(1)
    signed = v.where(c > pc, -v.where(c < pc, 0.0))
    # A missing close, prior close or volume is not a flat day (#1463).
    signed = signed.where(c.notna() & pc.notna() & v.notna())
    return signed.rolling(6, min_periods=6).sum()
