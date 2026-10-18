"""Alpha zoo: the 29 Vibe-Trading factors replayed by the Phase 15 tests.

Ported from HKUDS/Vibe-Trading @ d0db2e3, agent/src/factors/ (MIT; see THIRD_PARTY.md).
Changes: OpenTerm glue, not a Vibe file. ``ZOO`` lists the ported factors (metadata from Vibe's own factor registry) and
``compute_factor`` imports one module and calls its ``compute(panel)``.
"""

from __future__ import annotations

import importlib
from typing import Any

import pandas as pd

ZOO: list[dict[str, Any]] = [
    {
        "id": "alpha101_001",
        "family": "alpha101",
        "file": "openterm/quantlib/alpha/zoo/alpha101/alpha_001.py",
        "columns_required": [
            "close"
        ],
        "decay_horizon": 5,
        "min_warmup_bars": 25
    },
    {
        "id": "alpha101_002",
        "family": "alpha101",
        "file": "openterm/quantlib/alpha/zoo/alpha101/alpha_002.py",
        "columns_required": [
            "open",
            "close",
            "volume"
        ],
        "decay_horizon": 5,
        "min_warmup_bars": 10
    },
    {
        "id": "alpha101_003",
        "family": "alpha101",
        "file": "openterm/quantlib/alpha/zoo/alpha101/alpha_003.py",
        "columns_required": [
            "open",
            "volume",
            "close"
        ],
        "decay_horizon": 5,
        "min_warmup_bars": 10
    },
    {
        "id": "alpha101_004",
        "family": "alpha101",
        "file": "openterm/quantlib/alpha/zoo/alpha101/alpha_004.py",
        "columns_required": [
            "low",
            "close"
        ],
        "decay_horizon": 5,
        "min_warmup_bars": 9
    },
    {
        "id": "alpha101_006",
        "family": "alpha101",
        "file": "openterm/quantlib/alpha/zoo/alpha101/alpha_006.py",
        "columns_required": [
            "open",
            "volume",
            "close"
        ],
        "decay_horizon": 5,
        "min_warmup_bars": 10
    },
    {
        "id": "alpha101_009",
        "family": "alpha101",
        "file": "openterm/quantlib/alpha/zoo/alpha101/alpha_009.py",
        "columns_required": [
            "close"
        ],
        "decay_horizon": 5,
        "min_warmup_bars": 6
    },
    {
        "id": "alpha101_012",
        "family": "alpha101",
        "file": "openterm/quantlib/alpha/zoo/alpha101/alpha_012.py",
        "columns_required": [
            "close",
            "volume"
        ],
        "decay_horizon": 5,
        "min_warmup_bars": 2
    },
    {
        "id": "alpha101_013",
        "family": "alpha101",
        "file": "openterm/quantlib/alpha/zoo/alpha101/alpha_013.py",
        "columns_required": [
            "close",
            "volume"
        ],
        "decay_horizon": 5,
        "min_warmup_bars": 5
    },
    {
        "id": "alpha101_016",
        "family": "alpha101",
        "file": "openterm/quantlib/alpha/zoo/alpha101/alpha_016.py",
        "columns_required": [
            "high",
            "volume",
            "close"
        ],
        "decay_horizon": 5,
        "min_warmup_bars": 5
    },
    {
        "id": "alpha101_021",
        "family": "alpha101",
        "file": "openterm/quantlib/alpha/zoo/alpha101/alpha_021.py",
        "columns_required": [
            "close",
            "volume"
        ],
        "decay_horizon": 5,
        "min_warmup_bars": 20
    },
    {
        "id": "alpha101_033",
        "family": "alpha101",
        "file": "openterm/quantlib/alpha/zoo/alpha101/alpha_033.py",
        "columns_required": [
            "open",
            "close"
        ],
        "decay_horizon": 5,
        "min_warmup_bars": 1
    },
    {
        "id": "alpha101_034",
        "family": "alpha101",
        "file": "openterm/quantlib/alpha/zoo/alpha101/alpha_034.py",
        "columns_required": [
            "close"
        ],
        "decay_horizon": 5,
        "min_warmup_bars": 6
    },
    {
        "id": "alpha101_101",
        "family": "alpha101",
        "file": "openterm/quantlib/alpha/zoo/alpha101/alpha_101.py",
        "columns_required": [
            "open",
            "high",
            "low",
            "close"
        ],
        "decay_horizon": 5,
        "min_warmup_bars": 1
    },
    {
        "id": "qlib158_roc10",
        "family": "qlib158",
        "file": "openterm/quantlib/alpha/zoo/qlib158/roc10.py",
        "columns_required": [
            "close"
        ],
        "decay_horizon": 10,
        "min_warmup_bars": 10
    },
    {
        "id": "qlib158_std20",
        "family": "qlib158",
        "file": "openterm/quantlib/alpha/zoo/qlib158/std20.py",
        "columns_required": [
            "close"
        ],
        "decay_horizon": 20,
        "min_warmup_bars": 20
    },
    {
        "id": "qlib158_ma20",
        "family": "qlib158",
        "file": "openterm/quantlib/alpha/zoo/qlib158/ma20.py",
        "columns_required": [
            "close"
        ],
        "decay_horizon": 20,
        "min_warmup_bars": 20
    },
    {
        "id": "qlib158_beta10",
        "family": "qlib158",
        "file": "openterm/quantlib/alpha/zoo/qlib158/beta10.py",
        "columns_required": [
            "close"
        ],
        "decay_horizon": 10,
        "min_warmup_bars": 10
    },
    {
        "id": "qlib158_resi10",
        "family": "qlib158",
        "file": "openterm/quantlib/alpha/zoo/qlib158/resi10.py",
        "columns_required": [
            "close"
        ],
        "decay_horizon": 10,
        "min_warmup_bars": 10
    },
    {
        "id": "qlib158_rsqr20",
        "family": "qlib158",
        "file": "openterm/quantlib/alpha/zoo/qlib158/rsqr20.py",
        "columns_required": [
            "close"
        ],
        "decay_horizon": 20,
        "min_warmup_bars": 20
    },
    {
        "id": "qlib158_rank20",
        "family": "qlib158",
        "file": "openterm/quantlib/alpha/zoo/qlib158/rank20.py",
        "columns_required": [
            "close"
        ],
        "decay_horizon": 20,
        "min_warmup_bars": 20
    },
    {
        "id": "qlib158_corr10",
        "family": "qlib158",
        "file": "openterm/quantlib/alpha/zoo/qlib158/corr10.py",
        "columns_required": [
            "close",
            "volume"
        ],
        "decay_horizon": 10,
        "min_warmup_bars": 10
    },
    {
        "id": "qlib158_rsv10",
        "family": "qlib158",
        "file": "openterm/quantlib/alpha/zoo/qlib158/rsv10.py",
        "columns_required": [
            "high",
            "low",
            "close"
        ],
        "decay_horizon": 10,
        "min_warmup_bars": 10
    },
    {
        "id": "qlib158_wvma20",
        "family": "qlib158",
        "file": "openterm/quantlib/alpha/zoo/qlib158/wvma20.py",
        "columns_required": [
            "close",
            "volume"
        ],
        "decay_horizon": 20,
        "min_warmup_bars": 20
    },
    {
        "id": "academic_strev",
        "family": "academic",
        "file": "openterm/quantlib/alpha/zoo/academic/strev.py",
        "columns_required": [
            "close"
        ],
        "decay_horizon": 21,
        "min_warmup_bars": 21
    },
    {
        "id": "academic_illiq",
        "family": "academic",
        "file": "openterm/quantlib/alpha/zoo/academic/illiq.py",
        "columns_required": [
            "close",
            "volume"
        ],
        "decay_horizon": 21,
        "min_warmup_bars": 22
    },
    {
        "id": "academic_retskew",
        "family": "academic",
        "file": "openterm/quantlib/alpha/zoo/academic/retskew.py",
        "columns_required": [
            "close"
        ],
        "decay_horizon": 60,
        "min_warmup_bars": 61
    },
    {
        "id": "academic_mkt_rf",
        "family": "academic",
        "file": "openterm/quantlib/alpha/zoo/academic/mkt_rf.py",
        "columns_required": [
            "close"
        ],
        "decay_horizon": 21,
        "min_warmup_bars": 21
    },
    {
        "id": "academic_rmw",
        "family": "academic",
        "file": "openterm/quantlib/alpha/zoo/academic/rmw.py",
        "columns_required": [
            "close"
        ],
        "decay_horizon": 60,
        "min_warmup_bars": 60
    },
    {
        "id": "academic_smb",
        "family": "academic",
        "file": "openterm/quantlib/alpha/zoo/academic/smb.py",
        "columns_required": [
            "close",
            "volume"
        ],
        "decay_horizon": 60,
        "min_warmup_bars": 60
    }
]


def compute_factor(factor_id: str, panel: dict) -> pd.DataFrame:
    """Compute one zoo factor on a wide panel (dict of field -> DataFrame). Unknown id -> KeyError."""
    for entry in ZOO:
        if entry["id"] == factor_id:
            module_path = entry["file"].removesuffix(".py").replace("/", ".")
            return importlib.import_module(module_path).compute(panel)
    raise KeyError(factor_id)
