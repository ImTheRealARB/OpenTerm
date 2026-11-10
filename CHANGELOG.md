# Changelog

Format: newest first, one section per phase. Details for each release are in `docs/RELEASE_NOTES.md`.

## Orders, broker sync, journal, MCP client, extensions, web tools, alpha zoo (2026-11-10)
- `ORD` orders (Phase 18 step 1): paper by default (Alpaca paper); Alpaca live and Kite live only after the key, `L` plus a typed phrase, a mandate that allows the symbol and size (default allows nothing), and typing the symbol again. Every order gets a one-time confirm token (60 s, bound to that exact order); `X` kill switch cancels everything and blocks new orders across restarts; a hash-chained order ledger (migration 19); paper vs live decided by the broker host, never a flag. `I` adds fills to PORT as labelled lots. The AI cannot place, change or cancel orders.
- `SYNC` / `PORT SYNC` (Phase 18 step 2): read-only Kite holdings (and day positions) and IBKR through the Client Portal Gateway on this machine into a PORT portfolio; re-syncs replace only that broker's lots, manual lots are never touched (shown as CONFLICT). Not yet tried against real accounts.
- `JRNL` trade journal: import Zerodha, IBKR Flex, Alpaca or any CSV (migration 18); FIFO round trips, stats per currency, behaviour findings that print their rule and say `NOT ENOUGH HISTORY` instead of guessing, and a Shadow Account replay through the backtester. The AI reads only stats and findings (`journal` tool). Formats follow the brokers' documentation; not yet checked against real exports.
- `MCP` client: call tools of other MCP servers (stdio or HTTP) from AI and SWARM as `<server>.<tool>`; every server off until enabled, a per-tool allow-list, order-like tool names refused, results fenced as untrusted and never counted as grounding. Two NSE India presets (`stock-nse-india`, MIT; `nse-mcp`, no licence stated) are listed disabled; neither has been run by us.
- `EXT` extensions: read-only providers, AI tools and routes from installed packages or `<data dir>/extensions/`, off until enabled, a crashing one shows `ERR` and the rest keep working (`docs/EXTENSIONS.md`, example in `examples/extensions/hello/`). Remote mode `OPENTERM_REMOTE=1` for your own server: token login with a hashed token, session cookie, no loopback trust behind a proxy, `/mcp` refused, Caddy compose file (`docs/HOSTING.md`). There is no logout button yet.
- `SRC=NASDAQ` pins one data source for one command (it answers alone or says why not; no silent fallback), `SETTINGS SOURCE <kind> <source>` sets a preferred one; `sdk/python` (`openterm-sdk`) returns DataFrames with source and age attached.
- Keyed sources Twelve Data, Alpha Vantage and Polygon (free keys, `APIKEYS`); with no key they show `KEY REQUIRED` and nothing changes. Polygon and FMP fixtures are doc-shaped (NOT A RECORDING). The Alpha Vantage key test can report OK for a wrong key (the service answers 200 either way).
- AI: `SETTINGS AI STORETEXT ON` keeps question and answer text beside the ledger (off by default; purge keeps the chain valid, `AUDIT` shows it); OCR for scanned PDFs in `AI DOC` (optional `uv sync --extra ocr` plus `tesseract`); a `patterns` tool; `AI BT CODE <idea>` drafts a SignalEngine strategy, checked by the `BT EDIT` sandbox check and never run; `AI FILING <SYM> GUIDANCE` and `CHAIN`.
- Web tools for the AI, **off by default** (`SETTINGS AI WEB ON`): `web_search` (Brave or Tavily key, or your own SearXNG) and `read_url` (public addresses only, redirects re-checked, size and time caps, per-answer limits). Web text is fenced as untrusted and never counts as grounding; SWARM desks report web coverage.
- `ALPHA` alpha zoo: 435 factors from Vibe-Trading (commit `8b8e083`, MIT) in families `core` (the 29 before, still the default), `alpha101`, `qlib158`, `academic`, `gtja191`, `all`; 43 skipped with reasons in `docs/ALPHA_SKIPPED.md`; a no-lookahead test runs on every factor. GTJA factors use the typical price where they ask for VWAP (daily bars have none). `ROC10` now has the opposite sign, following upstream. `FAMILY=ALL` on 200 names takes about 36 s.
- `BT EXPORT <run> MQL5|PDF|XLSX`: a MetaTrader 5 Expert Advisor (rule runs only), a PDF report or an Excel workbook of a stored run. `UNLK` stays unbuilt (`docs/DATA_LIMITS.md`).
- Playbooks: 11 more Vibe-Trading skills (57 of 89): 7 translated from Chinese into English (credit-analysis, etf-analysis, financial-statement, fund-analysis, sector-rotation, sentiment-analysis, trade-journal on the `journal` tool; the etf-analysis leveraged-decay formula corrected to L(L-1)/2 x sigma^2 x T) and 4 that use the opt-in web tools. Web steps say "needs SETTINGS AI WEB ON" and are skipped, and said so, when web is off. 32 still skipped with reasons in `docs/PHASE_20_SKIPPED.md`.
- Packaging: the Dockerfile builds and runs under compose (health 200); the Tauri desktop app builds on Linux (deb 1.7 MB, AppImage 77 MB; the window only, the backend is not bundled yet); an optional updater and `release.yml` build tagged desktop releases into a draft GitHub release, unsigned unless you add the signing secrets. Not yet run on GitHub; Windows, macOS and code signing are owner steps (`docs/DESKTOP.md`).
- Screen: ORD's function band fits one row (Side, Type, Release, Fills to PORT and Reload are in the help drawer; their keys work).

