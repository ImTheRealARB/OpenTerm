# Data sources: the hierarchy and a free-source shortlist

## How OpenTerm picks a source

For each kind of data (quotes, history ...) the sources are ranked in one table,
[`backend/openterm/providers/hierarchy.py`](../backend/openterm/providers/hierarchy.py). The router walks it top-down and takes the first
source that is **switched on for that symbol** and **healthy**:

- no key set, or the symbol is not one the source covers (Upstox never sees AAPL): skipped, costs nothing;
- rate limited, down, or too shallow for the request: the next source answers, and the chart says `<name> DOWN, VIA FALLBACK`;
- a key added in `APIKEYS` takes effect at once (the history cache key changes with the set of keyed sources that are on).

Ranking weighs **depth** (how far back, which instruments), then **freshness** (real time or delayed), then **rate limits** (a source with a few
calls a day must not sit above one that can feed a 50-row grid). **Speed** is measured live on `SOURCES`; the circuit breaker demotes a slow or
failing source by itself, so the table does not guess it. Every entry records its reasons, and `SOURCES` shows where each provider sits.

How far back minute candles reach is a property of the source that answers, not a global rule: every provider can declare `intraday_days`, and
`GET /api/history/limits?symbol=X` reports the deepest source switched on for `X` (Yahoo 60 days; Upstox about 4.8 years for Indian shares once
a token is set). The chart's candle-length dropdown reads it.

`config.yaml` `providers:` can still pin a capability's order by hand. It wins over the table and the log says so; remove the line to get the
hierarchy back.

To add a source: write the adapter ([ADDING_A_PROVIDER.md](ADDING_A_PROVIDER.md)), register it, add one `Rank` at the position it earns, and
`backend/tests/test_hierarchy.py` checks the entry is complete.

## In the app today

| Source | Key | Kind | Position |
|---|---|---|---|
| **Upstox** (new) | free read-only Analytics Token | NSE/BSE shares + Nifty 50, Bank Nifty, Sensex: real-time quotes, minute candles from 2022, daily from 2000 | `quotes` #1, `history` #2 |
| Kite Connect | paid app, daily login | NSE, BSE, NFO, MCX with open interest | `history` #1 |
| **Frankfurter** (new) | none | ECB reference rates: one fix per business day for FX pairs (EURUSD=X, USDINR=X, crosses), back to 1999; no high/low | `history` below Yahoo, `quotes` below Yahoo (Yahoo-down fallback for FX) |
| **Companies House, Marketaux, Etherscan** (new) | free keys | `UKCO` UK register; `N` headlines with sentiment; `ADDR` EVM address and gas | specialists (Marketaux joins the news order) |
| Yahoo, Nasdaq, SEC EDGAR, FRED (keyless CSV), ECB, BoE, BoC, MoF, Treasury, CFTC, Deribit, OKX, Binance, CoinGecko, DefiLlama, Polymarket, Kalshi, World Bank, DBnomics, Open-Meteo, NWS, NSE archive, AMFI, GDELT, RSS | none | global shares, rates, futures, crypto, macro, weather, prediction markets, funds, news | fallbacks and specialists |
| Finnhub, Alpaca (IEX), FMP, EIA, OpenFIGI, Tradier, FRED API | free keys | news, ratings, real-time US trades, energy, identifiers, options | specialists |

## Free sources worth adding (catalog, researched 2026-11-05)

Legend. **Checked** = confirmed by a search result or the provider's own page during this work. **Memory** = my recollection, not verified: confirm
on the provider's page before building. Most search hits were comparison blogs, so even "checked" limits can drift; free tiers change often.
"In app" = already in OpenTerm, so nothing to add.

### Needs a free key

