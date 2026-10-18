"""Alpha IC categorisation helpers.

Ported from HKUDS/Vibe-Trading @ d0db2e3, agent/src/factors/bench_runner.py (MIT; see THIRD_PARTY.md).
Changes: only ``t_stat`` and ``categorise`` are copied, verbatim (the rest of that file drags in the Vibe app). The
thresholds (``ic_mean > 0.02``, ``ic_positive_ratio >= 0.55``, ``|t| > 2``) are inline in ``categorise``, as in Vibe.

Categorisation thresholds:

- ``alive``     : ic_mean > 0.02 and ic_positive_ratio >= 0.55 and |t| > 2
- ``reversed``  : ic_mean < -0.02 and |t| > 2
- ``dead``      : everything else
"""

from __future__ import annotations

import math
from typing import Any


def t_stat(ic_mean: float, ic_std: float, n: int) -> float:
    """Two-sided t-statistic of the IC series."""
    if not (n > 0 and ic_std > 0 and math.isfinite(ic_std)):
        return 0.0
    return ic_mean / (ic_std / math.sqrt(n))


def categorise(row: dict[str, Any]) -> str:
    """Bucket a per-alpha row into alive / reversed / dead.

    Thresholds are calibrated on daily next-bar ICs; at horizon h > 1 the
    |IC| > 0.02 floor is a looser bar (h-bar ICs are naturally larger in
    magnitude). The run envelope states its own horizon.
    """
    ic_mean = row["ic_mean"]
    pos = row["ic_positive_ratio"]
    t = t_stat(ic_mean, row["ic_std"], row["ic_count"])
    if ic_mean > 0.02 and pos >= 0.55 and abs(t) > 2:
        return "alive"
    if ic_mean < -0.02 and abs(t) > 2:
        return "reversed"
    return "dead"
