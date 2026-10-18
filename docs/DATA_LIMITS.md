# Data limits

Known limitations, surfaced in the UI where they apply. Updated each phase.

## Providers (verified 2026-10-17)

| Provider | Key | Coverage | Limits and caveats |
|---|---|---|---|
| Yahoo Finance | none | Global equities/ETFs (`.NS` `.BO` `.L` `.T` `.HK` ...), indices `^`, FX `=X`, crypto `-USD` | Unofficial and undocumented; can break or block without notice. Exchange-delayed. `v7/quote` now needs a session crumb (401), so quotes come from `v7/spark` and `v8/chart` metadata, and the day **open** is blank on batch quotes. Intraday lookback: 1m = 7 days, 2-30m = 60 days, 60m = 730 days. |
| Nasdaq.com API | none | Plain US tickers (stocks, ETFs) | Fallback only. **Daily history only.** Delayed. The `lastTradeTimestamp` label can lag the data by a session. ETF responses have no 52-week range. |
| Stooq | none | — | **Retired.** CSV downloads now serve a JavaScript bot check. OpenTerm does not bypass bot protection. |

Non-US symbols currently have **one** zero-key source (Yahoo). If Yahoo is down they show
`PROVIDER DOWN` (or their last cached value, labelled `STALE` with its age). Keyed fallbacks
(Twelve Data, Finnhub) are planned for phase 3.

## Streaming (phase 3)
- Live ticks come from Yahoo's public streamer (`wss://streamer.finance.yahoo.com`), unofficial and
  undocumented. It only sends a message when a price changes, so closed markets show no ticks;
  their rows show the last REST snapshot with its source and age.
- Prices arrive as **float32** and are rounded to the instrument's price hint (2 dp for most), so
  very large prices can be off by the last digit (e.g. BTC at 81,591.72 is exact to ±0.01).
- If the stream is down, the backend **polls REST quotes every 5 s** for subscribed symbols and
  sends only real changes; the UI labels these `POLL`, stream ticks `STREAM`, test data `SYNTHETIC`.
- **Daily charts do not add a new bar from ticks.** Live ticks extend today's bar; the next day's
  bar appears with the next history refresh (F5 or cache expiry), rather than being guessed.

## Descriptions (DES)
- From Yahoo `quoteSummary`, which needs the same cookie + crumb a browser session gets (no bot
  check is involved). Fallback for US symbols: Nasdaq company profile (sector, industry and
  description only; no valuation numbers).
- `EXCHANGE DATA DELAYED N MIN` is the delay reported by the source per exchange.

## Phase 5 sources (verified 2026-10-17)

| Function | Source chain | Limits and caveats |
|---|---|---|
| N (top stories) | Publisher RSS: CNBC, MarketWatch, BBC Business, Economic Times markets, Mint markets (override in `config.yaml` `news.feeds`) | Headlines, the feed's own teaser (max 300 chars, tags stripped) and a link only. Articles open on the publisher's site. Feeds that fail are listed as `NOT ANSWERING`. MarketWatch and Mint sometimes send invalid UTF-8; the bad bytes show as `�`. |
| N (security) | Yahoo headline RSS, then GDELT | Yahoo RSS is unofficial and sparse outside US listings. The GDELT fallback searches the symbol's base as a keyword (3+ letters only). |
| N (keyword) | GDELT DOC 2.0 (English, last 7 days) | GDELT asks for one request every 5 s and answers in 8-12 s from India. It often answers 429 even when calls are spaced; a second search inside 5 s waits for its slot (up to 6 s). |
| MOV | Nasdaq.com market movers (US only) | Includes warrants and penny stocks as Nasdaq reports them. Each tab shows Nasdaq's own "data as of" (tabs can be from different sessions). %CHG on the share-volume tab is derived from the reported last and change. Slow (4-5 s), hence a 12 s timeout. Yahoo predefined screeners returned zero rows on 2026-10-17 (a Saturday, with and without crumb), so they are not used. |
| CRYP | CoinGecko markets (top 50), then Binance `data-api.binance.vision` 24 h tickers | CoinGecko keyless is roughly 5-30 calls/min (backend TTL 60 s). Binance fallback: 22 fixed USDT pairs, prices in USDT, no rank or market cap (blank). Binance rejects the whole call if one pair does not exist. |
| WEI, FX, FXC, CMDTY | Yahoo quotes + stream (same path as Q) | Fixed symbol lists in `frontend/src/functions/boards.ts`, all checked on Yahoo spark. FXC crosses are triangulated through USD from `USDxxx=X` legs; a missing leg leaves the cell blank. Commodity units are contract specs (USC = US cents). |
| WL | SQLite (`watchlists` table) | Up to 500 symbols per list; aliases are resolved like the command line (EURUSD becomes EURUSD=X). |