## Audit fixes (2026-11-06)
All 29 findings of an external code audit, fixed with tests (PR #29).
- Security: other web pages in your browser can no longer send commands to OpenTerm (changing requests and the live socket need no `Origin` or a local one, and JSON bodies need `Content-Type: application/json`); the strategy sandbox closes an escape route and now also refuses file, process and network access while strategy code runs; CSV exports from PORT and BT neutralise spreadsheet formulas; webhooks cannot target your own machine or private networks; the Kite token is redacted from logs and every keyed source picks up a key set in APIKEYS without a restart.
- Data: a newer quote is no longer hidden by an older live tick; tick sources and the day range are labelled correctly; an expired Kite login no longer poisons the cache; `YTD` means since 1 January on every source; derivatives screens keep the STALE label of their inputs.
- Maths: RISK, OPT, ATTR and FACT read a holding's currency from its prices when none was typed; BT MC and BT WF work on options runs; an OR rule with CROSS works before the first cross (results of such rules change); crypto HIVG annualises with 365 days; YAS refuses yields at or below -50% instead of crashing.
- Reliability: shutdown waits for alert, delivery and job work before the database closes; a deleted backtest run cannot come back from memory; news alerts check every symbol at once.
- Screen: a second AI or SWARM command in a panel cancels the first paid stream and keeps the panel's chat across maximize; the chart's volume bars follow live ticks; the GUI candle-length list checks your default range; settings stay in sync across two open tabs; charts send indicator work in one message and keep their live subscription when you change range.
- Speed: every route sends its answer straight through orjson (a 50,000-bar chart 203 ms to 10 ms on the server); the BT run list has an index.
- Tooling: an ESLint gate for React hooks rules (it found and fixed real bugs in Grid, FXC and others); the quick test picker finds route tests; the bench measures the largest answers (39 budgets); CI actions pinned to exact versions, failing e2e tests keep a screenshot and trace; seven test races fixed.

## Home page and ticker tape (2026-11-05)
- New `HOME` function, and the page OpenTerm opens on: a dense terminal grid with a scrolling ticker tape on top, blocks of numbers (indices for the US, India, Europe and Asia; FX, commodities and crypto; rates and volatility) and blocks of headlines by section (top, markets, economy, companies, tech, India, commodities and crypto), each headline row showing source, age and title. `J` / `K` move between rows, `H` / `L` between blocks, Enter opens a headline's article (or a number's chart in a new panel), F5 refreshes; everything is clickable. A block that cannot load says `ERR` with the reason and never shows made-up headlines. Headline blocks use `GET /api/news?section=...`.
- New setting `startup` (`SETTINGS STARTUP HOME|LAYOUT`, also a row in SETTINGS): `home` (default) opens HOME in a new browser session; `layout` restores your saved workspace as before. Saved layouts and `LAYOUT LOAD` are unchanged, and the `HOME` command brings the page back any time.
- New `TAPE` command, stored in your settings and synced: `TAPE` lists the symbols, `TAPE ADD SYM [MKT]`, `TAPE DEL SYM`, `TAPE RESET`, `TAPE ON|OFF` (also show the tape in the top bar on every screen; `SETTINGS TAPE ON|OFF` is the same). Up to 30 symbols. The tape is one CSS transform animation (an allowed exception to "no animations": a tape is motion), paused on hover and while the tab is hidden, and off under the operating system's reduced-motion setting. Prices follow the live ticks; STALE, SYNTHETIC and ERR show per item. HOME and the tape share one quote request and one subscription.

