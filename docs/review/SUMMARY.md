# Review sprint summary (Phase 1, 2026-10-19)

Branch `claude/review-all` (from `main` 1e37af8). 10 Sonnet agents, about 17 minutes, no full gate, bench or Playwright run. Phase 2 verifies everything below.

## Bugs fixed (test in brackets)
Backend (tests in `backend/tests/test_review_*.py`, bug tests written failing first)
- Hub: repeated symbol in one sub frame leaked an upstream subscription; repeat in one unsub frame raised KeyError and dropped another client's ref; `Poller._last` grew without bound (backend_core).
- WebSocket bare `["ping"]` crashed the socket (backend_core).
- Scheduler: adapters without `probe()` stayed DOWN forever once tripped (backend_core).
- Jobs: racing identical submits started two jobs; dead-worker tracking by `id()` collided; cancel flag reset moved to the server (backend_compute). `.tmp` orphan sweep (backend_compute).
- Redaction: log filter now masks tracebacks, uvicorn handlers, Telegram tokens, `x-api-key`/Alpaca headers, `FRED_API_KEY=`; `key_error`, derivs/research/world/AI mid-stream error text now redact (backend_api, backend_compute, backend_ai).
- Validation: `$` regexes let a trailing newline through (currency, zone, chord, model id, names, symbols); `symbol` > 32 chars gives 422; JSON body > 4 MB gives 413 (backend_api).
- AI: tool allow-list bypass via `../` path arguments reaching any GET route (e.g. `/api/keys`); argument-type crashes; tool call without id; a raising tool ended the stream; stream-cancel leaks; swarm retried non-retryable errors; parallel tool calls with index 0 merged; Kite non-object body (backend_ai, 26 tests).
Frontend (tests in `*.review.test.ts`)
- COMP/HIST/ECO/CRYP/MACRO/N re-key load race (keyedLoad, `useEnvelope`); IMPORT accepted `0x10` prices; PORT refresh timer leak (frontend_functions_a).
- `SETTINGS POLL CONSTRUCTOR 30` threw TypeError (`Object.hasOwn`); SWARM left paid stream running after unmount (frontend_functions_b).
- Half-open socket showed BACKEND OK forever; tick merge erased earlier non-null fields; Grid repainted on no-op wheel (frontend_core).
- GP drawings saved to the wrong symbol after a symbol switch; OBV/MFI blank after one NaN volume; GIP rebuilt the chart every render; stale crosshair index (frontend_chart).

## Speedups (micro-benchmarks; see `docs/PERFORMANCE.md` "Review sprint")
Cache.get_many 526.8 -> 11.5 ms; JobStore.recent 1070 -> ~0.5 ms; GIP bucket ~24 -> ~5 ms; doc_search 171 -> 3.3 ms; AI DOC upload stall 828 -> 42 ms; job flush 0.614 -> 0.019 ms; indicator worker request 2.75 -> 0.97 ms.

## Tests removed
None. Agent 9 classified 804 backend, 437 vitest, 192 Playwright tests: no exact duplicates, no dead tests, all xfail/`it.fails`/`test.fail()` markers already gone. Removed one dead `RATES = xf(...)` definition and refreshed stale comments. Time saved: 0 s. See `test-pruning.md`, `REMOVED_TESTS.md`.

## Dev loop
`scripts/check.ps1|check.sh` (affected tests + tsc + ruff; `--dry-run`, `--all`), `gates.mjs` restructured (cheap checks first, heavy suites parallel, per-gate timing), CI as 5 jobs, `scripts/new_function.py`, CLAUDE.md and HANDOFF.md de-staled. See `devloop.md`.

## Decisions for the user
`DECISIONS_FOR_USER.md`.

## UNVERIFIED (Phase 2 must check)
1. Everything: no full `gates.mjs`, bench or Playwright run happened. Whole branch needs the gate.
2. Heartbeat (`3d0c2f9`): never run against a real half-open socket; risk of false DOWN under load in e2e. Revert if flaky.
3. SWARM unmount abort (`c820e22`): may cancel a run when the panel is maximized (remount). Check SWARM e2e.
4. `useEnvelope` conversion of HIST, ECO, CRYP, MACRO, N: no e2e run.
5. GP drawing-save wiring, `ChartView` effect-key change, indicator worker buffer transfer: never run in a browser. Run Phase 19 drawing and GP/GIP e2e.
6. Grid wheel early return and `.sr` write-on-change: type-checked only; Playwright mirrors `.sr`.
7. Tick null-carry (`state/tickMerge.ts`): check quote grids and alerts e2e.
8. Redaction filter on a live `uvicorn.run`; new 413/422 limits against real routes (full pytest).
9. `JobStore.recent` covering index and the jobs runner changes under the Phase 11/13/14/15 bench budgets; BT/quant job benches.
10. `Cache.get_many` in `DataService.quotes`: run bench backend latency lines.
11. `gates.mjs`, `check.mjs`/`check.sh` (Linux), new CI workflow, `new_function.py` (only dry-run in repo): never run for real.
12. `docs/FUNCTIONS.md` staleness test after the registry changes (agent 8 touched registry.ts only if listed; run `gen_functions_doc.py`).
13. Not audited: `quantlib/`, `quant/`, `valuation/`, `options/`, `rates/`, `secf/`, individual `quantjobs/*` bodies.
14. CLAUDE.md gotcha "ChartView captures writeReadout" is obsolete per agent 6; remove in Phase 2.

## Phase 2 revert candidates if a gate or budget fails
Per-commit: `3d0c2f9` heartbeat, `c820e22` SWARM abort, `e8eed43` ChartView, `fb5c07e` GP draw save, `4205941` tick merge, `ebbeeee` Grid wheel, `8803f4e` useEnvelope, `d0204cd` jobs runner, `47b9b33` JobStore.recent, `40bd090` Cache.get_many, `2931bcd` AI stream cancellation.
