# Review: backend-api (agent 2)

Scope: `userdata.py api.py world_routes.py keys.py redact.py responses.py settings_store.py logbuf.py models.py config.py portfolio.py drawings.py news_alerts.py world/**`.
Tests: `backend/tests/test_review_backend_api.py` (13 tests). Targeted runs only: this file, `test_userdata`, `test_phase8`, `test_phase10`, `test_phase11`,
`test_phase13_newsalerts`, `test_api`, `test_phase19_ticks`, `test_phase19_pred`, `test_phase19_energy`; ruff clean on every touched file.

## Fixed
| Commit | Finding | Test |
|---|---|---|
| 2bb897b `redact.py` | `RedactFilter` only masked the message. A logged traceback (`logger.exception`, httpx errors carry the full URL with `?token=`) reached stderr unmasked. uvicorn's loggers do not propagate to root, so their handlers (access line, "Exception in ASGI application" traceback) were never filtered. `FRED_API_KEY=`, `x-api-key:` headers and Telegram's `bot<id>:<token>` URL path were not matched by the generic patterns when the value was not registered. | `test_redact_filter_masks_secret_inside_a_logged_traceback`, `test_redact_install_filters_the_uvicorn_handlers`, `test_redact_masks_telegram_bot_token_shape_and_key_headers_even_when_unregistered` |
| c768a2e `api.py` | `key_error` (APIKEYS, strategies, spend cap) skipped `redact()`. `json_object` read any body size (a 5 MB body to any PUT/POST was buffered and parsed): now 413 `too_large` over 4 MB, checked from `Content-Length` before buffering. `/api/history`, `/profile`, `/resolve` took an unbounded `symbol` (each distinct string became an SWR cache entry and a provider call): `max_length=32`, matching the other routes (24). | `test_key_error_body_is_redacted`, `test_json_body_over_the_cap_is_refused_without_parsing`, `test_history_profile_and_resolve_refuse_an_unbounded_symbol` |
| bc7e06b regexes | `$` accepts a trailing newline: `check_currency("USD\n")` stored `"USD\n"` as a portfolio base/position currency; the same hole in the time zone, key chord, AI model id (settings), layout/watchlist/portfolio name, symbol and news word patterns. Switched to `\Z`. | `test_check_currency_refuses_a_trailing_newline`, `test_settings_zone_chord_and_model_refuse_a_trailing_newline` |
| 2a04ef2 `world/tickbuf.py` | GIP `bucket()` ran per-tick dict/list indexing on the event loop: 15-28 ms for a full 20k-tick ring, every poll. Single pass with scalar running values. | `test_bucket_matches_the_reference_on_ordered_unordered_and_volumeless_ticks` (oracle = the old implementation, ordered / shuffled / volumeless / empty, 4 bar sizes) |
| (this commit) `world/pred.py`, `world/commodity.py` | Error text placed in payloads (not via `api.error`) skipped `redact()`: PRED `_reason`, NRG row `error`, WETR NWS note. | `test_pred_reason_text_is_redacted` |

## Performance (before/after)
- What: `world.tickbuf.bucket()` (GIP `/api/world/ticks/{symbol}`), pure Python, runs on the event loop.
- Before: 14.7-28.4 ms per call (best of several runs; 1/5/15/60 s bars; 20,000 ticks, the ring cap), median about 24 ms. After: 4.2-5.6 ms (about 5x). `ring.view()` is 1.0-1.4 ms of the request on top.
- How: scratchpad micro-benchmark, 100 calls per bar size, `time.perf_counter`, old module loaded from `git show HEAD~` for the A/B; no server. Output is byte-identical to the old function (oracle test).
- Not done: caching the result per (symbol, bar, `ring.total`). It would only help when no tick arrived between two polls.

## Checked, no change needed
- `error()` / `bt_error()` redact message and detail; `/api/sources` redacts provider `last_error`; `/api/log` records only `getMessage()` (and the RingHandler carries the filter); `/api/keys` rows carry presence/source/state only; `run_test` records `type(e).__name__` for transport errors and redacts the HTTP body snippet (Telegram's token-in-URL never reaches `detail`).
- httpx timeouts: `keys.run_test` 10 s, SMTP 10 s; the shared client has 6 s. World modules do not open clients (they go through `svc._swr` / `svc.router.call`).
- Memory: log ring 1000, SWR cache `max_entries=5000`, tick rings 100 symbols x 20k, history 500, watchlists 500, portfolios 500, alerts 200/50, settings 16 KB, layouts 64 KB, drawings 200/symbol.
- Blocking work in handlers: keys use `asyncio.to_thread`; SQLite is aiosqlite; nothing else blocks.

## Left alone
- `KeyStore.statuses()` re-reads `.env` once per spec (2.3-3.3 ms for 13 specs, run in a thread on `/api/sources` and `/api/keys`). An mtime cache would save ~2 ms per poll; not worth the staleness risk.
- `write_dotenv` rewrites the file in place (`write_bytes`): a crash mid-write could truncate the user's `.env`. Atomic temp-file + `os.replace` is the fix; skipped because `.env` may also hold non-OpenTerm keys and Windows replace semantics when the file is open elsewhere need a manual check.
- `/bt/import` reads the whole body before the 20 MB check (`api.py`, local import only).
- `/api/deriv/{fn}` passes every query parameter to `derivs.run(**params)` (service layer, not my files): an unexpected name may raise `TypeError` (500 instead of 400). UNVERIFIED, not in scope.

## Decisions for user
- `keys.py:380-385` `_smtp_check`: `s.starttls()` with no context uses `ssl._create_stdlib_context()`, which does NOT verify the server certificate, so the SMTP app password is sent over an unauthenticated TLS channel. Fix: `s.starttls(context=ssl.create_default_context())`. Risk: a self-hosted or self-signed mail server then reports `ERROR SSLCertVerificationError` in APIKEYS (user visible). The actual alert sender (Phase 17, paused) is not built yet; do the same there.
- Deployment: `main.py` has no global request-size limit (not my file). Over loopback this is fine; with the Docker image binding 0.0.0.0 a reverse proxy or an ASGI middleware should cap bodies. `api.json_object` now caps its own routes at 4 MB.

## Unverified (needs full gate / bench)
- Full pytest, Playwright and bench were not run (brief). The uvicorn-handler filter was tested with a stand-in logger named `uvicorn.error`, not a live `uvicorn.run`.
