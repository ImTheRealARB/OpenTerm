# Phase 11 spec: keys, jobs, LLM gateway

Status: **spec written 2026-10-18, waiting for approval.** Tests come next, then code.
Source: [ROADMAP_PHASES_11-19.md](../ROADMAP_PHASES_11-19.md) "Phase 11" and "Rule changes".

## Decisions (proposed defaults; change any of them before the tests step)

Phase 11 decisions:

| # | Decision | Proposed default | Why |
|---|---|---|---|
| A | Function name for API keys | **`APIKEYS`** panel (alias `SETTINGS APIKEYS`) | `SETTINGS KEYS` already means keyboard shortcuts (`SETTINGS KEYS RESET`, Phase 10) |
| B | Where keys are stored | Order of lookup: **process env > OS keyring > `.env`** (repo root, gitignored). New keys are written to the **OS keyring** (`keyring` package: Windows Credential Locker, macOS Keychain, Secret Service). No keyring backend: written to `.env` | Matches the roadmap. Env stays the override so Docker and CI work |
| C | How a key is typed | Only in the `APIKEYS` panel's masked field. **Never on the command line**, so it can never land in command history (`/api/cmdhistory`) | Command history is stored and synced |
| D | Providers listed in `APIKEYS` now | OpenRouter, OpenAI, Anthropic, Finnhub, Alpaca (key id + secret), FMP, FRED, EIA, OpenFIGI, Tradier, Telegram, SMTP. Ollama has no key (base URL only) | The roadmap key table. Each one gets a cheap "test" call; the data adapters come in their own phases |
| E | Job workers | **Own small pool of long-lived worker processes** (not `ProcessPoolExecutor`), `min(4, cpu_count - 1)` workers, started on the **first job** (not at startup) | Cancel can kill one worker and respawn it; `ProcessPoolExecutor` cannot kill one task. Lazy start keeps cold start unchanged |
| F | Job history kept | Last **200 finished jobs** (SQLite migration 8 `jobs`); results larger than 8 MB are not cached | Bounded DB growth |
| G | LLM providers in the gateway | **OpenRouter (default), OpenAI, Ollama** through one OpenAI-compatible client; **Anthropic** through a thin adapter on its Messages API | Anthropic's tool calls and streaming differ from the OpenAI shape |
| H | Daily AI spend cap | **US$1.00 per day** (local date), editable in `APIKEYS` (`SETTINGS AI` arrives in Phase 16) | Safe default for pay-per-use |

Roadmap open decisions (settled here so later phases do not wait; each phase spec can still revisit its own):

| # | Decision | Proposed default |
|---|---|---|
| 1 | Strategy format | Vibe-Trading `SignalEngine` Python contract (`generate(data_map) -> {symbol: Series in [-1, 1]}`) in a sandboxed worker, plus a short rule syntax (`BT AAPL SMA20>SMA50 1D 5Y`) that compiles to it |
| 2 | Default AI model and cap | Default `anthropic/claude-sonnet-5.5` on OpenRouter (strong tool caller), cheaper choice `anthropic/claude-haiku-5.5`; cap US$1.00/day. Model ids are checked against OpenRouter's `/models` list in the Phase 16 spec |
| 3 | Market priority | **US first.** The India cost stack is ported with the `BT` engines (Phase 12) because it is cheap to port; Zerodha sync waits for Phase 18 |
| 4 | Live orders | **Stop at paper trading + read-only sync.** Live orders only if you ask later (Phase 18 step 3) |
| 5 | Paid-key functions (`TRAN`, `SEG`) | **Skip** until you have a paid FMP key; `SEG` uses free SEC XBRL segments where they parse cleanly |

## Rule changes (applied to CLAUDE.md in the "rules" step)
Copied from the roadmap: zero keys still works, a key unlocks more; `KEY REQUIRED` instead of failing; keys only in
env / keyring / `.env`, redacted from logs, `/api/perf`, `/api/log`, error text and (later) AI traces; AI output is
model output, labelled `AI · <model> · <time>`; ported code keeps its licence notice in `THIRD_PARTY.md`.

## 1. Key store (`backend/openterm/keys.py`)
- `KEY_SPECS`: one entry per provider: `name`, `fields` (env var names, e.g. `ALPACA_KEY_ID`, `ALPACA_SECRET`),
  `phase`, `purpose`, `test` (async callable or `None`), `signup` (URL shown in the panel).
