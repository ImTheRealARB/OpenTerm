# Review: frontend-chart (agent 6)

Scope read: `chart/ChartView.tsx`, `studies.ts`, `patterns.ts`, `drawings.ts`, `indicators.ts`, `indicators.worker.ts`, `functions/GP.tsx`, `gpArgs.ts`.
Checks run: `npx tsc --noEmit` (clean), `npx vitest run src/chart` (61 pass). No servers, no Playwright.

## Fixed

| Commit | What | Test |
|---|---|---|
| fb5c07e | GP drawings were saved to the wrong symbol. Panel.tsx keeps one GP instance when the panel's security changes, and the key handler (registered with deps `[panelId, picker, crossOn]`) kept an old render's `commit`, which scheduled `flush(<old symbol>)`. The `loadedFor !== sym` guard then dropped the save silently, so a drawing made after an in-place symbol switch was never stored. Also: an edit made before the list loaded stayed `dirty` and was saved over the server's list later. New pure `chart/drawSave.ts` saves to the symbol the list was loaded for and drops pre-load edits. | `chart/drawSave.review.test.ts` (4) |
| 0dc71b6 | OBV and MFI: one NaN volume (`toBarData` fills missing volume with NaN) poisoned every later OBV bar and every MFI window containing it, so the pane drew blank. Now a missing volume counts as 0, as VWAP and the volume histogram already do. | `chart/studies.review.test.ts` |
| e8eed43 | ChartView series effect depended on the `indicators` array identity. `GIP.tsx:155` passes an inline `indicators={[]}`, so every GIP render rebuilt all series and `fitContent()` reset the user's zoom. Now keyed on `listKey(indicators)`. | `listKey` test in `studies.review.test.ts` |
| e8eed43 | Keyboard crosshair index (`cross.current.idx`) was not clamped after the data changed (range key 5Y -> 1D with the crosshair on): `crosshairIndex()` returned an index past the end, so GP's draw-anchor Enter silently did nothing. Clamped (`clampIndex`) in the rebuild and in `crosshairIndex()`. | `clampIndex` test |

## Performance (before/after)

Indicator worker request (ChartView series effect), main-thread cost of handing 6 Float64Array columns to the worker:

- Change: `data.x.slice()` then plain `postMessage` (copy, then a second structured-clone copy) became `slice()` + transfer list (one copy, the clone is a move).
- Before: 2.75 ms per request at 50,000 bars. After: 0.97 ms (2.8x). Clone-only without slice would be 1.49 ms but would share nothing, so slice+transfer is the fastest safe option.
- How: Node `worker_threads` MessageChannel micro-benchmark, 200 iterations after 20 warm-up (scratchpad `clone.mjs`). Browser structured clone costs differ somewhat; the ratio (one copy fewer, no clone) holds.
- Typical GP (250-2500 bars) saves 0.01-0.1 ms: negligible there; only the 50k-bar PERF CHART benefits.

## Checked, no change needed

- Crosshair readout "stale closure" in CLAUDE.md: already fixed in the code. `writeRef.current = writeReadout` is reassigned every render and the crosshair subscription calls `writeRef.current`, so the readout reads the current `data`/`events`. The CLAUDE.md gotcha line can be dropped by the lead.
- Listeners: ResizeObserver disconnected, rAF cancelled, worker terminated, `chart.remove()` frees crosshair/range subscriptions. No leak found.
- Live ticks update the last bar via `series.update` (no rebuild, no indicator recompute). Good.
- Indicator math (`indicators.ts`, `studies.ts`, `patterns.ts`): pure, linear or O(n*window); SMC FVG fill scans are O(zones*n) worst case but capped by `PATTERN_MAX_BARS = 5000` and run in the worker. No change.
- `hitTest`, `segments`, `timeToLogical` are fine for the 200-drawing cap.

## Decisions for user

- `ChartView.tsx` series effect (~line 222-434): toggling any indicator (GP `I` picker) rebuilds the main series, volume, compare series, redoes the worker compute for ALL indicators and calls `fitContent()`, so the user's pan/zoom resets on every toggle. Splitting indicator series into their own effect (remove/add only those, keep the viewport) would be faster and friendlier but changes what the user sees and touches the `chart.extraSeries` gauge e2e reads. Risk: medium (pane indexing, gauges). Not done.
- `ChartView.tsx` `live()` (~line 574): the readout line keeps showing the loaded history bar's O/H/L/C/V while live ticks move the last bar on the chart (readout is only rewritten on crosshair moves). Writing the live bar into the readout when the crosshair is off is user-visible; an unlabelled stale last-bar readout may also conflict with the "never fake data" rule. Risk: low-medium (one DOM write per frame-batched tick).
- `ChartView.tsx` worker (~line 303): no `onerror` on the indicator worker, so a throw inside `compute` leaves the chart with no indicators and no message. A visible `IND ERR` status needs a UI surface (a prop or readout suffix). Risk: low, user-visible.
- `ChartView.tsx` `paintRef` (~line 454): every crosshair move and range change runs the overlay paint (resize check, `clearRect`, geo build) even when there are no drawings. An early exit when the canvas is already blank would save a layout read per move, but it cannot be measured without a browser, and `geoRef` (used by click-to-pick) must stay set. Not done (no measurement).
- Indicators are not recomputed for the live bar (SMA/RSI etc. stop at the last loaded bar until the next history refresh). Probably intended; mention in the GP help if not.

## Unverified

- GP wiring of `createDrawSaver` is covered by tsc and the pure tests only; the Playwright drawing specs (`e2e` Phase 19 draw tests) were not run (rule: no Playwright). The lead's full gate should run them.
- Worker transfer in a real browser was not run.
