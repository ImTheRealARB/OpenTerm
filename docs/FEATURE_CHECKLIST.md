# Feature checklist: Bloomberg Terminal vs OpenBB vs OpenTerm

Written 2026-10-18 from this branch's code (100 function codes in `frontend/src/functions/registry.ts`, ~40 provider
adapters in `backend/openterm/providers/`). The Bloomberg and OpenBB columns come from public product knowledge, not
from running either product. OpenBB changes often, so check a cell before you act on it.

Bloomberg has tens of thousands of functions. This list groups them into the feature families a user would notice.

**Legend:** ✅ has it · ⚠️ partial, approximate, or only with a key / paid provider · ❌ does not have it

OpenBB here means the open-source Platform (Python ODP, CLI, REST, MCP server) plus OpenBB Workspace (the web app).
Many OpenBB ✅ cells need a paid provider key (FMP, Polygon, Intrinio, Benzinga, Tiingo).

---

## 1. Platform and workflow

| Feature | BBG | OpenBB | OpenTerm | OpenTerm function / note |
|---|:-:|:-:|:-:|---|
| Command line with mnemonic function codes | ✅ | ⚠️ | ✅ | Ctrl+K, `GP`, `FA`, ... (OpenBB CLI has commands; Workspace is mouse/widget based) |
| Keyboard-first, every action without a mouse | ✅ | ❌ | ✅ | |
| Tiled panels, saved named workspaces | ✅ | ✅ | ✅ | `LAYOUT` / `MONITOR` |
| Fuzzy security search, ISIN/CUSIP/SEDOL/FIGI lookup | ✅ | ✅ | ✅ | `SECF` (OpenFIGI) |
| Watchlists | ✅ | ✅ | ✅ | `WL` |
| In-app price / % alerts | ✅ | ❌ | ✅ | `ALRT` (evaluated in the browser) |
| Alert delivery (email, SMS, Telegram, mobile push) | ✅ | ❌ | ❌ | Phase 17, paused |
| Themes, vim mode, custom keybindings, clocks | ⚠️ | ⚠️ | ✅ | `SETTINGS`, `THEME` |
| Data-source health, latency, quota screen | ❌ | ❌ | ✅ | `SOURCES`, `PERF`, `LOG` |
| STALE / ERR / PROVIDER DOWN labels with source and age | ⚠️ | ❌ | ✅ | |
| Excel add-in (live formulas) | ✅ | ✅ | ❌ | CSV export only (`E` / Alt+X) |
| Python library / SDK | ✅ | ✅ | ❌ | OpenBB's main strength |
| REST API for your own scripts | ✅ | ✅ | ⚠️ | Local FastAPI backend exists; not documented as a public API |
| MCP server (use the data from Claude, other AI clients) | ❌ | ✅ | ❌ | Phase 17, paused |
| Bring your own data / custom widgets | ⚠️ | ✅ | ⚠️ | `IMPORT` takes daily-bar CSVs only |
| Notes and research reports, PDF export | ✅ | ✅ | ⚠️ | `THESIS` notes; no PDF/report export |
| Multi-user sharing, teams | ✅ | ✅ | ❌ | Single user, local |
| Chat network (Instant Bloomberg / MSG) | ✅ | ❌ | ❌ | Bloomberg's network effect; not buildable |
| Mobile app | ✅ | ⚠️ | ❌ | Web only |
| Desktop app | ✅ | ✅ | ⚠️ | Tauri shell written in `desktop/`, never built |
| Free and open source | ❌ | ✅ | ✅ | BBG about US$30k per seat per year |

## 2. Market data and monitors

