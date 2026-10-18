"""Portfolio optimizer package.
Ported from HKUDS/Vibe-Trading @ d0db2e3, agent/backtest/optimizers/__init__.py (MIT; see THIRD_PARTY.md).
Changes: imports only.

Provides five weighting schemes:
- equal_volatility: inverse-volatility weights
- risk_parity: equal risk contribution (Spinu-style)
- mean_variance: max Sharpe via scipy
- max_diversification: maximize diversification ratio
- turnover_aware: mean-variance utility with an L1 turnover penalty

Select via ``optimizer`` in ``config.json``; default is off (1/N).
Add a new optimizer by dropping a module here that exposes ``optimize()``.
"""