## Phase 20: News feeds and filters (2026-11-05)
- NEWS reads 45 free, keyless RSS / Atom feeds from one table (`providers/news_feeds.py`): tech (TechCrunch, The Verge, Ars Technica, Wired, Hacker News, MIT Technology Review, Engadget, The Register, CNBC / BBC / Guardian / ET / Mint tech), global business, India (ET, Mint, Business Standard, BusinessLine, NDTV Profit, RBI, SEBI), official (Fed, ECB, SEC), oil and crypto. Plain `N` still shows the original five top-stories feeds.
- Feeds are fetched at once with a 6 s limit each; a dead feed is named under NOT ANSWERING and never blocks the rest. Per-feed cache 60 s (30 s for tech and crypto), identical headlines from different feeds show once, newest first, with source and age.
- `GET /api/news` takes `region`, `sector`, `commodity`, `section`, `q` and `limit`; same item shape as before (the answer adds `feeds_ok` and `feeds_total`). `N TECH`, `N INDIA`, `N COUNTRY IN`, `N SECTOR BANKS`, `N COMMODITY GOLD`, `N SEARCH rate cut`, combinable; the panel shows a FILTER line and `n/m FEEDS OK`. Matching is feed tags plus keyword tables in `news_tags.py`.

## Phase 20: SWARM desks, skills, desk tools, MCP command (2026-11-05)
- `AI FILING <SYMBOL> <question>` and `AI FILING <SYMBOL> DRIVERS` (US filers): answers from the newest 10-K / 10-Q, and every quote the model gives is checked word for word against the filing; unchecked quotes show `UNVERIFIED` and their claims are left out of the summary. Needs `SEC_USER_AGENT`; no transcripts.
- 12 new read-only tools for AI desks and MCP clients: `indicators option_price option_payoff etf holders insiders calendar pred energy crypto_funding crypto_depth rigor`. Same routes as the panels, 6,000-character results, no order tools (a test scans the names).
- SWARM engine: desks can declare variables (`NAME=value`), tasks that depend on earlier tasks, 2 roles at once, 8 tool rounds and 120 seconds per role, 40,000 output tokens per run. A cost estimate shows before a run; over the daily cap the server refuses with `spend_cap` (402) unless `--force`. Your own desks load from `<data dir>/presets/*.yaml`. Every desk shows a coverage label (FULL, PARTIAL, UNAVAILABLE) and what it cannot do.
- 30 Vibe-Trading desks ported (HKUDS/Vibe-Trading at 8172827, MIT; `THIRD_PARTY.md`): `EQRESEARCH`, `INVCOMM`, `RISKCOMM`, `CRYPTODESK` and more, code table in `docs/COMMANDS.md`. All are PARTIAL (no web search, no shell, no China A-share data): `docs/PHASE_20_PRESETS.md`.
- 46 of 89 Vibe-Trading skills ported; 43 skipped with reasons (`docs/PHASE_20_SKIPPED.md`). New `skills` search tool and a `section` argument on `skill`.
- `openterm-mcp` console command for MCP clients (same bridge as `python -m openterm.mcp`); MCP now lists 30 read-only tools. New `docs/API.md` for the REST routes, CSV export and Python / Excel use.
- Alerts now fire on the OpenTerm server, so a price or news alert reaches your delivery channels with the browser closed (`ALRT` shows engine state and why an alert was skipped; active only while OpenTerm runs). Delivery retries a failed send after 30 s, 2 min and 10 min, has a daily cap per channel (default 50), and Telegram messages are escaped and split at 4,096 characters.
- Recipients are private: `GET/PUT /api/delivery` no longer return the email address or Telegram chat id (only `configured` and a masked hint such as `a•••@gmail.com`); typing a new value replaces it, an empty one keeps it. `DLVR` `P` pairs Telegram: it shows the bot link and a one-time code (10 minutes, one use), the backend reads the chat id from Telegram and stores it, and the browser only learns `paired: true`.
- Per-alert delivery channels: `ALRT AAPL > 200 VIA TG,EMAIL` and `ALRT NEWS RECALL VIA WEBHOOK` send that alert only to the chosen channels (no `VIA` = every channel switched on in `DLVR`, as before). A chosen channel that is switched off is logged as skipped with the reason `CHANNEL OFF`; `ALRT` lists each alert's channels.
- Not in this phase: Filings Intelligence, a `patterns` tool, `web_search` / `read_url` (left out on purpose), and any rework of `BRIEF` (the Phase 17 versions stay).

