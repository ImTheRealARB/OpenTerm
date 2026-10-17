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
| `openterm/bt/engines/hooks.py` | `agent/backtest/engines/_market_hooks.py` | HKUDS/Vibe-Trading @ `d0db2e3` | MIT |

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