## Behaviour on failure
- Cached data is served instantly and marked `stale` with its `age_s` while a background refresh runs.
- A provider that fails 3 times in a row, or returns 429, is skipped for 5 s doubling up to 5 min,
  and probed every 30 s until it recovers.
- An unknown symbol is `NO DATA FOR SYMBOL`; it never trips a provider.
- Error responses carry `detail` with each provider's reason (e.g. `gdelt: rate_limited (...)`); the
  N, MOV and CRYP panels show it next to the error.

## Fixture mode
`OPENTERM_FIXTURES=1` replays recorded responses from `backend/tests/fixtures/` (tests and bench).
Only recorded symbols answer; everything else is `NO DATA FOR SYMBOL`. The status bar and SOURCES
show `FIXTURES` while it is on.

## Other
- **Market open/closed lights ignore exchange holidays.** They follow regular weekday sessions only (NY, LN, IN, TK, HK, with lunch breaks for Tokyo and Hong Kong).
- **Browser-reserved shortcuts.** In a normal browser tab, Ctrl+W, Ctrl+T, Ctrl+N and Ctrl+1..9 cannot be intercepted. Use Alt+W and Alt+1..9. The desktop (Tauri) build will not have this limit.

## Phase 6 sources (FA, FIL/SEC, OWN, HDS)

