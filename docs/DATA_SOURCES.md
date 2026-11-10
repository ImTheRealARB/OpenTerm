# Data sources: the hierarchy and a free-source shortlist

## How OpenTerm picks a source

For each kind of data (quotes, history ...) the sources are ranked in one table,
[`backend/openterm/providers/hierarchy.py`](../backend/openterm/providers/hierarchy.py). The router walks it top-down and takes the first
source that is **switched on for that symbol** and **healthy**:

- no key set, or the symbol is not one the source covers (Kite never sees AAPL): skipped, costs nothing;
- rate limited, down, or too shallow for the request: the next source answers, and the chart says `<name> DOWN, VIA FALLBACK`;
- a key added in `APIKEYS` takes effect at once (the history cache key changes with the set of keyed sources that are on).

Ranking weighs **depth** (how far back, which instruments), then **freshness** (real time or delayed), then **rate limits** (a source with a few
calls a day must not sit above one that can feed a 50-row grid). **Speed** is measured live on `SOURCES`; the circuit breaker demotes a slow or
failing source by itself, so the table does not guess it. Every entry records its reasons, and `SOURCES` shows where each provider sits.

How far back minute candles reach is a property of the source that answers, not a global rule: every provider can declare `intraday_days`, and
`GET /api/history/limits?symbol=X` reports the deepest source switched on for `X` (Yahoo 60 days; Kite about 11 years for minute candles of Indian symbols while a login is valid). The chart's candle-length dropdown reads it.

`config.yaml` `providers:` can still pin a capability's order by hand. It wins over the table and the log says so; remove the line to get the
hierarchy back.

To add a source: write the adapter ([ADDING_A_PROVIDER.md](ADDING_A_PROVIDER.md)), register it, add one `Rank` at the position it earns, and
`backend/tests/test_hierarchy.py` checks the entry is complete.

## In the app today

| Source | Key | Kind | Position |
|---|---|---|---|
| **Kite Connect** | paid app, daily login | NSE, BSE, NFO, BFO, MCX, CDS: real-time quotes; minute bars back to 2015 (1 minute verified 10 years), open interest | `quotes` #1, `history` #1 |
| **USGS earthquakes, NASA EONET** (new, `MAP`) | none | M4.5+ quakes of the past 7 days; open natural events (storms, volcanoes, floods, sea ice) without wildfires | `MAP` layers `QUAKES`, `EVENTS` |
| **Frankfurter** (new) | none | ECB reference rates: one fix per business day for FX pairs (EURUSD=X, USDINR=X, crosses), back to 1999; no high/low | `history` below Yahoo, `quotes` below Yahoo (Yahoo-down fallback for FX) |
| **Companies House, Marketaux, Etherscan** (new) | free keys | `UKCO` UK register; `N` headlines with sentiment; `ADDR` EVM address and gas | specialists (Marketaux joins the news order) |
| Yahoo, Nasdaq, SEC EDGAR, FRED (keyless CSV), ECB, BoE, BoC, MoF, Treasury, CFTC, Deribit, OKX, Binance, Kraken, Coinbase, CoinGecko, DefiLlama, Polymarket, Kalshi, World Bank, DBnomics, Open-Meteo, NWS, NSE archive, AMFI, GDELT, RSS | none | global shares, rates, futures, crypto, macro, weather, prediction markets, funds, news | fallbacks and specialists |
| Finnhub, Alpaca (IEX), EIA, OpenFIGI, Tradier, FRED API | free keys | news, ratings, real-time US trades, energy, identifiers, options | specialists |
| **Twelve Data, Polygon (now Massive), FMP, Alpha Vantage** (new, workstream 07) | free keys, inert until set | quotes, candles, symbol search, and (FMP, Alpha Vantage) FA statements; Twelve Data adds FX and non-US exchanges | `quotes` / `history` below Yahoo in this order: Twelve Data, FMP (quotes) or Polygon (history), then the other, Alpha Vantage last; `search` below Yahoo; `fundamentals` below SEC (FMP, then Alpha Vantage). With no key none of them is asked and the chain is exactly the old one. Limits and terms: see "Keyed market data" below |

## Free sources worth adding (catalog, researched 2026-11-05)

Legend. **Checked** = confirmed by a search result or the provider's own page during this work. **Memory** = my recollection, not verified: confirm
on the provider's page before building. Most search hits were comparison blogs, so even "checked" limits can drift; free tiers change often.
"In app" = already in OpenTerm, so nothing to add.

