# Decisions for the user (review sprint, 2026-10-19)

Nothing below was changed in code unless it says so. Full detail is in each area's notes file in `docs/review/`.

## Changed in code but user-visible (confirm or revert the named commit)
- **Socket heartbeat** (`3d0c2f9`, frontend-core): 10 s of silence marks the link DOWN and reconnects (`MAX_MISSED` in `net/heartbeat.ts`). A backend stalled for more than 10 s now shows DOWN.
- **`gates.mjs` stops after a ruff/tsc failure** (`5e107d3`, devloop): `--keep-going` restores the old behaviour. CI is now 5 jobs (static, pytest, vitest, e2e, bench).
- **New 413 / 422 limits** (`c768a2e`, backend-api): JSON bodies over 4 MB get 413; `symbol` over 32 characters on `/api/history`, `/api/profile`, `/api/resolve` gets 422.
- **AI stream `error` event of kind `internal`** (backend-ai): an exception after the SSE headers now ends the stream with a redacted error event.

## Deferred (risky or user-visible)
Quant
- `quantjobs/attr.py` `return_measures`: Modified Dietz can divide by zero or go negative after large withdrawals; `xirr` bisection assumes a flow sign pattern and can return a wrong root; `quantjobs/risk.py` values holdings at each series' own last close, not the last common day; `parse_deribit` forward is the upper median for an even instrument count (backend-quant). **DONE** (cloud 2026-11-04, `23fd1a2`).
AI/SWARM
- SWARM and AI panels never abort their paid SSE stream when closed (SWARM abort `c820e22` was reverted because maximize remounts the panel and would kill the run). A close-vs-remount distinction is needed.
Backend
- `cache` table is never pruned; the DB file grows for ever (backend-core). **DONE** (cloud 2026-11-04, `23fd1a2`).
- Yahoo quote batches above about 160 symbols trip the rate limit and put Yahoo in cooldown (backend-core). **DONE** (cloud 2026-11-04, `23fd1a2`).
- If a leader request is cancelled in `service._once`, waiters get `CancelledError` (backend-core). **DONE** (cloud 2026-11-04, `23fd1a2`).
- `DayStore.rows` decodes up to 250 days of msgpack on the event loop (backend-core). **DONE** (cloud 2026-11-04, `23fd1a2`).
- **DONE in Phase 17 (2026-11-03):** TLS is always verified (`delivery/email.smtp_connect`); a server with no STARTTLS is refused unless it is on loopback. Original note: `keys.py` `_smtp_check`: `starttls()` without a context does not verify the certificate. Fix is `ssl.create_default_context()`, but a self-signed mail server would show ERROR in APIKEYS (backend-api).
- No global request-size limit in `main.py`; only `api.json_object` routes are capped (backend-api).
- `jobs` can reach 200 rows x 8 MB; bt.mc/bt.wf store whole equity arrays in `params` (backend-compute).
- Worker spawn blocks the event loop; old worker pipes are not closed after a kill (backend-compute).
- Swarm retry has no backoff or jitter; the spend cap can overshoot when concurrent chats both pass the pre-check; Kite ticker reconnects every ~1 s with no jitter if the server accepts and drops; an expired Kite instrument dump fails instead of showing STALE; `llm/sse.py` line buffer has no cap (backend-ai).
Frontend
- `execute.ts` runs WL, PORT and ALRT edits before validating the target panel or panel limit: `7: WL X ADD AAPL` edits the list, then fails with `NO PANEL 7` (frontend-functions-b).
- After first paint `main.tsx` starts loading about 88 chunks (about 500 kB) at once; staggering is unverified without the bench (frontend-functions-b).
- Percent alerts read only the raw tick row, so a price-only tick could miss one (frontend-functions-b).
- `LivePrice` resubscribes the symbol on every quote refresh (frontend-functions-b).
- `AI.tsx` does not abort its SSE stream on unmount (frontend-functions-a).
- Toggling any indicator rebuilds the chart and resets zoom; the readout does not follow live ticks; the indicator worker has no `onerror` (frontend-chart).
- `functions/quoteRows.ts` `useLiveRows` redraws every 5 s in a hidden tab and rebuilds its symbol index on every `rows` change (frontend-core).
Tests and branches
- `test_phase12.py::test_migration_9_tables` looks redundant with the every-schema-version migration test; kept (test-pruning).
- Branches `claude/angry-easley-fc2d86` and `claude/openterm-phase-19-8ad9bb` can probably be deleted; nothing was touched (devloop).