| Feature | BBG | OpenBB | OpenTerm | OpenTerm function / note |
|---|:-:|:-:|:-:|---|
| Live streaming quotes | ✅ | ⚠️ | ⚠️ | Yahoo stream (keyless, some exchanges delayed); Alpaca / Finnhub / Tradier with a free key |
| Quote monitor, quote recap | ✅ | ✅ | ✅ | `Q`, `QR` |
| Every global exchange, exchange-direct feeds | ✅ | ⚠️ | ⚠️ | Whatever Yahoo covers |
| Equity Level 2 / market depth | ✅ | ❌ | ❌ | Crypto depth only (`CDEP`) |
| Time and sales, historical tick data | ✅ | ⚠️ | ⚠️ | `GIP` builds candles from ticks seen since the session began; no tick history |
| Intraday and daily history table | ✅ | ✅ | ✅ | `HIST`, `GP 5MIN/1H` |
| World indices board | ✅ | ✅ | ✅ | `WEI` |
| Top movers (gainers, losers, active, dollar volume) | ✅ | ✅ | ✅ | `MOV` |
| Market heat map | ✅ | ⚠️ | ✅ | `IMAP` (by sector, industry, country) |
| FX rates, cross matrix | ✅ | ✅ | ✅ | `FX`, `FXC` |
| Commodities board | ✅ | ✅ | ✅ | `CMDTY` |
| Crypto board | ✅ | ✅ | ✅ | `CRYP` |
| India: Kite Connect, NSE history, AMFI fund NAVs | ⚠️ | ❌ | ✅ | `KITE` (read-only), `SECF` fund rows |

## 3. Charting and technical analysis

| Feature | BBG | OpenBB | OpenTerm | OpenTerm function / note |
|---|:-:|:-:|:-:|---|
| Candle / OHLC / line / area, log scale | ✅ | ✅ | ✅ | `GP` |
| 20+ indicators (SMA, EMA, BB, RSI, MACD, VWAP, ATR, Ichimoku, SuperTrend, PSAR, ...) | ✅ | ✅ | ✅ | `GP` |
| Compare securities on one chart | ✅ | ✅ | ✅ | `GP VS SYM` |
| Drawing tools (saved per symbol) | ✅ | ⚠️ | ✅ | `GP` drawings |
| Candlestick and smart-money pattern detection | ⚠️ | ❌ | ✅ | `GP PAT:CANDLE`, `PAT:SMC` |
| Seasonality | ✅ | ❌ | ✅ | `SEAS` |
| Relative rotation graph (RRG) | ✅ | ✅ | ❌ | |
| Volatility cones | ✅ | ✅ | ⚠️ | `HIVG` has rolling realized vol, not cones |
| Fibonacci, DeMark, pivot points, Clenow | ✅ | ✅ | ❌ | |
| Chart events (earnings, dividends) on the chart | ✅ | ⚠️ | ✅ | `ChartView` events |

## 4. Company research and fundamentals

