# Perf hunt (cloud, 2026-11-04)

No bench was run (another session owns it); numbers below are build sizes and unit tests only.

## Changes
1. **Startup bundle: help drawer, welcome card and tour are separate chunks.**
   `frontend/src/gui/LazyGui.tsx` (new) loads them with a plain `import()` (no React.lazy/Suspense), preloads each when idle,
   and loads at once when its state opens. `gui/index.ts` and `gui/Overlays.tsx` use the wrappers.
   Entry chunk gzip 123.61 KB -> 121.02 KB (-2.6 KB); raw 374.86 -> 366.72 KB. Chunks: HelpDrawer 2.1, Tour 1.5, Welcome 0.8 KB gz.
   Initial JS+CSS total (what the bench counts) should drop by the same ~2.6 KB from 125.8 KB; still above main's 120.0 KB (+3.2 KB left).
2. **Idle preload staggered.** `main.tsx` used to start ~88 chunk downloads in one idle callback. `functions/idlePreload.ts` (new, pure,
   vitest `idlePreload.test.ts`) now loads 3 per idle slot. Not measured (needs a browser run): expected effect is less main-thread
   and network competition with the first keystrokes and first quote fetch. All chunks still get warmed.

Checks: `tsc` clean, vitest 589 pass, Playwright `beginner.spec.ts` 11 pass and `gui-shell.spec.ts` pass (one earlier failure was port 8000 contention with the bench).

## Verified already fixed on this branch (no change needed)
- `LivePrice` subscribes per symbol (commit 27ab3df).
- `useLiveRows`: symbol index cached (`cachedIndex`), age redraw skips hidden tabs (`startAgeRedraw`) in `functions/liveRowsCore.ts`.

## Not done / rejected
- Moving `settings/commands`, `alertArgs`, `portfolioArgs`, `sectors` out of the entry (~3 KB gz): `execute.ts` calls them synchronously,
  making command submit async risks keystroke-to-paint and e2e timing. Needs a bench to justify.
- `alerts.ts` must stay (alerts are evaluated app-wide from first tick).
- Indicator-toggle chart rebuild: ChartView effect rewrite broke GP e2e before (docs/review/REVERTED.md).
- Not reached: Grid/ticks per-frame allocation audit, screener compression, backend cached-route overhead (no budget left; need bench/browser).

## Data-oriented rewrite (method update): not started, design only
Target: `state/ticks.ts` (`live`/`pending` Maps keyed by symbol, a fresh `changed` Set per frame) -> `liveRowsCore.hitRows` (Map lookup, new `hit` array per tick) -> `Grid.redrawRows`.
Plan: intern each symbol once to an int id (rule 2); `Float64Array` price/change/pct; dirty ids as a `Uint32Array` bitset (rule 5) reused every frame (rule 4);
`useLiveRows` keeps an `Int32Array` id -> row position. Touches `TickListener`'s `ReadonlySet<string>` signature used by LivePrice, alerts, quoteRows, Board, PORT,
so it is a cross-cutting change that needs a browser tick-to-pixel measurement (bench is the other agent's) and a full e2e run. Left undone rather than done unmeasured.
