# Commands to try

Start the app by typing `openterm` (after the one-time `.\scripts\install-launcher.ps1`), or with `.\scripts\start.ps1` (or `./scripts/start`), then type in the command line at the top.
`Enter` runs in the focused panel, `Shift+Enter` in a new panel; press `/` first if the cursor is elsewhere.
Grammar: `[N:] SECURITY [MARKET] FUNCTION [ARGS]` or `[N:] FUNCTION [ARGS]`. The ticker comes first: `AAPL DES`,
not `DES AAPL`. A panel remembers its last ticker, so a bare `GP` or `FA` uses it.

Live mode works for any ticker. Fixture mode (`OPENTERM_FIXTURES=1`) only has recorded data for a few, mainly AAPL and MSFT.
`FA`, `FIL` and `OWN` need `$env:SEC_USER_AGENT = 'Your Name you@example.com'` set before starting the backend.

## Help
```
HELP                  every function
HELP GP               help for one function
SHORTCUTS             all keyboard shortcuts (or ?)
```

## Plain English, templates, indicators
```
apple stock price chart          -> AAPL GP (the command it understood is shown, so you learn the codes)
apple vs microsoft 1 year        -> AAPL chart over 1 year compared with MSFT (% change)
tech stocks under 50 dollars     -> EQS with sector and price filters (words it did not understand are listed)
TMPL                             ready-made workspaces; TMPL DAY / LONGTERM / MACRO / INDIA apply one (asks before replacing panels)
IND                              indicator library: search 109 indicators, F = your own formula, S / L = save / load a preset
AAPL GP ATR(14)                  library indicator on the chart; GP args also take LIB:CMF and F:<formula>
```
On a GP chart: `A` sets a price alert at the crosshair (or last price), Shift+A then a click sets one at the clicked price, Alt+click always does.
In GUI mode, hover a table's column header or press Shift+T for a one-line explanation, and `BT` offers a sentence-style rule builder.

## One stock (AAPL as the example)
```
AAPL DES              profile, valuation, 52-week range
AAPL QR               live quote recap
AAPL GP               1-year price chart
AAPL GP 5Y W LOG      5 years, weekly, log scale
AAPL GP 5D 15MIN      intraday
AAPL GP 1Y RSI MACD   indicators (SMA20 SMA50 EMA20 BB RSI MACD VWAP)
AAPL GP VS SPY        relative performance in %
AAPL HIST 3M          daily price table
AAPL N                company news
AAPL FA               income statement, annual (FA Q = quarterly; FA A BS / FA A CF)
AAPL FIL 10-K         SEC filings, one form type
AAPL OWN              insider trades (Form 4)
AAPL HDS              institutional and fund holders
AAPL COMP             peers with median and 1M-1Y returns
AAPL EE / EEO / ANR   estimates, revisions and surprises / analyst ratings and targets
AAPL MGMT             officers, governance scores, proxy statements
AAPL DVD / SPLT / CACS   dividends / splits / both merged;  AAPL SI  short interest;  AAPL EVTS  8-K items
AAPL CN               company news from every source, keyword score (NOT A MODEL)
AAPL DCF ERP=5.5 G=2.5 EXITX=14   valuation (NOT RUNNABLE lists missing inputs);  WACC;  RV PEERS=MSFT,GOOGL
AAPL ETF / MEMB SPX / MGR BERKSHIRE   ETF holdings (SEC N-PORT) / index members / manager 13F changes
IPO 2026-10           IPO calendar for a month
ALRT NEWS RECALL AAPL   alert when a newer AAPL headline contains the word (omit the symbol for market top stories)
RELIANCE IN GP        non-US: market code (IN, BO, LN, JP, HK, GR, CN, AU) or suffix (RELIANCE.NS)
```
Chart keys: `1`-`8` range, `c` type, `i` indicators, `←`/`→` pan, `+`/`-` zoom, `x` crosshair, `l` log.

## Indices, FX, crypto, commodities
```
WEI                           world indices
SPX GP                        aliases: SPX NDX NIFTY SENSEX EURUSD BTCUSD ...
Q SPX NDX NIFTY SENSEX        live monitor of anything
FX                            currency rates
FXC USD EUR GBP INR JPY       cross-rate matrix
EURUSD GP 5D 1H               FX chart
CRYP                          crypto board (CRYP INR for rupee prices)
ETH-USD GP 1Y LOG             crypto chart
CMDTY                         commodities
GC=F GP                       Yahoo futures tickers pass through as typed
CORR SPX NIFTY NDX 5Y         correlation matrix
```

