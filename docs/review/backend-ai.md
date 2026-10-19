# Review: backend-ai (llm/, ai/, kite/, kite_routes.py)

Tests: `backend/tests/test_review_backend_ai.py` (26 cases; committed in one commit after the fixes, so no commit in between is red).
Also green: test_phase16_agent / swarm / audit / doc, test_phase15_kite, test_phase11 (162 passed, `-n 0`). ruff clean on the area.

## Fixed (one commit each)
- **Tool allow-list bypass (security).** `cd7bad7` `ai/tools.py`: `backtest_get` `run_id` and `portfolio` `name` were put into the route path and httpx resolves
  dot segments, so `run_id="../../keys"` made the in-process runner GET `/api/keys` (any GET route was reachable by a model or by text injected through news or
  an AI DOC file). Path arguments are now matched against the portfolio-name / run-id grammar. Same commit: argument types are checked against the schema
  (`filings form=5` raised AttributeError and killed the SSE stream) and shapers that hit an odd payload return a tool error. Tests: `test_a_path_argument_cannot_walk_out_of_its_route`, `test_a_wrongly_typed_argument_is_a_tool_error_not_a_crash`.
- **Agent loop.** `a79063f` `ai/agent.py`: a tool call with no id (some providers) left the tool message unmatched, so the next request was invalid; it now gets a
  synthetic id. A `call_tool` that raises is a failed `tool_result` (exception type only, never the message) instead of ending the stream.
- **Stream cancellation.** `2931bcd`: `audited`, `save_events`, `with_evidence` and `agent.run` iterated the stream they wrap with a bare `async for`, so closing them
  left the inner stream (and the gateway's `finally` that charges the worst case and closes the HTTP stream) to the garbage collector. They use `aclosing` now.
  Same commit: a DB error while storing a run no longer loses the answer (logged, no `saved` event), and an exception after the SSE headers go out ends the
  stream with a redacted `error` event (kind `internal`) instead of a dropped connection.
- **SWARM.** `4d4c6f8` `ai/swarm.py`: `spend_cap`, `price_unknown` and `invalid` now stop the run at once like `key_required` (they were retried per role, 8 refused or 401 calls, then a
  failed chair). The total cost now counts usage of failed attempts (it only summed successful roles, so it understated what was spent).
- **Redaction.** `476490a` `llm/client.py`: a provider's error text arriving inside a stream (`error` payload) bypassed `redact()`; OpenAI echoes a masked key there.
- **OpenAI-compatible stream.** `ea53658`: parallel tool calls that all carry `index 0` (some OpenRouter backends) were merged into one call with corrupted JSON; they are
  now told apart by `id`. Risk: a provider that sends a different id on every chunk of the same call would now split it (not seen in the recordings).
- **Kite.** `41e03b4` `kite/client.py`: a JSON body that is not an object (list) raised AttributeError in `_json` and in the login exchange; now a DataError / login failure.

## Performance (before/after)
- **AI DOC search** (`d63da2b`): `doc_search` re-tokenised the whole document on every call, on the event loop. Index (per-chunk Counter) is built once per Doc.
  3,000,000 characters / 2317 chunks, 12 searches: median 171 ms (max 233) -> 3.3 ms; first call 169 ms is the index build, which now happens at upload.
  Script: scratchpad `bench_doc.py` (no server; `doc.chunk` + `doc.doc_search`).
- **AI DOC upload** (`32fc3dc`): extract + chunk + index ran inline in the async handler. 4.9 MB HTML: worst event-loop stall 828 ms -> 42 ms (total 833 -> 871 ms).
  Measured with a 5 ms heartbeat task, scratchpad `bench_upload.py`. The `/api/ai/doc/filing` route uses the same helper.

## Checked, no change needed
- No prompt or model output is logged anywhere in `llm/`, `ai/`, `kite/` (only `log.exception` in the ledger append, `log.warning(type(e).__name__)` in the Kite ticker).
- Gateway errors: HTTP error bodies, transport errors and `bad_output` are redacted or contain no body text. Spend cap: pre-call refusal, post-call real cost, worst-case charge in `finally`.
- Ledger chain: `append` holds a lock around read-prev + insert + commit; `at` round-trips exactly through SQLite REAL and orjson; verify catches change, removal and reorder
  (existing tests). Removing the newest entries is undetectable from the table (documented in the module).
- `ai_docs` keeps 5 documents (3M chars each at most), `ai_runs` keeps 200, history is cut to 12 messages of 4000 characters, tool results to 6000, rounds 8 / calls 24, ledger tool lines 60. No unbounded buffer found in the agent path.
- No order, margin, GTT or holdings route or tool in `ai/tools.py` or `kite/` (existing scanning tests untouched). The MCP server is not in this area (Phase 17 paused).

## Decisions for user
- `ai/swarm.py` retry: an immediate retry after a 429 (`quota`) or a transient `provider` error has no backoff or jitter. A fixed 1-2 s sleep would make the three retry tests slower; not changed. Risk: low (one retry, sequential).
- `llm/client.py` spend cap: the cap check and the charge are separate steps, so two chats started at the same moment can both pass the check and overshoot the cap by up to one call's worst case. Fix needs a reservation row in `kv` (schema-visible); not done.
- `kite/ws.py` `_run`: `backoff` resets to 1 s as soon as a connection opens, so a server that accepts and then drops immediately is reconnected every ~1 s forever, no jitter. Fix is "reset only after 30 s of life"; the WebSocket path has never run against a real key, so not changed blind.
- `kite/instruments.py`: an expired (>24 h) dump is dropped even when Kite is down, so every Kite function then fails instead of showing STALE. Serving it with a STALE label is user-visible; not changed.
- `llm/sse.py`: the SSE line buffer has no cap (a provider that never sends a newline grows it). Providers are trusted endpoints; not changed.

## Unverified
- Nothing needing a full gate was changed; the Playwright AI panels read the same SSE events (new events: `error` kind `internal`, no new `saved` when the store fails).
