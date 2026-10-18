# Third-party notices

OpenTerm itself is MIT licensed (`backend/pyproject.toml`). This file lists code ported from other projects and runtime
pieces whose licences ask for a notice. Ported code keeps its original notice here; a ported file also names its source
in its module docstring.

## Ported code

Filled from Phase 12 onwards. One row per ported file.

| OpenTerm file | Source file | Project @ commit | Licence |
|---|---|---|---|
| `openterm/bt/models.py` | `agent/backtest/models.py` | HKUDS/Vibe-Trading @ `d0db2e3` | MIT |
| `openterm/bt/metrics.py` | `agent/backtest/metrics.py` | HKUDS/Vibe-Trading @ `d0db2e3` | MIT |
| `openterm/bt/rebalance_mask.py` | `agent/backtest/rebalance_mask.py` | HKUDS/Vibe-Trading @ `d0db2e3` | MIT |
| `openterm/bt/engines/base.py` | `agent/backtest/engines/base.py` | HKUDS/Vibe-Trading @ `d0db2e3` | MIT |
| `openterm/bt/engines/global_equity.py` | `agent/backtest/engines/global_equity.py` | HKUDS/Vibe-Trading @ `d0db2e3` | MIT |
| `openterm/valuation/contracts.py` | `agent/src/quantlib/valuation/contracts.py` (+ `normalize_currency` from `agent/src/entities/models.py`) | HKUDS/Vibe-Trading @ `d0db2e3` | MIT |
| `openterm/valuation/dcf.py` | `agent/src/quantlib/valuation/dcf.py` (numpy/pandas removed) | HKUDS/Vibe-Trading @ `d0db2e3` | MIT |
| `openterm/valuation/comps.py` | `agent/src/quantlib/valuation/comps.py` (numpy removed) | HKUDS/Vibe-Trading @ `d0db2e3` | MIT |
| `openterm/research/fund_parse.py` (`diff_13f` only) | logic of `_diff_positions` in `agent/src/tools/institutional_holdings_tool.py`; written fresh, not copied | HKUDS/Vibe-Trading @ `d0db2e3` | MIT |
| `openterm/bt/engines/hooks.py` | `agent/backtest/engines/_market_hooks.py` | HKUDS/Vibe-Trading @ `d0db2e3` | MIT |
| `openterm/bt/engines/india_equity.py` | `agent/backtest/engines/india_equity.py` | HKUDS/Vibe-Trading @ `d0db2e3` | MIT |
| `openterm/bt/engines/crypto.py` | `agent/backtest/engines/crypto.py` | HKUDS/Vibe-Trading @ `d0db2e3` | MIT |
| `openterm/bt/engines/forex.py` | `agent/backtest/engines/forex.py` | HKUDS/Vibe-Trading @ `d0db2e3` | MIT |
| `openterm/bt/engines/futures_base.py` | `agent/backtest/engines/futures_base.py` | HKUDS/Vibe-Trading @ `d0db2e3` | MIT |
| `openterm/bt/engines/global_futures.py` | `agent/backtest/engines/global_futures.py` | HKUDS/Vibe-Trading @ `d0db2e3` | MIT |
| `openterm/bt/engines/composite.py` | `agent/backtest/engines/composite.py` | HKUDS/Vibe-Trading @ `d0db2e3` | MIT |
| `openterm/bt/engines/bands.py` | `agent/backtest/engines/china_a (only `_blocked_by_limit`).py` | HKUDS/Vibe-Trading @ `d0db2e3` | MIT |
| `openterm/bt/validation.py` | `agent/backtest/validation.py` | HKUDS/Vibe-Trading @ `d0db2e3` | MIT |
| `openterm/quant/options.py` | `agent/src/quantlib/options.py` (scipy and numpy removed) | HKUDS/Vibe-Trading @ `d0db2e3` | MIT |
| `openterm/quant/heston.py` | `agent/src/quantlib/volatility.py` (scipy `quad` replaced by an adaptive Gauss-Kronrod integrator) | HKUDS/Vibe-Trading @ `d0db2e3` | MIT |
| `openterm/quant/fixedincome.py` | `agent/src/quantlib/fixedincome.py` (numpy and scipy removed; `price_mid_period` and `ytm_from_clean` added) | HKUDS/Vibe-Trading @ `d0db2e3` | MIT |
| `openterm/quant/credit.py` (`cds_price`, hazard/survival conversion, `expected_loss` only) | `agent/src/quantlib/credit.py` (numpy, pandas and scipy removed) | HKUDS/Vibe-Trading @ `d0db2e3` | MIT |
| `openterm/quant/payoff.py` | `agent/backtest/options_payoff.py` (numpy removed; arrays became lists) | HKUDS/Vibe-Trading @ `d0db2e3` | MIT |
| `openterm/bt/engines/options_portfolio.py` | `agent/backtest/engines/options_portfolio.py` (loader / signal engine / run directory / CSV artifacts / run card replaced by an in-memory call; equity indexed by timestamp) | HKUDS/Vibe-Trading @ `d0db2e3` | MIT |
| `openterm/quantlib/risk.py` | `agent/src/quantlib/risk.py` (imports and safe lint fixes only) | HKUDS/Vibe-Trading @ `d0db2e3` | MIT |
| `openterm/quantlib/var_backtest.py` | `agent/src/quantlib/var_backtest.py` (imports and safe lint fixes only) | HKUDS/Vibe-Trading @ `d0db2e3` | MIT |
| `openterm/quantlib/portfolio.py` | `agent/src/quantlib/portfolio.py` (imports and safe lint fixes only) | HKUDS/Vibe-Trading @ `d0db2e3` | MIT |
| `openterm/quantlib/attribution.py` | `agent/src/quantlib/attribution.py` (imports and safe lint fixes only) | HKUDS/Vibe-Trading @ `d0db2e3` | MIT |
| `openterm/quantlib/factormodel.py` | `agent/src/quantlib/factormodel.py` (imports and safe lint fixes only) | HKUDS/Vibe-Trading @ `d0db2e3` | MIT |
| `openterm/quantlib/copula.py` | `agent/src/quantlib/copula.py` (imports and safe lint fixes only) | HKUDS/Vibe-Trading @ `d0db2e3` | MIT |
| `openterm/quantlib/microstructure.py` | `agent/src/quantlib/microstructure.py` (imports and safe lint fixes only) | HKUDS/Vibe-Trading @ `d0db2e3` | MIT |
| `openterm/quantlib/eventstudy.py` | `agent/src/quantlib/eventstudy.py` (imports and safe lint fixes only) | HKUDS/Vibe-Trading @ `d0db2e3` | MIT |
| `openterm/quantlib/multipletesting.py` | `agent/src/quantlib/multipletesting.py` (imports and safe lint fixes only) | HKUDS/Vibe-Trading @ `d0db2e3` | MIT |
| `openterm/quantlib/timeseries.py` | `agent/src/quantlib/timeseries.py` (imports and safe lint fixes only) | HKUDS/Vibe-Trading @ `d0db2e3` | MIT |
| `openterm/quantlib/optimizers/*.py` | `agent/backtest/optimizers/*.py` (lint only) | HKUDS/Vibe-Trading @ `d0db2e3` | MIT |
| `openterm/quantlib/regime.py`, `risk_xray.py`, `_vibe_backtest.py` | `agent/backtest/{regime,risk_xray}.py` (+ `_close_series` from `correlation.py`, `_json_safe` from `validation.py`) | HKUDS/Vibe-Trading @ `d0db2e3` | MIT |
| `openterm/quantlib/alpha/base.py`, `_backend.py`, `bench.py` | `agent/src/factors/{base,_backend}.py` (bottleneck path removed), `bench_runner.py` (`t_stat`, `categorise` only) | HKUDS/Vibe-Trading @ `d0db2e3` | MIT |
| `openterm/quantlib/alpha/zoo/*/*.py` (29 factors) | `agent/src/factors/zoo/{alpha101,qlib158,academic}/*.py` (import path and lint headers only) | HKUDS/Vibe-Trading @ `d0db2e3` | MIT |