## Macro and calendars
```
RATES                 Treasury yield curve and spreads
FRED UNRATE           any FRED series: DGS10, CPIAUCSL, GDP, FEDFUNDS ... [1Y|2Y|5Y|10Y|20Y|MAX]
MACRO                 common FRED series (MACRO housing searches; full search needs FRED_API_KEY)
ECO 30 MAJOR          US economic releases, next 30 days, major only
ERN TODAY             earnings calendar (TOMORROW, +7, -3, YYYY-MM-DD)
```

## News and scans
```
N                     top market news (N TOP forces top stories)
N oil prices          news search (GDELT, slow: 5-15 s)
N TECH                feeds by section: TECH INDIA MARKETS ECONOMY COMPANIES COMMODITIES CRYPTO WORLD ALL
N COUNTRY IN          feeds by country / area (IN US CN UK EU JP WORLD)
N SECTOR BANKS        feeds by sector (tech banks energy pharma autos retail realestate telecom metals)
N COMMODITY GOLD      feeds by commodity (oil gold silver copper gas wheat corn coffee lithium)
N SEARCH rate cut     quick search over every feed (all words must appear); filters combine: N TECH COUNTRY IN SEARCH chip
MOV GAINERS           LOSERS ACTIVE DOLLAR NDX100
EQS SECTOR=TECH MCAP>100B SORT=PCT     screener (PRICE<50 VOL>1M PCT>2 COUNTRY=US ...)
```

## Your own data
```
WL TECH ADD AAPL MSFT NVDA     watchlist (WL TECH opens it; WL DEL TECH deletes)
PORT MAIN ADD AAPL 50 180      portfolio lot: symbol, quantity, cost [, currency]
PORT MAIN                      live P&L; PORT MAIN EXPORT / IMPORT; PORT MAIN BASE INR
ALRT AAPL > 250                price alert (ALRT MSFT -5% = percent move)
ALRT                           list; ALRT DEL id, ALRT REARM id, ALRT CLEAR (triggered ones)
ALRT AAPL > 250 VIA TG,EMAIL   send this alert only to Telegram and email (TG = Telegram; also EMAIL, WEBHOOK; ALRT NEWS RECALL VIA WEBHOOK works too). No VIA = every channel switched on in DELIVERY. A chosen channel that is switched off is logged as skipped: CHANNEL OFF
ALRT alerts are checked by the OpenTerm server, so they fire with the browser closed (only while OpenTerm runs); the panel shows the engine state and why an alert was skipped (stale, synthetic or fixture data)
```
Clean up: `PORT DEL MAIN`, `WL DEL TECH`, `ALRT DEL <id>`, `LAYOUT DEL <name>`.

## Backtest (historical simulation, not a forecast)
```
BT AAPL SMA20>SMA50 1D 5Y                 a rule on 5 years of daily bars; V cycles CHART METRICS TRADES CODE
BT SPY,QQQ RSI14<30 1D 10Y SHORT FEES=5   several symbols, shorts allowed, fees in bps (SLIP=, CASH=, BENCH=SPY, MKT=india)
BT RELIANCE.NS RSI14<30 1D 10Y            India engine (STT, stamp duty, GST); also BTCUSDT.P (perp + funding), EURUSD=X, ES=F
BT AAPL,BTCUSDT.P CLOSE>SMA50             several markets in one shared-capital run (one currency only)
BT MC AAPL SMA20>SMA50 1D 10Y             run it, then shuffle its trades (Monte Carlo) + bootstrap Sharpe interval; M on an open run
BT WF AAPL SMA20>SMA50 1D 10Y             run it, then walk-forward windows; W on an open run
BT RUNS                                   stored runs (last 200): Enter opens, C marks two to compare, V switches to equity lines
BT OPEN <runid>   BT EXPORT <runid> PINE  open a run; export Pine Script (rule runs) or TRADES / EQUITY / METRICS as CSV (P, E in a run)
BT SAVE golden SMA20>SMA50                save a rule;  BT AAPL @golden 1D 5Y  runs it;  BT DEL golden removes it
BT EDIT mysma                             Python strategy editor (SignalEngine): a new name first offers templates (SMA cross, RSI mean reversion, breakout); T after Esc reopens them; sandbox errors show under the line; Ctrl+S save, Ctrl+Enter save and run; BT EDIT lists them
IMPORT MYBARS                             paste daily bars (date,open,high,low,close[,volume]); then GP MYBARS or BT MYBARS CLOSE>SMA20
IMPORT                                    list imported symbols (D twice removes; IMPORT DEL MYBARS)
```
Rule terms: `CLOSE OPEN HIGH LOW VOLUME SMAn EMAn RSIn HIGHn LOWn RETn`, numbers; `> < >= <= CROSS> CROSS<`; `AND OR`.
Orders fill at the next bar's open. Every result says HISTORICAL SIMULATION, NOT A FORECAST and shows its data sources, fees
and slippage. Imported bars are labelled LOCAL DATA. Python strategies run in a restricted worker (no files, no network).

