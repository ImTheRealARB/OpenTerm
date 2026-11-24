# Phase 21: chart depth I (spec, 2026-11-24)

GP draws and shows what traders expect from a modern charting tool. No new data source except Binance 1-second candles
(free, public). Built under the minimal test bar (owner decision 2026-11-24): unit tests for pure maths and parsers only, one
full gate after the phase, bench once after the phase.

## Items (all built)

1. **Drawing tools** (`frontend/src/chart/drawings.ts`, one `TOOLS` table; the backend mirror is `POINTS` in
   `backend/openterm/drawings.py`, kept equal by `test_phase21_drawings.py`):
   ray, extended line, vertical line, cross line; parallel channel, regression channel (least squares on closes, +-2
   standard deviations of the residuals), rectangle, ellipse, triangle, path (2 to 10 anchors); text, note pinned to a bar,
   arrow up / down; price range, date range, price and date range; fib extension, fib time zones, fib fan; pitchfork, Gann
   fan; long and short position planners (entry, stop, target, reward / risk, size from "ACCOUNT RISK%"; planning only,
   it places nothing); XABCD with its ratios; Elliott impulse (0-5) and correction (0, A-C) labels.
   Keyboard: `W` opens the tool picker (one key per tool), the crosshair picks each anchor, `P` cycles the anchor price
   (close / high / low / open), `Enter` places it, `Shift+Enter` places a path's last anchor, `Esc` cancels. Text and
   position tools then ask for their text in a box. `T` / `H` / `B` stay as quick keys. `[` / `]` select, `E` re-places the
   selected drawing's anchors, `D` removes it.
2. **Object tree** (`O`): drawings and studies in one list; `V` hides, `D` removes, `R` renames (a drawing's label, which is
   a TEXT / NOTE's words), `L` locks (a locked drawing cannot be removed or moved), `Enter` selects. Hidden studies stay in
   the panel's args (this panel only); drawing flags are stored.
3. **Stored format, schema 2:** `kv drawings:<SYMBOL>` now holds `{"v": 2, "drawings": [...]}`; each drawing may carry
   `label` (<= 200 characters), `hidden`, `locked`. Unknown fields are still refused. A document without `v` is schema 1 and
   reads unchanged.
4. **Chart types** (`chart/bricks.ts`, `chart/customSeries.ts`, `chart/chartTypes.ts`): RENKO, KAGI, PNF (X / O glyphs),
   LINEBREAK (3 lines), RANGE, COLUMNS, HIGHLOW (high-low-close bars), STEP, VOLCANDLE (body width by volume). Brick types
   take `BOX=<price>` (absent: ATR 14) and `REV=<n>` (P&F reversal, default 3) and say on screen
   `BUILT FROM <interval> BARS · NON-LINEAR TIME AXIS` with the box actually used. On a brick chart indicators, compare and
   drawings are off (their clock is the source bars') and the panel says so.
5. **More candle lengths** (`backend/openterm/resample.py`, wired in `DataService.history`): `2h 3h 4h 6h 8h 12h` from 60m
   (each local trading day's buckets start at that day's first bar: 09:30 US, 09:15 India, 00:00 UTC crypto), `2d 3d` from
   1d, `2wk` from 1wk, `3mo` (quarterly) and `12mo` (yearly) from 1mo on calendar boundaries. Cached under a key naming the
   target interval; the base call keeps its own cache, source order and errors. `/api/history/limits` reports the hour
   lengths with 60m's reach.
6. **Crypto 1-second candles:** Binance spot `1s` (12 pages of 1,000 = about 3.3 hours; the answer's range says what it
   holds). Other sources refuse `1s`; a non-crypto symbol gets `ONLY AVAILABLE FOR BINANCE SPOT USDT PAIRS`.
7. **PAT:GEO** (`chart/geoPatterns.ts`, in the indicator worker): double top / bottom, head and shoulders (and inverse),
   ascending / descending / symmetric triangles, rising / falling wedges, bull / bear flags, from zigzag swing pivots
   (2 x ATR14). Dashed outlines, a marker naming the rule, and the line `PATTERN RULE, NOT A SIGNAL`.

## Tests (minimal bar)

- vitest: `drawings21.test.ts` (position sizing, regression, fib extension, ray / extended line, parallel channel, every
  tool draws, schema 2 parsing), `bricks.test.ts` (each transform on hand-checked input, 50k-bar timing printed),
  `geoPatterns.test.ts` (zigzag, double top, head and shoulders, worker format).
- pytest: `test_phase21_drawings.py` (new tools and fields round-trip, bad input refused, TS / Python tool tables equal),
  `test_phase21_resample.py` (US and India hour anchoring, quarterly, 2d, Binance 1s fixture).

## Bench (proposed, measured once after the phase)

Renko / P&F / Kagi on 50k bars <= 15 ms (vitest timing: 8.6 ms for all three), 200 drawings pan p95 <= 16 ms, 4h resample
of 2 years of 60m bars <= 20 ms server-side.

## Known limits

- Brick charts built from bars are an approximation of tick-built ones (labelled).
- A live tick never starts a new resampled hour candle in a new session (it would land on the wrong grid): that candle
  arrives with the next history load. New 2d / 3d / weekly+ candles also wait for the next load, as daily ones always did.
- No mouse placement of drawings (keyboard first; a click still selects a drawing).
