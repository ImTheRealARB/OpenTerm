# Review: frontend functions A-R, bt/, research/, markets/ (agent 7)

## Checked
Panel load/key-handler patterns across `functions/[A-R]*` (GP excluded), `bt/csvImport.ts`, `research/chartMath.ts`.
Every `registerPanelKeys` handler that reads state uses `useLatest`/refs (AI, AUDIT, DES, ECST, FRED, KITE, PerfViews are fine:
they only call setters or read refs). ResearchPanel, FRED, ECST, PRED, GIP, DES already guard against stale answers.

## Fixed
- 67d7742 COMP: a slow answer for the previous symbol overwrote the new symbol's peers (and cleared `loading`). New pure
  `functions/keyedLoad.ts` `latestOnly()`; test `keyedLoad.review.test.ts`.
- 8803f4e HIST, ECO, CRYP, MACRO, N: five hand-copied `env/error/loading + load()` blocks had the same race (re-key while a
  request is in flight). They now use `useEnvelope` from `secPanel.tsx` (read only; agent 8 owns it): key = their args.
  Behaviour kept: poll intervals, F5 `reload(true)`, env reset on re-key (CRYP now also resets, which is correct). ~65 lines removed.
  No unit test (hook behaviour needs a DOM; vitest is Node). tsc clean.
- csvImport: the browser preview accepted `0x10`, `0b1`, `0o7` as prices; the backend (Python `float`) rejects them, so
  a file previewed as valid failed on store. Test `bt/csvImport.review.test.ts`.
- PORT: the 250 ms throttled refresh `setTimeout` was never cleared on cleanup. Hygiene only, no test.

## Left (and why)
- Same duplicated load block remains in CENB, EQS, MOV, NRG, RATES, IMAP, ERN: no parameters, so no race; ERN has a no-date
  path (`Promise.resolve()`) and already ignores a mismatched date (`cur`). Converting them is churn without a bug.
- BT.tsx `submit()`: a POST answer for older args can still set `running` after the command changed. Rare, needs a
  mocked race to test; not touched.
- AI.tsx `send` does not abort on unmount; maximize remounts the panel, so aborting would kill a running answer (user-visible).

## Decisions for user
- AI.tsx:~178: abort the SSE stream on unmount? Saves backend work when a panel closes, but a maximize would cancel a running answer. Left as is.

## Unverified
- Playwright/bench not run (brief forbids). The five converted panels need one e2e pass (HIST, ECO, CRYP, MACRO, N specs).
- `useEnvelope` sets `loading` true only inside `reload`; first paint of a converted panel shows loading from the initial `useState(true)`, same as before.

## Performance (before/after)
None claimed; no perf changes made.
