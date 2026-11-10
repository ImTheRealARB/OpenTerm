"""Alpha zoo: the Vibe-Trading price/volume factors OpenTerm can feed (Phase 15, extended; the count is in ``zoo_index.json``).

Ported from HKUDS/Vibe-Trading (see ``SOURCE`` for the commit; MIT, Qlib Alpha158 parts Apache-2.0; see THIRD_PARTY.md), agent/src/factors/.
Changes: OpenTerm glue, not a Vibe file. ``ZOO`` lists the ported factors (metadata from Vibe's own factor files, written by
``scripts/port_vibe_alphas.py`` into ``zoo_index.json``), ``compute_factor`` imports one module and calls its ``compute(panel)``, and
``extend_panel`` adds the two series Vibe's bar loader supplies that a plain OHLCV panel lacks. Factors that need data OpenTerm has
not got are not in the zoo; ``docs/ALPHA_SKIPPED.md`` lists them with the reason.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

ZOO: list[dict[str, Any]] = json.loads(Path(__file__).with_name("zoo_index.json").read_text(encoding="utf-8"))
FAMILIES = ("alpha101", "qlib158", "academic", "gtja191")
_BY_ID = {z["id"]: z for z in ZOO}


def extend_panel(panel: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """The panel plus ``vwap`` and ``amount`` when absent (a new dict; a complete panel is returned as it is).

    Daily bars carry no traded value, so both are the references Vibe's own ``vwap`` helper uses for non-China markets: ``vwap`` is
    the typical price (open + high + low + close) / 4 and ``amount`` is ``volume * vwap``. Both read the same bar only (no lookahead).
    """
    if "vwap" in panel and "amount" in panel:
        return panel
    out = dict(panel)
    if "vwap" not in out:
        out["vwap"] = (panel["open"] + panel["high"] + panel["low"] + panel["close"]) / 4.0
    if "amount" not in out:
        out["amount"] = panel["volume"] * out["vwap"]
    return out


def compute_factor(factor_id: str, panel: dict) -> pd.DataFrame:
    """Compute one zoo factor on a wide panel (dict of field -> DataFrame). Unknown id -> KeyError."""
    entry = _BY_ID[factor_id]
    module_path = entry["file"].removesuffix(".py").replace("/", ".")
    return importlib.import_module(module_path).compute(extend_panel(panel))
