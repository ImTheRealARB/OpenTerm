# Phase 13 spec: equity research gaps

Status: **approved as written 2026-10-19 (roadmap defaults pre-approved by the user); steps 1-7 done (step 8, docs and bench, is next).**
Source: [ROADMAP_PHASES_11-19.md](../ROADMAP_PHASES_11-19.md) "Phase 13", [FEATURE_GAP.md](../FEATURE_GAP.md), Vibe-Trading `d0db2e3`
(MIT: `quantlib/valuation/{contracts,dcf,comps}.py`, `tools/institutional_holdings_tool.py`).

Rule that shapes every choice: **zero keys still works; a key unlocks more.** Every function below has a keyless source. The
roadmap named Finnhub and FMP for several rows; probing the real endpoints on 2026-10-18 showed Yahoo `quoteSummary` and the
Nasdaq API already answer them without a key, so the keyed adapters (Finnhub, Alpaca) are *additions* (more news sources,
real-time quotes, a fallback for ratings and surprises), never the only path. FMP is not wired (its useful endpoints are
paid; DATA_LIMITS records it). `TRAN` and `SEG` stay removed.

## Decisions (defaults, approved)

| # | Decision | Default | Why |
|---|---|---|---|
| A | Payload shape | One **table payload** for every new function: `{symbol, title, headline:[{label,value}], sections:[{id,title,columns:[{key,title,kind,align}],rows:[{...}],note}], notes:[str]}`; `kind` is text/int/num/pct/money/price/date; a row's `url` is opened by Enter. One generic panel (`ResearchPanel`) renders it with the canvas `Grid`, `V` cycles sections, `E` exports the visible section | Each later function is a parser plus a ten-line panel file; speed lever 3 |
| B | Routes | `GET /api/research/{ee,eeo,anr,mgmt,si,dvd,splt,cacs,ipo,evts,cn,etf,memb,mgr}` and `GET /api/valuation/{dcf,wacc,rv}`; all answer the standard envelope (`data`, `source`, `stale`, `age_s`, `fallback_from`) | Same cache (SWR + coalescing) and fallback as FA/OWN |
| C | Sources (keyless first) | EE/EEO/ANR/MGMT/ETF info/SI fallback: Yahoo `quoteSummary` modules (`yahoo_research`, subclass of the cookie+crumb adapter). DVD/IPO/SI/ANR extras: Nasdaq API (`nasdaq_research`). SPLT/DVD fallback: Yahoo chart events. SI daily short volume: FINRA Reg SHO files (`finra`). EVTS: SEC 8-K items from the submissions feed already used by FIL. ETF full holdings and MEMB: SEC N-PORT (`sec_nport`). MGR: SEC 13F-HR information tables (`sec_13f`) | All probed live 2026-10-18; fixtures recorded by `scripts/record_phase13.py` |
| D | Keyed adapters | `finnhub` (recommendation trend, earnings surprises, company news, market news) and `alpaca` (news, latest IEX trades). They sit **after** the keyless providers in each capability order, and `supports()` is false without a key so they cost nothing. Fixtures for them are doc-shaped and labelled so in the file (no key was available to record) | Roadmap rows "Finnhub/Alpaca news", "Real-time L1" |
| E | Sentiment (`CN`) | A transparent keyword score (positive minus negative word hits from a fixed list in `research/sentiment.py`), shown as `POS` / `NEG` / `NEU` and labelled `KEYWORD SCORE, NOT A MODEL`. No sentiment from Finnhub (the free tier has none) | Never fake data: the label says what it is |
| F | Valuation (`DCF`, `WACC`, `RV`) | Port Vibe's `contracts.py`, `dcf.py`, `comps.py` (header names the source file and commit; pandas/numpy replaced by plain Python in `sensitivity_grid` and the percentile, so the server never imports them; cross-checked against Vibe's own numbers). A missing input makes the model **NOT RUNNABLE** and the panel lists every missing field. Inputs found in data are shown with source and date (risk-free = Treasury 10Y, beta = Yahoo, tax and interest from SEC filings); inputs that are opinions (equity risk premium, terminal growth, exit multiple, forecast growth, capital-structure basis, discounting, terminal method) must be typed (`ERP=5.5 G=2.5 EXITX=14 GROWTH=6 BASIS=CURRENT CONV=MID TV=PERP`) and are echoed back with their basis `typed on the command line` | The Vibe rule: no default hides an opinion |
| G | Tickers in N-PORT | N-PORT lists name, CUSIP and ISIN but no ticker. `ETF` and `MEMB` show a ticker only when the issuer name matches exactly one SEC `company_tickers` title after normalising (`INC`, `CORP`, punctuation, share-class words dropped); otherwise `-`, and the headline says `TICKERS MATCHED BY NAME: n OF m (APPROXIMATE)` | A guess would be fake data |
| H | ETF to series | Ticker to (CIK, series) from SEC `company_tickers_mf.json`; unit investment trusts that file lacks (SPY, DIA, MDY) from a short curated table; filings found through the EDGAR series atom feed (`browse-edgar?CIK=<series>&type=NPORT-P`). Public N-PORT is quarterly with a 60-day lag; the panel says `AS OF <period end>` | Probed live: works for multi-series trusts such as iShares |
| I | `MGR` | `MGR <name or CIK>` lists a manager's latest 13F-HR against the one before: `NEW / ADDED / TRIMMED / EXITED / UNCHANGED`, grouped by CUSIP (Vibe's diff logic: sum duplicate lines, compare shares). A curated table of about 25 well-known managers maps names to CIKs and is verified against the submissions `name`; any numeric CIK works | Reverse lookup (who holds AAPL) stays Yahoo `HDS` |
| J | Real-time L1 | With Alpaca keys, Alpaca's IEX feed (REST latest trades polled for subscribed US symbols, 1 s) replaces Yahoo ticks for those symbols; the tick source code `a` renders `RT IEX`, every other source `DELAYED`. Without keys nothing changes. Tick-to-pixel budgets must not regress (bench) | The feed is IEX-only volume, labelled as such |
| K | News upgrades | `N` and `CN` gain Finnhub and Alpaca sources when keyed (appear on SOURCES; a missing key shows `KEY REQUIRED: set FINNHUB_API_KEY in APIKEYS` on the section, not an error). Keyword alerts: `ALRT NEWS <WORD> [SYM]` fires when a fetched headline contains the word (checked on each news refresh) | Roadmap "keyword alerts" |
| L | Labels | Every table says its source and age in the header (existing `Header`); keyed-only sections that are missing say `KEY REQUIRED`; anything computed by us says so (`CACS` merges rows, `CN` score, `MEMB` proxy) | Non-negotiables |
| M | TTLs (s) | estimates/ratings/mgmt/etf info 21600; dividends/splits/si 21600; ipo 3600; short volume 21600 (per day file, kept in memory 12 days); n-port and 13F 86400; news 120 | Data changes daily or quarterly |