### HKUDS/Vibe-Trading (MIT)

Source: <https://github.com/HKUDS/Vibe-Trading>, ported from commit `d0db2e3` (2026-10-17).
Licence text from that commit's `LICENSE`:

```
MIT License

Copyright (c) 2026 Vibe-Trading Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### Qlib Alpha158 factor definitions (microsoft/qlib)

The roadmap expected Apache-2.0 for these parts. Qlib's own `LICENSE` (checked 2026-10-19 on `main`) is
**MIT, "Copyright (c) Microsoft Corporation."** When the Alpha158 parts are ported (Phase 12), check the header of the
exact Vibe-Trading file they come from, copy whatever notice it carries here, and fill in the table row.

## Runtime libraries with notice requirements

| Library | Version | Licence | Notice |
|---|---|---|---|
| [TradingView Lightweight Charts™](https://www.tradingview.com/lightweight-charts/) | 5.2.1 | Apache-2.0 | Copyright © TradingView, Inc. The chart's logo is off (`attributionLogo: false`), so attribution and a link to <https://www.tradingview.com/> are shown in GP's status line and in the README, as the library's README asks. |

Other runtime dependencies (React, FastAPI, httpx, orjson, aiosqlite, apscheduler, websockets, keyring) are MIT, BSD or
Apache-2.0 packages used unmodified through their package managers; their licences ship inside `node_modules/` and the
Python environment.