## Workspace and app
```
LAYOUT SAVE MYDESK    save panels (LAYOUT lists, LAYOUT MYDESK loads, Ctrl+S / Ctrl+O)
THEME GREEN           AMBER GREEN WHITE LIGHT
SETTINGS              vim mode, clocks, number format, refresh rates, key rebinding, interface mode
SETTINGS FONT Fira Code   switch font: presets JetBrains Mono (default), GitHub Mono, Geist Mono, Fira Code, Mononoki, Hack, Monaco, DejaVu Sans Mono, Menlo, Consolas, Comic Sans; NEXT / PREV step through them; any other installed font name works too. GUI mode: the font dropdown in the menu bar
SETTINGS MODE GUI     GUI mode: menu bar, sidebar, panel buttons (SETTINGS MODE TERMINAL, or Alt+G, switches back)
Alt+H                 GUI mode: help drawer for the focused panel
SOURCES               data source health and latency
APIKEYS               optional API keys: Enter edit (masked), T test, D twice delete, O sign-up page, C AI spend cap
DLVR                  alert delivery: Up/Down move, Space on/off, Enter type a NEW recipient (the address and chat id are never shown, only a masked hint; empty keeps the stored one; Esc cancels), T test, L log, P pair Telegram (shows the bot link and a one-time code OT-123456 valid 10 min; send it to the bot, then C checks). Email, Telegram, webhook, desktop, brief schedule
BRIEF                 last daily brief: R build now, S build and send
JOBS                  background jobs: Esc/X cancel, R re-run, C clear finished (JOBS TEST 20 100 runs a test job)
LOG                   backend log
PERF                  performance monitor (PERF GRID 10000, PERF CHART 50000 load tests)
```
Keys: `Ctrl+\` / `Ctrl+-` split, `Alt+1..9` focus, `Alt+W` close, `Ctrl+Shift+F` maximize, `Ctrl+[` / `Ctrl+]`
panel history, `E` or `Alt+X` export a table to CSV.

A four-panel macro desk: `RATES` (Enter), then `FRED CPIAUCSL`, `FX`, `CRYP` (each Shift+Enter), then `LAYOUT SAVE MACRO`.

## Phase 14 step 7: futures, policy and calculators

`CT CL` futures curve (contango or backwardation, spread to front, roll yield; `C` charts the curve) · `WIRP` implied fed funds path across FOMC meetings · `COT ES` CFTC positions, weekly change, 3-year net chart and
percentile (`COT CRUDE`, `COT GOLD`, or part of a CFTC market name) · `FXFA EURUSD [1W,1M,3M] [R1=pct R2=pct]` forward estimate by covered interest parity · `YAS CPN=4.5 MAT=2034-05-15 YLD=4.7` (or `PX=` clean price;
`FREQ= SETTLE= DAYS=ACT/ACT|30/360 FACE=`) · `SWPM N=10000000 FIXED=4.0 TENOR=5 DIR=PAY|REC [FREQ= CURVE=TSY|FLAT:4.0]` · `CDSW SPREAD=150 REC=40 TENOR=5 RF=3 COUPON=100 N=10000000`. The calculators never default an
opinion: a missing input shows `NOT RUNNABLE: MISSING ...`.

### BT options (Phase 14)
`BT <UNDERLYING> MKT=options` runs the last `OSA` structure for that symbol (API: `engine="options"` plus `structure`). Option prices are Black-Scholes marks on trailing historical vol
(`MODEL-PRICED OPTIONS (BLACK-SCHOLES ON HISTORICAL VOL), NOT MARKET QUOTES`). A missing structure field gives `NOT RUNNABLE: MISSING <fields>`. `FEES=` is bps of premium; slippage is not modelled.

## Phase 16: AI (needs your OpenRouter key in `APIKEYS`; without one it says KEY REQUIRED)
`AI [question]` research assistant. It answers from tools (quotes, history, filings, news, screener, options, rates, macro, your portfolio, backtests, quant jobs), shows every tool call with source and age,
cites them as [T1], and says UNGROUNDED when no tool returned data or UNSOURCED NUMBERS for figures no tool returned. `I` types, Enter sends, Esc cancels, `X` clears. AI output is model output, not data.
`AI BT <idea in words>` drafts one backtest rule (checked with the BT parser, shown with its command; the AI never runs it: `B` puts the command on the command line, Enter runs it).
`AI CHART` sends the chart of your newest `GP` panel to the vision model (labelled CHART IMAGE ONLY). `AI` playbooks (valuation, earnings, options, risk, macro) load automatically when a question needs them.
`AI DOC FILING <SYMBOL> [FORM]` loads the latest SEC filing of that form (default 10-K); `U` in the AI panel uploads a TXT, CSV, HTML, DOCX, XLSX or PDF (10 MB, kept in memory only, the last 5).
While a document is loaded, questions use ONLY its text (chunks C1, C2... cited); `AI DOC OFF` goes back to market data. Scanned PDFs need OCR, which is not built.

`AI AUTO <hypothesis>` turns a hypothesis into one rule, backtests it (`backtest_run`, a stored BT run) and writes an evidence report; the EVIDENCE line names the BT run ids, or says NO BACKTEST WAS RUN. The run is stored.
`SWARM [COMMITTEE|RISK|EARNINGS|MACRO|QUANT] <subject>` runs a preset desk (the 5 original desks are the "lite" desks; Phase 20 adds 30 more, see the SWARM desks section below): analyst roles with their own tool lists, then a chair. A failed role is retried once and shown if it still fails; the chair's figures are checked against the analysts' notes. `SWARM` lists presets and stored runs; `SWARM REPLAY <id>` shows a stored run again with no model call. `T` saves the desk answer as a THESIS note, `Esc` cancels.
`THESIS [SYMBOL]` lists thesis notes (status, invalidation rule, linked runs); `THESIS ADD <SYMBOL> <text>`, `THESIS INVALID <id> <rule>`; `S` cycles the status, `D` `D` deletes, Up/Down select.
`AUDIT` shows the hash-chained ledger of AI, SWARM, AI AUTO and BT runs (manifest hashes, question/answer hashes, tool calls; no text), verifies the chain on open and says where it breaks; `R` verifies again. Note the HEAD hash to detect removal of the newest entries.
`SETTINGS AI MODEL <id>` / `VISION <id>` / `PROVIDER OPENROUTER|OPENAI|ANTHROPIC|OLLAMA` / `RESET` (default `deepseek/deepseek-v4-pro`; the AI rows in `SETTINGS` cycle common models).

### AI FILING (Phase 20): answers from a 10-K / 10-Q with machine-checked quotes
`AI FILING <SYMBOL> <question>` answers from the newest 10-K or 10-Q of a US filer; `AI FILING <SYMBOL> [10-K|10-Q] DRIVERS` asks what drives revenue, margins and risk. Name `10-K` or `10-Q` after the symbol to pick the form.
How it works: OpenTerm downloads the filing from SEC EDGAR (needs `SEC_USER_AGENT` in `.env`, else `KEY REQUIRED`), splits it at its "Item" headings, and searches the passages with SQLite's built-in full-text search (FTS5, ranked by BM25; no embeddings, nothing written to disk). The best passages go to the model, which must answer only from them and give an exact quote for each claim.
Every quote is then checked by plain text search against the whole filing (case, spacing, curly quotes and dashes are ignored; wording is not). A matching quote shows `VERIFIED` with its Item. A quote that is paraphrased, shortened with "...", invented, or under 5 words shows `UNVERIFIED`, and its claim is left out of the summary the panel shows. The panel also shows the filing (form, filed date, accession number, `SEC EDGAR`), the passages sent to the model, `AI · <model> · <time>`, and `UNGROUNDED` if no passage matched (the model is then not called and nothing is spent). The run is written to `AUDIT` as hashes only. Limits: US filers only, 10-K and 10-Q only, no earnings-call transcripts; a verified quote proves the words are in the filing, not that the model's claim about them is right.

### SWARM desks (Phase 20)
`SWARM <CODE> <subject> [NAME=value ...] [--force]` runs a desk. A desk is a small team of AI roles (analysts, then a chair who writes the answer). `SWARM` or `SWARM LIST` shows every desk with its coverage label and a cost estimate; `SWARM REPLAY <run id>` shows a stored run again with no model call.
- A desk may ask for variables (for example `target` and `market`). Type them as `NAME=value`, or type only the subject and it fills the first variable. A word like `GC=F` stays a ticker unless the desk declares a variable with that name.
- Before a run starts, the panel shows the worst-case tokens and US dollars. If that is more than what is left of today's AI spend cap, the server refuses with `spend_cap` (HTTP 402). `--force` runs it anyway, and the cap still stops a run that actually reaches it.
- Coverage is `FULL` (every tool the desk needs exists), `PARTIAL` (something was cut, and the panel says what) or `UNAVAILABLE` (it refuses and says why). All 30 ported desks are `PARTIAL`: no web search, no code execution, no China A-share data (see `docs/DATA_LIMITS.md`).
- Your own desks: put a YAML file in `<data dir>/presets/` (same shape as the packaged ones in `backend/openterm/ai/presets/`). It is checked on load and never executed; a bad file is listed as an error in `SWARM`. Codes are upper case, 2 to 14 characters, and cannot reuse `COMMITTEE RISK EARNINGS MACRO QUANT`.

```
SWARM EQRESEARCH market=US goal=AI-chip-demand
SWARM INVCOMM AAPL market=US
SWARM CRYPTODESK BTC-USDT timeframe=4h --force
SWARM REPLAY 3fa9c2d17b40
```

Code to Vibe-Trading name (source: HKUDS/Vibe-Trading at commit 8172827, MIT; `docs/PHASE_20_PRESETS.md` lists what each desk cannot do):

| Code | Vibe-Trading preset | Title | Roles | Coverage |
|---|---|---|---|---|
| COMMODITY | commodity_research_team | Commodity Research Team | 3 | PARTIAL |
| CONVERT | convertible_bond_team | Convertible Bond Research Team | 4 | PARTIAL |
| CREDIT | credit_research_team | Fixed Income Credit Research Team | 4 | PARTIAL |
| CRYPTODESK | crypto_trading_desk | Crypto Trading & Risk Desk | 4 | PARTIAL |
| CRYPTOLAB | crypto_research_lab | Crypto Asset Research Lab | 4 | PARTIAL |
| DERIVS | derivatives_strategy_desk | Derivatives Strategy Desk | 3 | PARTIAL |
| EARNDESK | earnings_research_desk | Earnings Research Desk | 4 | PARTIAL |
| EQRESEARCH | equity_research_team | Equity Research Team | 4 | PARTIAL |
| ETFALLOC | etf_allocation_desk | ETF Allocation Desk | 4 | PARTIAL |
| EVENTDRIVEN | event_driven_task_force | Event-Driven Task Force | 3 | PARTIAL |
| FACTORS | factor_research_committee | Factor Research Committee | 4 | PARTIAL |
| FUNDAMENTAL | fundamental_research_team | Fundamental Deep Research Team | 4 | PARTIAL |
| FUNDSEL | fund_selection_panel | Fund Selection Panel | 3 | PARTIAL |
| GEOPOL | geopolitical_war_room | Geopolitical Risk War Room | 4 | PARTIAL |
| GLOBALEQ | global_equities_desk | Global Equities Research Desk | 4 | PARTIAL |
| GLOBALLOC | global_allocation_committee | Global Allocation Committee | 4 | PARTIAL |
| INVCOMM | investment_committee | Investment Committee | 4 | PARTIAL |
| MACROFORUM | macro_strategy_forum | Macro Strategy Forum | 4 | PARTIAL |
| MLQUANT | ml_quant_lab | Machine Learning Quant Lab | 3 | PARTIAL |
| PAIRS | pairs_research_lab | Pairs Trading Research Lab | 4 | PARTIAL |
| PORTREVIEW | portfolio_review_board | Portfolio Review Board | 4 | PARTIAL |
| QUANTDESK | quant_strategy_desk | Quant Strategy Desk | 5 | PARTIAL |
| RATESFX | macro_rates_fx_desk | Macro / Rates / FX Desk | 4 | PARTIAL |
| RISKCOMM | risk_committee | Risk Committee | 4 | PARTIAL |
| SECTORROT | sector_rotation_team | Sector Rotation Research Team | 4 | PARTIAL |
| SENTIMENT | sentiment_intelligence_team | Market Sentiment Intelligence Unit | 4 | PARTIAL |
| SOCIAL | social_alpha_team | Social-Media Alternative Data Team | 4 | PARTIAL |
| STATARB | statistical_arbitrage_desk | Statistical Arbitrage Desk | 4 | PARTIAL |
| TECHPANEL | technical_analysis_panel | Technical Analysis Panel | 6 | PARTIAL |
| VALUEINV | value_investing_committee | Value Investing Committee (Buffett / Munger / Duan / Li Lu) | 5 | PARTIAL |

## Phase 15: risk, quant library, alphas, Kite
`RISK [PORTFOLIO] [RANGE=3y] [BENCH=SPY] [CONF=95] [HOR=1]` VaR / ES (historical, normal, EVT), beta, drawdown, contributions, stress replays (2008, 2020, 2022), VaR backtest ·
`PORT OPT [PORTFOLIO] [METHOD=EQVOL|RP|MV|MAXDIV|HRP|TURN] [CAP=0.25] [LOOKBACK=252] [RF=0] [TC=0]` trades and before/after preview; key `A` saves the proposal as a new portfolio `<NAME>.OPT`
(never edits the original, never orders) · `PORT ATTR [PORTFOLIO] [BENCH=SPY] [RANGE=1y]` Brinson-Fachler and returns; the valuation table behind TWR / MWR / Dietz is edited with
`PORT ATTR MAIN ADD 2025-01-01 VALUE=10000 FLOW=500` and `PORT ATTR MAIN DEL 2025-01-01` (under two rows: `NEEDS 2 VALUATIONS`) ·
`FACT AAPL 3y` or `FACT MAIN` Fama-French 5 + momentum exposures (data lags about two months) · `QL GARCH AAPL H=5`, `QL OU AAPL`, `QL COINT AAPL MSFT`, `QL HEDGE AAPL MSFT`, `QL COPULA AAPL MSFT`,
`QL ROLL|AMIHUD|KYLE|VPIN AAPL`, `QL EVENT AAPL DATE=2024-08-01`, `QL DSR SR=1.5 N=20 T=500`, `QL ADF AAPL`, `QL HVAR AAPL` ·
`ALPHA [UNIVERSE=TOP100|WL:<name>|LIST:A,B,C|SYN] [RANGE=2y] [FAMILY=alpha101|qlib158|academic] [H=1,5,10,20]` Alpha Zoo scan: IC, IR, decay, alive / reversed / dead (Enter on a factor shows its formula) ·
`CORR REGIME [WL:<name>|LIST:A,B,C] [WIN=60] [EDGE=0.5]` correlation edge density and fused / diffuse episodes (no list: the symbols of the `CORR` panel).

Kite (read-only, needs your own Kite Connect app): paste `KITE_API_KEY` and `KITE_API_SECRET` in `APIKEYS`, register `http://127.0.0.1:8000/api/kite/callback` as the redirect URL, then
`KITE LOGIN` (once per trading day), `KITE STATUS`, `KITE LOGOUT`. After login `RELIANCE.NS`, `^NSEI` and NFO/MCX bars come from Kite, and `OMON NIFTY.NFO R=6.5 Q=1.2` builds the chain with OI
(IV and Greeks only when `R=` / `Q=` are typed, labelled computed here). There is no order surface.
Option chains and futures tables work on every Kite derivatives exchange: `OMON NIFTY.NFO`, `OMON SENSEX.BFO` (BSE index options), `OMON CRUDEOIL.MCX`, `OMON USDINR.CDS`; `CT NIFTY.NFO`, `CT SENSEX.BFO`, `CT GOLD.MCX`, `CT USDINR.CDS`.
On MCX and CDS there is no spot index, so the nearest future that expires with the option stands in as the spot (the table says so). `GP RELIANCE.NS 1D` shows the last session (09:15 to 15:30 IST), as it does for US names.