| Function | Source chain | Limits and caveats |
|---|---|---|
| FA | SEC EDGAR XBRL company facts (`data.sec.gov`), US filers only | One call per company serves annual and quarterly views (4-5 MB for large filers, 15 s timeout, backend TTL 6 h). Columns come from each filing's own fiscal labels. Q4 is not filed on its own: it is derived as the fiscal year minus the 9-month YTD and shown with `*`. Free cash flow is computed (operating cash flow minus capex), not reported. A line a company does not tag shows `—`; companies use different tags, so lines are not comparable across companies without care. |
| FIL, SEC | SEC EDGAR submissions index | The most recent filings (a company's `recent` list, up to 300 shown). The document opens on sec.gov in a new tab; filing text is not downloaded or scraped. Backend TTL 15 min. |
| OWN | SEC Form 4 XML (up to the 20 newest filings), Yahoo `insiderTransactions` as fallback | Each Form 4 is parsed once and kept forever (filings never change). Filings that fail to download or parse are counted as `FORM 4 NOT READ`. BOUGHT and SOLD total only open-market codes P and S; grants, option exercises and gifts are listed but not totalled. Yahoo's fallback has no Form 4 link for most rows and about 80 rows covering roughly two years. Backend TTL 1 h. |
| HDS | Yahoo `quoteSummary` (institutionOwnership, fundOwnership, majorHoldersBreakdown) | Top 10 institutions and top 10 funds only. Holders come from 13F filings, which are quarterly and filed up to 45 days after quarter end, so positions can be months old; the `REPORTED` column shows each holder's date. Needs the Yahoo cookie + crumb (see Yahoo notes). Works for most US listings, thin elsewhere. Backend TTL 6 h. |

- **SEC fair access:** at most 10 requests per second per client and a declared `User-Agent` with a contact. OpenTerm sends
  at most 8 per second (token bucket, burst 8). Set `SEC_USER_AGENT="Your Name you@yourdomain"` in `.env`. Without it a
  generic agent is sent, SEC may answer 403, and FA, FIL and OWN show `PROVIDER DOWN` with the instruction to set it.
  The address is read from the environment only; it is never written to the repo.
- **US filers only:** non-US listings (`.NS`, `.L`, ...), indices, FX, futures, crypto and funds without 10-K/10-Q show
  `SEC DATA COVERS US FILERS ONLY`. That is a coverage limit, not an error. HDS and Yahoo-based OWN may still answer.
- **Ticker to CIK** uses SEC's `company_tickers.json`, cached in memory for 24 h. Class shares map `BRK.B` and `BRK-B` to the same filer.

## Phase 7: macro (FRED, MACRO, RATES, ERN, ECO)
Probed 2026-10-17. All of it works with zero keys except FRED search and series titles.
- **FRED values (keyless).** `fred.stlouisfed.org/graph/fredgraph.csv?id=X[&cosd=YYYY-MM-DD]`. Values only: no
  title, units or frequency (OpenTerm adds built-in titles for the ~20 series in MACRO's list; any other id shows
  "no title or units"). Missing observations are empty fields and stay missing (shown as a count, never filled).
  Unknown id = 404. **A browser User-Agent makes this host hang**, so the adapter sends `OpenTerm/0.1`. Several ids of
  mixed frequency come back as a zip and same-frequency ids ignore `cosd`; the adapter fetches one id per call and
  slices to the range itself. Updated by FRED on each series' release schedule: daily series lag by about a day,
  monthly ones by weeks.
- **FRED API (`FRED_API_KEY`, free).** Adds titles/units/frequency, MACRO search across ~800k series and a release
  calendar fallback. 120 requests/min upstream; OpenTerm paces at 2/s. The key travels in the query string, so error
  text is redacted before it reaches the UI or the log. No recorded answers exist for the keyed paths (no key was
  available): the `fred_api_docshape_*` fixtures are built from the documented response shape, labelled as such in
  `providers/fixtures.py`. Treat the keyed path as untested against the live API.
- **RATES (Treasury).** `home.treasury.gov` par yield curve CSV, one file per calendar year, newest row first. The
  curve date is the last business day published (usually yesterday), shown on the panel with a day count when it is
  more than 4 days old. 1.5M exists only since 2025-02. The 1Y comparison needs last year's file; if that file fails
  the panel says so and drops the 1Y column. Fallback when Treasury is down: FRED `DGS*` series (fewer tenors,
  same par yields), flagged on screen.
- **ERN (Nasdaq).** `api.nasdaq.com/api/calendar/earnings?date=`: one call per day, 1-4 s. Future days carry the
  consensus EPS and last year's figure; past days carry reported EPS and surprise. Weekends and holidays answer
  `rows: null`, shown as an empty day. Times are only pre-market / after-hours / not supplied. Estimates come from
  Nasdaq's data vendor and are not verified by OpenTerm. Days further than 400 days from today are refused.
- **ECO (BLS + BEA).** Official ICS schedules, keyless: BLS `bls.ics` (current through 2026-12 when probed) and BEA's
  subscription feed (through 2027-12). They list **release dates and times only: no forecasts, no actuals, no
  previous values**. Not covered: FOMC and Fed releases, Census, ISM and other private surveys. "MAJOR" is a name
  match on a short list of market-moving releases, not an importance rating from the agencies. BLS returns 403 unless
  the User-Agent names a contact (`SEC_USER_AGENT` in `.env`); BEA times are UTC and are shown in US Eastern. If one
  agency's feed is down the panel says which one is missing.
- **Cache TTLs (config.yaml):** FRED values 1 h, FRED search 24 h, curve 30 min, earnings 15 min, calendar 6 h.

## Phase 9: EQS, COMP, HIST, CORR
- **EQS universe = Nasdaq screener download** (`api.nasdaq.com/api/screener/stocks?tableonly=true&download=true`): about 7,000 US-listed
  rows (Nasdaq, NYSE, AMEX), roughly 2.2 MB and 2-3 s to fetch. Cached 15 min server-side (`screener_ttl_s`), 5 min in the browser;
  the payload is reduced to a columnar form of about 1 MB. Prices are the last session's (not live). Rows with no market cap or sector
  stay in the universe but never pass a numeric / sector filter on that field. Non-US markets are not covered.
- **COMP peers = Yahoo `v6/finance/recommendationsbysymbol/SYM`** (keyless, no crumb): about 5 "people also viewed" symbols with a
  score. An unknown symbol returns an empty list; then COMP falls back to the largest same-industry names in the screener (US only) and
  says so (`SAME INDUSTRY, LARGEST FIRST`). Peers come from a recommender, not an official peer group. Cached 24 h.
- **Period returns (COMP) and CORR use adjusted closes** when Yahoo sends them (daily and longer bars); other sources give raw closes and
  the panel header says `RAW CLOSES`. A return is blank when the history does not reach that far back.
- **CORR** needs the dates every symbol traded (exchange-local), so mixing exchanges with different holidays shrinks the sample; the panel
  warns below 20 common returns and when time zones are mixed. At most 20 symbols (20 history calls).
- **CSV export** is client-side only (what the grid shows, formatted); nothing is sent to a server.

## Phase 11: keys, jobs, LLM gateway (2026-10-19)
- **No data source changes.** Every function still works with zero keys. Keyed rows on SOURCES show `KEY REQUIRED`,
  `UNTESTED`, `OK`, `INVALID`, `QUOTA` or `ERROR` from the key store; a key test only reports the state, never data.
- **Key tests cost one call each**, made only when you save a key or press `T` in APIKEYS (none on a timer). Endpoints:
  OpenRouter `/api/v1/key`, OpenAI and Anthropic `/v1/models`, Finnhub `/quote?symbol=AAPL`, Alpaca paper `/v2/account`,
  FMP `/stable/quote`, FRED `series`, EIA `/v2/`, OpenFIGI one mapping, Tradier sandbox clock, Telegram `getMe`,
  SMTP `EHLO` + `AUTH` (no mail sent).
- **LLM gateway:** no AI functions yet (Phase 16), so nothing calls a model on its own. OpenRouter reports the real cost per
  answer (usage accounting); `:free` models cost US$0 but have their own low rate limits. OpenAI and Anthropic direct
  need a price in `config.yaml` `llm.prices` (none shipped: prices change), else the call is refused (`PRICE UNKNOWN`).
  Daily spend cap US$1.00 by default (APIKEYS `C`), checked before each call against the worst case (`max_tokens` at the
  output price) and reset at local midnight.
- **Ollama** (local, free, no key): SOURCES shows `OK` with the model count if `http://127.0.0.1:11434/api/tags` answers in
  300 ms, else `DOWN`. Probed at most every 10 s.
- **Background jobs** run in local worker processes; no upstream calls. Phase 11 ships only the `sleep` TEST JOB.
- **Fixture mode:** key tests replay recorded 401s (and a doc-shaped OpenRouter success); the Ollama port refuses; OpenRouter
  chat replays `llm_openrouter_stream.txt` once it is recorded (not yet: waits for the key); other LLM calls are 404.

## Backtester engines and Binance candles (Phase 12 step 5)
- **Engines built:** US, UK, Hong Kong, Canada (global equity), India (delivery), crypto perpetuals, forex, global
  futures, composite. **Not built:** China A, China futures, Korea, Vietnam, Brazil, Argentina (a composite or `MKT=`
  naming one fails with the market's name). Options waits for Phase 14.
- **Crypto `perpetual_strict` is cut.** Vibe's strict mode (mark-price frames, maintenance-bracket schedules, cross-margin
  risk, evidence files) needs mark-price and bracket series that no keyless source gives. The engine refuses
  `perpetual_strict=True` instead of running with invented inputs. Funding uses the recorded Binance rate per bar; a
  crypto run through the API charges **no funding on spot** (`funding_rate` 0) and the recorded rate on `.P` perps.
- **Binance candles** (`binance_klines`, keyless): `BTCUSDT` / `BTC-USDT` spot from `data-api.binance.vision`;
  `BTCUSDT.P` USD-M perpetual from `fapi.binance.com` with the mean funding rate of each daily or weekly bar. Binance
  refuses some regions on `fapi` (HTTP 451): the perp then shows PROVIDER DOWN with that status. Funding history is paged
  (1000 settlements per call, 12 pages at most); bars before the first recorded funding settlement are dropped from a
  perp run, never filled. Volume goes through `Bars.v` as a whole number (BTC volume 459024.106 reads 459024).
- **Spot uses the perpetual fee model** (taker 0.05% open, maker 0.02% close) because that is Vibe's crypto engine;
  `FEES=<bps>` adds to it. Only `USDT` pairs: `BTC-USD` still comes from Yahoo and is a spot-like crypto run.
- **Forex ignores `SLIP`** (its cost is a spread plus slippage in pips) and says so. **Composite refuses mixed
  currencies** (no FX translation yet) and any symbol it cannot place in a built market.

## Phase 13: equity research (2026-10-18)
- **Estimates, ratings, officers, key statistics, fund profile** come from Yahoo `quoteSummary` (unofficial, cookie + crumb); consensus is Yahoo's
  aggregation. **Dividends / splits** use Nasdaq, with Yahoo chart events as the fallback. **Short interest** is Nasdaq (twice a month, a delay of
  days); **short volume** is FINRA Reg SHO daily files (off-exchange TRF volume only, not total volume).
- **ETF / MEMB** read SEC N-PORT: quarterly, filed about 60 days after the period end, and the panel says `HOLDINGS AS OF`. N-PORT lists name and CUSIP,
  not ticker, so a ticker is shown only when the name matches exactly one SEC company; the headline counts the matches (approximate). SPY, DIA and
  MDY are unit investment trusts missing from the SEC fund-ticker file, so a short curated table maps them. `MEMB` is the proxy ETF's holdings, not
  the index provider's list. **MGR** diffs the manager's two latest 13F-HR filings (long US equity positions only, 45 days after quarter end);
  a curated table maps about 25 well-known names, any numeric CIK works.
- **DCF / WACC / RV** use filed figures from SEC companyfacts. A company whose filings do not tag a needed line (MSFT: EBITDA) is NOT RUNNABLE, never
  filled in. RV peers default to Yahoo's recommended symbols and only those that are SEC filers with a market cap are used (`PEERS USED: n`).
  The forecast is your assumptions applied to filed figures: a scenario, not a prediction.
- **Finnhub and Alpaca** (keys in `APIKEYS`) are written from the documented response shapes; no key was available to record them, so their fixtures
  are labelled doc-shaped and the live shapes are unverified. Finnhub backs `ANR` with the recommendation trend only (no targets) and `EEO` with EPS
  surprises only (no revisions), and says so. **FMP is not wired** (its useful endpoints are paid). `TRAN` and `SEG` are not built (paid data).
- **Real-time quotes (`RT IEX`)** are the last trade on IEX only (one exchange, about 2-3% of volume): the price can differ from the consolidated last
  sale and the size is IEX volume. Polled once a second for at most 100 US symbols; Yahoo ticks resume when IEX stops answering for 5 seconds.
- **CN** leaves GDELT out (one call per 5 s, 8-12 s answers); `N <SYM>` still uses it as a fallback. The score is a fixed positive/negative word list.
- **News alerts** are evaluated in the open browser app only (like price alerts); a headline older than the alert never fires it.

## Imported bars (Phase 12 step 8)
- `IMPORT` stores daily bars you provide; they are never from a market source and are labelled LOCAL DATA in GP and BT. There is no
  adjusted close: a CSV with split-adjusted prices is used as given. Intraday bars are refused. A stored symbol shadows a real ticker
  of the same name everywhere (history, GP, BT) until you `IMPORT DEL` it; quotes and streaming still come from the market sources.

## Phase 14 rates sources (RATES views; recorded 2026-10-18)
No key is needed for any of them. Each table header shows the source, its age and, when a fallback answered, which provider failed first.
- **`RATES EUR` (ECB, `ecb`)**: ECB Data Portal SDMX, euro area AAA government spot curve (Svensson fit by the ECB), tenors 3M, 6M, 1Y, 2Y, 5Y, 10Y, 20Y, 30Y.
  It is an estimated curve, not a traded yield. Published each TARGET business day, about one day behind. Cached 1 h.
- **`RATES GBP` (Bank of England, `boe`)**: Interactive Database CSV, nominal par yields at **5, 10 and 20 years only** (IUDSNPY, IUDMNPY, IUDLNPY): the full gilt curve
  is not offered as a keyless download. Three points are too few for a Nelson-Siegel fit, so `RATES NS GBP` answers "needs 4 curve points". One to two days behind.
- **`RATES CAD` (Bank of Canada Valet, `boc`)**: Government of Canada benchmark yields for 2, 3, 5, 7 and 10 years. The LONG and real-return series have no fixed
  maturity and are left out. About one business day behind (the newest day is often missing until the evening).
- **`RATES JPY` (Japan MoF, `mof`)**: the ministry's daily JGB CSV, 1Y to 40Y. The file is the whole history (about a megabyte), downloaded on a cache miss; the newest
  40 days are kept. A dash in the file (no benchmark that day for that maturity) is shown as no value. One business day behind.
- **`RATES SPRD` (FRED OAS, `fred_oas`)**: ICE BofA option-adjusted spreads (US corporate, high yield, BBB, BB, CCC) from the keyless `fredgraph.csv`, read with a plain
  client User-Agent (FRED hangs on a browser one). FRED serves only the last three years of ICE data and is about one business day behind. The 1-year percentile is computed here
  from the daily values of the last 365 days. Cached 6 h. A series that fails shows no value and is named in the notes.
- **`RATES AUCT` (TreasuryDirect, `treasurydirect`)**: the securities API, auction results of the last 30 days and the announced upcoming auctions. Results appear within
  minutes of an auction; an auction is announced about a week before. Bid-to-cover and high rate are the Treasury's figures; an upcoming auction has neither (shown as no value).
- **`RATES NS <ccy>`**: a Nelson-Siegel fit computed here (the Vibe-Trading `fit_yield_curve` port) to the shown yields as zero rates; parameters, RMSE in bp and the fitted column
  are labelled as a model fit, not a source figure.
- Day changes are against the previous *observation* (not calendar day) and five observations back; they show a dash when the source returned fewer observations.

## Phase 14 step 7: futures, COT, policy path and calculators

- **`CT <root>`**: one Yahoo `v8/chart` per contract (`yahoo_futures`, delayed, unofficial). Yahoo returns no expiry date, so roll yield is annualised by *contract month spacing*, not days to expiry. A contract Yahoo
  does not list (recorded: `ZNM27`) is skipped and named in the notes, never invented. SHAPE (CONTANGO / BACKWARDATION / MIXED) is called only from the listed contracts. Cached 120 s.
- **`WIRP`**: `ZQ` fed funds futures (implied average rate = 100 - price) chained across the FOMC decision dates parsed from federalreserve.gov (cached 24 h), starting from the effective rate (FRED `DFF`). The decision
  takes effect the next day, so a month with the decision on day d averages d days at the old rate; a decision in the last quarter of its month reads the next month's contract instead. "25BP MOVE SHARE" is
  |change| / 25 bp, illustrative, labelled `NOT A PROBABILITY FORECAST`. No term premium or day-count refinement is applied.
- **`COT <market>`**: CFTC legacy futures-only report (Socrata `6dca-aqww`), 160 weeks, as of Tuesday and released Friday; cached 6 h. Names resolve through a curated alias table, else a substring search of the CFTC market
  names seen in the last 90 days (cached 24 h). The percentile is computed here over the weeks shown. Options-and-futures-combined and disaggregated reports are not used.
- **`YAS`, `SWPM`, `CDSW`, `FXFA`** are calculators: no free bond, swap or CDS database exists, so the instrument is described by its terms and a missing term makes the answer `NOT RUNNABLE` listing every missing field.
  YAS yield is a periodic-compounding yield with a fractional first period; SWPM is single-curve (the Treasury par curve is a *discount proxy, not SOFR/OIS*); CDSW is the flat-hazard credit-triangle engine, not the
  ISDA standard model; FXFA is covered interest parity from government yields (USD Treasury bills, EUR ECB 3M-1Y, JPY MoF 1Y) or typed `R1=`/`R2=`, ACT/360 simple interest, not a dealer quote. A currency with no free
  short rate (GBP, CAD, ...) is NOT RUNNABLE until its rate is typed.

## Phase 14 options sources
- **Yahoo options** (keyless, crumb + cookie): eight expiries per symbol, picked as the nearest plus those closest to a 7-day spacing. Yahoo's own IV is shown
  as a cross-check; Greeks are computed here (Black-Scholes on the mid) and labelled so.
- **Tradier** (optional `TRADIER_TOKEN`, inert without it): its Greeks and IV replace the computed ones when it answers. The recorded fixture
  (`tradier_*_aapl*.json`) is **doc-shaped, NOT a recording**: bid/ask/volume come from Yahoo, Greeks and IV are round placeholder numbers. Shape drift is unverified live.
- **Deribit** (keyless): BTC options in fixture mode; ETH, SOL, XRP work live only. IV is the exchange mark IV.
- **Smile fit**: quadratic in log-moneyness, never extrapolated outside the quoted strikes. **IV30** is interpolated from the chain and stored once a day in
  `iv_snapshots` (LOCAL SNAPSHOTS): `HIVG` implied history starts the day you first open it; there is no free historical IV source.
- **BT options** prices structures with Black-Scholes on trailing historical vol, not quotes (MODEL-PRICED, NOT MARKET QUOTES).
- **BT options limits**: model marks only (no bid/ask, no skew dynamics, no early assignment, no slippage); the IV is 0.30 until a 30-bar window exists, and the run says so (`iv_note`). Option trade rows leave entry price, pnl % and holding bars empty.
- **OSA to BT**: `B` in OSA opens `BT <SYM> MKT=options`. OSA has no open date or exercise style, so type `OPEN=yyyy-mm-dd STYLE=european|american` (and `EXP=` in OSA); until then the run says NOT RUNNABLE: MISSING. The stored structure lives in memory and is lost on reload.
- **`FACT` (Ken French library, `kenfrench`)**: daily Fama-French 5 factors and momentum from the keyless Dartmouth zips (plain User-Agent), parsed in pure Python and cached 24 h. The library lags about two months, so the regression window ends at the last factor day (shown as `FACTOR DATA ENDS`). US long-only factors: non-US names load on them loosely (labelled).
- **`QL` calculators**: daily bars only. `ROLL`, `KYLE`, `VPIN` and `AMIHUD` are coarse proxies of tick-level quantities (labelled `DAILY BARS, NOT TICK DATA`); signed flow is a bulk volume classification of each day. `QL DSR` needs no bars; without `TRIAL_SR_STD` it assumes 1/sqrt(T-1).
- **`KITE` (Zerodha Kite Connect, `kite`)**: the one paid source, read-only. Needs your own Kite Connect developer app (`KITE_API_KEY`, `KITE_API_SECRET` in APIKEYS) and a **login every trading day** (`KITE LOGIN`; the one-day token is kept hidden in the key store and ends at 06:00 IST or on any 403 TokenException, shown as `KITE LOGIN EXPIRED`, with Yahoo answering meanwhile). Nothing logs in unattended. Used for `.NS`/`.BO`/`^NSEI`/`^NSEBANK` and NFO/MCX bars (3 requests/s, chunked to Kite's per-call window), `<X>.NFO|.MCX` OMON chains and CT futures with open interest (quotes 10 requests/s, 500 instruments per call) and the ticker (`RT KITE`, off in fixture mode). IV and Greeks are computed here only when `R=` (and `Q=`) are typed (`COMPUTED HERE (BLACK-SCHOLES), NOT VENDOR`); MCX expiry time is taken as 15:30 IST. **There are no orders, GTT, margins, holdings or positions anywhere**; a test scans for them. The `kite_*` fixtures are **doc-shaped from the Kite Connect v3 documentation, NOT A RECORDING**, and every fixture-mode answer says so; `scripts/record_phase15.py --kite` records real answers once a key and a login exist.

## Phase 15 limits (risk, quant library, alphas, Kite)
- **`RISK` stress replays** use unadjusted closes over the three fixed windows; a holding with no history over a window is excluded and the row shows `COVERAGE` (covered weight). The loss is on the covered weight only.
- **History range `20Y`** (`range=20y&interval=1d`) keeps daily bars back to about 2006; Yahoo `range=max` is downsampled to monthly, so it is not used. Yahoo's burst limit paces many-symbol fetches in `_bars`, so a 100-name `ALPHA` scan fetches slowly the first time.
- **`FACT`**: the Ken French library lags about two months; the regression window ends at the last factor day (`FACTOR DATA ENDS`). Live file shapes are only fixture-tested.
- **`ALPHA`**: `TOP100` takes the 100 largest names of the screener payload and has not been run on live data; `SYN` is synthetic and says so. Enter on a factor does not open its formula yet.
- **`QL`**: `VPIN`, `ROLL`, `KYLE` and `AMIHUD` run on daily bars (`DAILY BARS, NOT TICK DATA`).
- **`PORT OPT`**: `CAP` is enforced by re-solving with bounds for the SLSQP methods and by clipping and redistributing for `EQVOL` and `HRP` (`CAP BY CLIPPING, NOT RE-OPTIMISED`). Results are estimates from the lookback window, not forecasts.
- **`PORT ATTR` BRINSON** holds today's holdings constant over the range (not your historical weights); benchmark sector weights come from the benchmark ETF's current sector weighting.
- **Kite**: the WebSocket ticker has never run against a live key, and the `kite_*` fixtures are doc-shaped (Kite Connect v3 documentation), not recordings. Expect shape drift on first live use (see `scripts/record_phase15.py --kite`).
