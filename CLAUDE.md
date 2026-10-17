# OpenTerm: notes for Claude

Keyboard-first, open-source market terminal (amber on black, command line + tiled panels).
The full spec is the "SUPER PROMPT" the user gave in the first session. Its build plan, budgets and rules
are summarized in [HANDOFF.md](HANDOFF.md). Read HANDOFF.md first: it says what is done and what is next.
All 10 phases are built and on `main`. **Phases 11-19 are in progress on branch `claude/openterm-phases-11-19-a99b2b`**
(Phase 11 done except one OpenRouter recording; next is the Phase 12 spec; HANDOFF.md "Resume here" has the next action and the user's step rules). Phases 6-10 were built in parallel worktrees (since removed): see HANDOFF.md
"How Phases 6-10 were built" and [docs/PARALLEL_BUILD.md](docs/PARALLEL_BUILD.md) if a parallel build is ever repeated.
**Usage rule:** Sonnet subagents only (Opus drains the Pro 5-hour window in minutes), 2-3 at a time. When the
5-hour or weekly plan window reaches 90%, stop all subagents, update HANDOFF.md
so another account can resume, and pause.

## Non-negotiables (from the spec)
- Speed over looks. No shadows, gradients, radii, transitions or web fonts. Color only carries meaning.
- Never fake data. A failure shows STALE / ERR / PROVIDER DOWN with source and age. Test data
  (fixtures, SYNTHETIC) is always labelled on screen.
- Every action works from the keyboard. Mouse is optional.
- Performance budgets are gated by `node scripts/bench.mjs`. A phase is not done if a budget regresses.
  Record before/after numbers in `docs/PERFORMANCE.md`.
- **Zero keys still works; a key unlocks more** (Phase 11 rule change). A function that needs a key shows
  `KEY REQUIRED: set X in APIKEYS` instead of failing. Paid keys are allowed, never required. Never bypass bot checks or captchas.
- Keys live only in env, the OS keyring or `.env` (`keys.py`). Never in the repo, the command line, command history, a URL
  sent to the frontend or any API response; redacted from logs, `/api/perf`, `/api/log`, `/api/sources`, error text and AI traces.
- AI output is model output, not data: every AI panel says `AI · <model> · <time>` and links the tool calls that grounded
  it; an answer that used no tool data says `UNGROUNDED`. Backtests say `HISTORICAL SIMULATION, NOT A FORECAST` with source,
  adjusted vs raw closes, fees and slippage.
- Orders: paper first. Live orders only if the user turns them on, behind a mandate (symbol allowlist, size and daily caps)
  and a kill switch. Order tools never appear in the MCP server or the AI agent.
- Ported code keeps its licence notice in [THIRD_PARTY.md](THIRD_PARTY.md) and names its source file and commit.
- No Bloomberg name, logo or assets. The product name lives in `frontend/src/config.ts` and `backend/openterm/__init__.py`.

## Layout
- `backend/` Python 3.12, FastAPI, httpx (HTTP/2), orjson, aiosqlite (WAL), apscheduler, websockets. Managed by `uv`.
  - `providers/` adapters (yahoo, nasdaq, synthetic, fixtures, `news.py` = rss/yahoo_rss/gdelt, `crypto.py` = coingecko/binance, `sec.py`/`sec_parse.py` = SEC EDGAR, `ownership.py` = Yahoo holders/insiders).
    `router.py` (fallback + circuit breaker), `service.py` (SWR cache, coalescing), `streaming/` (Yahoo protobuf stream,
    poller, hub), `userdata.py` (layouts, command history, watchlists in SQLite), `api.py`, `main.py` (lifespan + `/ws`).
- `frontend/` React 19 + TS + Vite 7. No UI kit and no state library: a tiny store in `state/store.ts`.
  - Function modules in `src/functions/`, registered in `functions/registry.ts` (one file per function).
    `functions/quoteRows.ts` = shared snapshot + live-tick + nav-key logic for every quote grid (Q, WL, boards);
    `functions/Board.tsx` + `boards.ts` = the fixed sectioned boards (WEI, FX, CMDTY) and the FXC cross math.
  - `components/Grid.tsx`: canvas virtualized grid. `chart/ChartView.tsx`: lightweight-charts 5.2.1, indicators in a Web Worker.
  - `state/ticks.ts`: per-frame tick batching. `net/socket.ts`: one WebSocket with refcounted subscriptions.
  - `perf/metrics.ts`: instrumentation, exposed as `window.__openterm_perf` (the bench uses it).
- `scripts/` setup, dev, bench (`.ps1` versions for Windows). `docs/` PERFORMANCE, DATA_LIMITS, ADDING_A_FUNCTION, ADDING_A_PROVIDER.

## Commands (Windows PowerShell 5.1: no `&&`)
```
cd backend; uv run pytest -q; uv run ruff check .   # pytest runs on 4 xdist workers (addopts); -n 0 to debug
cd frontend; npx tsc --noEmit; npx vitest run; npx playwright test
node scripts/bench.mjs          # from repo root; builds, starts servers in fixture+synthetic mode, prints PASS/FAIL
.\scripts\dev.ps1               # backend :8000 + vite :5173 (vite binds to localhost / ::1, use http://localhost:5173)
.\scripts\start.ps1             # user mode: builds frontend if stale, backend serves it on :8000, opens the browser
```
Env flags: `OPENTERM_FIXTURES=1` (replay `backend/tests/fixtures`), `OPENTERM_SYNTHETIC=1` (SYN0000-SYN9999 + tick
stream), `OPENTERM_FIXTURE_LATENCY_MS`, `OPENTERM_DB_PATH`.

## Gotchas learned the hard way
- **React 19 Suspense throttles reveals by ~300 ms.** Don't use `React.lazy`/Suspense for panels. Use `loadModule()` / `loadedModule()` from the registry.
- **Yahoo:** `v7/quote` needs a crumb (401), so quotes come from `v7/spark` + `v8/chart` meta. `quoteSummary` needs the cookie (fc.yahoo.com) + crumb, and `getcrumb` returns **406 if you send `Accept: application/json`**.
- **Stooq is retired:** it serves a JS bot check. Don't re-add it.
- **Windows timers tick at ~15.6 ms.** Drive rates by elapsed time, not sleep counts. Node `fetch` on Windows loopback adds ~16 ms, so the bench gates backend latency server-side via `/api/perf`.
- **Browsers reserve Ctrl+W / Ctrl+T / Ctrl+1..9.** Alt+W and Alt+1..9 are the web bindings.
- **Panel keys:** the focused panel gets unmodified keys first (`keys/panelKeys.ts`). In grids and charts letters are panel keys, so commands start with `/`.
- **Long multi-line bash heredocs containing `'''` or backslashes sometimes fail to parse** in this harness. Write a patch script with the Write tool and run it with `python <file>`.
- **`/api/history` is price bars.** Command history is `/api/cmdhistory`; layouts are `/api/layouts`.
- **Python's `read_text()`/`write_text()` default to cp1252 and CRLF on Windows.** Patch scripts must use
  `encoding="utf-8"` and `write_bytes` (or `newline="\n"`), or they corrupt UTF-8 docs and line endings.
- **A failed heredoc can hang the whole command.** If bash cannot parse it (or the Python inside has `'''`),
  `python -` waits on stdin until the tool timeout. Use the Write tool + `python <file>`, or the Edit tool.
- **Vitest runs in Node (no `window`).** Anything importing `net/api` or `perf/metrics` cannot be unit-tested.
  Keep parsers pure in their own file (`state/layoutState.ts`, `command/watchlistArgs.ts`, `functions/boards.ts`, `functions/newsArgs.ts`).
- **Canvas grids are invisible to the DOM.** `Grid` mirrors the selected row into `.grid .sr` (an a11y live
  region); Playwright asserts on that. It updates on selection or row changes, not on ticks.
- **Fresh worktree:** run `uv sync` (backend) and `npm ci` (frontend) first. npm warns that the esbuild
  postinstall is blocked; builds still work.
- **GDELT is slow and strict** (one call per 5 s, 8-12 s answers, frequent 429). Never call it from tests or probes.
- **SEC EDGAR needs `SEC_USER_AGENT` in env** (default empty; SEC may 403 without it). Never write an address into the repo.
  `providers/sec.py` + `sec_parse.py` (pure parsers) serve FA/FIL/OWN; `ownership.py` (`yahoo_own`) serves HDS/OWN.
- **Playwright port 4173 is shared by every worktree.** If another worktree's preview is up, tests silently hit that build
  (symptom: functions show "NOT BUILT YET"). Check the port is free; run with `CI=1` (PowerShell: `$env:CI='1'`).
- **Backend port 8000 and dev port 5173 are shared by every worktree too.** A second backend fails to bind 8000 and
  the Vite proxy silently talks to whichever worktree's backend is already up. Check the port before previewing.
- **PowerShell 5.1 `Invoke-WebRequest` to `localhost` costs ~2 s** (tries IPv6 `::1` first; uvicorn listens on
  127.0.0.1). Health probes in scripts use `http://127.0.0.1:<port>`, or a 2 s timeout fails every time.
- **The panel tab names the sticky security only when the function uses it** (`needsSecurity`, or bare `N`).
  The security itself stays on the panel, so `GP` after `FRED` still charts the last ticker.
- **Charts with no volume skip the volume histogram** (`ChartView`): zero-height bars drew a flat line on FRED.
- **Don't assert "NOT BUILT YET" in e2e tests**; each phase makes it false for its own functions.
- **Grid cursor below a header row:** call `grid.moveTo(1)` in an effect keyed on the payload (`initialSelected` is clamped to 0 while rows are empty).
- **A lone bench miss (50k-bar chart pan 33 ms, tick-to-pixel NaN / ~52 ms) has been noise;** rerun before investigating.
- **Panel key handlers registered once (`useEffect` with stable deps) must read state through `useLatest`,** never the render's variables
  (PORT's import preview Enter did nothing until fixed). The `.sr` mirror does not refresh when only a dependent quote (an FX leg)
  ticks: assert converted values on the DOM summary (`data-testid=port-summary`).
- **Alerts are evaluated in the frontend** on raw ticks (`onRawTicks` hook in `ticks.ingest`); the status-bar flash replaces the
  "ALRT n" count for 15 s, so do not assert the count right after a trigger. Only Phase 8 adds migrations (6-7: `portfolios`, `alerts`).
- **FXC e2e needed `toPass` retry:** a tick lands on the next frame flush, so re-select the row until the mirrored text updates.
- **Windows is case-insensitive for TS imports:** a panel `CORR.tsx` and a helper `corr.ts` in one folder break `tsc` (TS1149); name helpers
  distinctly (`corrMath.ts`). CORR is a DOM table (canvas grid has no per-cell fills); `.sr` mirrors its cursor cell.
- **CSV export:** `functions/tableExport.ts` `useCsvExport(panelId, () => gridCsv(name, COLUMNS, rows))`; global binding `exportCsv` = Alt+X,
  plus the `E` panel key (`{ panelKey: false }` if the panel already uses E). E / Alt+X while a panel loads says NOTHING TO EXPORT: wait for content in e2e.
- **Screener (`/api/screener`) is the whole US universe as one columnar ~1 MB payload,** filtered in the browser (`eqsFilter.ts`). COMP peers fall back to the
  largest same-industry names in it (`basis: "industry"`). Bars carry an optional `adj` (adjusted close) read from Yahoo `adjclose`.
- **Don't use a ~50 ms TTL in a timing test:** 4 xdist workers on this machine stall longer (`test_stale_while_revalidate` used to flake).
- **Settings:** `settings/schema.ts` (pure defaults/validate), `settings/runtime.ts` (store + localStorage mirror; do not import `net/api`), `settings/sync.ts`
  (GET after paint, last write wins by `updated_at`). Stored in `kv` key `settings`, no migration. Themes are `:root[data-theme=...]` blocks; Grid and
  ChartView re-read CSS vars on `displayVersion`. Keybinding overrides in `keys/overrides.ts`; vim in `command/vim.ts`.
- **`useEffect(() => x?.method())` returns the method's result;** React 19 then throws "destroy is not a function". Use a block body.
- **Panel keys register after the lazy module loads:** a key pressed right after the panel text appears can be lost and type into the command line. In e2e wait until a key visibly works.
- **Panel key handlers must ignore bare modifier keys** (Playwright `Shift+R` sends a `Shift` keydown first). Maximizing a panel remounts it, so panel-local state is lost.
- **vitest blanks CSS imports and there is no `@types/node`:** `themes.test.ts` reads `styles.css` via `process.getBuiltinModule("node:fs")`.
- **Docker (`Dockerfile`, `OPENTERM_STATIC_DIR`) and Tauri (`desktop/`) are written but never built** (no Docker or Rust here).
- **fredgraph.csv hangs on a browser User-Agent; BLS ICS needs a UA with contact info** (403 otherwise). FRED API paths need `FRED_API_KEY`
  and are only fixture-tested; the keyless `fred_csv` / `treasury` / `nasdaq_earnings` / `agency_ics` (BLS + BEA) providers serve Phase 7.
- **`ChartView` captures `writeReadout` in its create-once effect,** so the crosshair readout keeps the first render's data. FRED remounts
  the chart with `key={id:range}`; GP may have the same stale-readout bug.
- **Panel arg changes go through `replaceView(panelId, v => ({...v, args}))`** so ERN/ECO/FRED state survives layout save/load.
- **In Playwright, assert on fetched requests with `expect.poll`:** the `.ph` title changes before the panel's fetch fires.
- **`SETTINGS KEYS` means keyboard shortcuts** (Phase 10). API keys live in the `APIKEYS` panel (Phase 11 spec); a key is typed only in
  its masked field, never on the command line, so it never reaches `/api/cmdhistory`.
- **Tests-first steps mark new tests expected-to-fail** so every suite stays green: pytest `xfail(strict=True)` per step group (`KEYS`,
  `JOBS`, `LLM` in `test_phase11.py`), vitest `it.fails` with a variable-path `import()` (tsc would reject a missing module), Playwright
  `test.fail()`. The build step deletes the markers (and switches vitest to static imports). Strict xfail turns an accidental pass red.
- **`conftest.py` `client` sets `OPENTERM_KEYRING=memory`, `OPENTERM_DOTENV_PATH` (tmp) and `OPENTERM_JOB_WORKERS=2`** and connects
  as `127.0.0.1` (key writes are loopback-only). Tests must never touch the real OS keyring or the repo `.env`.
- **Key store (`keys.py`):** env > keyring > `.env`; `keyring` is never imported at startup (a pinned test checks it); keyring-stored
  keys are applied 2 s after startup in a thread. A keyed adapter must read its key from `app.state.keys` (or be refreshed by
  `on_key_change`), not only from `Settings`, or a key set in APIKEYS does nothing until restart. `KeyStore.set` shadows the builtin
  `set` in the class body: keep `from __future__ import annotations` at the top of `keys.py`.
- **Jobs:** `openterm/jobs/__init__.py` and `kinds.py` are imported by every worker process: keep them free of FastAPI, aiosqlite
  and heavy libraries (import those inside a kind's `fn`). Migration tests that fake an old DB must also `DROP TABLE jobs`.
  Bench job budgets are split like backend latency: the Vite preview proxy adds ~16 ms on Windows, so end to end is INFO.
- **Any app error text goes through `redact()`** (`api.error`, SOURCES `last_error`, key-test detail). New error paths must too.
- **LLM gateway (`openterm/llm/`) is imported on first use** (`api.llm_of`). Prompts and outputs are never logged. In fixture mode
  the Ollama port raises ConnectError (the generic fallback route would answer 200 and fake an `OK`); keep LLM hosts routed explicitly.
- **A session cannot write into another worktree** (hook). Bring the branch here with `git merge --ff-only <branch>` instead.
- **The app's preview tool may still point at an old folder.** Start servers yourself and screenshot via a Playwright script (see HANDOFF.md).

## Conventions
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Commit only when the user says so. The repo has no remote yet.
- LF line endings (`.gitattributes`), except `*.ps1`.
- Tests never hit the network: record fixtures with real responses, and add a route in `providers/fixtures.py`.