## GUI layout and README screenshots (2026-11-05)
- The sidebar and the menu bar's category menus are now one or the other: with the sidebar open the strip under the command line holds only the `Sidebar` and `Tabs`/`Tiles` buttons; hide the sidebar and the seven category menus appear there. The tour's first step follows.
- With the status bar off (the GUI default) its grid row no longer stays reserved: the workspace reaches the bottom of the window.
- README screenshots are GUI mode now and are taken on a 960 x 600 page at 2x (was 1440 x 810): GitHub scales a picture to about 880 px, so the old ones showed the text at 60% size. `scripts/screenshots.mjs` has the new sizes, a `gui-sidebar` shot, and `keepOnly` to close the starter panels.
- e2e: 3 new/changed GUI tests (sidebar/menus swap, no empty footer strip); the specs that open a horizontal menu hide the sidebar first.

## Strategy editor (2026-11-03)
- `BT EDIT` uses CodeMirror 6: Python syntax colours, line numbers, bracket matching, undo history. It loads as its own chunk (126 KB gzip) only when an editor opens; startup bundle unchanged (119.9 KB).
- Starter templates: SMA cross, RSI mean reversion, breakout (`GET /api/bt/templates`). A new strategy name opens the template list; `T` (after Esc) reopens it.
- Inline sandbox errors: 0.4 s after typing stops, `POST /api/bt/check` runs the sandbox check (nothing saved) and the message shows under the offending line and as a `SANDBOX:` line.
- Tests: 14 new pytest (1708 total), 6 vitest, new Playwright cases (226 total).
- `start.ps1` / `start` (and so `openterm`) run `npm ci` before building when `package-lock.json` is newer than the last install, so a `git pull` that adds packages no longer breaks the build.

## Phase 17: MCP server, alert delivery, daily brief (2026-11-03)
- MCP server: `POST /mcp` (loopback only, Origin guard) and a stdio bridge `python -m openterm.mcp`; 17 read-only tools from the AI registry, each result labelled with source and age. No order tools (a test scans for them). `docs/MCP.md`.
- Alert delivery: price and news alerts can be sent by email (SMTP, TLS always verified), Telegram or a webhook (new key `ALERT_WEBHOOK_URL`). Everything off by default; `DLVR` panel with test sends and a delivery log (migration 15 `deliveries`).
- Daily brief: watchlist movers, alerts of the last 24 h, today's earnings and economic events, top headlines; every section names its source and age. Scheduled with apscheduler (off by default), `BRIEF` panel (`R` build, `S` build and send).
- Fixes the open SMTP TLS-verification item from the review sprint.
- Tests: 64 new pytest (1694 total), new vitest suites, 3 Playwright (223 total).

