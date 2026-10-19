# Review: frontend-functions-b (agent 8)

Scope: `functions/` S-Z + registry, `command/`, `components/` (not Grid), `keys/`, `settings/`, `App.tsx`, `main.tsx`, `vite.config.ts`, `index.html`.

## Fixed
- `9f9e1d4` `settings/commands.ts`: `SETTINGS POLL CONSTRUCTOR 30` (or `__PROTO__`) threw `TypeError: object is not iterable`
  out of `execute()` (the `k in POLL_BOUNDS` test matches inherited object keys). Now `Object.hasOwn`, so the user sees the usage message.
  Test: `settings/commands.review.test.ts` (failed before, passes after).
- `c820e22` `functions/SWARM.tsx`: closing the panel, or running another function in it, left the SWARM SSE stream running
  (paid model calls with nobody watching). Now aborted on unmount. UI-only effect, no Node test possible (vitest has no DOM); checked by reading
  (the stream already handles `AbortError`). Same pattern exists in `AI.tsx` (agent 7's file): its only abort is the Esc key.

## Bundle audit (`npx vite build`, 250 modules, 4.1 s)
- Main chunk `index-*.js` 333.6 kB (109.8 kB gzip). By source map: react-dom 210.7 kB, registry.ts 22.6 kB (titles + arg schemas of ~170 functions),
  react 8.6 kB, scheduler 3.7 kB, `net/api.ts` 7.7 kB, everything else of ours about 80 kB. Nothing heavy is loaded eagerly.
- Heaviest lazy chunks: ChartView 204.9 kB (lightweight-charts; loaded only for GP / BT / GIP / FRED, `idlePreload: false` already), BT 35.5, PORT 19.1,
  AI 12.1, ResearchPanel 11.0, GP 9.5, SWARM 9.0, SECF 8.0; the other ~115 chunks are under 8 kB. 126 JS chunks, 869 kB total.
- `package.json`: 3 runtime deps (react, react-dom, lightweight-charts) and all are used; every devDependency is used (vite, vitest, tsc, playwright, plugin-react, types).
  Nothing to remove.
- Only Vite warning: `Shortcuts.tsx` is imported statically by `App.tsx` (cheatsheet overlay) and dynamically by the registry, so the dynamic import cannot split it.
  It is 1.9 kB; moving it to `loadModule()` would delay the first `?` overlay for no gain. Left alone. No split done (nothing to gain, so nothing to measure).

## Checked, no bug found
- Command parser (`parser.ts`): `CN` is both a market suffix and a function; `!isFunction(t1)` guard handles it. `in MARKET_SUFFIX` is safe (tokens are upper-cased).
- Key handling: `App.tsx` handler re-registers on `[cheatsheet]` and reads everything else from stores (no stale closure). `keys/overrides.ts` `mergeBindings` / `checkChord` fine.
- Once-registered panel key handlers in S-Z files (SEAS, SECF, SETTINGS, STBL, SWARM, THESIS, WECO, WETR, WL, tableExport) all read state through `useLatest` or a ref.
- Settings sync (`settings/sync.ts`, `runtime.ts`, `schema.reconcile`): edits during an in-flight PUT stay dirty and a new push is scheduled; startup edit before GET returns still wins. OK.
- Startup before first paint: `installObservers`, `initSettings` (localStorage only), `render`; the socket, alerts, sources, settings sync and history all start in `afterPaint`.
  `Clock` calls `loadHolidays()` and `KiteState` calls `refreshKite()` on mount (network, not blocking paint).

## Decisions for user
- `command/execute.ts:~60-90`: `WL NAME ADD ..`, `PORT NAME ADD/RM/BASE ..` and `ALRT ..` run their backend edit BEFORE the target panel is validated.
  `7: WL TECH ADD AAPL` (no panel 7) or Shift+Enter at the 9-panel limit edits the list and then says `NO PANEL 7` / `PANEL LIMIT`. Fix is to validate
  `parsed.target` and the panel limit first. Not done: needs an e2e test (execute imports `net/api`, not unit-testable in Node) and it changes what a failed command leaves behind.
- `main.tsx` idle preload: after first paint one idle callback starts `loadModule` for ~88 chunks (~500 kB) at once. Chrome allows 6 connections per host to the
  HTTP/1.1 backend, so an `/api` call made in that window can queue behind chunk downloads. Staggering (e.g. 4 at a time, one per idle callback) would be
  behaviour-neutral but cannot be measured without running servers; only the bench can show it. UNVERIFIED.
- `command/alerts.ts:110` pct alerts read `pct`/`change` from the raw tick row only. If a provider sends a price-only tick (pct and change null) a `+5%` alert
  cannot fire on it although `state/ticks.ts` still holds the last pct. Needs a look at what the Yahoo stream and poller really send. UNVERIFIED.
- `components/LivePrice.tsx:31`: the subscribe effect depends on `quote`, so each quote refresh unsubscribes and resubscribes the symbol
  (WS `unsub` then `sub`, a gap in ticks when the refcount reaches 0). Fix would be to depend on `quote.symbol` only. Not done: touches live-tick behaviour, wants the bench.

## Unverified (needs full gate or bench)
- Nothing run beyond `npx tsc --noEmit`, `npx vitest run src/settings`, `npx vite build`.
