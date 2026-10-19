# Review: backend-compute (agent 3)

Scope: `bt/`, `quant/`, `quantjobs/`, `quantlib/`, `quant_routes.py`, `jobs/`, `research/`, `valuation/`, `options/`, `derivs/`, `rates/`, `secf/`.
Read closely: `jobs/*` (runner, worker, store, kinds), `bt/store.py`, `bt/job.py`, `bt/frames.py`, `bt/limits.py`, `quantjobs/common.py`,
`quant_routes.py` (`_bars`, data-file writing), the BT routes in `api.py` (read only, not my area). Not audited line by line: `quantlib/`,
`quant/`, `valuation/`, `options/`, `rates/`, `secf/`, the individual `quantjobs/*` bodies (pure maths, no sign of leaks or server-side heavy imports).

## Fixed
| Commit | Finding | Test (`backend/tests/test_review_backend_compute.py`) |
|---|---|---|
| d0204cd | `JobRunner.submit`: two identical submits racing through the `await store.done_by_hash` both started a job (duplicate work, two ids). Now re-checks live jobs after the await, and a job that finished but is not yet in the store (`_done`) answers an identical submit as cached. | `test_concurrent_identical_submits_run_once` (failed before), `test_submit_right_after_finish_hits_the_result_not_a_rerun` |
| d0204cd | Reader thread tracked dead workers in a set of `id(w)`. CPython reuses ids after a free, so a replacement worker at a freed address was ignored forever (its results and death never read; the job then hung until its time limit). Now a `Worker.dead` attribute; the set is gone (it also grew without bound). | `test_pool_does_not_key_dead_workers_by_id` (simulates id reuse; failed before), `test_pool_survives_repeated_worker_deaths` (passed before: the real collision is probabilistic) |
| d0204cd | Cancel flag was reset by the worker after it received a task, so a cancel sent right after dispatch could be wiped (only the 2 s hard-kill then stopped it). The server now resets the flag before sending; the worker no longer touches it. | none (timing window of a few ms, not deterministic; existing cancel tests in `test_phase11.py` pass) |
| 47b9b33 | `JobStore.recent` (behind `GET /api/jobs`) selected every column, including each row's result blob. SQLite stores columns in order, so reading `error/created_at/...` after the result walks the blob's overflow pages. Now `NULL` for result plus a covering index `jobs_recent` (created lazily like `jobs_hash`, no migration). | `test_recent_listing_skips_result_blobs_but_keeps_rows` |
| 48cc6f0 | `BtStore.write_data` sweep only looked at `*.msgpack`: a crash between write and rename left `<sha>.<uuid>.tmp` forever. It also raised if a file vanished mid-sweep, failing the request. Both fixed (shared by every quant function: all use `write_data`). | `test_data_sweep_removes_orphan_temp_files_and_survives_vanishing_files` |
| (this batch) | Provider error text embedded in payload notes without `redact()`: HIVG `bars_error`, calc-rate `SOURCE FAILED`, short-volume `reasons`. Adapters with keys already redact, so this is defence in depth; identity on normal text. | none (covered by existing phase13/14 tests staying green) |

## Performance (before/after)
- **`JobStore.recent(50)`**: 50 stored jobs with ~1 MB results each (60 saved). Before: 1070 ms per call (21.3-21.6 s for 20 calls); after only NULLing
  the result: 110 ms; after NULL + covering index: **0.35-0.8 ms per call**. Measured with a throwaway script (aiosqlite, temp DB, no server).
  Real results are usually much smaller (a 10-year BT run is ~100-200 KB), so a typical gain is 10-100x for the jobs panel poll, but the
  cost scaled with the largest stored results (cap 8 MB x 200 rows).

## Checked, no change
- `jobs/__init__.py`, `jobs/kinds.py`, `jobs/worker.py` stay light (stdlib + orjson only); heavy imports are inside each job's `fn`. The
  server-never-imports-pandas/scipy guards are untouched; my only new server import is `redact` (a leaf module).
- Timers: `_finish` cancels every kill timer, `_last_frame` / `_pending_frame` are cleaned on finish; no per-job leak found. Time-limit and
  hard-cancel kills go through `_replace`, which respawns a worker.
- Error text from workers goes through `redact()` in `_on_msg` / `_finish_hooked`.
- BT worker memory cap: one Job Object per worker, created once.

## Left, and why
- **Spawn cost on the event loop**: `_start_pool` spawns up to 4 workers synchronously on the first submit, and `_replace` spawns one after
  every kill/death. `Process.start()` with spawn on Windows blocks the loop for tens of ms each. Moving it to a thread changes startup ordering
  and the reader thread's view of `self.workers`; not done without a measurement on a loaded loop (UNVERIFIED, needs a bench).
- **Old worker's pipes are not closed after kill/death** (`_replace`). The reader thread may still be inside `wait()` on them, and closing a
  connection another thread waits on is unsafe on Windows. They are closed when the object is garbage collected. Risky, left.
- **Worker import cost per spawn**: each worker re-imports `openterm.jobs.kinds` through the `openterm` package `__init__`; pandas/numpy load
  on the first job of each kind in each worker (the cost is paid once per worker, not per run). Prewarming would raise idle memory: a product decision.
- `_bars` in `quant_routes.py` is sequential across the 3-4 fetch phases of RISK (range, 20Y stress, bench). Running them concurrently would
  break the 4 requests/s pacing: left.

## Decisions for user
- `jobs/store.py` KEEP=200 rows x `MAX_RESULT_BYTES` 8 MB allows a 1.6 GB `jobs` table in the worst case, and bt.mc / bt.wf store their whole
  equity curve and trades in `params` as well. In practice results are small. A lower cap (for example 2 MB) or storing bt.mc/bt.wf params
  without the arrays would bound the DB; user-visible (a big result would no longer be cached), so not changed. Risk: more reruns.