- `KeyStore.get(name) -> dict[str, str] | None` with the lookup order in decision B. `set(name, values)`,
  `delete(name)`, `status(name) -> {"name", "present", "source": "env"|"keyring"|"dotenv"|None, "state", "checked_at", "detail"}`.
  `state` is one of `MISSING`, `UNTESTED`, `OK`, `INVALID`, `QUOTA`, `ERROR`.
- A key set by env cannot be changed or deleted from the UI (status says `SET IN ENV`).
- `keyring` is imported on first use, never at startup. Writing to `.env` keeps the other lines and their order,
  writes LF, UTF-8.
- `Settings` keeps its existing `*_api_key` fields; `KeyStore` reads them through the same env names so Phase 7's
  `FRED_API_KEY` keeps working.
- Test calls (no data is shown, only the state): OpenRouter `GET /api/v1/key` (also returns usage and limit),
  OpenAI `GET /v1/models`, Anthropic `GET /v1/models`, Finnhub `/api/v1/quote?symbol=AAPL`, Alpaca
  `GET /v2/account` (paper host), FMP `/stable/quote?symbol=AAPL`, FRED `series?series_id=DGS10`, EIA `/v2/`,
  OpenFIGI `POST /v3/mapping` with one ISIN, Tradier sandbox `/v1/markets/clock`, Telegram `getMe`,
  SMTP `EHLO` + `AUTH` (no mail sent). HTTP 401/403 = `INVALID`, 429 or a quota body = `QUOTA`, other = `ERROR`.
  Exact paths are checked against each provider's docs in the code step.

### Redaction (`backend/openterm/redact.py`)
- `redact(text) -> str` replaces every currently known secret value (length >= 8) with `***` and also masks
  common shapes (`token=`, `apikey=`, `api_key=`, `key=` query values; `Authorization: Bearer ...`; `sk-...`).
- Installed as a `logging.Filter` on the `openterm` logger and on `httpx`/`httpcore` loggers, so URLs with
  query-string keys are masked before they reach the ring buffer or stderr.
- Applied to: every error `detail` returned by the router, `/api/log`, `/api/perf`, `/api/sources`, job error text.
- `/api/keys` never returns a value, only status. No endpoint returns a key. The frontend never receives one.

### API
- `GET /api/keys` -> list of statuses (all specs). `PUT /api/keys/{name}` body `{fields: {ENV_NAME: value}}`
  -> status after an immediate test. `POST /api/keys/{name}/test` -> status. `DELETE /api/keys/{name}`.
- `PUT`/`DELETE` only accept requests from loopback clients (the server binds 127.0.0.1 anyway; this guards the
  Docker case).

### `KEY REQUIRED` state
- New `ErrorKind` `key_required` in the router; HTTP 424 envelope `{"error": "KEY REQUIRED", "key": "FINNHUB",
  "detail": "KEY REQUIRED: set FINNHUB in APIKEYS"}`. A keyed provider with no key raises it instead of a network
  call; the router falls through to the next provider first, and reports `KEY REQUIRED` only when no keyless
  provider can answer.
- Frontend: shared `KeyRequired` line (amber, not red) naming the key and the command; `Enter` on it opens
  `APIKEYS` with that provider selected.
- `SOURCES` keyed rows read from `KeyStore.status` (replaces the `KEYED` / `keyed_status` table; `NOT BUILT`
  stays for providers whose adapter is a later phase).

### `APIKEYS` panel
- Rows: provider, state, source, purpose, phase, last check. `J/K` move, `Enter` edit (masked input per field,
  `Tab` between fields, `Enter` save + test, `Esc` cancel), `T` test, `D` twice delete, `O` open the sign-up page.
- Values are masked as `••••1234` (last 4 chars) only while typing; after save the panel shows state, never
  characters. Paste works.
- Bottom line: AI spend today `US$0.00 / 1.00 cap`, editable with `C`.

## 2. Job runner (`backend/openterm/jobs/`)
- `jobs/pool.py`: `WorkerPool` with N worker processes (spawn context). Each worker has a task pipe and writes
  progress to one shared result queue read by an asyncio reader task. Workers import heavy libraries themselves,
  so the server process never imports numpy/pandas for jobs.