## GUI mode (2026-11-02)
- One app, two shells: a `mode` setting (`terminal` | `gui`) switched from the status bar, `Alt+G` or `SETTINGS MODE`. New users start in GUI mode; settings saved before GUI mode existed load as Terminal. Terminal mode is unchanged apart from the toggle.
- GUI shell (`frontend/src/gui/`): menu bar by category (`functions/categories.ts`), searchable function sidebar, symbol picker, per-panel toolbar that fires the panel's own keys (`gui/toolbars.ts`), `?` help drawer (`Alt+H`), "Switch to Terminal mode" banner, first-run welcome card and a 5-step tour (replay from the Settings menu or HELP).
- Panel polish for Q, WL, WEI/FX/CMDTY, N, GP, FA, PORT, BT: one `PanelNote` look for loading, empty, error and stale states, with a next-step hint on every empty state; clearer summary-line hierarchy; tabular digits.
- Tests: 37 new Playwright tests (220 total), new vitest suites for settings mode, categories, GUI search, toolbars and news hints. Bench adds an INFO line for GUI-mode cold start.

## Public release and docs (2026-11-02)
- Repo made public. README rewritten for beginners (tool install with winget/brew, three-command setup, first-five-minutes table, troubleshooting) and now leads with the measured speed budgets.
- New screenshots in `docs/screenshots/` (workspace, chart with indicators, backtest, fundamentals, rates and calendar) replace `docs/screenshot-phase3.png`.
- `scripts/setup` is the light install by default (about 330 MB); `-Dev` / `--dev` adds test and lint tools and Chromium. The `start` scripts use `uv run --no-dev`.

## Review sprint and terminal look (2026-10-19)
- Review sprint (13 agents, details in `docs/review/SUMMARY.md`): about 30 bugs fixed, each with a test (hub and WebSocket leaks, jobs runner races, redaction gaps, AI tool-path bypass, validation `$` vs `\Z`, load races in HIST / ECO / CRYP / MACRO / N / COMP, chart and drawing bugs, option and JGB parsers); speedups (`Cache.get_many` 527 -> 11.5 ms, `JobStore.recent` 1070 -> ~0.5 ms, GIP bucket 24 -> 5 ms, `doc_search` 171 -> 3.3 ms); two risky commits reverted (`docs/review/REVERTED.md`).
- Dev loop: `scripts/check.ps1` / `check.sh` (affected tests only), `gates.mjs` runs ruff + tsc first then the heavy suites in parallel with per-gate timing, CI split into 5 jobs, `scripts/new_function.py`, Playwright on 4 workers. Full gate 123 s (was 167 s, with 9 flaky e2e).
- Terminal look: yellow command field with a prompt and GO key, a key-hint row, ticker / name title bands, status bar dividers, amber grid headers with row and column rules, blue selection bar, dim chart grid (`components/dataColors.css`). No gradients, shadows, radii or web fonts; bench 37/37.
- `scripts/install-launcher.ps1`: type `openterm` in any terminal to start the app.

## Phase 19: charting, discovery, macro, crypto (complete 2026-10-18; UNLK not built; merged to main)
- Added to `GP`: 12 studies (`ATR STOCH ADX OBV CCI WILLR MFI KELT DONCH SUPERTREND PSAR ICHIMOKU`), rule-based pattern overlays (`PAT:CANDLE` 9 candlestick patterns, `PAT:SMC` swings, BOS / CHOCH, fair-value gaps, order blocks; `PAT:ICHI` = `ICHIMOKU`),
  drawings by keyboard (`T` trend ray, `H` horizontal, `B` fib; `P` anchor price, `Enter` places, `[` `]` select, `D` removes) saved per symbol on the server, `EVT` markers (E earnings = last four reported, D ex-dividend, S split),
  `VS A B C PANE` (each compare symbol in its own pane). The indicator picker uses keys 1-9 then letters. The crosshair readout no longer goes stale.
