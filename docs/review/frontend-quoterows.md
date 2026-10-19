# frontend-quoterows (agent 12, second wave)

Scope: `functions/quoteRows.ts`, `Board.tsx`, `boards.ts`, `components/LivePrice.tsx` (the only definition of `LivePrice`).

## Checked
- `useLiveRows` (used by Q, WL, ALRT, PORT, Board): subscription key, symbol index, 5 s age redraw.
- `LivePrice` (DES, QR): subscription lifetime.
- `Board.tsx`, `boards.ts`: no change needed (pure data + columns; `rows` memo is keyed on quotes/def).

## Fixed
1. `useLiveRows` rebuilt its symbol index (`index.set(s, [...old, i])`, quadratic for duplicate symbols) in an effect keyed on the `rows` array identity, so every REST refresh and every PORT/ALRT edit tore down and re-created the tick listener and the interval. Now the index is cached on the symbol layout (symbol per row position): a refresh with the same symbols in the same order keeps the same index and the same listener. A sort, add or remove changes the layout and rebuilds, as before. Index positions are still exact because the cache key includes order.
2. The 5 s `grid.redraw()` interval ran while the tab was hidden. `startAgeRedraw` stops the timer while `document.hidden`, and redraws once on `visibilitychange` back to visible, then resumes. Visible behaviour is unchanged (AGE/STALE text is repainted on return).
3. `LivePrice` unsubscribed and resubscribed its symbol on every quote refresh (effect keyed on `quote, stale, ageS`): refcount went 1 -> 0 -> 1, sending `unsub` then `sub` to the server each time. Now a separate effect keyed on `quote.symbol` subscribes; the paint effect keeps its old keys.

Pure logic is in `frontend/src/functions/liveRowsCore.ts`; tests in `liveRowsCore.review.test.ts` (9 tests: index/hit/key, cache reuse vs rebuild on reorder, timer visible/hidden/return/cleanup/no document). `npx tsc --noEmit` clean.

## Performance (before/after)
What: cost of one `rows` change (REST refresh, same symbols, fresh row objects) in `useLiveRows`: key + index build (old) vs layout + key + cached index (new).
How: Node micro-benchmark (esbuild bundle, 2000 iterations after 200 warm-up, 20 pre-built row sets, 10% duplicate symbols; 3 runs, ranges below). No React, no server.

| rows | before | after |
|---|---|---|
| 200 | 21.5-27.7 us | 8.4-9.6 us |
| 2000 | 241-294 us | 83-92 us |

About 2.7x cheaper per refresh, plus no listener/interval teardown per refresh (not measured, no DOM in Node). The `LivePrice` change removes 2 WebSocket messages (`unsub`, `sub`) per quote refresh per panel by construction (refcount arithmetic in `net/socket.ts`); not measured. The hidden-tab saving is the removal of one full-grid canvas redraw per 5 s per quote panel while hidden; not measured.

## Left / UNVERIFIED
- React wiring of the hook and `LivePrice` is covered by tsc only; no e2e was run (no Playwright allowed). Worth one run of the Q/WL/PORT/DES e2e specs in the lead's gate.
- Not changed: `sortRows` INPUT does `rows.find` per input (O(n^2), only on explicit sort request; n <= a few hundred). `useQuotes` effect still refetches on a new `inputs` array identity (callers memoize).

## Decisions for user
None.