### Needs a free key

| Source | Adds | Free limits | Status |
|---|---|---|---|
| **BLS API v2** | US CPI, jobs, wages, productivity | registered: 500 queries/day, 50 series per query; renew yearly | Checked |
| **BEA API** | US GDP, trade, income, industry accounts | UserID by sign-up; limits not confirmed | Checked (key only) |
| **Census API** | US trade, retail sales, housing, demographics | key now required for all queries (2026 Census video) | Checked |
| **UN Comtrade** | Trade flows between every pair of countries, by product | free key: 500 calls/day, 100,000 records per call | Checked |
| **UK Companies House** | UK company profiles, officers, filings, charges | free key, 600 requests per 5 minutes (HTTP 429 after) | Built: `UKCO` (profile, officers, filings, search; charges not read). Run live: fixtures `companies_house_real_*.json` are real recordings |
| **EDINET (Japan FSA)** | Japanese company filings | free `Subscription-Key`; the key page was reported blank on 2026-09-16 | Checked (blogs) |
| **Marketaux** | Financial news with sentiment scores | about 100 requests/day (unverified); the adapter stops at 90 a day and keeps answers 15 minutes | Built: merged into `N` headlines, sentiment shown on the detail line. Run live: `marketaux_real_news_aapl.json` is a real recording |
| **Etherscan** | Ethereum and some other chains: balances, transactions, gas | 3 calls/s, 100,000/day, selected chains | Built: `ADDR` (balance, last 20 transactions, gas). Run live: fixtures `etherscan_real_*.json` are real recordings |
| **CoinMarketCap Basic** | Crypto ranks and prices beyond the top 50 | 15,000 credits/month, 50 requests/minute | Checked (CMC's own article) |
| **AISstream** | Live ship positions, destinations, ETAs, ship details (WebSocket) | free, **beta, no uptime promise**; 3 connections per account and per IP (docs) | Built: `AIS` (ship positions in a chokepoint or box, listen up to 15 s). Run live 2026-11-05: `ais_stream_recording.json` is a real 46-message recording |
| **Twelve Data, Alpha Vantage** | Fallback prices, daily history | **Built** (workstream 07, see "Keyed market data" below) | Built |
| **Tiingo** | Fallback prices, daily history | not built | Checked |
| **Angel One SmartAPI, Fyers** | Indian broker data, backup to Kite | free with account; TOTP login | Checked (forums) |
| **USDA NASS QuickStats** | US crop, livestock and food statistics | free key | Memory |
| **USASpending.gov** | Federal contracts, grants, agencies (USD obligated) | no key | Built: `USASP` (top contract recipients and largest awards for a keyword over 3 fiscal years; `USASP AGENCY` top agencies, Enter drills into an agency). Run live 2026-11-05, real recordings |
| **Federal Register** | Rules, proposed rules, notices, presidential documents | no key | Built: `FEDREG [RULE\|PROPOSED\|NOTICE\|PRESDOC] <words>`. Run live 2026-11-05, real recordings (an empty search has no `results` key) |
| **OpenFEC** | US campaign finance: candidates, committees, totals by cycle | free api.data.gov key `FEC_API_KEY`, 1,000 calls/hour | Built: `FEC`. DOC-SHAPED, NOT RUN with a key (fixtures `fec_*_docshape`, invented numbers). Only the gateway 403 answers are real **Status 2026-11-05: the owner decided not to get this key; stays DOC-SHAPED, never run live.** |
| **Congress.gov API v3** | US bills, sponsors, latest actions | free api.data.gov key `CONGRESS_API_KEY`, 5,000 calls/hour | Built: `CONGRESS`. DOC-SHAPED, NOT RUN with a key. The bill list has no sponsor and (per the docs) no text search, so words filter titles of the 250 latest updated bills **Status 2026-11-05: the owner decided not to get this key; stays DOC-SHAPED, never run live.** |
| **OpenSky Network** | Live aircraft (ADS-B) by box; history not used | works with no account (anonymous: 400 credits/day, 10 s resolution); optional free account via OAuth2 client credentials (`OPENSKY_CLIENT_ID` + `OPENSKY_CLIENT_SECRET`): 4,000/day, 5 s. One call costs 1-4 credits by box area; HTTP 429 carries `X-Rate-Limit-Retry-After-Seconds` | Built: `FLT` (`providers/opensky.py`, pure `world/flights.py`). **Doc-shaped, unrun:** OpenSky refused every connection from the build machine on 2026-11-05, so no live recording exists and the OAuth flow is tested only with a fake transport **Status 2026-11-05: the service was unreachable; never run live, fixtures are doc-shaped until it is back.** |
| **NewsAPI, NewsData.io** | News search | small free tiers; NewsData about 200/day | Memory |
| **OilPriceAPI** | WTI, Brent, gold, silver, gas; its freight endpoints are "being onboarded" | free key | Checked (vendor page); skip: EIA, FRED and Yahoo futures already cover it |

### Keyless (nothing to sign up for)

| Source | Adds | Status |
|---|---|---|
| **IMF PortWatch** | Daily ship transit counts through 28 chokepoints (Suez, Panama, Hormuz, Malacca ...) and activity at about 1,600 ports; ArcGIS REST, 1,000 records per call; satellite AIS, so data lags | Checked |
| **Frankfurter** | ECB FX rates for about 30 currencies back to 1999 | Built (real recording): `history` #5 and `quotes` #3, FX pairs only, daily fix |
| **OECD SDMX, Eurostat, BIS, IMF data API** | Official macro, banking, debt, property prices, trade statistics | Checked (third-party guides; confirm endpoints) |
| **Kraken, Coinbase Exchange public APIs** | Second crypto exchange when Binance is blocked or down: CRYP board, chart candles, CDEP order book | Built (real recordings, 2026-11-05): `history` #4 Coinbase and #5 Kraken (below Yahoo), `crypto` board #3 Kraken and #4 Coinbase, `crypto_depth` #3 Kraken and #4 Coinbase. Numbers and limits in "Kraken and Coinbase" below |
| **MFapi.in** | Mutual fund NAV history for every AMFI scheme | Memory |
| **Drewry World Container Index** | Weekly container freight rates | Free on Drewry's site; API only "on request": not scrapable (bot rules) |
| **SCFI (Shanghai Shipping Exchange)** | Weekly container index | Published weekly; no API found |

### Keyed market data (Twelve Data, Alpha Vantage, Polygon / Massive, FMP): workstream 07

Read-only fallbacks that sit below Yahoo (and SEC for statements). **Every limit and term below is "per provider docs, not verified here":** no
account was available to check the live plans, and free tiers change. Re-check on the provider's page before relying on a number.

| Source | Key (APIKEYS) and where it travels | Free limits | Data on the free plan | Terms to know |
|---|---|---|---|---|
| **Twelve Data** | `TWELVEDATA_API_KEY`, `Authorization: apikey` header (never the URL) | 8 credits a minute, 800 a day; 1 credit per symbol per call; 5000 bars per call | quotes, daily and minute candles, symbol search, FX, shares on NSE, BSE, LSE, TSX, HKEX, TSE, Xetra, Euronext and others; some exchanges and fields need a paid plan; prices can be delayed | Terms page not read here. The `demo` key is public and covers a few symbols only (the fixtures are recorded with it) |
| **Alpha Vantage** | `ALPHAVANTAGE_API_KEY`, `apikey` query parameter (the API has no header form; masked everywhere, see below) | 25 requests a day, 1 a second | US quotes, daily candles (last 100 sessions), income statement, balance sheet, cash flow (3 requests for FA); intraday and full history can be premium | Terms page not read here. The API does **not validate keys**: a made-up key gets data or the 25-a-day text, so APIKEYS TEST can say OK for a wrong key |
| **Polygon.io, now Massive** (`api.massive.com`) | `POLYGON_API_KEY`, `Authorization: Bearer` header | 5 requests a minute | US shares and ETFs: the PREVIOUS session's bar as the quote (not live), daily to minute candles for about 2 years (minute candles include pre- and after-market), symbol search | Terms page not read here. Real-time, snapshots and unlimited calls are paid |
| **Financial Modeling Prep** (`/stable`) | `FMP_API_KEY`, `apikey` query parameter | 250 requests a day | US quote, daily candles (about 5 years), search, annual statements (FA); quarterly statements, intraday and most non-US data are paid (the Q view is left empty with a note, never filled from annual numbers) | Terms page not read here |

- **Where they rank and why** is in `providers/hierarchy.py` (each `Rank` carries covers, depth, freshness, limits and the reason). None sits above Yahoo
  because quotas of 25 a day to 800 a day cannot feed a chart or a 50-row grid and Yahoo needs no key; among themselves, depth first, then limits, then
  freshness. For `quotes`: Twelve Data, FMP, Polygon, Alpha Vantage. For `history`: Twelve Data, Polygon, FMP, Alpha Vantage. `fundamentals`: SEC, FMP, Alpha Vantage.
- **No key, no change.** The adapters are skipped (`supports()` is false), so the chains, SOURCES order and answers are exactly what they were; a test
  (`tests/test_keyed_market.py`) compares the order with the old one.
- **Not live data.** Polygon's quote is the previous session (its `market_time` is that session); Alpha Vantage sends only a date, so its quote time is that day
  at 00:00 UTC and its age is never understated. Every answer carries its source, fetch time and age, and a cached one past its time to live is `STALE`.
- **Fixtures.** Real recordings exist only where a public demo key allows one: `twelvedata_real_*` (demo key) and `alphavantage_real_*` (demo key, plus two
  real limit texts), and the real 401 answers `keytest_{twelvedata,polygon,fmp}_401`. Everything else for Polygon, FMP and Alpha Vantage's daily and premium
  answers is `*_docshape_*`, marked NOT A RECORDING inside the file; field names there are not checked against a live key.
  `scripts/record_providers.py` re-records them (never run in CI) and refuses to write a file that contains the key.
- **Attribution.** No code from these providers or their SDKs is used, so `THIRD_PARTY.md` has no row. Whether a provider's terms ask for an attribution or
  forbid redistribution on screen was not checked here; read each provider's terms before shipping data from them anywhere beyond your own screen.

### Already in OpenTerm (no action)

Yahoo, Nasdaq, SEC EDGAR, FRED, ECB, BoE, BoC, Japan MoF, US Treasury and TreasuryDirect, CFTC, FINRA, Deribit, OKX, Binance, CoinGecko, DefiLlama,
Polymarket, Kalshi, World Bank, DBnomics, Open-Meteo, NWS, NSE archive, AMFI, GDELT, RSS, Ken French, OpenFIGI, EIA, Finnhub, Alpaca, Tradier, FMP
(quotes, daily candles, search and annual statements as a keyed fallback; quarterly statements, intraday and most non-US data are paid), Twelve Data, Alpha Vantage, Polygon, Kite.

### What Bloomberg has that has no free equivalent

Sell-side research and price targets (Finnhub gives the recommendation trend only), consensus estimates with revisions, real-time global exchange
data (the free tiers are delayed or US-IEX only), bond and loan pricing (FINRA TRACE is paid; FRED has option-adjusted spreads, which OpenTerm uses),
earnings-call transcripts, supply-chain and ownership graphs, CDS and swap quotes, carrier sailing schedules (Searoutes, project44 and Portcast are paid;
AISstream's destination and ETA fields are the free partial substitute), and the Baltic Dry Index (licensed; I found no free feed).

## Built and what is left (updated 2026-11-05)

Built in this branch (none committed yet):
1. **IMF PortWatch** (keyless) as `SHIP`: daily ship counts at 28 chokepoints. Real recording; the ArcGIS service randomly answers a valid
   request with `Invalid URL` (about 2 calls in 3), so the adapter retries up to 6 times and only for that known glitch.
2. **UN Comtrade, BLS, BEA, Census** (free keys) as `TRADE` and `USMAC`. Doc-shaped fixtures, never run with a key.
3. **Frankfurter** (FX history and quotes behind Yahoo), **Companies House** (`UKCO`), **Marketaux** (news sentiment), **Etherscan** (`ADDR`).
4. **AISstream** (free key `AISSTREAM_API_KEY`, beta WebSocket) as `AIS`: `providers/aisstream.py` (socket, one listen at a time, hard caps of 15 s / 5,000 messages), `aisstream_parse.py` (pure),
   `world/ais.py` (presets SUEZ PANAMA HORMUZ MALACCA BABEL BOSPHORUS GIBRALTAR DOVER, `BOX S W N E`). **Run against the real service on 2026-11-05** (`ais_stream_recording.json` is a real 46-message recording; the free feed is sparse). Not a streaming
   feature: the server opens the socket for one short listen per request (cached 20 s), so nothing is subscribed at startup. The key goes in the first message, never in a URL. Details and
   the list of untested guesses: HANDOFF.md "AISstream".

### Kraken and Coinbase (keyless second crypto exchanges, verified live 2026-11-05)

`providers/kraken.py`, `providers/coinbase.py`, pure parsers in `providers/cryptoex_parse.py` and `world/cryptodepth.py` (`parse_kraken_book`, `parse_coinbase_book`). Polling only: no WebSocket
stream was built for either (Binance and Yahoo streams are untouched). A USD pair is not a USDT pair: `Bars.currency`, `Coin.quote` and the depth ladder carry the real quote; a pair is never swapped.
Symbols are the app's `BTC-USD` / `BTC-USDT` / `ETH-EUR` (dash required, so a share ticker can never reach an exchange); Kraken's `XBT` / `XDG` names and `XXBTZUSD` result keys are mapped inside the parser.

| | Kraken | Coinbase Exchange |
|---|---|---|
| Board (`CRYP`) | `Ticker` takes all 22 pairs in one call: USD and EUR, 280-435 ms. **No 24h change** (Kraken only has today's open since 00:00 UTC, a different window), so that column is empty. Volume = 24h coins x 24h VWAP | one `/products/<id>/stats` call per coin, 21 coins in USD only (TRX has no product), about 2 s in all. Exact rolling 24h change. **No volume value** (volume is in coins) |
| Candles | `OHLC`: **only the last 720 candles** of any length; `since=` cannot page back. 1m = 12 hours, 5m = 2.5 d, 15m = 7.5 d, 30m = 15 d, 60m = 30 d, 1d = 720 d; weekly goes back to 2013 (684 rows). No 2m / 90m / monthly. 205-240 ms | `candles`: 300 per call and a request for more is refused, so a range is fetched as windows of 299 candles in parallel (up to 14 calls = 4,000 candles; 0.85-0.95 s). API depth is much more (daily to 2015-07, 1 minute verified 1,000 days back); our cap is the paging budget. Only 1m / 5m / 15m / 1h / 1d: no 2m, 30m, weekly, monthly. Row order is `[time, low, high, open, close, volume]` |
| Too deep | `ProviderError("depth")`, e.g. `INTERVAL 60m ONLY AVAILABLE FOR THE LAST 30 DAYS`; weekly never | intraday over 4,000 candles = `depth` (`1m` 2 days, `5m` 13, `15m` 41, `60m` 166); daily over 4,000 returns the newest 4,000 days |
| Order book (`CDEP`) | `Depth?count=100`, 100 levels a side, ~200 ms real latency | `/book?level=2` is the **whole** book (~20,000 levels, ~1 MB); only the best 100 a side are kept, 280-400 ms |
| Limits | public REST about 1 call/s (bucket 1/s, burst 5) | about 10 calls/s per IP (bucket 8/s, burst 12); a `User-Agent` header is required |
| Declared `intraday_days` | 5m 2, 15m 7, 30m 15, 60m 30 (1m is 12 hours: not expressible in whole days, not declared) | 1m 2, 5m 13, 15m 41, 60m 166 |

Errors: Kraken answers every error as HTTP 200 with an `error` list (`EQuery:Unknown asset pair` = not found, `EAPI:Rate limit` = rate limited); Coinbase answers 404 `{"message":"NotFound"}` for an unknown product.
Fixtures (`backend/tests/fixtures/kraken_*.json`, `coinbase_*.json`) are real answers, long ones trimmed to their newest rows; `coinbase_stats_usd.json` joins the 21 per-product answers into one file.
Order: `history` `... binance_klines, yahoo, coinbase, kraken ...` (Coinbase above Kraken because it can be paged; both below Yahoo because Yahoo's BTC-USD goes back 20 years, and Yahoo does not carry USDT pairs so those fall through to them);
`crypto` board and `crypto_depth` are plain lists in `DEFAULT_ORDER` (`providers/hierarchy.py`), not ranked `HIERARCHY` entries, which exist only for `quotes` and `history`.

Built after that (branch `claude/ports-and-official-stats`): `PORTS` (PortWatch ports) and `DBSRCH` (DBnomics series search). OECD, Eurostat, BIS and IMF series are
reached through DBnomics (`DBSRCH`, then `ECST DBN:...`), so no separate adapters were written.

Built for `MAP` (2026-11-05, branch `claude/map-function-5ea8a7`): `USGS` (`providers/geo.py`, the `4.5_week.geojson` summary feed, refreshes every minute) and `NASA EONET`
(`providers/geo.py`, `api/v3/events?status=open&category=<all but wildfires>`; 69 events in 175 KB in 0.9 s, whereas the unfiltered open list is 7,235 events / 5 MB / 7.5 s, 99% of them wildfires, so wildfires
are left out and the panel says so). Both measured live on 2026-11-05 and recorded (`usgs_quakes_4_5_week`, `eonet_open_no_wildfires`). `PortWatchProvider.ports_geo` adds the busiest 100 ports with coordinates
(3 small calls: newest date, server-side sum of calls, port-list rows by id; recorded: `portwatch_ports_db_top25`). **OpenSky** (aircraft) was tried: `opensky-network.org` refused the connection from this machine
(`ECONNREFUSED`), so no layer was built; try again from another network before writing one. Recorder: `node scripts/record_map_fixtures.mjs`.

Left, in order:
1. **EDINET** (Japan filings), **Angel One / Fyers** (Indian backups to Kite), **Tiingo, MFapi**, CoinMarketCap, USDA NASS, FEC. (OpenSky is built as FLT but still needs a live check from a network that can reach it.)
2. Live-test every keyed source that has only doc-shaped fixtures (AISstream included).

None of the global free tiers beats Yahoo for charts, so none should be ranked above it.

## News feeds (2026-11-05)

`NEWS` pools 45 keyless RSS / Atom feeds listed in one table, `backend/openterm/providers/news_feeds.py` (name, url, sections, region, sectors, fast). Each was checked once on 2026-11-05 with a polite request (a user-agent naming the app, no personal address) and kept only if it answered 200 with items. Tech, crypto and a few breaking-news feeds are marked fast (30 s cache); the rest cache 60 s. Feed addresses change: a feed that starts showing under NOT ANSWERING needs its URL re-checked.

Dropped, with the reason:

| Feed | Reason |
|---|---|
| Reuters (business) | `feeds.reuters.com` no longer resolves; Reuters has no open RSS now |
| VentureBeat | HTTP 429 on the first request |
| Yahoo Finance `news/rssindex` | 404 (per-symbol Yahoo headlines still work through `yahoo_rss`) |
| Mining.com | 403 (blocks non-browser clients) |
| Kitco | 404 on the feed address tried |
| IMF news | 403 (the older `external/rss` address returns an HTML page) |
| World Bank | feed addresses tried return HTML or 404 |
| US Treasury press releases | both addresses tried 404 |
| Moneycontrol | answers, but the newest item is from April 2024 (stale) |
| MarketWatch real-time and market pulse | answer, but the newest items are from mid 2025 (stale); the top-stories feed is kept |
| hnrss.org front page | duplicate of the Hacker News feed that is kept |

Details that matter: RBI sends dates without a zone (local time), so a date later than now is capped to now; SEBI dates have no weekday and need a second date format. The Fed press feed is slow-moving (days between items) by nature. Only titles, teasers and links are used; articles open on the publisher's site.

## Honest limits of what is built

Upstox was built and then removed (2026-11-05): the owner could not get a token and will use paid Kite instead. Kite is the Indian source.

**Kite measured live (2026-11-05, RELIANCE.NS, logged in as the paying user):**
- Depth: 5, 15, 30 and 60 minute bars start on 2015-02-02; 1 minute was verified back 10 years (2016-11-04). Per call Kite caps the window (1 minute 60 days, 3/5/10 minute 100, 15/30 minute 200, 60 minute 400, daily 2000); `kite/client.py` chunks longer asks.
- Speed (server side, median of 10 different large caps, same symbols; Kite includes ~15 ms loopback because it was timed over HTTP, Yahoo was called in-process): quote Kite 52 ms vs Yahoo 341 ms; 5 min x 1 month history Kite 125 ms vs Yahoo 216 ms. Long asks are slower because they are many calls at 3 requests/s: 5 min x 1 year about 1.5 s, 1 min x 5 years 18 s.
- Prices: Kite last 1310.1 vs Yahoo 1308.5 (Yahoo is delayed). 1,581 common 5 min bars over a month: mean close difference 0.005%, max 0.1%, 328 identical.
- Rate limits used: 3 requests/s historical, 10 requests/s everything else, `/quote` up to 500 instruments per call (`kite/client.py`).
- Login expired: Kite is still tried, fails without a network call, Yahoo answers, and the response carries `fallback_from: ["kite"]` plus `fallback_notes: {"kite": "KITE LOGIN EXPIRED: run KITE LOGIN"}`; GP, Q, DES and HIST show that text (`functions/fallbackText.ts`). A missing key or no login at all stays silent (zero keys still works).
- Fixtures: real recordings (`scripts/record_kite_live.py`, 2026-11-05, no token or user id inside): `kite_quote_reliance_nifty_sensex_real`, `kite_historical_reliance_5m_real`, `kite_quote_derivs_real` (NFO / BFO / MCX / CDS futures, an option, BSE equity), `kite_historical_{reliance,nifty_fut,gold_fut,usdinr_fut}_day_real` (daily bars with open interest), `kite_instruments_real_subset`, `kite_error_token_real` (the TokenException answer; used by fixture mode), `kite_ws_packets_real` (binary WebSocket frames, hex). Still doc-shaped, labelled so: the full instruments dump (the option-chain tests depend on its invented NIFTY 25000 layout), the session answer and the 25000 NIFTY quote.

**Kite follow-ups, measured live 2026-11-05 (market open, logged in):**
- REST, every segment answers: `.NS`, `.BO` (`RELIANCE.BO`), indices (`^NSEI`, `^BSESN`), NFO futures and weekly options (`NIFTY26NOVFUT.NFO`, `NIFTY26N0924400CE.NFO`), BFO (`SENSEX26NOVFUT.BFO`), MCX (`GOLD26DECFUT.MCX`, `CRUDEOIL26NOVFUT.MCX`), CDS (`USDINR26NOVFUT.CDS`). Daily bars `20Y` of RELIANCE.NS and ^NSEI: 4,956 bars from 2006-11-06, 0.1-1.4 s (the first call chunks into Kite's 2000-day windows, repeats are cached). 5 min and 15 min bars for futures, options, MCX and CDS: 60-250 ms. Futures and options carry open interest; cash symbols do not.
- A derivative is typed as its exact Kite trading symbol plus the suffix (`NIFTY26NOVFUT.NFO`). A bare `NIFTY.NFO` or an expired contract is `not_found` and the message now lists the live contracts (`NIFTY CONTRACTS: NIFTY26NOVFUT, ...`; Kite's dump has no expired contracts).
- Found and fixed live: (1) Yahoo-style BSE scrip codes (`500325.BO`) were `not_found`; Kite's trading symbol is the name and the code is `exchange_token`, now looked up in the dump (quotes, bars and ticks). (2) Bars of shares and indices came back with `oi` = a list of zeros; it is now empty unless the instrument is a FUT / CE / PE. (3) An untraded contract (a weekly USDINR future) has `last_trade_time` `1970-01-01 05:30:00` and open/high/low of 0: the time now falls back to the quote's own `timestamp`, and zero prices become empty cells, not a 0.00 low.
- Ticker, live: one WebSocket (`wss://ws.kite.trade`) carried RELIANCE.NS, RELIANCE.BO / 500325.BO, ^NSEI, a NIFTY future and option, a GOLD future, a USDINR future through the existing hub; 6 symbols gave 6-46 ticks in 12 s. Packet lengths seen: 8 (not used), 28 / 32 (index), 44 (quote), 184 (full: OI and 5-level depth); the decoder matched the REST prices on all segments and the CDS /1e7 divisor gave sane rupee prices. Two fixes: the frontend had no label for source `k` (the SRC column showed a bare `k`; now `RT KITE`), and `KiteTicker.covers` dropped Yahoo's delayed ticks only for 8 s after the last Kite tick, so a quiet option would flip back to a 15-minute-old Yahoo price: it now owns a symbol while the socket is up and the symbol is subscribed, and hands it to Yahoo (label STREAM) or the poller (label POLL) the moment the socket drops or the login ends.
- Since fixed (wrap-up, 2026-11-05): OMON / CT work for `.NFO`, `.BFO`, `.MCX` and `.CDS` (`CHAIN_EXCHANGES` in `kite/symbols.py`; live: NIFTY 245 strikes, GOLD 6 futures, CRUDEOIL 198 strikes), and a `1D` range on Kite is the newest IST session (7-day lookback, then trimmed), like Yahoo's `1d`.
