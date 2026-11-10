# Feature gap: OpenTerm vs a professional terminal, plus Vibe-Trading

Written 2026-10-17 after Phases 1-10. Feeds [ROADMAP_PHASES_11-19.md](ROADMAP_PHASES_11-19.md).
Function codes in the left column are the familiar mnemonics users type; OpenTerm implements its own
versions and never uses the other product's name, logo or assets on screen.

Legend: **HAVE** built · **PART** partly built · **FREE** reachable with no key · **KEY** needs a free key ·
**PAID** needs a paid plan · **NO** not reachable (see the end).

## What OpenTerm already has (38 codes)
GP, DES, Q, QR, HIST, N, WL, WEI, MOV, FX, FXC, CRYP, CMDTY, RATES, ERN, ECO, MACRO, FRED, FA, FIL/SEC, HDS, OWN,
EQS, CORR, COMP, PORT, ALRT, LAYOUT/MONITOR, SETTINGS/THEME, SOURCES, LOG, PERF, HELP, SHORTCUTS.

## Gaps by area

### Equities and company research
| Code | What | Status | Source | Phase |
|---|---|---|---|---|
| EE, EEO | Consensus estimates, revisions, surprise history | KEY | Finnhub (surprises, recs), FMP (estimates) | 13 |
| ANR | Analyst ratings and target prices | KEY / PAID | Finnhub recs free; targets on paid plans, Yahoo `quoteSummary` free | 13 |
| DVD, CACS, SPLT | Dividends, splits, corporate actions | FREE | Yahoo chart events, Nasdaq | 13 |
| IPO | IPO calendar and recent deals | FREE / KEY | Nasdaq IPO calendar, Finnhub | 13 |
| SI | Short interest and daily short volume | FREE | FINRA Reg SHO daily files, FINRA bi-monthly short interest | 13 |
| MGMT | Officers, board, pay | FREE | Yahoo `assetProfile`, SEC DEF 14A | 13 |
| EVTS, CN | Company events and company news | FREE / KEY | SEC 8-K, Finnhub/Alpaca news | 13 |
| TRAN | Earnings call transcripts | PAID | FMP / Finnhub premium | 13 (optional) |
| SEG | Segment revenue | FREE / PAID | SEC XBRL segments (messy), FMP paid | 13 |
| DCF, WACC, RV | Valuation: DCF, comps multiples, relative value | FREE | Computed from FA + EQS data (Vibe valuation engine) | 13 |
| MEMB | Index members and weights | FREE / KEY | ETF holdings as proxy (SEC N-PORT), FMP | 13 |
| ETF, FLOW | ETF holdings look-through, fund flows | FREE | SEC N-PORT, issuer CSVs | 13 |
| MA | M&A deal tracker | PART | SEC 8-K / SC TO / DEFM14A filings only | 13 (stretch) |
| BRC | Broker research | NO | Paywalled | - |
| SPLC, ESG | Supply chain, ESG scores | NO | Proprietary databases | - |
| Real-time L1 | Undelayed US last sale and bid/ask | KEY | Alpaca IEX websocket, Finnhub trades websocket | 13 |

### Options and volatility
| Code | What | Status | Source | Phase |
|---|---|---|---|---|
| OMON | Options chain with Greeks | FREE / KEY | Yahoo `v7/options` (needs crumb), Tradier sandbox | 14 |
| OV, OVME | Option pricer (BS, binomial, Heston, barrier) | FREE | Vibe `quantlib.options` / `volatility` | 14 |
| OVDV, SKEW | Implied vol surface and skew | FREE | Fitted from the chain; crypto from Deribit (no key) | 14 |
| HIVG | Historical vs implied vol | FREE | From bars + chain | 14 |
| OSA | Multi-leg payoff and scenario | FREE | Vibe `options_payoff` | 14 |
| PCR | Put/call ratio, open interest by strike | FREE | From the chain | 14 |
| Unusual options flow | Block and sweep prints | PAID | Paid feeds only | - |

### Rates, credit, FX, commodities
| Code | What | Status | Source | Phase |
|---|---|---|---|---|
| YAS | Bond yield/price, duration, convexity | FREE | Vibe `quantlib.fixedincome` | 14 |
| SWPM, CDSW | Swap and CDS calculators (no market quotes) | FREE | Vibe `quantlib` (ISDA CDS, key-rate duration) | 14 |
| WIRP | Implied policy-rate path | FREE | Fed funds futures from Yahoo per-contract quotes | 14 |
| GC, WB | Non-US yield curves, world bond yields | FREE (daily patchy) | ECB SDW, BoE, FRED international series | 14 |
| CRPR, credit | Credit spread indices | FREE | FRED (ICE BofA OAS series) | 14 |
| Auctions | Treasury auction results and schedule | FREE | TreasuryDirect | 14 |
| CT, CTM | Futures term structure, contract table | FREE | Yahoo per-contract symbols | 14 |
| COT | Futures positioning | FREE | CFTC Socrata | 14 |
| FXFA | FX forwards from rate differentials | FREE | Computed (labelled as covered-interest-parity estimate) | 14 |
| NRG | Energy inventories, production | KEY (free) | EIA | 19 |
| WETR | Weather for commodity regions | FREE | NWS / Open-Meteo | 19 |

