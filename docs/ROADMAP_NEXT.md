# Roadmap: the next 25 features (functions a professional terminal has that OpenTerm lacks)

Written 2026-11-10 from a brainstorm with the owner. Every item below was checked against the code on `main` (`824e428`) and
does **not** exist yet. Every item is buildable with free data unless its row says otherwise. Nothing here is started.
Replaces nothing: [FEATURE_GAP.md](FEATURE_GAP.md) is the older gap list (almost all of it is built now) and
[ROADMAP_PHASES_11-19.md](ROADMAP_PHASES_11-19.md) is the finished phase plan.

**Not in this list on purpose:** a Rust port (decided no on 2026-11-10: server p95 is 0.3-2.5 ms, the time goes to network and
browser drawing, and the maths already runs in numpy/scipy), and anything in "Not reachable even with keys" at the end of
FEATURE_GAP.md (consolidated L2, the other vendor's news wire and research, chat network, ESG and supply-chain databases).

## Rules for every item (same as every phase so far)
- Read `DESIGN.md`, `docs/ADDING_A_FUNCTION.md` and, for a new data source, `docs/ADDING_A_PROVIDER.md` first.
- Never fake data: a failed source shows `STALE` / `ERR` with source and age; test data and doc-shaped fixtures are labelled
  (NOT A RECORDING); tests never hit the network.
- Zero keys still works: a keyed source answers `KEY REQUIRED: set X in APIKEYS` through `KEY_SPECS`.
- Secrets never reach the frontend, logs, URLs or error text (`redact.redact()`).
- Keyboard first; mouse optional. A new function goes in `registry.ts`, `categories.ts` and `gui/toolbars.ts`, lazy-loaded, and
  `python scripts/gen_functions_doc.py` regenerates `docs/FUNCTIONS.md`.
- **Speed:** heavy work runs as a job (process pool), never in the request; no Python per-bar or per-window loops in hot paths
  (vectorise with numpy/pandas; see the 2026-11-10 ALPHA fix in `scripts/port_vibe_alphas.py` BASE_PATCHES); results cached by
  hash; every new hot path gets a budget in `scripts/bench.mjs` and a row in `docs/PERFORMANCE.md`; the initial bundle stays
  under 400 KB gz (125 KB today), so new panels are lazy chunks and do not idle-preload if heavy.
- **Command codes:** the codes below are proposals. A code must not be a real ticker people type first (rule in
  `frontend/src/functions/aliases.ts`): check every one against SEC `company_tickers.json` before adding it. Known clashes:
  `CAL` (Caleres), `LINK` (Interlink Electronics; also the Chainlink coin), `EPR` (EPR Properties).
- Gates before merge: ruff, pytest, typecheck, lint, vitest, Playwright, bench (39/39 today).

Effort: **S** about a day of agent work, **M** a few days, **L** a week or more. Data: **FREE** no key, **KEY** free key,
**UNOFF** unofficial endpoint (may break; label it).

## Suggested order
1. **Wave 1, workflow** (felt every day): 1 link groups, 2 condition alerts, 3 custom columns, 5 unified calendar.
2. **Wave 2, infrastructure:** 25 local history store (7 breadth and 14 technical screener need bars for a whole universe).
3. **Wave 3, analytics:** 9 volatility board, 12 money markets, 13 nowcasts, 8 options extras, 10 spread panel, 11 rotation,
   7 breadth, 14 technical screener.
4. **Wave 4, research:** 15 full-text search, 18 press releases, 19 fundamentals over time, 17 activists and insiders,
   16 subsidiaries and customers, 20 alternative data.
5. **Wave 5, India:** 21 (move it earlier if the owner trades Indian markets mostly).
6. **Wave 6, portfolio and reach:** 22 tax lots, 23 what-if, 24 benchmark stats, 4 spreadsheet link, 6 mobile layout.

## 1. Workflow

| # | Feature | Proposed code | What it does | Data | Effort |
|---|---|---|---|---|---|
| 1 | Panel link groups | none (window menu + key chord) | Tag panels with a colour group (e.g. Alt+1..4); typing a new security in one panel of a group re-points every panel in that group (GP, DES, N, FA, OMON...). Panels with no group stay independent (today's behaviour). Saved in layouts. | none | M |
| 2 | Condition alerts | `ALRT` (new forms) | Server-side alerts beyond price / percent: indicator crosses (`SYM RSI14 < 30`, `SYM SMA50 X SMA200`), volume spike (`VOL > 3x ADV20`), new 52-week high/low, new 8-K for a watchlist, earnings within N days. News keyword alerts already exist (`ALRT NEWS`, `news_alerts.py`). | FREE | M |
| 3 | Custom monitor columns | `Q` / `WL` + `COLS ...` | Pick the columns of a quote monitor or watchlist: P/E, dividend yield, market cap, RSI, % from 52-week high, next earnings date, short interest. Column sets saved per watchlist. | FREE | M |
| 4 | Spreadsheet link | `XLS` (check) | Phase 1: CSV/JSON endpoints shaped for Excel `WEBSERVICE` / Power Query and Google Sheets `IMPORTDATA` (remote mode), documented with copy-paste formulas. Phase 2 (optional): an Excel custom-functions add-in (`=OT("AAPL","PX_LAST")`). Read only; the same token rules as remote mode. | none | M (L with the add-in) |
| 5 | Unified calendar | `CALR` / `EVCAL` (check) | One date-ordered view for a watchlist or portfolio: earnings, ex-dividend and pay dates, splits, IPO lock-ups where known, FOMC and central-bank meetings, economic releases, monthly option expiries, exchange holidays. Built from the existing ERN, DVD, SPLT, IPO, ECO, CENB sources. | FREE | S-M |
| 6 | Mobile layout | none | A single-column, touch-friendly layout when the remote-mode page is opened on a phone: command line, one panel at a time, swipe between panels. Desktop layout unchanged. | none | M |

## 2. Market analytics

| # | Feature | Proposed code | What it does | Data | Effort |
|---|---|---|---|---|---|
| 7 | Market breadth | `BRDT` (check) | Advancers vs decliners, % of names above the 50- and 200-day average, new 52-week highs and lows, McClellan oscillator and summation index, over an index's members (MEMB via the proxy ETF). Computed in a job from cached daily bars. | FREE (needs 25) | M |
| 8 | Options extras | `OMON` views / `GEX` (check) | (a) Dealer gamma exposure by strike and total, flip level, max pain, from the chain's open interest and Greeks computed here (label: assumes dealers short calls/long puts, a model). (b) Implied earnings move from the straddle of the first expiry after the next earnings date, next to the stock's past earnings-day moves. (c) Unusual option volume: volume / open interest and volume vs 20-day average per contract, across a watchlist (job). | FREE | M |
| 9 | Volatility board | `VOLB` (check) | VIX term structure (9-day, 30-day, 3-month, 6-month) with contango/backwardation, VVIX, MOVE, OVX, GVZ, India VIX, each with 1-year percentile. Index quotes plus FRED history. | FREE | S |
| 10 | Spread and regression panel | `HS` / `HRA` (check) | Two securities (or a security and an index): price spread and ratio, z-score, rolling beta and correlation, regression line with R-squared and residual plot, half-life of the spread. Reuses `QL HEDGE` / `COINT` maths. | FREE | S-M |
| 11 | Sector rotation chart | `RRG` (check) | Sector or custom-list ETFs plotted by relative strength vs a benchmark and its momentum, with tails over N weeks. The commercial RRG formula is proprietary: implement a documented RS-ratio / RS-momentum approximation and label it. | FREE | S-M |
| 12 | Money markets monitor | `BTMM` / `MMKT` (check) | SOFR, EFFR, OBFR, TGCR/BGCR, reverse-repo usage, T-bill yields, the Fed balance sheet (WALCL), Treasury General Account, bank reserves, with day changes. New York Fed Markets API (no key) and FRED. | FREE | S |
| 13 | Growth nowcasts | `NOWC` (check; `NOW` is ServiceNow) | Atlanta Fed GDPNow (FRED series `GDPNOW`) and the New York Fed Staff Nowcast, latest estimate and its path this quarter, next update date. | FREE | S |
| 14 | Technical screener | `EQS` (new criteria) | Add RSI, moving-average position and crosses, 52-week high/low distance, volume vs average and pattern hits to EQS criteria. Needs bars for the screened universe: from the local store (25), refreshed in a job. | FREE (needs 25) | M |

## 3. Research

| # | Feature | Proposed code | What it does | Data | Effort |
|---|---|---|---|---|---|
| 15 | SEC full-text search | `FTS` (check) | Search a phrase across all EDGAR filings since 2001 (EDGAR full-text search), filter by form, date and company; Enter opens the filing in FIL. Needs a descriptive User-Agent (SEC rule) and SEC's 10 requests/second limit. | FREE | S |
| 16 | Subsidiaries and customers | `RELS` (check) | Subsidiaries from the latest 10-K Exhibit 21; major customers and suppliers that 10-Ks disclose (customers over 10% of revenue), extracted by AI with verbatim quotes (the AI FILING machine-checked quote rule) and labelled as extracted. A free stand-in for a supply-chain database. | FREE (AI part needs a model key) | M |
| 17 | Activists and insider clusters | `ACTV`, `INSB` (check) | New 13D / 13G / amendments with the filer, stake and purpose (Item 4 text); market-wide insider purchases from Form 4 with cluster detection (several insiders buying within N days). Daily EDGAR index, parsed in a job. | FREE | M |
| 18 | Earnings press releases | `FIL` view / `ERNR` (check) | The 8-K Item 2.02 Exhibit 99.1 for each quarter, readable in the panel, with an optional AI summary (guidance, segment notes) through AI DOC. A free stand-in for paid call transcripts. | FREE (summary needs a model key) | S-M |
| 19 | Fundamentals over time | `GF` (check) | Chart any statement line (revenue, margins, EPS, free cash flow, share count...) over 10+ years, quarterly or annual, against up to 5 peers, from SEC XBRL company facts. | FREE | M |
| 20 | Biotech and alternative data | `TRIAL`, `FDA`, `LOBY`, `PATN` (check) | ClinicalTrials.gov v2 trials by sponsor (phase, status, completion dates); openFDA drug approvals and recalls; Senate LDA lobbying spend by client; patents by assignee (USPTO PatentsView; needs a free key). | FREE / KEY | M (each S) |

## 4. India

| # | Feature | Proposed code | What it does | Data | Effort |
|---|---|---|---|---|---|
| 21 | India pack | `FIID`, `BULK`, `ANNC` (check) | FII/DII daily cash-market flows; bulk and block deals; corporate announcements; a native NSE option chain (today only through the NSE MCP presets); India VIX (Yahoo); results calendar. NSE and BSE endpoints are unofficial and NSE refuses cloud IPs (seen 2026-11-10), so: doc-shaped fixtures in tests, live use from the owner's home connection, `PROVIDER DOWN` when refused, and a check of each site's terms before shipping. Reuse the `stock-nse-india` MCP preset where it already covers a feed. | UNOFF | L |

## 5. Portfolio

| # | Feature | Proposed code | What it does | Data | Effort |
|---|---|---|---|---|---|
| 22 | Tax lots and realised gains | `PORT TAX` | Lot-level realised and unrealised gains (FIFO default, specific-lot option), holding period, India short-/long-term capital gains and US wash-sale flags. Rates and thresholds live in a dated config file, never hard-coded (they change with each budget). Labelled: an estimate, not tax advice. Reuses JRNL's FIFO round trips. | none | M |
| 23 | What-if trade | `ORD` / `RISK` | Before sending an order, show how it changes portfolio VaR, expected shortfall, beta, sector weights and concentration (RISK engine on the hypothetical portfolio). Read only; never places anything. | none | S-M |
| 24 | Benchmark statistics | `ATTR` / `RISK` | Tracking error, information ratio and active share against a chosen benchmark (active share uses the proxy ETF's N-PORT holdings). | FREE | S |

## 6. Infrastructure

| # | Feature | Proposed code | What it does | Data | Effort |
|---|---|---|---|---|---|
| 25 | Local price-history store | `SETTINGS DATA` | Daily (and optional intraday) bars kept in Parquet or DuckDB under the data dir, filled incrementally (only the missing days are fetched), used first by BT, ALPHA, breadth and the technical screener; works offline; fewer upstream calls and rate limits. Each bar keeps its source and fetch time; a stale store says so. Bench: a 10-year 500-name read under a set budget. | none | M-L |

## Also pending (not Bloomberg gaps)
- **Desktop app (owner, later):** bundle the backend as a Tauri sidecar so the desktop app is one install that starts and stops its
  own server; tear-off panel windows for multiple monitors.
- **Settings sync per-field merge (waiting for the owner's yes/no):** see HANDOFF.md.