- Added `SEAS` (seasonality by month, weekday, day of month, ISO week), `GIP` (candles built from the live ticks this server has seen, buffer 20,000 ticks per symbol), `IMAP` (treemap heat map of the EQS universe: size = market cap, colour = % change).
- Added `SECF` (fuzzy security finder; ISIN / CUSIP / SEDOL / FIGI lookup via OpenFIGI), `ECST` (World Bank / DBnomics indicator chart), `WECO` (G20 table, each cell with its own data year), `CENB` (policy rates and decision dates of eight banks), FOMC decisions in `ECO`, exchange holidays (`HOL` / `EARLY`) on the market lights.
- Added `NRG` (crude, gas, refined products, retail fuel from FRED's keyless CSV; prices only) and `WETR` (demand-city degree-day basket, place forecast from Open-Meteo, NWS alerts when `SEC_USER_AGENT` is set), `PRED` (Polymarket and Kalshi odds, labelled MARKET-IMPLIED PROBABILITY, NOT A FORECAST).
- Added crypto depth: `CDEP` (order book, Binance with OKX fallback on HTTP 451), `FUND` (funding annualised from each venue's interval, perp and quarterly basis, 30-print history), `LIQ` (latest OKX liquidations), `STBL` (stablecoin supply by coin and chain), `DEFI` (yield pools over US$1M TVL, filtered server side). `UNLK` is NOT BUILT: DefiLlama emissions are paid.
- Added India zero-key data: NSE archive end-of-day bars as the last `history` fallback for `.NS` at `1d` (built from daily bhavcopy files, kept in SQLite, labelled with the file count), and AMFI mutual fund NAV rows in `SECF` (`M`). `config.yaml`'s history order now includes `nse_archive`.
- New routes: `GET/PUT /api/drawings/{symbol}`, `GET /api/world/events`, `GET /api/world/ticks/{symbol}`. New Nasdaq `earnings-surprise` source. Bench 36/36 with five new chart-maths budgets.

## Phase 16: AI layer (in progress)
- Added `AI`: a chat panel over an agent that calls 14 read-only tools in-process (quotes, history, profile, financials, filings, news, screener, research tables, options chain, rates, macro, portfolio, backtest, quant jobs).
  Every answer lists its tool calls (source, age, STALE / FAILED / EMPTY), cites them as [T1], and carries `AI · model · time · MODEL OUTPUT, NOT DATA`; no tool data = `UNGROUNDED`, figures no tool returned = `UNSOURCED NUMBERS`.
  Loop guard (3 failed or empty calls in a row, or the same call twice), context budget, daily spend cap. No order tools exist. No key = `KEY REQUIRED`. `SETTINGS AI` picks the model.
- Added `AI BT <idea>` (drafts a BT rule, validated by the engine parser, shown with its command, never run by the AI), `AI CHART` (the newest GP chart to a vision model), five finance playbooks the agent loads on demand
  (valuation, earnings, options, risk, macro) and a `strategy_check` tool. AI BT drafts rule strings only; `SignalEngine` code drafts are not built.
- Added `AI DOC`: ask questions about one SEC filing (`AI DOC FILING AAPL 10-Q`) or an uploaded TXT / CSV / HTML / DOCX / XLSX / PDF. Local parsing (new dependency: pure-Python `pypdf`), keyword search over chunks,
  chunk citations, the same UNGROUNDED / UNSOURCED checks. Documents stay in memory (last 5). No OCR.
- Added `SWARM` (five preset desks of analyst roles plus a chair, each role with its own tools, one retry, stored runs that replay with no model call), `THESIS` (notes per ticker with status,
  invalidation rule and linked runs) and `AI AUTO` (hypothesis, backtest, evidence report; the evidence line comes from the backtest runs the server saw). New migration 13 (`ai_runs`, `theses`).
- Added `AUDIT`: a hash-chained ledger (migration 14, `ai_ledger`) of AI chat, AI BT, AI DOC, SWARM, AI AUTO and BT runs with a manifest (prompt, tool registry and skill hashes, app version, model) and metadata (question and answer hashes,
  tool calls with argument hashes, cost, grounding verdict). No prompt or answer text is stored. The panel verifies the chain and names the first broken entry.
- Recorded with the real OpenRouter key: one plain stream and a tool-call round (the pending Phase 11 recording is done).

## Phase 15: risk, quant library, alphas, Kite
- Added `RISK` (VaR / ES by history, normal and EVT, beta, drawdown, contributions, stress replays of 2008, 2020 and 2022 with COVERAGE, Kupiec / Christoffersen / Basel backtest),
  `PORT OPT` (EQVOL, RP, MV, MAXDIV, HRP, TURN preview; `A` saves `<NAME>.OPT`, never edits the original), `PORT ATTR` (Brinson-Fachler plus TWR / MWR / Dietz / XIRR from a stored valuation table),
  `FACT` (Fama-French 5 + momentum, keyless Ken French data), `QL` (GARCH, OU, cointegration, copula, microstructure, event study, deflated Sharpe), `ALPHA` (29-factor zoo scan: IC, IR, decay,
  alive / reversed / dead, lookahead sentinel test) and `CORR REGIME` (edge density, fused / diffuse episodes).
- The math is the new worker-only `quantlib` package ported from Vibe-Trading (MIT, `THIRD_PARTY.md`); every function runs as a job through `POST /api/quant/{fn}`. History accepts a `20Y` range of daily bars.
- Added `KITE` (Zerodha Kite Connect), READ-ONLY: daily `KITE LOGIN`, status, Indian bars, NFO / MCX chains with OI (`OMON NIFTY.NFO R= Q=`), ticker decoder. Inert without your own key; no order surface exists.
  Its fixtures are doc-shaped, NOT recordings.
- `ALPHA`: `Enter` on a factor shows its formula line (the ported module's docstring, inputs, warm-up). Bench 29 of 29. Checked in the real app: fixture smoke run of every Phase 15 function, and live keyless `FACT AAPL`, `RISK` and `ALPHA TOP100`.

## Phase 14: options, rates, futures
- Added `OMON` (chain with Greeks, OI, volume), `PCR`, `OV` (Black-Scholes, binomial, Heston, barrier, IV solver) and `OSA` (multi-leg payoff, scenario
  grid, Greeks by leg), `OVDV` / `SKEW` (implied-vol surface, quadratic smile never extrapolated), `HIVG` (realised vs implied; IV30 is built from LOCAL
  SNAPSHOTS, so history starts the day you first open it). Crypto options come from Deribit. Yahoo options are keyless; Tradier (`TRADIER_TOKEN`) is an optional fallback.
- Added `RATES` upgrade (EUR, GBP, CAD, JPY curves, Nelson-Siegel fit, FRED OAS credit spreads, Treasury auctions), `CT`, `WIRP`, `COT`, `FXFA`
  (labelled a CIP estimate), `YAS`, `SWPM`, `CDSW`. A missing input makes a model NOT RUNNABLE and lists the fields; nothing defaults silently.
- Quant library (`openterm/quant/`) ported from Vibe-Trading (MIT, `THIRD_PARTY.md`) and cross-checked against Vibe's own numbers. `BT` can run
  options structures from `OSA`, labelled MODEL-PRICED OPTIONS (BLACK-SCHOLES ON HISTORICAL VOL), NOT MARKET QUOTES. Migration 12 adds `iv_snapshots`.

## Phase 13: equity research gaps
- Added `EE` / `EEO` (estimates, revisions, EPS surprises), `ANR` (ratings, targets, rating changes), `MGMT` (officers, governance, proxies),
  `DVD` / `SPLT` / `CACS`, `IPO`, `SI` (short interest and FINRA short volume), `EVTS` (8-K items decoded), `ETF`, `MEMB` (constituents via the
  proxy ETF's N-PORT), `MGR` (13F, quarter over quarter) and `CN` (company news from every source, keyword-scored, NOT A MODEL).
  All work with zero keys (Yahoo `quoteSummary`, Nasdaq, FINRA, SEC); a key unlocks more.
- Added `DCF` / `WACC` / `RV` on the valuation engine ported from Vibe-Trading (MIT): a missing input makes the model NOT RUNNABLE and lists it; opinions
  (ERP, terminal growth, exit multiple) must be typed (`ERP=5.5 G=2.5 EXITX=14`).
- Added the keyed Finnhub and Alpaca sources (set in `APIKEYS`): their headlines join `N` and `CN`, Finnhub backs `ANR` / `EEO` when Yahoo is down, and
  Alpaca keys turn on real-time US last trades (IEX only), labelled `RT IEX`. Without keys nothing changes.
- Added `ALRT NEWS WORD [SYM]`: fires when a newer headline contains the word (checked on each news refresh, every 2 minutes while the app is open).

## Phase 12: backtester (Phase 11, keys and jobs, is on the same branch)
- Added `BT`: rule syntax (`BT AAPL SMA20>SMA50 1D 5Y`), Python strategies (`BT EDIT`, `@name`), saved rules, results with chart, metrics,
  trades and code views, every result labelled HISTORICAL SIMULATION, NOT A FORECAST with its sources, fees and slippage.
- Engines ported from Vibe-Trading (MIT, `THIRD_PARTY.md`): US, UK, Hong Kong, Canada, India, crypto perpetuals with funding, forex,
  global futures, composite baskets. China A, China futures, Korea, Vietnam and Brazil are not built.
- Added `BT MC` / `BT WF` (Monte Carlo trade shuffle, bootstrap Sharpe interval, walk-forward), `BT RUNS` (compare), `BT EXPORT` (CSV, Pine).
- Added `IMPORT` (your own daily bars, labelled LOCAL DATA) and the keyless `binance_klines` source (spot and USD-M candles with funding).
- Added `scripts/gates.mjs` (the five test gates in parallel) and faster test suites.

## After Phase 10: fixes and browser start
- Added `scripts/start.ps1` / `scripts/start`: build the frontend if stale, serve it from the backend on :8000, open the browser.
- Added `docs/COMMANDS.md`, a list of commands to try.
- Fixed: the panel tab named the last ticker on functions that do not use one (FRED, PORT, EQS, SETTINGS ...).
- Fixed: charts of series without volume (FRED) drew a flat line along the bottom.

## Phase 10: settings and packaging
- Added `SETTINGS` and `THEME`: themes (amber, green, white, light), number format, header clocks, chart defaults, poll intervals.
- Added opt-in vim mode for the command line and vim list keys (`g`, `G`, `Ctrl+D`, `Ctrl+U`).
- Added keybinding overrides with conflict and browser-reserved checks.
- Added `/api/settings` (validated, versioned, stored in SQLite `kv`).
- Added `OPENTERM_STATIC_DIR` static serving, `Dockerfile`, `docker-compose.yml`, `.dockerignore`.
- Added the Tauri scaffold in `desktop/` and `docs/DESKTOP.md`.

## Phase 9: research
- Added `EQS`, `CORR`, `COMP`, `HIST` and CSV export.

## Phase 8: portfolio and alerts
- Added `PORT` (CSV import/export) and `ALRT`.

## Phase 7: macro and calendars
- Added `MACRO`, `FRED`, `ECO`, `RATES`, `ERN`.

## Phase 6: filings and fundamentals
- Added `FA`, `FIL` / `SEC`, `HDS`, `OWN`.

## Phase 5: boards and lists
- Added `WL`, `N`, `MOV`, `CRYP`, `WEI`, `FX`, `FXC`, `CMDTY`; pytest-xdist; parallel Playwright.

## Phase 4: workspace
- Added named layouts and SQLite persistence for layouts and command history.

## Phase 3: first functions
- Added live streaming, `Q`, `QR`, `DES`, `GP`, canvas grid.

## Phase 2: data core
- Added Yahoo and Nasdaq adapters, router with fallback, SWR cache, `SOURCES`, `LOG`, fixture mode.

## Phase 1: scaffold
- Added shell UI, tiling workspace, command parser, autocomplete, keybindings, `PERF`, bench script, CI.
