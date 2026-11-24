# Phase 24: replay and practice (spec, 2026-11-24)

Built under the minimal test bar (owner decision 2026-11-24). Practice only: nothing here sends an order anywhere
(NO LIVE ORDERS).

## Items

1. **Bar replay on GP:** `GP AAPL 1Y REPLAY 2024-03-01` (no date: the last 100 bars are hidden). The chart, every indicator,
   study and profile receive ONLY the revealed bars (`chart/replay.ts` `revealed`), so none can see a hidden bar; a unit
   test changes the hidden bars and checks every built-in indicator gives the same values. Keys: `.` next bar, `,` back,
   Space play / pause, `s` speed 1 / 2 / 5 / 10 bars per second. No live ticks while replaying.
2. **Practice trading inside replay:** Shift+B buy, Shift+S sell, Shift+F flatten (100 units per press); every order fills at
   the NEXT revealed bar's open, so a price already seen can never be traded. Position, average price and P&L on the panel
   line. Shift+J saves the session's fills to the journal (JRNL) as `REPLAY <SYMBOL> <date>` through the generic CSV
   import. Deviation from the plan, on purpose: the practice book lives in the replaying panel, not as an ORD paper account,
   and has no stop / target orders (the intrabar fill rule arrives with Phase 26).
3. **Recorder (crypto, OFF by default):** `REC BTCUSDT ON|OFF` records exchange trades and order-book snapshots to files on this
   computer (`<data dir>/recordings/`), with a disk cap and retention in SETTINGS. `FOOT|TAS|DOM BTCUSDT REC=<id>` show a
   recorded session labelled `RECORDED BY OPENTERM <date>`. Kite tick recording is not built (needs the paid daily login).
4. **Multi-panel replay:** GP panels in the same link group that are also replaying follow the replay clock.

## Tests (minimal bar)

Unit: no-look-ahead for every indicator, reveal start, practice fills and P&L (long, short, reversal, flatten), recorder
start / stop / dedupe / cap / retention, REC= argument parsing. Smoke: `AAPL GP 1Y REPLAY`, `REC`.

## Bench (proposed, not yet gated)

A replay step re-renders a chart with 5 studies <= 16 ms; play at 10 bars/s holds 60 fps.