## Functions

| Code | Args | Shows |
|---|---|---|
| `EE` | security | Consensus EPS and revenue for the current/next quarter and year: average, low, high, analysts, year-ago, growth |
| `EEO` | security | Estimate trend (now, 7, 30, 60, 90 days ago), up/down revisions, last four quarters' actual vs estimate and surprise % |
| `ANR` | security | Recommendation mix by month, mean rating, price target mean/high/low/median with upside, recent rating and target changes by firm |
| `MGMT` | security | Officers with title, age, pay and fiscal year; governance risk scores; latest proxy (DEF 14A) links (board members are in the proxy, not parsed) |
| `SI` | security | Short interest by settlement date with change and days to cover; FINRA daily short volume and short % of volume |
| `DVD` / `SPLT` / `CACS` | security | Dividend history with declaration, record and payment dates and the next ex-date; split history; both merged by date |
| `IPO` | `[YYYY-MM]` | Upcoming, priced, filed and withdrawn US IPOs for the month |
| `EVTS` | security | 8-K filings with each item decoded (2.02 results, 5.02 officer change, ...), link to the filing |
| `CN` | security | Company news from every available source with a keyword score and a source column |
| `DCF` / `WACC` / `RV` | security + `KEY=VALUE` | Vibe valuation engine; `NOT RUNNABLE` lists missing inputs; results show every bridge |
| `ETF` | security | Fund profile (family, category, expense ratio, net assets), full N-PORT holdings (top 10 from Yahoo if N-PORT is unavailable), sector weights |
| `MEMB` | `SPX/NDX/DJI/RUT/MID` or an ETF ticker | Constituents and weights from the proxy ETF's N-PORT |
| `MGR` | `<name or CIK>` | Manager 13F holdings with quarter-over-quarter change |

`HDS` is unchanged (Yahoo holder list with its own percent change). Real-time L1 and the news upgrades touch existing functions
(`Q`, `WL`, `GP`, `N`, `ALRT`), see decisions J and K.

## Build steps (each ends with the five gates and a commit)

1. Spec, recorded fixtures, API tests (strict-xfail per group, markers deleted by the step that makes them pass).
2. Shared layer: table payload helpers, `ResearchPanel`, `yahoo_research` module parsing, `EE EEO ANR MGMT`.
3. Corporate data: `DVD SPLT CACS IPO SI EVTS` (Nasdaq, Yahoo events, FINRA, filings).
4. Valuation: ported engine, `DCF WACC RV`.
5. Funds and managers: N-PORT, `ETF`, `MEMB`, `MGR`.
6. Keyed layer: Finnhub and Alpaca adapters, `CN`, news upgrades, keyword alerts.
7. Real-time L1.
8. Docs (COMMANDS, DATA_LIMITS, CHANGELOG, PERFORMANCE), bench, real-backend smoke run, handoff.

## Done when
Each provider has recorded (or labelled doc-shaped) fixtures and a DATA_LIMITS entry; each function has an e2e test with data
and, where a section needs a key, the `KEY REQUIRED` path; all gates green; bench unchanged (recorded in PERFORMANCE.md).
