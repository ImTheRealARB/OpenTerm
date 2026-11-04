# Frontend bugs fixed (cloud 2026-11-04)

## 1. SWARM / AI never aborted their paid stream when the panel was closed
- Root cause: no abort on close. The earlier fix (`c820e22`, reverted in `6016f7d`) aborted on React unmount, but maximize/restore remounts the panel, so it killed running runs.
- Fix: the workspace state decides. `state/panelGone.ts` (pure): a panel is gone when its id left `panels` or it now shows another function; `maximized` is ignored. `functions/panelGoneWatch.ts` `watchPanelGone(panelId, onGone)` subscribes to the workspace store. `AI.tsx` and `SWARM.tsx` start the watch when a stream starts and stop it in `finally`, so the watch lives with the stream (not the component) and survives a maximize remount.
- Known edge: loading a saved layout that reuses the same panel id with the same function does not abort.
- Tests: `state/panelGone.test.ts` (vitest, 4); `e2e/panel-close-abort.spec.ts` (hanging mocked `/api/ai/swarm`, fetch wrapper counts abort signals: maximize + restore = 0 aborts, Alt+W close = 1). Verified failing on the old code at the close step. Existing `phase16.spec.ts` and `phase16b.spec.ts` pass.
- Files: `frontend/src/state/panelGone.ts`, `frontend/src/functions/panelGoneWatch.ts`, `AI.tsx`, `SWARM.tsx`.

## 2. Command history not re-fetched after the backend came back
- Root cause: `main.tsx` called `history.sync()` once at page load and swallowed the failure.
- Fix: `command/syncGate.ts` `createSyncGate(load)` retries until one load succeeded (no parallel loads); `main.tsx` calls it at load and on every `link` store change (the socket reports OK).
- Tests: `command/syncGate.test.ts` (fail then OK retries; loads once; no overlap). Failed first (module missing).
- Files: `frontend/src/command/syncGate.ts`, `frontend/src/main.tsx`.

## 3. India (NSE) market light had no holiday source
- Root cause: Nager.Date has no India data, so `/api/world/holidays?mkt=IN` answered 404 and the light used weekday sessions only.
- Fix: `backend/openterm/world/nse_holidays.py` (pure, no scraping): fixed-date holidays on weekdays (Jan 26, Apr 14, May 1, Aug 15, Oct 2, Dec 25; weekend dates are dropped, not shifted) plus Good Friday (from `nyse_holidays.easter`). Apr 14 (Ambedkar Jayanti) is also fixed-date, so it was added to the list asked for. The route returns `basis: "fixed"` with label "... FESTIVAL HOLIDAYS NOT INCLUDED". Frontend: `Basis` gets `"fixed"`, `basisNote()` in `markets/hours.ts` gives the tooltip (TopBar) saying festivals are missing. NY rules were already tested (`test_phase19_holidays.py`, 2024-2027 published lists): untouched.
- Tests: `backend/tests/test_nse_holidays.py` (weekday and weekend cases, Good Friday, range, honest label, route); the old "IN is 404" test in `test_phase19_macro.py` was removed; `hours.test.ts` covers `basisNote`.
- Files: `backend/openterm/world/nse_holidays.py`, `holidays.py`, `world_routes.py` (docstring), `frontend/src/markets/hours.ts`, `holidays.ts`, `components/TopBar.tsx`, `net/api.ts`, `docs/DATA_LIMITS.md`.
