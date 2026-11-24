# Phase 22: linked panels and symbol math (spec, 2026-11-24)

Built under the minimal test bar (owner decision 2026-11-24). No new data source.

## Items

1. **Link groups.** A panel joins a colour group A, B, C or D (`LINK A`, `LINK OFF`; GUI chip in the panel header; saved in
   layouts as the panel's `link`). Typing a new security into one panel of a group loads it in every other panel of that
   group that shows a security. Default: no group (no surprise behaviour).
2. **Chart sync inside a group:** crosshair time, visible date range and candle length, each switched on or off in SETTINGS
   (`SETTINGS LINK CROSSHAIR|RANGE|INTERVAL ON|OFF`, default on; they act only on linked charts).
3. **Symbol math:** `GP AAPL/MSFT`, `GP ES=F-NQ=F`, `GP 2*GLD-SLV`: + - * / and parentheses over symbols and numbers,
   computed on the server from each leg's bars aligned on timestamps (inner join; the number of dropped bars is shown), the
   result labelled with its formula and every source. Works wherever `/api/history` is used (GP, HIST, BT). A stored
   synthetic symbol: `IMPORT SYNTH NAME = AAPL/MSFT`.
4. **TRA:** total return over a period from adjusted closes (price + dividends), annualised, vs a benchmark, for one security
   or a list.
5. **BETA:** OLS of a security's returns on a benchmark's: beta, alpha, R², standard error, adjusted beta
   (0.67 x raw + 0.33), daily / weekly / monthly returns, a scatter plot and a rolling beta line.
6. **GRAB:** the focused panel as a PNG (canvas grids and charts included): `GRAB` copies it to the clipboard, `GRAB SAVE`
   downloads it, `GRAB VIA TG,EMAIL` sends it through the delivery channels (fixture mode never sends). Shortcut Alt+G.
7. **Watchlist flags and sections:** a colour flag per symbol (7 colours) with a filter, and section headers inside a list.
8. **IMPORT intraday:** CSV of intraday bars (timestamp with its zone), labelled `LOCAL DATA`.

## Tests (minimal bar)

Unit tests for the expression parser and aligner, TRA and BETA maths, the intraday CSV parser and the link-group
propagation rule; smoke cases for `GP AAPL/MSFT`, `TRA`, `BETA` and `LINK`.

## Bench (proposed)

Link-group symbol change re-renders 4 panels <= 100 ms to last paint; symbol-math alignment of 2 x 10Y daily <= 10 ms.