## Trade, shipping and official data
- `SHIP` ship counts through 28 sea chokepoints (IMF PortWatch). `PORTS` the 25 busiest ports; `PORTS singapore` finds ports by name or country. No key.
- `AIS HORMUZ` (also `SUEZ PANAMA MALACCA BABEL BOSPHORUS GIBRALTAR DOVER`, or `AIS BOX <S> <W> <N> <E>`) ships that reported a position during an 8 second listen. Needs a free `AISSTREAM_API_KEY`.
- `DBSRCH inflation` searches IMF, OECD, Eurostat, BIS and ECB series; Enter drills in, and the last step opens the series in `ECST`. No key.
- `TRADE USA CHN 85 8Y` trade flows by product (here US with China, HS chapter 85, 8 years) (`UN_COMTRADE_KEY`). `USMAC BLS CPI`, `USMAC BEA GDPG`, `USMAC CENSUS RETAIL` US macro series (`BLS_API_KEY`, `BEA_API_KEY`, `CENSUS_API_KEY`).
- `UKCO tesco` UK company profile, officers and filings (`COMPANIES_HOUSE_KEY`). `ADDR GAS` or `ADDR 0x...` Ethereum balance, recent transactions and gas (`ETHERSCAN_KEY`).

## Phase 19: charting, discovery, macro, crypto, India data
- `AAPL GP 1Y ATR STOCH KELT SUPERTREND ICHIMOKU PAT:CANDLE PAT:SMC` : new studies and pattern marks (rule-based, not signals). `I` in GP opens the picker (keys 1-9, then A, B, C...).
- `AAPL GP 1Y EVT` : earnings (last four reported), ex-dividend and split markers. `AAPL GP VS MSFT NVDA PANE` : up to three compare symbols, one pane each (without `PANE` only the first is overlaid as %).
- GP drawing keys: `T` trend ray, `H` horizontal line, `B` fib retracement; `P` cycles the anchor price (close / high / low / open); `Enter` places an anchor; `Esc` cancels; `[` `]` select; `D` or `Del` removes. Saved per symbol; hidden while a `VS` % overlay is on.
- `AAPL SEAS [MONTH|WEEKDAY|DOM|WOY]` : average returns by calendar bucket (`V` cycles, `E` CSV). `AAPL GIP [1S|5S|15S|1M]` : tick candles (`S` bar size). `IMAP [SECTOR|INDUSTRY|COUNTRY] [N=3000] [MCAP>10B ...]` : heat map (arrows move, `Enter` opens Q, `Z` zoom group, Backspace out).
- `PERF CALC` : times the Phase 19 chart maths on generated test data.
- `SECF <text | ISIN | CUSIP | SEDOL | FIGI:id>` : fuzzy finder and identifier lookup. `ECST USA CPI` / `ECST DBN:IMF/WEO:latest/USA.NGDP_RPCH` : country indicator chart. `WECO` : G20 table (keys 1-5 sort, Enter opens ECST). `CENB` : central bank rates and next decisions.
- `NRG` : energy prices board (Enter or `NRG WTI` opens the series on FRED). `WETR` : degree-day basket; `WETR Houston` or `WETR 29.76,-95.37` : 7-day forecast plus NWS alerts (US, needs `SEC_USER_AGENT`); `B` toggles basket / place.
- `PRED [text] [SRC=POLY|KALSHI|ALL]` : prediction markets; Enter shows outcomes and price history. Odds are market-implied probabilities, not forecasts.
- `CDEP [PAIR] [LEVELS]` (`CDEP ETHUSDT 50`) : order book depth, spread and imbalance (Binance, OKX fallback). `FUND` : perpetual funding board (annualised) and quarterly basis; Enter or `FUND BTC` : last 30 prints, Backspace back.
  `LIQ [COIN]` : latest OKX liquidations. `STBL [CHAIN]` : stablecoin supply (`C` coins / chains, Enter opens a chain). `DEFI [CHAIN|PROJECT]` : yield pools over US$1M TVL. `UNLK` is not built (paid source).
- `SECF axis bluechip` : also lists Indian mutual fund schemes from AMFI NAV; `M` switches to the fund rows. `RELIANCE.NS GP 1Y` : when Yahoo cannot answer, daily bars come from the NSE archive (labelled, raw prices).