| Source | Adds | Free limits | Status |
|---|---|---|---|
| **Upstox Analytics Token** | Real-time NSE/BSE, minute candles from 2022 | 500 requests/minute | Built (unrun live) |
| **BLS API v2** | US CPI, jobs, wages, productivity | registered: 500 queries/day, 50 series per query; renew yearly | Checked |
| **BEA API** | US GDP, trade, income, industry accounts | UserID by sign-up; limits not confirmed | Checked (key only) |
| **Census API** | US trade, retail sales, housing, demographics | key now required for all queries (2026 Census video) | Checked |
| **UN Comtrade** | Trade flows between every pair of countries, by product | free key: 500 calls/day, 100,000 records per call | Checked |
| **UK Companies House** | UK company profiles, officers, filings, charges | free key, 600 requests per 5 minutes (HTTP 429 after) | Built: `UKCO` (profile, officers, filings, search; charges not read). Doc-shaped, unrun |
| **EDINET (Japan FSA)** | Japanese company filings | free `Subscription-Key`; the key page was reported blank on 2026-09-16 | Checked (blogs) |
| **Marketaux** | Financial news with sentiment scores | about 100 requests/day (unverified); the adapter stops at 90 a day and keeps answers 15 minutes | Built: merged into `N` headlines, sentiment shown on the detail line. Doc-shaped, unrun |
| **Etherscan** | Ethereum and some other chains: balances, transactions, gas | 3 calls/s, 100,000/day, selected chains | Built: `ADDR` (balance, last 20 transactions, gas). Doc-shaped, unrun |
| **CoinMarketCap Basic** | Crypto ranks and prices beyond the top 50 | 15,000 credits/month, 50 requests/minute | Checked (CMC's own article) |
| **AISstream** | Live ship positions, destinations, ETAs, ship details (WebSocket) | free, **beta, no uptime promise**; no published quotas found | Checked |
| **Twelve Data, Tiingo, Alpha Vantage** | Fallback prices, daily history | see above | Checked |
| **Angel One SmartAPI, Fyers** | Indian broker data, backup to Upstox | free with account; TOTP login | Checked (forums) |
| **USDA NASS QuickStats** | US crop, livestock and food statistics | free key | Memory |
| **FEC, USASpending, Federal Register, Congress.gov** | Political money, federal contracts, rules, bills | free keys, generous | Memory |
| **OpenSky Network** | Live and historical flights | free account, daily credit limits | Memory |
| **NewsAPI, NewsData.io** | News search | small free tiers; NewsData about 200/day | Memory |
| **OilPriceAPI** | WTI, Brent, gold, silver, gas; its freight endpoints are "being onboarded" | free key | Checked (vendor page); skip: EIA, FRED and Yahoo futures already cover it |

### Keyless (nothing to sign up for)

| Source | Adds | Status |
|---|---|---|
| **IMF PortWatch** | Daily ship transit counts through 28 chokepoints (Suez, Panama, Hormuz, Malacca ...) and activity at about 1,600 ports; ArcGIS REST, 1,000 records per call; satellite AIS, so data lags | Checked |
| **Frankfurter** | ECB FX rates for about 30 currencies back to 1999 | Built (real recording): `history` #5 and `quotes` #3, FX pairs only, daily fix |
| **OECD SDMX, Eurostat, BIS, IMF data API** | Official macro, banking, debt, property prices, trade statistics | Checked (third-party guides; confirm endpoints) |
| **Kraken, Coinbase public APIs** | Second crypto exchange when Binance is blocked | Memory |
| **MFapi.in** | Mutual fund NAV history for every AMFI scheme | Memory |
| **Drewry World Container Index** | Weekly container freight rates | Free on Drewry's site; API only "on request": not scrapable (bot rules) |
| **SCFI (Shanghai Shipping Exchange)** | Weekly container index | Published weekly; no API found |

### Already in OpenTerm (no action)

Yahoo, Nasdaq, SEC EDGAR, FRED, ECB, BoE, BoC, Japan MoF, US Treasury and TreasuryDirect, CFTC, FINRA, Deribit, OKX, Binance, CoinGecko, DefiLlama,
Polymarket, Kalshi, World Bank, DBnomics, Open-Meteo, NWS, NSE archive, AMFI, GDELT, RSS, Ken French, OpenFIGI, EIA, Finnhub, Alpaca, Tradier, FMP
(stored but not wired: its useful endpoints are paid), Kite.

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

Left, in order:
1. **AISstream** (free key, beta): live vessel positions and ETAs. A WebSocket, so it fits the streaming hub; the biggest piece, no uptime promise.
2. **PortWatch ports** (`Daily_Ports_Data` layer exists on the same service): port calls and trade by port.
3. **OECD, Eurostat, BIS, IMF** (keyless) behind MACRO and ECO. **EDINET** (Japan filings). **Angel One, Tiingo, Twelve Data, Kraken, MFapi** as extras.

None of the global free tiers beats Yahoo for charts, so none should be ranked above it.

## Honest limits of what is built

The Upstox adapter was written from the official docs. No Upstox token was available, so its fixtures and tests are **doc-shaped, not recordings**
(same status as Finnhub and Kite). Offline checks passed (unit tests, a fake server, the fallback path in a real running app). **The first live
call with your token is the real test**: a wrong shape shows as an `ERR` line and Yahoo answers, never as wrong prices. If it fails, `SOURCES` shows
the exact error. Things the docs did not state, and how the code handles them: the maximum number of instruments per quote call (batches of 100),
how quote answer keys relate to the requested instrument key (matched on `instrument_token`), and whether the instruments files need a token
(the code sends none).
