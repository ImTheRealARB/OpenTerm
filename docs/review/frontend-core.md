# Review: frontend-core (Grid, state/, net/, perf/)

Scope read in full: `components/Grid.tsx`, `state/{ticks,store,workspace}.ts`, `net/{socket,jobs,jobFrames}.ts`, `perf/metrics.ts`. `net/api.ts` (1132 lines) and `state/layoutState.ts` only skimmed (not hot path).
Checked with `npx tsc --noEmit` (clean) and `npx vitest run` on the new test files, `net/phase11.test.ts`, `state/`. No dev server, bench or Playwright.

## Fixed
1. **Half-open socket showed BACKEND OK forever** (`net/socket.ts`, new `net/heartbeat.ts`). A dead TCP connection never fires `close`, so the status bar kept its last pong and no data arrived with no STALE/DOWN marker. Now two ping intervals (10 s) with no message of any kind after a ping marks the link DOWN and reconnects through the normal backoff. Counts "anything received since the previous ping", so a background tab whose timers fire once a minute does not misfire. `onclose` logic moved into one `handleClose` that runs once per socket (guard), so heartbeat + a late `close` cannot schedule two reconnects. Test: `net/heartbeat.review.test.ts`.
2. **Tick buffer dropped fields within one frame** (`state/ticks.ts`, new `state/tickMerge.ts`). `ingest` keeps only the last row per symbol per frame, and `flush` applies `!= null` fields only, so a second tick with `volume`/`change`/`high`/`low` null erased the first tick's values (they stayed stale until a later tick carried them). `carryNulls` fills null slots from the buffered row, in place, no allocation. Test: `state/tickMerge.review.test.ts`.
3. **Grid repainted on a wheel event that moved nothing** (`components/Grid.tsx`, new `state/gridScroll.ts`): at the top/bottom, with fewer rows than the viewport, or on a horizontal wheel, a full canvas redraw ran for no change. Now returns early (still `preventDefault`). Test: `state/gridScroll.review.test.ts`.
4. **Grid `.sr` live region re-announced identical text** on every rows replacement (every quote reload): `describe()` now writes `textContent` only when it differs.

## Performance (before/after)
- **Jobs frame flush** (`net/jobs.ts` + `net/jobFrames.ts` `applyJobFrames`): `batch.reduce(applyJobFrame)` copied the whole job Map once per frame (O(frames x jobs)); now one copy per flush. Measured in vitest (Node, `jobFrames.review.test.ts` "bench"): 300 jobs, 40 frames per flush, mean of 500 runs after warm-up: **0.614 ms -> 0.019 ms (32x)**. Output equality with the loop is tested. Real-world gain is smaller (typical batch is 1-5 frames); it matters when many jobs report progress at once (10/s/job cap).
- Items 1-4 above are correctness, no measurement claimed (the Grid early return removes repaints at the scroll ends; not measured).

## Checked and left alone
- `ticks.ts` flush: one `Set` + one `afterPaint` closure per frame (not per tick); live entries mutate in place; listeners get the shared `changed` set. Fine. A hidden tab keeps `oldestRecv` set so the first `tickToPixel` sample after returning is huge (metrics only).
- `socket.ts` `subscribe` refcounting is symmetric (duplicates in one call included), resubscribes on open, `unsub` is idempotent. Reconnect backoff 0.5 s doubling to 15 s, reset on open. No jitter, and it resets even if the server accepts then closes at once (500 ms retry loop): minor, left.
- `Grid.tsx`: listeners and ResizeObserver are removed on unmount; `displayVersion` subscription returned. `redrawRows` allocates one small array + closure per call (per frame); fine. The pending one-frame-highlight rAF is not cancelled on unmount; harmless (draws on a detached canvas).
- `store.ts`: Set-based listeners, `useSyncExternalStore` with stable `subscribe`. `workspace.subscribe` serialises the whole workspace to localStorage on every store change, but changes are user actions, not ticks.
- `perf/metrics.ts`: ring buffers, no per-sample allocation; `panelRender` Map never drops closed panels (64 doubles each), negligible.
- `jobs.ts`: `received`, `painted`, `framed`, `pending` are all bounded/cleaned.

## Not in my scope (found, not changed)
- `functions/quoteRows.ts` `useLiveRows` (line 121-145): rebuilds the symbol index on every `rows` change and runs `grid.redraw()` every 5 s even when the tab is hidden; `hit.push(...idx)` per frame allocates. Owner of `functions/` should look.
- `workspace.ts` `navigate`/`historyStep` throw if the panel id no longer exists (`s.panels[id]` undefined); callers are expected to pass live ids. Left.

## Decisions for user
- `net/socket.ts` heartbeat: closing the socket after 10 s of total silence is a visible behaviour change (status goes DOWN, subscriptions are re-sent on reconnect). Threshold `MAX_MISSED = 2` in `net/heartbeat.ts`. Risk: a backend event loop blocked for more than 10 s would now show DOWN and reconnect instead of staying OK; arguably more honest. Not exercised against a real half-open socket (UNVERIFIED, needs a manual test: block the backend process with a debugger or firewall rule).

## Unverified
- No Playwright/bench run (rules). Grid wheel and `.sr` changes are only type-checked.
