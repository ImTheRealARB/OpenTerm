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
| **BLS API v2** | US CPI, jobs, wages, productivity | registered: 500 queries/day, 50 series per query; renew yearly | Checked |
| **BEA API** | US GDP, trade, income, industry accounts | UserID by sign-up; limits not confirmed | Checked (key only) |
| **Census API** | US trade, retail sales, housing, demographics | key now required for all queries (2026 Census video) | Checked |
| **UN Comtrade** | Trade flows between every pair of countries, by product | free key: 500 calls/day, 100,000 records per call | Checked |
| **UK Companies House** | UK company profiles, officers, filings, charges | free key, 600 requests per 5 minutes (HTTP 429 after) | Built: `UKCO` (profile, officers, filings, search; charges not read). Doc-shaped, unrun |
| **EDINET (Japan FSA)** | Japanese company filings | free `Subscription-Key`; the key page was reported blank on 2026-09-16 | Checked (blogs) |
| **Marketaux** | Financial news with sentiment scores | about 100 requests/day (unverified); the adapter stops at 90 a day and keeps answers 15 minutes | Built: merged into `N` headlines, sentiment shown on the detail line. Doc-shaped, unrun |
| **Etherscan** | Ethereum and some other chains: balances, transactions, gas | 3 calls/s, 100,000/day, selected chains | Built: `ADDR` (balance, last 20 transactions, gas). Doc-shaped, unrun |
| **CoinMarketCap Basic** | Crypto ranks and prices beyond the top 50 | 15,000 credits/month, 50 requests/minute | Checked (CMC's own article) |
| **AISstream** | Live ship positions, destinations, ETAs, ship details (WebSocket) | free, **beta, no uptime promise**; 3 connections per account and per IP (docs) | Built: `AIS` (ship positions in a chokepoint or box, listen 8 s). Doc-shaped, unrun: no key yet |
| **Twelve Data, Tiingo, Alpha Vantage** | Fallback prices, daily history | see above | Checked |
| **Angel One SmartAPI, Fyers** | Indian broker data, backup to Kite | free with account; TOTP login | Checked (forums) |
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
4. **AISstream** (free key `AISSTREAM_API_KEY`, beta WebSocket) as `AIS`: `providers/aisstream.py` (socket, one listen at a time, hard caps of 15 s / 5,000 messages), `aisstream_parse.py` (pure),
   `world/ais.py` (presets SUEZ PANAMA HORMUZ MALACCA BABEL BOSPHORUS GIBRALTAR DOVER, `BOX S W N E`). **Built from the documentation only; never run against the real service.** Not a streaming
   feature: the server opens the socket for one short listen per request (cached 20 s), so nothing is subscribed at startup. The key goes in the first message, never in a URL. Details and
   the list of untested guesses: HANDOFF.md "AISstream".

Built after that (branch `claude/ports-and-official-stats`): `PORTS` (PortWatch ports) and `DBSRCH` (DBnomics series search). OECD, Eurostat, BIS and IMF series are
reached through DBnomics (`DBSRCH`, then `ECST DBN:...`), so no separate adapters were written.

Left, in order:
1. **EDINET** (Japan filings), **Angel One / Fyers** (Indian backups to Kite), **Tiingo, Twelve Data, Kraken, Coinbase, MFapi**, CoinMarketCap, USDA NASS, FEC, OpenSky.
2. Live-test every keyed source that has only doc-shaped fixtures (AISstream included).

None of the global free tiers beats Yahoo for charts, so none should be ranked above it.

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
- Not done: OMON / CT work for `.NFO` and `.MCX` (live: NIFTY 245 strikes, GOLD 6 futures, CRUDEOIL 198 strikes) but not for `.BFO` (SENSEX options) or `.CDS` (`CT USDINR.CDS` says UNKNOWN ROOT); `derivative_root` in `kite/symbols.py` knows only NFO and MCX. A `1D` range on Kite is the last 48 hours, not one session (Yahoo's `1d` is one session); left as is.