| Feature | BBG | OpenBB | OpenTerm | OpenTerm function / note |
|---|:-:|:-:|:-:|---|
| Company description | ✅ | ✅ | ✅ | `DES` |
| Financial statements (IS, BS, CF, annual / quarterly) | ✅ | ✅ | ⚠️ | `FA`, US SEC filers only (BBG is global and standardized) |
| Revenue by segment and geography | ✅ | ⚠️ | ❌ | `SEG` dropped: only paid sources |
| Ratios and key metrics | ✅ | ✅ | ⚠️ | Inside `FA`, `COMP`, `RV` |
| Analyst estimates, revisions, surprises | ✅ | ⚠️ | ✅ | `EE`, `EEO` |
| Analyst ratings and price targets | ✅ | ⚠️ | ✅ | `ANR` |
| Earnings calendar | ✅ | ✅ | ✅ | `ERN` |
| Earnings call transcripts | ✅ | ⚠️ | ❌ | No free source |
| Live earnings call audio | ✅ | ❌ | ❌ | |
| Management, governance, proxy statements | ✅ | ✅ | ✅ | `MGMT` |
| Executive compensation tables | ✅ | ⚠️ | ⚠️ | Proxy statements linked in `MGMT` |
| Company events (8-K by item) | ✅ | ⚠️ | ✅ | `EVTS` |
| Dividends, splits, corporate actions | ✅ | ✅ | ✅ | `DVD`, `SPLT`, `CACS` |
| IPO calendar | ✅ | ✅ | ✅ | `IPO` |
| Peer comparison, relative valuation | ✅ | ✅ | ✅ | `COMP`, `RV` |
| DCF and WACC models | ✅ | ❌ | ✅ | `DCF`, `WACC` |
| SEC filings browser | ✅ | ✅ | ✅ | `FIL` / `SEC` |
| Full-text search across filings and documents | ✅ | ⚠️ | ⚠️ | `AI DOC FILING` reads one filing; no search across filings |
| Institutional holders (13F), manager positions | ✅ | ✅ | ✅ | `HDS`, `MGR` |
| Insider transactions | ✅ | ✅ | ✅ | `OWN` |
| Short interest, short sale volume | ✅ | ✅ | ✅ | `SI` (FINRA) |
| Securities lending, borrow fee | ✅ | ❌ | ❌ | |
| Dark pool / OTC (ATS) volume | ✅ | ✅ | ❌ | FINRA publishes it free |
| Fails-to-deliver | ✅ | ✅ | ❌ | SEC publishes it free |
| Congress / government official trades | ❌ | ⚠️ | ❌ | |
| ESG scores | ✅ | ⚠️ | ❌ | No free source |
| Supply chain, customers, suppliers | ✅ | ❌ | ❌ | |
| M&A deals, league tables, company trees | ✅ | ❌ | ❌ | |
| Sell-side research, Bloomberg Intelligence | ✅ | ❌ | ❌ | Licensed content |
| Credit ratings (S&P, Moody's, Fitch) | ✅ | ❌ | ❌ | Licensed content |
| Equity screener | ✅ | ✅ | ✅ | `EQS`, whole US universe (BBG is global) |

## 5. News

| Feature | BBG | OpenBB | OpenTerm | OpenTerm function / note |
|---|:-:|:-:|:-:|---|
| Market news feed | ✅ | ✅ | ✅ | `N` (RSS, Yahoo RSS, GDELT) |
| Company news | ✅ | ✅ | ✅ | `CN` |
| Proprietary first-to-market newswire | ✅ | ❌ | ❌ | |
| News sentiment | ✅ | ⚠️ | ⚠️ | `CN` keyword scoring, not a model |
| News alerts | ✅ | ❌ | ⚠️ | `ALRT` news alerts in-app; no delivery |

## 6. Funds, ETFs, indices

| Feature | BBG | OpenBB | OpenTerm | OpenTerm function / note |
|---|:-:|:-:|:-:|---|
| ETF profile and full holdings | ✅ | ✅ | ✅ | `ETF` (SEC N-PORT) |
| Index members and weights | ✅ | ⚠️ | ⚠️ | `MEMB` via the proxy ETF, not the official index file |
| Fund / ETF screener | ✅ | ⚠️ | ❌ | |
| Fund flows | ✅ | ❌ | ❌ | |
| Mutual fund NAVs | ✅ | ⚠️ | ⚠️ | India AMFI only (`SECF`) |

## 7. Options and futures

| Feature | BBG | OpenBB | OpenTerm | OpenTerm function / note |
|---|:-:|:-:|:-:|---|
| Option chain with IV and Greeks | ✅ | ✅ | ✅ | `OMON` |
| Put/call ratio | ✅ | ⚠️ | ✅ | `PCR` |
| Option pricer (BS, binomial, Heston, barrier) | ✅ | ❌ | ✅ | `OV` |
| Multi-leg strategy payoff and scenarios | ✅ | ❌ | ✅ | `OSA` |
| Vol surface, skew, realized vs implied | ✅ | ⚠️ | ✅ | `OVDV`, `SKEW`, `HIVG` |
| Unusual options activity | ✅ | ⚠️ | ❌ | |
| Historical option prices | ✅ | ⚠️ | ❌ | Live chain only |
| Futures term structure, roll yield | ✅ | ✅ | ✅ | `CT` |
| Commitments of Traders | ✅ | ✅ | ✅ | `COT` |
| Implied fed funds path | ✅ | ❌ | ✅ | `WIRP` |
| Crypto derivatives (funding, basis, liquidations, Deribit vol) | ⚠️ | ⚠️ | ✅ | `FUND`, `LIQ`, `OVDV` |

## 8. Fixed income, credit, FX

| Feature | BBG | OpenBB | OpenTerm | OpenTerm function / note |
|---|:-:|:-:|:-:|---|
| Government yield curves (US, EUR, GBP, CAD, JPY) | ✅ | ✅ | ✅ | `RATES` |
| Treasury auctions | ✅ | ✅ | ✅ | `RATES AUCT` |
| Credit spread indices (ICE BofA OAS) | ✅ | ✅ | ✅ | `RATES SPRD` |
| Money market rates (SOFR, EFFR, ESTR, SONIA) panel | ✅ | ✅ | ⚠️ | Only as single FRED series (`FRED`) |
| Bond yield / risk calculator | ✅ | ❌ | ✅ | `YAS` (you type the terms) |
| Corporate bond search and prices (TRACE) | ✅ | ⚠️ | ❌ | |
| Munis, MBS, ABS, loans | ✅ | ❌ | ❌ | |
| Dealer quotes (ALLQ), BVAL prices | ✅ | ❌ | ❌ | Licensed |
| Swap valuation | ✅ | ❌ | ⚠️ | `SWPM` on the Treasury curve (not SOFR) |
| CDS market spreads | ✅ | ❌ | ⚠️ | `CDSW` values your inputs only |
| FX forwards | ✅ | ❌ | ⚠️ | `FXFA` by covered interest parity, not dealer points |
| FX option vol surface | ✅ | ❌ | ❌ | |

## 9. Economy and macro

| Feature | BBG | OpenBB | OpenTerm | OpenTerm function / note |
|---|:-:|:-:|:-:|---|
| Economic calendar | ✅ | ✅ | ⚠️ | `ECO`: dates from BLS / BEA / FOMC; no consensus, actual or surprise |
| FRED search and charts | ✅ | ✅ | ✅ | `MACRO`, `FRED` |
| World stats by country (World Bank, IMF) | ✅ | ✅ | ✅ | `ECST`, `WECO` |
| OECD, BLS, IMF direct datasets | ✅ | ✅ | ⚠️ | Via DBnomics (`ECST DBN:`) |
| Central bank rates and meeting calendar | ✅ | ⚠️ | ✅ | `CENB` |
| Economist forecasts (consensus by indicator) | ✅ | ❌ | ❌ | |
| Shipping, port volumes, trade flows | ✅ | ✅ | ❌ | IMF PortWatch is free |
| Prediction market odds | ❌ | ❌ | ✅ | `PRED` (Polymarket, Kalshi) |

## 10. Commodities and world

| Feature | BBG | OpenBB | OpenTerm | OpenTerm function / note |
|---|:-:|:-:|:-:|---|
| Energy prices board | ✅ | ✅ | ✅ | `NRG` |
| EIA inventories, production, short-term outlook | ✅ | ✅ | ❌ | FRED CSV 404s these; needs the free EIA key |
| USDA crop supply and demand (WASDE / PSD) | ✅ | ✅ | ❌ | |
| Weather for commodities | ✅ | ❌ | ✅ | `WETR` (degree days, forecasts, NWS alerts) |
| Maps (ships, pipelines, power plants) | ✅ | ❌ | ❌ | |

## 11. Crypto

| Feature | BBG | OpenBB | OpenTerm | OpenTerm function / note |
|---|:-:|:-:|:-:|---|
| Prices board | ✅ | ✅ | ✅ | `CRYP` |
| Order book depth | ⚠️ | ❌ | ✅ | `CDEP` |
| Stablecoin supply, DeFi yields | ⚠️ | ❌ | ✅ | `STBL`, `DEFI` |
| Token unlocks | ⚠️ | ❌ | ❌ | `UNLK` placeholder: only paid source |
| On-chain metrics (addresses, flows, whales) | ⚠️ | ❌ | ❌ | |

## 12. Portfolio and risk

| Feature | BBG | OpenBB | OpenTerm | OpenTerm function / note |
|---|:-:|:-:|:-:|---|
| Portfolio with live P&L, multi-currency, CSV import | ✅ | ⚠️ | ✅ | `PORT` |
| VaR, expected shortfall, stress tests, VaR backtest | ✅ | ❌ | ✅ | `RISK` |
| Optimizer (HRP, risk parity, mean-variance, ...) | ✅ | ❌ | ✅ | `OPT` |
| Performance attribution (Brinson, TWR, MWR) | ✅ | ❌ | ✅ | `ATTR` |
| Factor regression (Fama-French) | ✅ | ⚠️ | ✅ | `FACT` |
| Broker holdings sync | ✅ | ❌ | ❌ | `KITE` is read-only market data, no holdings |
| Tax lots, realized gains | ✅ | ❌ | ❌ | |

## 13. Quant and backtesting

| Feature | BBG | OpenBB | OpenTerm | OpenTerm function / note |
|---|:-:|:-:|:-:|---|
| Backtester with fees and slippage | ✅ | ❌ | ✅ | `BT` (rules, strategy code sandbox, stored runs) |
| Quant calculators (GARCH, OU, cointegration, VPIN, ...) | ⚠️ | ⚠️ | ✅ | `QL` |
| Alpha factor library with IC / IR / decay | ⚠️ | ❌ | ✅ | `ALPHA` |
| Correlation matrix and regimes | ✅ | ✅ | ✅ | `CORR`, `REGIME` |
| Econometrics (OLS, panel, Granger causality) | ✅ | ✅ | ⚠️ | Only `COINT`, `ADF`, `HEDGE` in `QL` |
| Sharpe / Sortino / Omega / CAPM as standalone stats | ✅ | ✅ | ⚠️ | Inside `BT` and `RISK` output |
| Notebook environment (BQuant / Jupyter) | ✅ | ✅ | ❌ | |
| Background jobs with progress and cancel | ⚠️ | ❌ | ✅ | `JOBS` |

## 14. AI

| Feature | BBG | OpenBB | OpenTerm | OpenTerm function / note |
|---|:-:|:-:|:-:|---|
| AI assistant grounded in the terminal's data, with citations | ✅ | ✅ | ✅ | `AI` (needs OpenRouter key) |
| AI questions over a filing or document | ✅ | ✅ | ✅ | `AI DOC` |
| AI writes and runs a backtest | ❌ | ⚠️ | ✅ | `AI BT`, `AI AUTO` |
| Multi-agent analyst desks | ❌ | ⚠️ | ✅ | `SWARM` |
| Hash-chained audit log of AI runs | ❌ | ❌ | ✅ | `AUDIT` |
| News and earnings-call summaries | ✅ | ⚠️ | ❌ | No transcripts |
| Choose any model | ❌ | ✅ | ✅ | Any OpenRouter model, daily spend cap |

## 15. Trading

| Feature | BBG | OpenBB | OpenTerm | OpenTerm function / note |
|---|:-:|:-:|:-:|---|
| Order entry / execution management | ✅ | ❌ | ❌ | Phase 18, paused |
| Paper trading | ⚠️ | ❌ | ❌ | Phase 18, paused |
| Broker connections | ✅ | ❌ | ⚠️ | `KITE` data only, by design no orders |

---

## What OpenTerm can't do yet (the to-do checklist)

Grouped by how reachable each one is. "Free" means a keyless or free sign-up source exists, as far as I know;
check each source's terms and bot checks before building.

### Free data exists: could be built
- [ ] Dark pool / OTC (ATS) weekly volume (FINRA OTC transparency)
- [ ] Fails-to-deliver (SEC CSV files)
- [ ] Relative rotation graph (from daily bars already fetched)
- [ ] Fibonacci, pivot points, DeMark, volatility cones on `GP`
- [ ] Econometrics in `QL`: OLS, Granger causality, panel regression (statsmodels is already a worker dependency)
- [ ] Standalone performance-ratio panel (Sharpe, Sortino, Omega, CAPM beta/alpha)
- [ ] Money-market rates panel (SOFR, EFFR, ESTR, SONIA)
- [ ] Shipping and port volumes (IMF PortWatch)
- [ ] ETF / fund screener (SEC N-PORT / N-CEN data)
- [ ] Unusual options activity, computed from live chains (volume vs open interest), labelled as computed here
- [ ] Full-text search across SEC filings (SEC EDGAR full-text search)
- [ ] PDF / report export of a panel or layout

### Needs a free API key
- [ ] EIA inventories, production and short-term energy outlook
- [ ] USDA crop supply and demand
- [ ] Corporate bond prices (FINRA TRACE, free account)

### Paused by you (Phases 17-18)
- [ ] Alert delivery (email, Telegram, push)
- [ ] MCP server so Claude and other AI clients can use OpenTerm data
- [ ] Paper trading, then broker orders behind a mandate and kill switch

### Platform gaps
- [ ] Excel add-in (or a documented REST / web-query endpoint Excel can pull)
- [ ] Python client library and documented public REST API
- [ ] Desktop build (Tauri written, never built) and a mobile layout
- [ ] Custom data widgets beyond daily-bar CSV import
- [ ] Multi-user sharing

### Paid-only or not buildable (Bloomberg's moat; OpenBB mostly lacks these too)
- [ ] Equity Level 2, exchange-direct real-time on every exchange, tick history
- [ ] Earnings call transcripts and audio
- [ ] Segment and geographic revenue (`SEG` dropped)
- [ ] ESG scores, credit ratings, sell-side research, Bloomberg Intelligence
- [ ] Supply chain, M&A deals, league tables
- [ ] Munis, MBS, ABS, loans, dealer quotes, BVAL
- [ ] CDS and FX-option market quotes, historical options data
- [ ] Economist consensus forecasts and ECO actual-vs-consensus surprises
- [ ] Securities lending / borrow fees, fund flows, token unlocks, on-chain analytics
- [ ] Chat network (IB), proprietary newswire, ship and pipeline maps

## What OpenTerm has that OpenBB does not

- Keyboard-first command line with Bloomberg-style mnemonics, tiled panels, vim mode
- Backtester (`BT`) with stored runs, strategy sandbox, AI-written backtests
- Portfolio risk, optimizer and attribution (`RISK`, `OPT`, `ATTR`)
- Option pricer and multi-leg analysis (`OV`, `OSA`), implied fed path (`WIRP`), bond and swap calculators (`YAS`, `SWPM`, `CDSW`)
- DCF and WACC (`DCF`, `WACC`)
- Alpha factor zoo and correlation regimes (`ALPHA`, `REGIME`)
- Multi-agent AI desks with a hash-chained audit ledger (`SWARM`, `AUDIT`)
- Prediction markets, crypto depth / funding / liquidations / DeFi, commodity weather (`PRED`, `CDEP`, `FUND`, `LIQ`, `DEFI`, `WETR`)
- India: Kite Connect data, NSE history, AMFI NAVs
- Zero keys works; every failure shows STALE / ERR with source and age; a data-source health screen
