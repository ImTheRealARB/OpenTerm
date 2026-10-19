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

## Phase 2 result (2026-10-19)
- Full gate on the final tree: ALL PASS (pytest 1628, ruff, tsc, vitest, e2e 183) in 123.3 s; `main` took 167.4 s and FAILED 9 e2e tests (load flakes). See `BASELINE.md`.
- Bench: 37/37 after one rested rerun (first run: two BT misses, throttling). See `docs/PERFORMANCE.md`.
- Reverted: `c820e22` (SWARM abort, remount hazard) and `e8eed43` (ChartView: broke 6 GP e2e tests). See `REVERTED.md`.
- Added after the self-review: swarm fatal error after earlier roles still ends with `swarm_done` (test), `\Z` path regex, whole floats for integer tool args (`cffa895`). Playwright now 4 workers (the default 10 flaked 8-9 tests per run, on `main` too).
- Wave 2 added: quant parsers (`parse_deribit`, `parse_mof`), `rolling_cc` 44.1 -> 19.1 ms, `useLiveRows`/`LivePrice` (index rebuild 241-294 -> 83-92 us at 2000 rows; hidden-tab redraw stops).
- Tests removed: 0 (none were redundant); +60 new tests.

## UNVERIFIED items, now checked
Items 1, 4, 6, 7, 9, 10, 12 (and the quoteRows wiring): covered by the full gate and bench above. Item 5: GP drawings e2e pass (ChartView revert, `drawSave` kept). Item 2 (heartbeat): e2e passes, never run against a real half-open socket. Item 3: resolved by the revert. Item 8: pytest passes; the uvicorn-handler filter was only tested with a stand-in logger.
STILL UNVERIFIED: `check.mjs` Playwright stage and `check.sh` on Linux/macOS; the new 5-job CI on GitHub; `new_function.py` for real in the repo (only dry-run + scratch copy); heartbeat on a real half-open socket; modules not audited line by line (`valuation/`, `quantlib/`, most of `quant/`, `quantjobs/{opt,fact,ql,alpha}`).