### Macro
| Code | What | Status | Source | Phase |
|---|---|---|---|---|
| ECST, WECO | World economic stats by country | FREE | DBnomics, World Bank, IMF, OECD, ECB | 19 |
| ECFC | Consensus forecasts | NO / PART | IMF WEO and OECD outlook projections only | 19 |
| CENB, FOMC | Central bank calendars and decisions | FREE | Agency calendars (Fed, ECB, BoE, RBI, BoJ) | 19 |
| Holidays | Exchange holiday calendars in market lights | FREE | Static yearly tables per exchange | 19 |

### Portfolio, risk, quant
| Code | What | Status | Source | Phase |
|---|---|---|---|---|
| PORT risk | VaR/ES, beta, drawdown, tail risk, factor exposure | FREE | Vibe `risk_xray`, `quantlib.risk` | 15 |
| PORT OPT | Optimizers: risk parity, mean-variance, max diversification, equal vol, turnover-aware, HRP | FREE | Vibe `backtest/optimizers`, `quantlib.portfolio` | 15 |
| PORT ATTR | Brinson attribution, TWR/MWR/XIRR | FREE | Vibe `quantlib.attribution`, `performance` | 15 |
| BTST | Backtester | FREE | Vibe engines | 12 |
| Factor library | 478 alphas, IC/IR, decay | FREE | Vibe Alpha Zoo + Strategy Development Manager | 15 |
| Fama-French | Factor returns for regressions | FREE | Ken French data library | 15 |
| Order entry, EMS | Orders with limits and kill switch | KEY | Alpaca paper, Zerodha Kite, IBKR | 18 |

### Charting and discovery
| Code | What | Status | Source | Phase |
|---|---|---|---|---|
| GP extras | Drawing tools, event markers, multi-pane compare | FREE | Frontend only | 19 |
| GIP | Intraday tick chart | PART | Live ticks since open; Yahoo 1m lookback | 19 |
| SEAS | Seasonality | FREE | From bars | 19 |
| Patterns | Candlestick, Ichimoku, SMC, harmonic | FREE | Vibe pattern tool | 19 |
| IMAP | Market heat map | FREE | EQS universe | 19 |
| SECF | Security finder with FIGI | KEY (optional) | OpenFIGI | 19 |
| L2 depth | Order book | FREE (crypto only) | Binance / OKX public depth | 19 |

### Workflow, AI, delivery
| Code | What | Status | Source | Phase |
|---|---|---|---|---|
| ALRT server-side | Alerts that fire with the tab closed | FREE | Backend scheduler | 17 |
| Push | Telegram, email, desktop notifications | KEY (free) | Telegram bot token, SMTP | 17 |
| BQL, Excel API | Query language and spreadsheet pull | FREE | REST + CSV + Python client | 17 |
| NOTE | Notes and theses attached to tickers | FREE | SQLite | 16 |
| AI assistant | Tool-grounded research agent | KEY | OpenRouter (any model) | 16 |
| SWARM desks | 5 lite + 30 Vibe-Trading desks with variables, cost estimate and your own YAML desks | KEY | OpenRouter (any model) | 16, 20 |
| MSG, IB chat | Messaging network | NO | Proprietary network | - |

## Vibe-Trading: what to bring over
Read from the code (`git clone --depth 1`, commit `d0db2e3`, 2026-10-17). License MIT (HKUDS); Qlib Alpha158
parts are Apache-2.0. Ported code keeps its notices in `THIRD_PARTY.md`.