- `jobs/registry.py`: `JOB_KINDS = {"sleep": dummy, ...}`; a kind is a top-level function
  `fn(params: dict, progress: Callable[[float, str], None]) -> dict` plus a `version` string.
  Phase 11 ships only `sleep` (test/demo: `steps`, `step_ms`, optional `fail_at`), labelled `TEST JOB`.
- `jobs/runner.py`: `submit(kind, params) -> job` hashes `sha256(kind, version, canonical params, data fingerprint)`.
  A finished job with the same hash returns at once (`cached: true`). The same hash already running returns the
  running job (coalescing).
- States: `queued`, `running`, `done`, `error`, `cancelled`. Progress `0..1` plus a short message.
- **Cancel:** sets a per-worker shared flag; `progress()` raises `JobCancelled` when it sees it. A job that does not
  stop within 2 s gets its worker terminated and respawned. Both paths end in `cancelled`.
- Time limit per kind (default 300 s) and memory is the OS's; a worker that dies mid-job ends it in `error`
  (`WORKER DIED`) and is respawned.
- Migration 8: `jobs (id TEXT PRIMARY KEY, kind TEXT, hash TEXT, state TEXT, params BLOB, result BLOB, error TEXT,
  created_at REAL, started_at REAL, finished_at REAL)`, index on `hash`. Trimmed to the last 200 finished.

### API and socket
- `POST /api/jobs` `{kind, params}` -> job. `GET /api/jobs` (running + last 50 finished, no results),
  `GET /api/jobs/{id}` (with result), `DELETE /api/jobs/{id}` = cancel.
- `/ws` new server frame: `["J", {id, kind, state, progress, msg, cached}]`, sent to every client, at most 10
  per second per job (the last one always sent). No new client op. The docstring in `main.py` is updated.
- Frontend: `net/jobs.ts` (store of jobs fed by `J` frames, `submitJob`, `cancelJob`, `useJob(id)`); pure
  frame parser in `net/jobFrames.ts` for vitest.

### `JOBS` panel
- Grid: id, kind, state, progress bar (text, e.g. `#####.....  52%`), message, elapsed, cached flag.
- `J/K`, `Esc` or `X` cancels the selected running job, `Enter` opens the job's result view (Phase 11: JSON
  summary), `R` re-runs, `C` clears finished, `E` CSV.
- `JOBS TEST [steps] [ms]` submits a `sleep` job (for users and e2e).
- Status bar shows `JOBS n` while any job runs.

## 3. LLM gateway (`backend/openterm/llm/`)
- `llm/client.py`: `chat(messages, model, tools=None, stream=True, max_tokens, temperature) -> AsyncIterator[Event]`
  where `Event` is `token`, `tool_call` (id, name, JSON args, assembled from streamed deltas), `usage`
  (prompt/completion tokens, cost), `done`, `error`. Uses the app's shared httpx client (HTTP/2), SSE parsing in
  `llm/sse.py` (pure).
- `llm/openai_compat.py` (OpenRouter `https://openrouter.ai/api/v1`, OpenAI, Ollama `http://127.0.0.1:11434/v1`),
  `llm/anthropic.py` (Messages API, `x-api-key`, `anthropic-version` header; tool_use blocks mapped to the same events).
- Cost: OpenRouter usage accounting (`usage: {include: true}`) gives the cost; OpenAI/Anthropic use a price table
  in `config.yaml` (`llm.prices`, per million tokens); Ollama costs 0. Unknown price = cost `null`, and the call is
  refused when a cap is set (`PRICE UNKNOWN`), unless the model is local.
- **Spend cap:** before a call, refuse if `spent_today + max_tokens * price > cap` (`SPEND CAP REACHED`); after,
  add the real cost. Stored in `kv` key `llm_spend:<YYYY-MM-DD>`.
- No AI functions in Phase 11. `GET /api/llm/health` and `SOURCES` rows: `openrouter` / `openai` / `anthropic`
  (`KEY REQUIRED` or the key state), `ollama` (`OK` with model count if `GET /api/tags` answers in 300 ms, else `DOWN`).
