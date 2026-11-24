# Phase 27: scanners, indicator columns, smart alerts (spec, 2026-11-24)

Built under the minimal test bar (owner decision 2026-11-24). Script alerts are out (Phase 25 is deferred).

## Items

1. **One rule engine:** SCAN and indicator alerts use the backtester's rule grammar and maths (`bt/rules.py`), widened with
   `ATR<n>` (Wilder average true range; the Pine and MQL5 exports map it too). Evaluated in job workers, never in the server.
2. **SCAN:** `SCAN <UNIVERSE> <RULE>`, e.g. `SCAN SPX RSI14<30 AND CLOSE>SMA200`. Universes: `SPX NDX DJI RUT MID` (index
   members from the proxy ETF's SEC N-PORT, the MEMB function), `MEMB:<ETF>`, `WL:<NAME>`, `LIST:A,B,C`, `NIFTY50` /
   `NIFTY500` (NSE Indices' constituent CSV, downloaded on this computer, never shipped; doc-shaped fixture). The server
   downloads daily bars (paced for Yahoo, progress shown), a `scan.run` job evaluates the rule on each symbol's newest bar.
   Matches first, with every term's value; `PARTIAL` when some symbols had no data. Enter opens GP with the rule's averages,
   RSI or ATR drawn.
3. **Scheduled scans:** `SCAN SAVE <NAME> <UNIVERSE> <RULE> [DAILY=HH:MM]` (weekdays, this computer's time) sends the matches
   through DELIVERY; `SCAN SAVED`, `SCAN RUN <NAME>` (run and send now), `SCAN DEL <NAME>`.
4. **Indicator columns** in WL and Q: `Q AAPL MSFT COLS=RSI14,ATR14,PCT_SMA200,REL_VOL`, `WL TECH COLS=RSI14<30`. Up to 6
   columns: any rule term, `PCT_SMA<n>` / `PCT_EMA<n>` (close vs the average, %), `REL_VOL[<n>]` (newest volume over the
   average of the n bars before it, default 20). A comparison colours the cell when it holds. The newest DAILY bar (today's
   is still forming); a `scan.cols` job computes them (`scanner/cols.py` parses, `bt/rules.py` keeps the maths); a formula row
   gets a note instead of values.
5. **Indicator alerts:** `ALRT AAPL RSI14<30`, `ALRT AAPL SMA50 CROSS> SMA200`: the rule on COMPLETED daily bars (today's
   bar counts after 16:30 in the exchange's zone, a 24-hour market's after midnight), checked by the server every 15 minutes
   and right after creation, with the browser closed. Fires once through DELIVERY; never in fixture mode (the reason is
   shown). Listed in ALRT as S<id>; `ALRT DEL S<id>`.
6. **Drawing alerts:** `ALRT AAPL LINE [N]`: the price crosses a GP TREND / RAY / XLINE / HLINE (extended to the right), or
   leaves a PCHAN channel. N = its place among the symbol's alertable drawings (none = the newest). Checked on every live
   tick by the alerts engine; refused on synthetic, stale or fixture ticks with the reason kept.
7. **MRR:** `MRR <UNIVERSE> [1D|1W|1M|3M|YTD|1Y]`: members ranked by return and contribution (index weight x return, in
   percentage points); NIFTY lists have no weights, so returns only (said on screen).
8. **Heat maps** `IMAP CRYPTO [N=50]` (CoinGecko board) and `IMAP ETF [N=150] [FSRC filter]` (the FSRC data; size = total
   assets); `IMAP NIFTY` NOT BUILT YET.
9. **ETF screener `FSRC`:** the US ETF list from Nasdaq Trader's symbol file plus expense ratio, total assets and category
   from Yahoo's fund profile, loaded in a paced background task, cached a day, `PARTIAL` until complete.

## Tests (minimal bar)

Unit: universe words, NSE CSV and MEMB payload parsing, mover returns and contributions, the forming-bar rule, drawing
geometry (line, ray extension, channel), ATR, SCAN / MRR / ALRT argument parsing. API: a LIST scan and an indicator alert
that matches but does not fire in fixture mode. Smoke: `SCAN`, `MRR`.
