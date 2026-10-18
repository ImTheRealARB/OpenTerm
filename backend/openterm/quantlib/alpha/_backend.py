"""Numpy-only backend for the alpha operators.

Ported from HKUDS/Vibe-Trading @ d0db2e3, agent/src/factors/_backend.py (MIT; see THIRD_PARTY.md).
Changes: the optional bottleneck fast path and the ``get_env_config`` lookup are removed; ``HAS_BOTTLENECK`` is always
False and ``bn`` is None, so the pandas / numpy path runs (the path the recorded Vibe numbers were produced with).
"""

from __future__ import annotations

from typing import Any

# numpy sliding_window_view: always available (numpy >= 1.20)
from numpy.lib.stride_tricks import sliding_window_view

__all__ = ["HAS_BOTTLENECK", "bn", "sliding_window_view"]

HAS_BOTTLENECK: bool = False
bn: Any = None
