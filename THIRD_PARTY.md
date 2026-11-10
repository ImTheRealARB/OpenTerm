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
| `openterm/quantlib/alpha/_backend.py`, `bench.py` | `agent/src/factors/_backend.py` (bottleneck path removed), `bench_runner.py` (`t_stat`, `categorise` only) | HKUDS/Vibe-Trading @ `d0db2e3` | MIT |
| `openterm/quantlib/alpha/base.py` | `agent/src/factors/base.py` (import line only) | HKUDS/Vibe-Trading @ `8b8e083` | MIT |
| `openterm/quantlib/alpha/zoo/{alpha101,qlib158,academic,gtja191}/*.py` (435 factors: 82 + 154 + 12 + 187; ONE ROW FOR THE DIRECTORY, generated by `scripts/port_vibe_alphas.py`, every file names its own source path and commit in its header) | `agent/src/factors/zoo/{alpha101,qlib158,academic,gtja191}/*.py` (import path and lint header only; five GTJA files carry a warm-up NaN mask listed as `PATCHES` in the script). The 43 factors that were not ported are listed with reasons in `docs/ALPHA_SKIPPED.md` | HKUDS/Vibe-Trading @ `8b8e083` (full SHA `8b8e0836e92906b3472ee85c515c22815e0f02cc`; the commit and its MIT LICENSE checked on GitHub 2026-11-10) | MIT (the Qlib158 definitions are Microsoft Qlib's, also MIT, see below) |
| `scripts/port_vibe_alphas.py`, `scripts/vibe_alpha_crosscheck.py` (OpenTerm's own tools: the generator and the replay of Vibe's code that wrote `backend/tests/fixtures/alpha_vibe_expected.json`) | written for OpenTerm; they read a local Vibe checkout and copy nothing into the repo | HKUDS/Vibe-Trading @ `8b8e083` | n/a |
| `openterm/ai/presets/*.yaml` (30 swarm presets; generated by `scripts/port_vibe_presets.py`) | `agent/src/swarm/presets/*.yaml` (tool names mapped to OpenTerm tools, shell / file / web steps cut by rule, coverage label and limits added; each file names its source in its header; report in `docs/PHASE_20_PRESETS.md`) | HKUDS/Vibe-Trading @ `8172827` | MIT |
| `openterm/ai/skills/*.md` (ported ones start with `<!-- Ported from HKUDS/Vibe-Trading`) | `agent/src/skills/<name>/SKILL.md` and its English `references/*.md` (frontmatter dropped; shell, file and Vibe-only tool steps cut; Vibe tool names renamed to OpenTerm tools, web steps marked opt-in; one header comment added; Chinese-language skills, and the Chinese references of the elliott-wave, harmonic and ichimoku skills, ported from English translations in `scripts/vibe_skill_overrides/`; list in `docs/PHASE_20_SKIPPED.md`) | HKUDS/Vibe-Trading @ `8172827` | MIT. NOTICE: "Vibe-Trading, Copyright 2026 HKUDS contributors. This product includes software developed at HKUDS (https://github.com/HKUDS)." |

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

The swarm presets (commit `8172827`) are taken from the same project; its `NOTICE` there reads "Copyright 2026 HKUDS contributors. This product includes software developed at HKUDS (https://github.com/HKUDS)." The licence text of that commit's `LICENSE` is the one above ("Copyright (c) 2026 Vibe-Trading Contributors").

### Qlib Alpha158 factor definitions (microsoft/qlib)

The roadmap expected Apache-2.0 for these parts. Qlib's own `LICENSE` (checked 2026-10-19 on `main`) is
**MIT, "Copyright (c) Microsoft Corporation."** When the Alpha158 parts are ported (Phase 12), check the header of the
exact Vibe-Trading file they come from, copy whatever notice it carries here, and fill in the table row.

Update (alpha zoo, 154 `qlib158` files, Vibe-Trading @ `8b8e083`): they are covered by the directory row in the table above; the Qlib licence is MIT (Copyright (c) Microsoft Corporation), the same as Vibe's, so one notice applies.

## Map outline data (MAP panel)

| Data | Source | Licence | Notice |
|---|---|---|---|
| Coastlines and country borders drawn by `MAP` (`frontend/src/map/worldData.json`) | [Natural Earth](https://www.naturalearthdata.com/) 1:50m "Admin 0 - Countries", read through the npm package `world-atlas` 2.0.2 (<https://github.com/topojson/world-atlas>, a pre-built TopoJSON of the Natural Earth files) | Natural Earth: public domain ("no permission needed", their terms of use). `world-atlas`: ISC. | Natural Earth asks for no credit; credit is given here anyway. The file is OUR OWN reduced copy, made by `scripts/build_world_map.mjs`: Antarctica dropped, each line simplified to about 2 km (Douglas-Peucker) and stored as delta-coded integers. Rebuild with `node scripts/build_world_map.mjs`. |

Live data layers on the map (USGS earthquakes, NASA EONET, IMF PortWatch, AISstream) are fetched at run time, never bundled; see
`docs/DATA_SOURCES.md` for their terms. No map tiles are used or downloaded.

## Runtime libraries with notice requirements

| Library | Version | Licence | Notice |
|---|---|---|---|
| [TradingView Lightweight Charts™](https://www.tradingview.com/lightweight-charts/) | 5.2.1 | Apache-2.0 | Copyright © TradingView, Inc. The chart's logo is off (`attributionLogo: false`), so attribution and a link to <https://www.tradingview.com/> are shown in GP's status line and in the README, as the library's README asks. |
| [fpdf2](https://github.com/py-pdf/fpdf2) (`BT EXPORT <runid> PDF`) | 2.9.0 | LGPL-3.0-only | Used unmodified as a separate Python package installed by the package manager (dynamic linking in LGPL terms); you may replace it with any compatible version. Its dependencies Pillow (MIT-CMU) and fontTools (MIT) come with it. Only the built-in core PDF fonts are used, no font files are bundled. |

## Third-party MCP servers (MCP panel presets): referenced, not bundled

OpenTerm's MCP client has two presets, both shipped disabled. No code from either project is in this repository or in OpenTerm's packages:
`npx` / `uvx` fetch them from npm / PyPI on the user's machine only when the user enables the server and it is first used.
Both are unofficial community projects, not affiliated with or endorsed by NSE India; their data terms are those of their sources.

| Project | Run as | Licence |
|---|---|---|
| [stock-nse-india](https://github.com/hi-imcodeman/stock-nse-india) (hi-imcodeman) | `npx -y stock-nse-india mcp` | MIT (LICENSE in the repository, checked 2026-11-10) |
| [nse-mcp](https://github.com/jugaad-py/nse-mcp) (jugaad-py), built on jugaad-data | `uvx nse-mcp` | **No licence stated** (no LICENSE file in the repository, no licence field on PyPI 0.1.1; checked 2026-11-10). Without a licence all rights are reserved by default: OpenTerm only names it as an opt-in preset and never bundles, copies or redistributes it. |

Other runtime dependencies (React, FastAPI, httpx, orjson, aiosqlite, apscheduler, websockets, keyring, XlsxWriter) are MIT, BSD or
Apache-2.0 packages used unmodified through their package managers; their licences ship inside `node_modules/` and the
Python environment.

## Bundled fonts (SETTINGS font presets)

Font files live in `frontend/public/fonts/` and are declared in `frontend/src/fonts.css`; each licence text is kept in
`frontend/public/fonts/licenses/`. Fonts are downloaded only when selected (`local()` first, so an installed copy is used).
Latin subsets, taken unmodified from the sources below.

| Font | Source | Licence |
|---|---|---|
| JetBrains Mono | npm `@fontsource/jetbrains-mono` 5.3.0 (JetBrains/JetBrainsMono) | SIL OFL 1.1 |
| Geist Mono | npm `@fontsource/geist-mono` 5.3.0 (vercel/geist-font) | SIL OFL 1.1 |
| Fira Code | npm `@fontsource/fira-code` 5.3.0 (tonsky/FiraCode) | SIL OFL 1.1 |
| Mononoki | npm `@fontsource/mononoki` 5.3.0 (madmalik/mononoki) | SIL OFL 1.1 |
| Hack | npm `hack-font` 3.3.0 (source-foundry/Hack) | MIT, with the Bitstream Vera licence for its base glyphs |
| DejaVu Sans Mono | npm `@fontsource/dejavu-mono` 5.3.0 (dejavu-fonts) | Bitstream Vera licence; DejaVu changes are public domain |

Monaco, Menlo, Consolas and Comic Sans MS are not bundled: they are used only if the computer already has them.
