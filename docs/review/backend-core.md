# Review: backend-core (agent 1)

Scope: providers/** (adapters, streaming), router.py, service.py, cache.py, db.py, scheduler.py, main.py, perf.py, ranges.py, ratelimit.py, symbols.py.
Tests: `backend/tests/test_review_backend_core.py` (8 tests, all failed before the fixes except the control; run with `-n 0`).

## Fixed
| Commit | Bug / finding | Test |
|---|---|---|
| b4d7735 | `Hub.subscribe/unsubscribe`: a symbol repeated inside one `sub` frame bumped the upstream ref twice but the client's set once, so the Yahoo/poller subscription leaked until restart. A repeat inside one `unsub` frame raised `KeyError` (and dropped another client's reference first). Both now dedupe the frame. `Poller._last` also kept a price for every symbol ever watched; it now follows the subscription. | `test_duplicate_symbols_in_one_*`, `test_poller_forgets_*` |
| b666f47 | `/ws`: a bare `["ping"]` raised `IndexError` and closed the socket with a traceback. Now ignored. | `test_ws_ping_without_timestamp_*` |
| eb73ca7 | `scheduler.probe_down_providers`: 9 adapters (deribit, futures x3, options_yahoo, ownership, research_yahoo, sec_funds x2) have no `probe()`. Once tripped, the 30 s probe loop hit `NotImplementedError`, which `Router._attempt` counted as a fresh failure (+ a full traceback in the log every 30 s) and which reset the cooldown to up to 300 s each time. They never recovered by cooldown and showed DOWN; as a fallback behind another source they were never tried again. The loop now skips providers without their own `probe()`; their cooldown runs out. | `test_probe_loop_skips_providers_without_a_probe` (+ control: a provider with a probe still recovers) |
| 40bd090 | `DataService.quotes` read the cache one key at a time: each memory miss was a separate SQLite round trip through the aiosqlite thread. New `Cache.get_many` (one `IN (...)` query per 500 keys; same hit/miss accounting and LRU promotion as `get`). | `test_get_many_*` |

## Performance (before/after)
- **`DataService.quotes` cold cache read (2000 symbols, every key only in SQLite):** 526.8 ms before, 11.5 ms after (`Cache.get` loop vs `Cache.get_many`; best of 5, temp SQLite file, no server). Warm memory hits are unchanged (same dict lookups). Script: scratchpad `m2.py`, measured in-process with `asyncio.run`.
- Tried and REJECTED (no gain, so no change): moving `screener_from_body` (7000 rows, 26 ms), `parse_companyfacts` (10 ms on the trimmed AAPL fixture) and the NSE bhavcopy unzip+parse (16 ms per file, 12 per history request) into `asyncio.to_thread`. Measured max event-loop stall: screener 27 ms sync vs 16 ms threaded (the 15.6 ms Windows timer floor), bhavcopy x12 60 ms sync vs 121 ms threaded (GIL contention). Pure-Python CPU holds the GIL either way.

## Checked, nothing to change
- Import cost (`python -X importtime -c "import openterm.main"`, warm): about 1.6 s, almost all FastAPI/pydantic/httpx/apscheduler. Own modules are each under 12 ms. numpy, pandas, scipy and keyring are not imported by the server (only `yaml`).
- `Router` circuit breaker: single-threaded asyncio, no await between read and write of `Health`, so no races. `key_required` correctly does not strike.
- `_once` coalescing and `_swr`: leader/waiter flow and `_inflight` cleanup are correct on errors. Event-loop blocking: no `time.sleep`, `requests`, sync SQLite or file reads in non-test provider code (fixture loading is test-only).
- `perf.py` ring buffer is bounded (4096); `Hub.outbox` bounded (1000); `Client.pending` coalesces.
- SQLite: `cache(key PK)`, `kv(key PK)` are the only lookups here; all hot reads are by primary key. No N+1 in this area.

## Decisions for user
- `backend/openterm/db.py` / `cache.py`: the `cache` table is never pruned. Every history range/interval, news keyword, search string and Form 4 accession adds a row that is overwritten only when the same key comes back, so the DB file grows for ever (history blobs can be hundreds of KB). A prune of rows older than N days at startup would fix it, but it means very old STALE data stops being served when every provider is down, and `f4:` (Form 4 accessions) must be exempt because they are meant to live for good. User-visible, so not done. Needs an index on `cache(stored_at)` too.
- `backend/openterm/providers/yahoo.py:205` (`quotes`) with `rate = (4.0, 8)`, `max_wait = 0.25`: a batch above about 160 symbols (more than 8 spark chunks of 20) fires all chunks at once, the bucket refuses the later ones, `rate_limited` is re-raised, the whole batch fails over to Nasdaq and Yahoo is put in a 5 s+ cooldown. Fix is to raise `max_wait` for Yahoo (queue instead of fail, costs up to a few seconds on big boards) or to throttle chunk issue. Changes latency behaviour, so a decision.
- `backend/openterm/service.py` `_once`: if the leader's task is cancelled, every waiter gets `CancelledError` (looks like their own cancellation). Nothing in the app cancels request tasks today, so not changed; revisit if request timeouts are added.
- `backend/openterm/providers/nse_archive.py` + `world/india_store.py` (not my files): `DayStore.rows()` decodes up to 250 days of msgpack in the event loop on every NSE history call. Cached by the SWR layer for 1 h, so low priority.

## Unverified
- Nothing needing a full gate or the bench. Only targeted runs: `test_review_backend_core.py`, `test_core.py`, `test_streaming.py`, `test_api.py -k quote`, ruff on the touched files.
