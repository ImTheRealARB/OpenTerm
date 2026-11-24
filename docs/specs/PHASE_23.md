# Phase 23: volume and order flow (spec, 2026-11-24)

Built under the minimal test bar (owner decision 2026-11-24): unit tests for pure maths and parsers, smoke cases for each new
code, one full gate and one bench after the phase. Owner decision pending (default used): the trade / depth / tick
RECORDER stays off; panels keep what they saw while open, in memory only.

## Items

1. **Volume profile on GP** (`VP` study): visible range, session (one profile per day), week, month, anchored (from a bar).
   Point of control, value area (70%, `VA=` configurable), high and low volume nodes. Built from the finest bars the source
   allows inside the range (1m, else 5m, 15m, 60m, then the chart's own bars), each bar's volume spread evenly over its
   high-low range, labelled `ESTIMATED FROM <interval> BARS`. Exact for crypto when built from trades (item 4).
2. **Anchored VWAP and bands** (`AVWAP` study): session, week, month, or from an anchor bar; 1, 2 and 3 standard deviation
   bands (volume-weighted variance).
3. **TPO / market profile** panel `TPO SYM [DAYS] [BRACKET=30]`: letters per bracket (default 30 minutes), POC, value
   area, initial balance (first two brackets), single prints, poor high / low. From bar high-low per bracket (the standard
   construction, so exact for the bars used; the bars' interval is shown).
4. **Crypto order flow (exact):** Binance spot aggregated trades (public REST, buyer-maker flag = aggressor side).
   `TAS SYM` time and sales, `BIGT SYM [MIN=<coins>|USD=<amount>]` big trades, `FOOT SYM [INTERVAL]` footprint (bid x ask
   volume per price level per bar, imbalance highlight >= 3:1, delta per bar, cumulative delta). Crypto only; any other
   symbol says `ORDER FLOW: CRYPTO ONLY (BINANCE SPOT PAIRS)`.
5. **Depth ladder `DOM SYM` (read-only)** from the existing crypto depth sources, refreshed while open; `LIQH SYM` liquidity
   heatmap from the depth snapshots taken while the panel is open (memory only).
6. **India tick-rule estimate:** for a Kite-streamed symbol, `TAS` classes each tick buy if the price rose, sell if it fell
   (unchanged = previous side), labelled `ESTIMATED (TICK RULE)`. US: no free tick feed, not built.

## Tests (minimal bar)

Unit tests: volume profile (POC, value area), VWAP bands, TPO letters / POC / initial balance, aggTrades parser, footprint
binning and delta, tick rule. Smoke cases: `AAPL GP 1Y VP`, `AAPL GP 1Y AVWAP`, `TPO`, `TAS`, `BIGT`, `FOOT`, `DOM`, `LIQH`.

## Bench (proposed)

Volume profile of ~95k bars <= 40 ms; footprint render of 300 bars x 40 levels <= 16 ms per frame.