- Redaction applies to every request/response logged; prompts and outputs are not logged at all in Phase 11.
- `httpx` timeouts: connect 5 s, read 60 s between chunks.

## 4. `THIRD_PARTY.md`
At repo root: MIT notice for HKUDS/Vibe-Trading and Apache-2.0 notice for the Qlib Alpha158 parts, with a table
"ported file -> source file @ commit `d0db2e3`" (empty in Phase 11, filled from Phase 12). Lists the existing
third-party runtime pieces that need notices (lightweight-charts Apache-2.0 attribution).

## Tests (written first, in the tests step)
Backend (`tests/test_phase11.py`, no network):
- Key store: lookup order env > keyring > `.env` (keyring faked with an in-memory backend); `.env` round-trip keeps
  other lines and LF; env-set keys refuse change/delete; `/api/keys` returns no values (assert the secret string is
  absent from every response body).
- Redaction: a secret set via `PUT /api/keys/finnhub`, then a provider call that logs the URL with `token=<secret>`
  and fails; the secret appears in none of `/api/log`, `/api/perf`, `/api/sources`, the error body, captured
  stderr/log records.
- Key tests: recorded 401 bodies (recorded live without keys) map to `INVALID`; 429 maps to `QUOTA`; success shapes
  built from the providers' docs (marked as such, like Phase 7's FRED API fixtures).
- `KEY REQUIRED`: a keyed-only capability with no key -> 424 envelope with the key name; with a keyless fallback the
  fallback answers.
- Jobs: dummy job streams increasing progress over `/ws` (`J` frames) and finishes; same params -> `cached: true`
  in < 20 ms; concurrent identical submits coalesce; cooperative cancel; hard cancel of a job that ignores the flag
  (worker respawned, next job runs); worker crash -> `WORKER DIED`; migration 8 present; trim to 200.
- Gateway: SSE parser on recorded chunks (text, tool-call deltas split across chunks, `[DONE]`, usage chunk);
  OpenRouter recorded streaming response -> tokens + usage + cost; Anthropic recorded stream -> same events;
  spend cap refuses before the call and adds the real cost after; unknown price refused under a cap; Ollama
  health `DOWN` when nothing listens.
Frontend:
- vitest: `jobFrames.ts` parser, progress text, `KEY REQUIRED` envelope parsing, `APIKEYS` masking helper.
- Playwright `e2e/phase11.spec.ts` (mocked routes + WebSocket): `APIKEYS` lists providers, enter + save a key
  (the typed value is never in the DOM after save nor in `/api/cmdhistory` posts); a function returning 424 shows
  the `KEY REQUIRED` line and `Enter` opens `APIKEYS`; `JOBS TEST` shows progress and `Esc` cancels; `SOURCES`
  shows the LLM rows.

## Recording needs (flagged now)
- The gateway's "recorded-response test" needs one real streamed answer. **OpenRouter key needed for that step**
  (a free `:free` model is enough, cost US$0). Anthropic and OpenAI streams can be built from their docs unless you
  give those keys. Without any key the gateway step stops and asks.
- 401 bodies for the key tests are recorded live with no key (no account needed).

## Performance budgets
- Unchanged: every existing bench budget (cold start must not grow: `keyring`, job pool and LLM modules load lazily).
- New, recorded in `docs/PERFORMANCE.md` and gated in `scripts/bench.mjs`:
  - Job round trip (warm pool): submit to first `J` progress frame painted in `JOBS` < 50 ms.
  - Cached job (same hash): submit to `done` < 20 ms server-side.
  - `APIKEYS` and `JOBS` open: cached-command budget (< 100 ms to paint).
- Measured, not gated: pool cold start (first job), expected 300-800 ms on Windows (spawn).

## Steps (each one a commit)
1. Spec (this file). **Done when you approve it** (or change the defaults above).
2. Tests set: all tests above, failing for the right reason.
3. Key store, redaction, `/api/keys`, `KEY REQUIRED` state, `APIKEYS` panel, SOURCES rows.
4. Job runner, migration 8, `J` frames, `JOBS` panel, bench budgets.
5. LLM gateway + health (needs the OpenRouter key to record).
6. `THIRD_PARTY.md`, CLAUDE.md rule changes, docs (`ADDING_A_PROVIDER.md` keyed section, `DATA_LIMITS.md`), phase verification.
