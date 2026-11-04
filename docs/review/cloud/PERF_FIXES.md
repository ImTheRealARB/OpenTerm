# Perf fixes: SEAS and BT open (cloud box, 2026-11-04)

## 1. SEAS MONTH+WOY+DOM 10,000 daily bars (budget 15 ms, was 15.5-22 ms, baseline 12.2 ms)
Cause: every bar allocated a `Date` (and `isoWeek` made three more) and, with an exchange zone, formatted a string through Intl plus a Map cache.
Fix (`seasMath.ts`, new `dayMath.ts`):
- Each call computes ONE `Float64Array` of day numbers (days since 1970) and all three kinds reuse it. Year, month, day, weekday and ISO week come from integer civil-from-days math. [rule: data-oriented, typed arrays; no per-bar allocation]
- Exchange-local day: `localDayNumbers` builds a small offset-transition table once per call (Intl probed monthly, bisected where the UTC offset changes) and the sorted bar times walk it with one moving index. No Date, string or Map per bar. [rule: a table is data, not a cache]
- `corrMath.ts` `dayKey` lost its Map caches (formatter and string); `alignCloses` now uses day-number columns and a merge intersection instead of `Map<string,number>` per series. [rules: remove CPU memo caches, integer indices instead of hash lookups]
- Tests: `seasMath.test.ts` (integer math equals Date over 5,000 random timestamps 1900-2100, leap days, year ends, ISO week 53), `dayMath.test.ts` (equals Intl for 5 zones over 12 years, DST included). Existing SEAS/CORR tests unchanged and green.

## 2. BT result open to first paint (budget 100 ms, was 121-175 ms)
Cause (CDP profile, not a guess): the cached POST answers in about 20 ms and already carries the run, so there is no second GET (`bt.getMs` is NaN on that path by design). The other 60-100 ms was the chart: lightweight-charts creating two canvas panes plus a compare series and painting them in the same frame as the labels. JS self time was small; the cost is canvas setup and paint.
Fix (`BT.tsx`): the labels, headline and view line paint first; the chart mounts one frame later (`chartFor` state set in the `afterPaint` callback; a `DRAWING CHART…` line shows meanwhile). Numbers and labels (HISTORICAL SIMULATION..., source, fees, slippage) are untouched and exact. Also `chartData` fills the benchmark typed arrays in a plain loop (no callback/temp array per point). [rule: no per-point allocation; defer secondary work past first paint]
Local measurement (own harness, same fixture setup as bench): btOpen p95 175 ms -> 36 ms.

## Not changed
Backend data/job/SWR caches stay. `bt.getMs` stays NaN on the cached path.
