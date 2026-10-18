# Commands to try

Start the app with `.\scripts\start.ps1` (or `./scripts/start`), then type in the command line at the top.
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
N oil prices          news search
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
BT EDIT mysma                             Python strategy editor (SignalEngine): Ctrl+S save, Ctrl+Enter save and run; BT EDIT lists them
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
SETTINGS              vim mode, clocks, number format, refresh rates, key rebinding
SOURCES               data source health and latency
APIKEYS               optional API keys: Enter edit (masked), T test, D twice delete, O sign-up page, C AI spend cap
JOBS                  background jobs: Esc/X cancel, R re-run, C clear finished (JOBS TEST 20 100 runs a test job)
LOG                   backend log
PERF                  performance monitor (PERF GRID 10000, PERF CHART 50000 load tests)
```
Keys: `Ctrl+\` / `Ctrl+-` split, `Alt+1..9` focus, `Alt+W` close, `Ctrl+Shift+F` maximize, `Ctrl+[` / `Ctrl+]`
panel history, `E` or `Alt+X` export a table to CSV.

A four-panel macro desk: `RATES` (Enter), then `FRED CPIAUCSL`, `FX`, `CRYP` (each Shift+Enter), then `LAYOUT SAVE MACRO`.
