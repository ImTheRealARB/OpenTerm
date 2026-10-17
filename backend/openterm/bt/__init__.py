"""Backtester `BT` (Phase 12, spec: docs/specs/PHASE_12.md).

Everything under this package that imports numpy or pandas runs in job workers only; the server process imports
just `rules` (pure parser) and `store`. The engine core is ported from HKUDS/Vibe-Trading @ d0db2e3 (MIT).
"""