| Vibe-Trading part | Where it lives | Bring over as | Phase |
|---|---|---|---|
| Backtest runner + `SignalEngine` contract (`generate(data_map) -> {code: Series in [-1, 1]}`) | `agent/backtest/runner.py`, `engines/` | `BT` engine and strategy format | 12 |
| Engines: global equity, India equity (STT/stamp/SEBI/GST), crypto spot + perps funding, futures, forex, options portfolio, composite | `agent/backtest/engines/` | `BT` engines (skip China A, Korea, Vietnam, Brazil unless asked) | 12 |
| 15 metrics, benchmark, Monte Carlo, Bootstrap, Walk-Forward, purged CV | `metrics.py`, `validation.py`, `quantlib/crossvalidation.py` | `BT`, `BT WF`, `BT MC` | 12 |
| Run cards (hashed execution records) | `run_card.py` | `BT` run history | 12 |
| 5 optimizers, rebalance masks, constraints | `optimizers/`, `rebalance_mask.py`, `constraints.py` | `PORT OPT`, `BT` sizing | 12, 15 |
| Risk x-ray, regime, correlation regime | `risk_xray.py`, `regime.py`, `correlation.py` | `RISK`, `CORR REGIME` | 15 |
| quantlib: 306 tested functions, 23 modules | `agent/src/quantlib/` | `QL`, `OV`, `YAS`, `SWPM`, `CDSW` | 14, 15 |
| Valuation: DCF, comps, three-statement; missing input = NOT RUNNABLE | `quantlib/valuation/` | `DCF`, `WACC`, `RV` | 13 |
| Alpha Zoo (478 alphas, lookahead-banned operators) + decay lifecycle | `agent/src/factors/zoo/`, `strategy_discovery/` | `ALPHA` (435 ported 2026-11-10 in families; 43 skipped with reasons in `docs/ALPHA_SKIPPED.md`) | 15 |
| Agent loop: tool grounding, loop guard, context budget, memory, skills | `agent/src/agent/` | `AI` (12 more read-only desk tools in Phase 20) | 16, 20 |
| 30 swarm presets (investment committee, risk committee, earnings desk...) | `agent/src/swarm/presets/` | `SWARM` (all 30 ported 2026-11-05, every one PARTIAL: no web, no shell, no China A-share; see `docs/PHASE_20_PRESETS.md`) | 16, 20 |
| 90 finance skills (markdown playbooks) | `agent/src/skills/` | Prompt library for `AI` and `SWARM` (46 of 89 ported, 43 skipped with reasons in `docs/PHASE_20_SKIPPED.md`) | 16, 20 |
| Hypothesis registry, Research Autopilot, thesis tracker | `hypotheses/`, `goal/` | `THESIS`, `AI AUTO` | 16 |
| Document reader (PDF/DOCX/XLSX + OCR), chart vision, web reader | `tools/doc_reader_tool.py`, `image_vision_tool.py` | `AI DOC` (OCR optional), `AI CHART`, `read_url` / `web_search` (opt-in, off by default, 2026-11-10) | 16 |
| Governance: run manifest, hash-chained audit ledger, sink-aware redaction | `governance/`, `tools/redaction.py` | Audit log for AI, BT and orders | 16 |
| Trade journal parsers + Shadow Account (behaviour diagnostics) | `tools/trade_journal_*`, `shadow_account/` | `JRNL` (built 2026-11-10: Zerodha, IBKR Flex, Alpaca, generic CSV; Shadow Account via BT jobs) | 17 |
| Scheduled research, IM channels (Telegram, Slack, email...) | `scheduled_research/`, `channels/` | `BRIEF`, push alerts (Telegram + email + desktop only) | 17 |
| MCP server + MCP client mode | `tools/mcp.py` | OpenTerm MCP server (HTTP and the `openterm-mcp` stdio command) and, since 2026-11-10, an MCP client (`MCP`, servers off until enabled, results untrusted); REST routes documented in `docs/API.md` | 17, 20 |
| Broker connectors with mandates (allowlist, size caps, daily cap, kill switch) | `trading/`, `live/` | `ORD` (built 2026-11-10: Alpaca paper and live, Kite live; mandate, confirm token, kill switch) and read-only `SYNC` (Kite, IBKR) | 18 |
| Exports: Pine Script, MT5, PDF, xlsx | `skills/pine-script`, `tools/pdf_report.py` | `BT EXPORT` (Pine, MQL5, PDF, XLSX built) | 12, 17 |
| Options chain / pricing / payoff tools | `tools/options_*` | `OMON`, `OV`, `OSA` | 14 |
| ETF look-through, 13F QoQ diffs, prediction markets, research papers | `tools/etf_holdings_tool.py`, `institutional_holdings_tool.py`, `prediction_market_tool.py`, `research_papers_tool.py` | `ETF`, `HDS` diffs, `PRED`, `AI` tool | 13, 19 |
| Crypto: perp funding/basis, liquidation heatmap, stablecoin flow, DeFi yield, token unlocks | `skills/crypto-*`, `tools/*` | `CRYP` sub-views | 19 |
| Local data loader (CSV/Parquet/DuckDB) | `loaders/local_loader.py` | `IMPORT` bring-your-own bars | 12 |

**Not porting:** China A-share flow tools (dragon-tiger, northbound, margin, tushare/akshare/eastmoney loaders),
Pixel Office, the 14 IM channels beyond Telegram/email, ZimaOS packaging, 16 of the 19 brokers, QVeris
(referral marketplace). Add any of them on request.

**Port carefully:** Vibe-Trading is pandas-heavy and agent-first. OpenTerm keeps its speed rules: lazy imports,
process-pool jobs, vectorized paths, results cached by hash, and no Python per-bar loops in hot paths.

## Not reachable even with keys
Consolidated real-time data and full-depth Level 2 for every equity venue; the other vendor's evaluated pricing and
CDS quotes; its news wire and intelligence research; supply-chain, ESG and loan/CLO databases; the chat network;
dealer execution. Broker research and consensus forecasts beyond IMF/OECD are paywalled.
