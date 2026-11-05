# OpenTerm: notes for Claude

Keyboard-first, open-source market terminal (amber on black, command line + tiled panels).
The full spec is the "SUPER PROMPT" the user gave in the first session. Its build plan, budgets and rules
are summarized in [HANDOFF.md](HANDOFF.md). Read HANDOFF.md first: it says what is done and what is next.
**State 2026-11-05 (paused):** `main` (e605b5b) also has Kite Connect as the top Indian source (Upstox was removed), the source hierarchy, AIS, SHIP, PORTS, DBSRCH and the free-data batch. Unmerged work: worktree `map-function-5ea8a7` (MAP, unfinished) and branch `claude/wrapup-f02dcc` (Kite BFO / CDS chains for OMON / CT, Kite `1D` = last session, ticker reconnect tests, README refresh; `main` merged into it, staged and uncommitted in `C:\otwrap`, gates green; left: a clean bench rerun and the README / `docs/PERFORMANCE.md` speed numbers); see HANDOFF.md "RESUME HERE" before doing anything. Child sessions refuse a push/merge relayed by another session; the parent runs `git`/`gh` itself after the user says so.
Phases 1-17 and 19, GUI mode and the strategy editor are DONE and on `main`; the beginner-GUI / bugs / audit / terminal-conventions job (`docs/specs/GUI_SIMPLE_AND_BUGS.md`) and the NEXT_FEATURES job (`docs/specs/NEXT_FEATURES.md`: plain-English commands, header glossary, indicator library, BT sentence builder, templates, chart alerts) are DONE and on `main` too (PR #1 merged 2026-11-05; origin = GitHub repo ImTheRealARB/OpenTerm, now public; last full gate 2026-11-05: pytest 1776, vitest 1020, e2e 297, bench 37/37, see `docs/PERFORMANCE.md`). Open items and what is next: HANDOFF.md "Resume here". **Phase 18 (brokers/orders) stays PAUSED.** Phases 6-10 were built in parallel worktrees (since removed): see HANDOFF.md
"How Phases 6-10 were built" and [docs/PARALLEL_BUILD.md](docs/PARALLEL_BUILD.md) if a parallel build is ever repeated.
**Usage rule:** Opus may orchestrate (plan, review, run gates) with at most 2 Sonnet subagents building; Opus does not build large
changes itself (decided 2026-11-02, `docs/specs/NEXT_SESSION.md`; replaces the 2026-10-19 "Sonnet only" rule). Subagents are Sonnet. Agents are allowed (at most 2 at a time) but run targeted tests only; the main session runs the full gates once per step (output tail only).
Pause at 95% of the 5-hour window when the user asked for unattended work, else at 60%. If the same gate fails twice on the same problem, stop, write the state and
exact next action to HANDOFF.md, commit, and tell the user (they may switch to Opus for that one problem). When the
5-hour or weekly plan window reaches the pause level, stop all subagents, update HANDOFF.md so another account can resume, commit,
and pause.

## Non-negotiables (from the spec)
- Speed over looks. No shadows, gradients, radii, transitions or web fonts (exception: the SETTINGS font presets, bundled in `public/fonts`, declared in `src/fonts.css`, loaded only when selected, `local()` first, `font-display: swap`). Color only carries meaning.
- Never fake data. A failure shows STALE / ERR / PROVIDER DOWN with source and age. Test data
  (fixtures, SYNTHETIC) is always labelled on screen.
- Every action works from the keyboard. Mouse is optional.
- Performance budgets are gated by `node scripts/bench.mjs`. A phase is not done if a budget regresses.
  Record before/after numbers in `docs/PERFORMANCE.md`.
- **Zero keys still works; a key unlocks more** (Phase 11 rule change). A function that needs a key shows
  `KEY REQUIRED: set X in APIKEYS` instead of failing. Paid keys are allowed, never required. Never bypass bot checks or captchas.
  Scope decision 2026-10-19: no paid data APIs get built; the only paid service is OpenRouter (AI layer).
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
cd backend; uv run pytest -q; uv run ruff check .   # pytest: 6 xdist workers, worksteal (addopts); -n 0 to debug
cd frontend; npx tsc --noEmit; npx vitest run; npx playwright test
node scripts/bench.mjs          # from repo root; builds, starts servers in fixture+synthetic mode, prints PASS/FAIL
node scripts/gates.mjs          # all gates: ruff + tsc first (fail fast), then pytest + vitest, then Playwright; per-gate timing; --skip=e2e,pytest --keep-going --parallel (e2e alongside, faster, flaky here) --list
.\scripts\check.ps1            # dev loop: only tests affected by `git diff main` + tsc + ruff on changed files; -DryRun prints the plan, -All = everything, -NoE2e, -Base REF
./scripts/check.sh              # same for bash (--dry-run --all --no-e2e --base REF); both wrap scripts/check.mjs
python scripts/new_function.py FOO --title "..." [--security] [--args "..."] [--dry-run]   # panel + registry entry + vitest stub + docs/FUNCTIONS.md
.\scripts\dev.ps1               # backend :8000 + vite :5173 (vite binds to localhost / ::1, use http://localhost:5173)
openterm                        # after `.\scripts\install-launcher.ps1` once: same as start.ps1 from any terminal (flags -NoBrowser, -Rebuild)
.\scripts\start.ps1             # user mode: npm ci if package-lock.json is newer than node_modules/.package-lock.json, builds frontend if stale, backend (uv run syncs uv.lock) serves it on :8000, opens the browser
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
  ChartView re-read CSS vars on `displayVersion`. Keybinding overrides in `keys/overrides.ts`; vim in `command/vim.ts`. Font: `Settings.font` = a preset name from `settings/fontPresets.ts` (bundled files or a system font) or any installed font's name (`SETTINGS FONT NEXT|<name>`, menu-bar dropdown `font-select`, SETTINGS row), CSS `--font` = `var(--font-user, var(--font-base))`; every DOM and canvas font reads `--font`, so never hardcode a family. A new settings field also needs a validator in `backend/openterm/settings_store.py` (unknown fields are rejected).
- **`useEffect(() => x?.method())` returns the method's result;** React 19 then throws "destroy is not a function". Use a block body.
- **Panel keys register after the lazy module loads:** a key pressed right after the panel text appears can be lost and type into the command line. In e2e wait until a key visibly works.
- **Panel key handlers must ignore bare modifier keys** (Playwright `Shift+R` sends a `Shift` keydown first). Maximizing a panel remounts it, so panel-local state is lost.
- **vitest blanks CSS imports and there is no `@types/node`:** `themes.test.ts` reads `styles.css` via `process.getBuiltinModule("node:fs")`.
- **Docker (`Dockerfile`, `OPENTERM_STATIC_DIR`) and Tauri (`desktop/`) are written but never built** (no Docker or Rust here).
- **fredgraph.csv hangs on a browser User-Agent; BLS ICS needs a UA with contact info** (403 otherwise). FRED API paths need `FRED_API_KEY`
  and are only fixture-tested; the keyless `fred_csv` / `treasury` / `nasdaq_earnings` / `agency_ics` (BLS + BEA) providers serve Phase 7.
- **`ChartView` readout:** `writeRef.current` is reassigned every render (the old stale-readout note no longer applies); FRED still remounts the chart with `key={id:range}`.
  A transferred-buffer / effect-key rewrite of ChartView broke 6 GP e2e tests (reverted, `docs/review/REVERTED.md`): retry it with a browser open.
- **lightweight-charts applies scroll/zoom on its next paint:** `getVisibleLogicalRange()` stays stale until then, so `ChartView.pan/zoom` build on
  `pendingRange` (cleared one frame later). Without it, keys pressed inside one frame were lost on a fast machine (`gp-toggle` e2e).
- **The gate runs e2e after pytest + vitest by default** (2026-11-05, user's decision; `--parallel` = old mode): fully parallel, 1-2 random e2e tests failed per run (each passes alone),
  plus the `eqsFilter` 10k-row timing vitest. A delayed `setTimeout` focus (BT EDIT `CodeBox`) must not refocus after the user pressed Esc.
- **The in-app browser tool's key events differ from a keyboard:** Shift+T arrives as `key: "t"` with Shift, and `+` / `=` arrive as an empty key.
  Check those bindings in Playwright, not through the browser pane.
- **Playwright runs 4 workers** (`playwright.config.ts`): the default 10 flaked 8-9 e2e tests per run on a 20-thread machine, on `main` too. A failing e2e spec is
  worth rerunning alone before suspecting the change.
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
- **BT cross-check values come from Vibe-Trading's own engine** (`scripts/vibe_crosscheck.py`, run in a throwaway venv
  with Vibe's `agent/` on PYTHONPATH; never vendor Vibe into the repo). Its semantics: signals act one bar later at the
  open; US sizes round to 0.01 shares; an open position closes at the last close (with slippage) as `end_of_backtest`.
- **A strict-xfail API test can pass by accident on FastAPI's own 404** for a route that does not exist yet: assert on
  the body (e.g. the symbol in the error), not only the status code.
- **BT jobs:** `bt.run` is an internal job kind (only `/api/bt/run` submits it). The server fetches bars, writes a
  content-addressed data file and passes its path + hash; the job hash leaves out `labels` (they carry data age).
  `JobRunner.on_done["bt.run"]` saves the run to `bt_runs` before the job shows done. Deleting a run forgets its job hash.
- **Never import pandas/numpy in the server process** (`test_server_never_imports_pandas`): `bt.rules` parsing,
  `bt.sandbox.check`, `bt.catalog` and `bt.store` are pure; pandas code lives in `bt.engine`, `frames`, `job`.
- **Ported Vibe files stay verbatim apart from imports and the listed cuts**; their header line names the source file.
  Behaviour changes there break the cross-check tests, which is the point. Lint: only ruff's safe autofixes plus
  `# noqa` (TRY004, BLE001, B023, UP040) where a fix would change Vibe's behaviour; the header's `Changes:` line says so.
- **A new migration needs its tables in the migration test.** One test upgrades from every schema
  version; list the new tables in `TABLES_BY_VERSION` (`test_userdata.py`), or it fails.
- **Test setup:** pytest runs `-n 6 --dist worksteal`; new e2e specs use `openApp()` from
  `e2e/app.ts` (one page load); unmocked e2e requests still reach port 8000, so keep it free while Playwright runs.
- **Tab never reaches a panel:** it is the global next-panel key (`ALWAYS_GLOBAL`). Panel views cycle with another key
  (BT uses `V` / `Shift+V` and `1`-`4`); the `Tab` cases in FA, FIL and MOV are dead code.
- **Big JSON routes must return `Orjson(...)`, not a dict:** FastAPI runs `jsonable_encoder` over a returned dict even with
  `default_response_class=Orjson` (~30 ms for a 10-year equity curve).
- **BT panel:** POST `/api/bt/run` answers with `run_id` (and the stored `run` when cached); `net/jobs.ts` `adoptJob` puts
  the job in the store so `J` frames update it. A done frame can arrive before the POST answer: the job effect handles it.
  `BaseEngine._bar_row` (our addition to the ported engine) caches `df.loc[ts]` per bar; hooks must not mutate rows.
- **Strategy sandbox is defence in depth:** allowlisted imports, no dunder/`format` attribute access, no file or network
  entry points of numpy/pandas, restricted builtins, sockets off in the worker, memory cap via a Windows Job Object.
- **A session cannot write into another worktree** (hook). Bring the branch here with `git merge --ff-only <branch>` instead.
- **The app's preview tool may still point at an old folder.** Start servers yourself and screenshot via a Playwright script (see HANDOFF.md).

- **Vibe-Trading's symbol detector (`bt/engines/hooks.py` `_detect_market`) reads Yahoo-style `BTCUSDT.P`, `BRK-B`, `^GSPC` as China A** (its catch-all).
  Composite runs go through `composite.market_of`, which fails closed. Vibe's crypto `perpetual_strict` mode is not ported.
- **A textarea that stops key propagation also swallows Ctrl+K.** IMPORT and BT EDIT let Ctrl+K through; copy that if you add another text box.
  BT EDIT is CodeMirror 6 (`bt/codeEditor.ts`): only Ctrl/Cmd+K bubbles (Ctrl+S bubbling would also fire the global workspace save); `App.tsx` ignores `defaultPrevented` keys, so CodeMirror's
  mac `Ctrl-k` binding is filtered out of `defaultKeymap`. Import `codeEditor` only via dynamic `import()` (keeps it out of the startup bundle and the BT chunk). Templates: `bt/templates.py`; live check: `POST /api/bt/check`.
  `sandbox.load()` disables sockets for the whole process: tests that load a strategy in-process monkeypatch `sandbox.disable_network`.
  The mocked Playwright suites cannot see this: run the real-backend smoke (build the frontend, `OPENTERM_FIXTURES=1 OPENTERM_STATIC_DIR=frontend/dist`).
- **Bench throttling:** the BT 10-year run (budget 300 ms) reads 230 ms rested and 380-490 ms after several back-to-back bench runs. Rest, then rerun once.
- **Harness quirks:** a `python - <<'EOF'` heredoc containing `'''` fails to parse (write a script file, run it with `python -I file args`); `rm -f` is blocked;
  Python that reads downloaded files runs from another directory with `-I`. `node scripts/gates.mjs` runs ruff + tsc first, then pytest + vitest side by side, then Playwright (ports 4173 and 8000 must be free; it checks).
- **`POST /api/bt/import` takes the CSV as the raw body;** `/api/history` is columnar (`data.t/o/h/l/c/v`), never `data.bars`. A stored symbol shadows a real ticker.
- **`quantlib` is worker-only:** scipy, statsmodels and arch are imported only inside job kinds and tests, never by the server process (`test_server_never_imports_scipy` guards it).
  `openterm/quant/` (Phase 14) stays pure Python.
- **Phase 15 job pattern:** `POST /api/quant/{fn}` (`quant_routes.py`; fn = risk opt attr fact ql alpha regime) parses args, fetches bars (`_bars`), writes a content-addressed data file and submits an internal
  job (`quantjobs/`: `risk.run opt.run attr.run fact.run ql.run alpha.scan corr.regime`); the job never touches the network and returns the Phase 13/14 table payload for `ResearchPanel`.
  A repeat is a cache hit, so benches and tests vary a parameter. Kite lives in `kite/` + `kite_routes.py`.
- **Kite chains and ticker (wrap-up, 2026-11-05):** `derivative_root` covers NFO / BFO / MCX / CDS (`kite/symbols.py` `CHAIN_EXCHANGES`); spot for options = the index (`spot_key`: NFO to NSE, BFO to BSE) or, on MCX and CDS, the nearest future at or after the option's expiry. A `1D` Kite request is the newest IST session only (7-day lookback, then trimmed); `5D` is still 5 calendar days. `KiteTicker._sleep` is the test hook for the reconnect backoff and the reader's done-callback wakes the loop, so a dropped socket sets `status` off OK immediately; tests replace `websockets.connect` (see `test_kite_wrapup.py`).
- **Running e2e / bench while the user's app holds port 8000:** nothing is configurable (`vite.config.ts` proxy, `bench.mjs`, `gates.mjs` hard-code 8000 / 4173). Use throwaway edits on ports 8100 / 4273 and revert them: recipe in HANDOFF.md "Wrap-up job". The bench also needs `OPENROUTER_API_KEY` unset in the shell (409 env_locked otherwise). The grid always mounts an empty `.sr` live region: do not assert `.sr` count 0 for "nothing shown".
- **Kite is read-only with no order surface** (a test scans route paths, tools and module names for `order`, `gtt`, `margins`, holdings). Fixtures: `kite_*_real*.json` are real recordings
  (`scripts/record_kite_live.py`, needs the OS-keyring key and a login made today; rerun it to refresh), `kite_*_docshape.json` are doc-shaped and labelled NOT A RECORDING (the instruments dump the chain tests use, the session answer).
  The REST routes, the ticker and the login callback have run against a real paid key (2026-11-05; the stored login came from the app's own `/api/kite/callback`). Tokens last one trading day (`KITE LOGIN EXPIRED`).
  Derivatives are typed as the exact Kite trading symbol + suffix (`NIFTY26NOVFUT.NFO`, `GOLD26DECFUT.MCX`, `USDINR26NOVFUT.CDS`); BSE scrip codes (`500325.BO`) resolve through the dump's `exchange_token`; `oi` exists only for FUT / CE / PE.
  Tick source `k` = `RT KITE`; `KiteTicker.covers` owns a symbol while the socket is up, so Yahoo's delayed ticks never overwrite it. Live test recipe: start your own backend (`OPENTERM_DB_PATH` in a scratch dir; the key and token come from the keyring), then `/api/quote`, `/api/history`, and a `/ws` `["sub", [...]]`.
- **Yahoo `range=max` is monthly:** history needing daily bars back to 2006 uses `20Y` (`range=20y&interval=1d`). Yahoo's burst limit paces many-symbol fetches inside `_bars`.
- **Bench Phase 15 budgets (5, server-side like BT):** RISK 20 names x 3Y <= 400 ms, PORT OPT HRP and RP 20 names <= 400 ms each, CORR REGIME 20 names <= 300 ms, ALPHA SYN 100 names x 2Y <= 8 s; total 29 with the older 24.
- **Swarm, runs, theses, audit (Phase 16 steps 5-6):** `ai/swarm.py` (presets, roles run one after another, one retry, chair numbers checked against the analysts' notes), `ai/routes_run.py` (swarm, auto, stored runs and replay, `/api/theses`),
  `ai/store.py` (`ai_runs` keeps non-token events for replay with no model call; `theses`), `ai/audit.py` (BT run ids are 16 hex characters, the AI/thesis run ids 12; `ai_ledger` hash chain, written at the final event; hashes and metadata only; `audit_of` rebuilds its log when the DB object changes because tests reuse the app).
  The installed FastAPI wraps routers in `_IncludedRouter`: list paths with `app.openapi()["paths"]`, not `app.routes`. A model answering nothing makes `agent.run` make a second (closing) gateway call: scripted tests need an extra entry.
- **AI (Phase 16):** `openterm/ai/` (tools via in-process ASGI to the app's own routes, agent loop, guard, context, grounding) behind `POST /api/ai/chat` (SSE). Fixture mode replays two recorded OpenRouter turns for ANY question (labelled RECORDED);
  tests inject a scripted gateway (`FakeGateway` in `test_phase16_agent.py`). The default model `deepseek/deepseek-v4-pro` is a reasoning model: give it >= 400 output tokens or it answers nothing. The bench sets a fake key into a memory keyring (`OPENTERM_KEYRING=memory`).
  A job-based tool (`quant`, `backtest_run`) cannot be probed from a bare script on Windows (worker spawn re-imports `__main__`: guard with `if __name__ == "__main__"`).
- **Inputs inside a panel (AI question box) must let Ctrl/Alt/Meta chords bubble** (`if (!e.ctrlKey && !e.altKey && !e.metaKey) e.stopPropagation()`), or Ctrl+K stops working there and the next command is typed into the box.
  `AI DOC` documents are in memory only (`app.state.ai_docs`, last 5); the filing text path is only unit-tested (fixture mode has no filing documents).
- **Command line keeps focus after a run:** in a manual or browser-driven check press `Esc` before a panel key (`Enter`, `A`, `J`); Playwright's `keyboard.press` already lands on the panel.
  `ResearchPanel` `onKey(e, props, data, say, row)` gets the selected row as 5th argument (ALPHA Enter shows the row's `info`: ported module docstring + inputs).
- **Manual smoke without keys:** `OPENTERM_DB_PATH=<temp>` keeps the user's DB out; portfolio positions are `{symbol, qty, cost}` (`PUT /api/portfolios/<name>`), not `quantity`/`avg_cost`.

- **Phase 19 (done, spec `docs/specs/PHASE_19.md`; new pure code in `backend/openterm/world/`: `energy.py weather.py commodity.py pred.py cryptodepth.py crypto.py india*.py`; the PRED agent used `SRC=` filter; fixtures for NRG / WETR / PRED / crypto / India recorded by `record_phase19.py 6|7|8|9`; crypto panels share `functions/cryptoLoad.ts`):** new backend routes live in `world_routes.py` (`/api/world/...`) with pure code in `backend/openterm/world/` (`tickbuf.py`); drawings in `drawings.py` (kv `drawings:<SYMBOL>`). Frontend: `chart/studies.ts`, `chart/patterns.ts`, `chart/drawings.ts`, `functions/gpArgs.ts`, `seasMath.ts`, `treemap.ts`, `imapData.ts`, `imapPaint.ts`, `gipArgs.ts`.
  `ChartView` takes `draw`, `events`, `comparePanes`; it publishes gauges `chart.extraSeries / markers / events / drawSegs` that e2e reads (canvas is invisible to the DOM). `PERF CALC` feeds the Phase 19 bench lines. Shared e2e helpers: `frontend/e2e/p19util.ts`. Recorder: `scripts/record_phase19.py <step>`.
  `config.yaml` `providers:` OVERRIDES `DEFAULT_ORDER` per capability: a new provider for an existing capability (`history`) must be added there too. On Linux cloud sessions the pinned Playwright wants a newer headless shell than `/opt/pw-browsers` has: point `PLAYWRIGHT_BROWSERS_PATH` at a scratch dir with a `chromium_headless_shell-<rev>/chrome-headless-shell-linux64/chrome-headless-shell` symlink to the installed one.
  Tool gotchas: the Bash tool cannot parse heredocs containing `'''` (use the Write tool + `python file.py`); the PowerShell tool keeps its cwd between calls (use absolute `Set-Location`).

- **Source hierarchy (2026-11-05, `docs/DATA_SOURCES.md`):** the order sources answer in for `quotes` and `history` is ONE table, `providers/hierarchy.py` (`HIERARCHY`, best first, each entry records covers / depth / freshness / limits / why; `test_hierarchy.py` insists the reasons are filled in); `main.py` builds `order` from it and `config.yaml` no longer pins those two (a `providers:` pin wins and logs a warning). Router rules: a source whose `supports(cap, symbol)` is false (no key, not covered) is skipped; `ProviderError("depth")` = too shallow (no breaker strike; if every source is too shallow the user gets HTTP 400 `bad_request` with the message). **Intraday depth lives in each provider** (`Provider.intraday_days`, Yahoo's 7/60/730 days in `yahoo.py`; `ranges.normalize` no longer checks it) and `Router.history_limits(symbol)` reports the deepest source that is on. `SOURCES` rows carry `hierarchy` (rank and reasons per capability). To add a source: adapter, `ADAPTERS`, a `Rank`, `KeySpec` + `TESTS` entry in `keys.py`, `on_key_change` + `apply_stored_keys` in `main.py`, and a cache-key tag in `service.history` if it is key-gated.
- **Upstox was removed (2026-11-05):** the owner could not get a token and will pay for Kite instead. **Kite is now the Indian source (2026-11-05):** `providers/kite.py` serves `quotes` and `history`, ranked #1 above Yahoo for `.NS .BO .NFO .BFO .MCX .CDS ^NSEI ^NSEBANK ^BSESN`; a valid OR expired login counts as on (expired raises `login_expired`: no network call, no circuit-breaker strike, `fallback_from` + `fallback_notes` carry `KITE LOGIN EXPIRED`). `Provider.why_down()` is the hook for such reasons. `intraday_days` 4200 (1m: 3650), measured live. Details and timings: `docs/DATA_SOURCES.md`.

- **Data-source batch (2026-11-05):** `SHIP` = PortWatch via `providers/portwatch.py` + pure `world/shipping.py` (capability `shipping_chokepoints`); ArcGIS answers valid requests with a bogus
  `Invalid URL` / `Object reference` error about 2 calls in 3, so only those two messages are retried (`shipping.FLAKY_MESSAGES`), never other errors. Keyed family: `providers/tradeus.py` + `world/{comtrade,bls,bea,census,seriesboard,usdata}.py`
  (`TRADE`, `USMAC`), `providers/{frankfurter,marketaux,companies_house,etherscan}.py` (`UKCO`, `ADDR`). Fixtures named `*_docshape_*` are invented numbers shaped from docs, not recordings; `classify()` in `keys.py`
  also reads bad-key errors that arrive inside an HTTP 200 body (BLS, BEA, Etherscan). See `docs/DATA_SOURCES.md` for what is left.

- **AIS / AISstream (2026-11-05):** `providers/aisstream.py` (+ pure `aisstream_parse.py`, `world/ais.py`, route `/api/world/ais`, panel `AIS`) is a socket-per-request source: one listen of <= 15 s / 5,000 messages, behind an `asyncio.Lock`
  (the account allows 3 connections), `websockets` imported inside functions. Key `AISSTREAM_API_KEY` is sent only in the first WebSocket message; its test is `aisstream.check_key` (run_test branch, not `TESTS`). Built from the docs with no key: fixture
  `ais_stream_docshape.json` is invented ("DOC SHAPE" ships) and labelled DOC-SHAPED. Tests use a real local `websockets.serve` server; measure elapsed time INSIDE the `async with` (leaving it waits for the fake server's handler). The panel's preset list
  (`aisArgs.ts` `AIS_AREAS`) must equal `world/ais.py` `PRESETS` (a pytest reads the TS file). Never `ws.close()` without `close_timeout` after stopping reading: a full client queue never sees the close frame and `close()` waits 10 s.
- **PORTS / DBSRCH (2026-11-05):** PORTS reuses `PortWatchProvider` (capability `ports_activity`; never downloads the whole 1,600-port layer: server-side `outStatistics` for the top 25, or a name/country match for at most 20 ports; ArcGIS first-query latency is 12-33 s, timeout 45 s).
  DBSRCH = `world/dbsearch.py` + `DbnomicsProvider.search_datasets/search_series` (capability `worldstats_search`); OECD/Eurostat/BIS/IMF are reached via DBnomics, not separate adapters. The `DBN_REF` dataset part allows `@`.

## Public repo (2026-11-02)
- The repo is public. `scripts/setup(.ps1)` is the LIGHT install (`uv sync --no-dev`, `npm ci`, about 330 MB); `-Dev`/`--dev` adds test tools and Chromium (about 1.5 GB). `start` scripts use `uv run --no-dev`.
- README is written for beginners (winget/brew install steps, first-five-minutes table, troubleshooting) and leads with the speed table: when `docs/PERFORMANCE.md` numbers change, update the README table.
- Screenshots live in `docs/screenshots/` (2x, 1440x810 CSS px, live data), retaken with `node scripts/screenshots.mjs [name ...]` against a throwaway server on its own port and temp `OPENTERM_DB_PATH` (setup is in the script's header comment; `SEC_USER_AGENT` must look like `Name noreply@example.com` or SEC answers 403 and FA shows PROVIDER DOWN; fresh browser context per shot, or panels pile up from the saved layout). GUI shots must NOT seed `openterm.welcomed`: the starter layout only applies to a first-run user. The README (rewritten 2026-11-05: centered header, per-OS install blocks, full-width screenshots) references workspace, chart, backtest, fundamentals, macro, bt-editor, gui-search, gui-glossary, gui-error-next-step.
- Never write real keys, emails or personal paths into docs or fixtures; history was scanned clean on 2026-11-02.

- **GUI mode (2026-11-02):** `settings.mode` is `terminal | gui`; `normalize`: nothing saved = gui, a saved object without `mode` = terminal, so `diffFromDefaults` always writes `mode: "gui"` and never `terminal`.
  `document.documentElement.dataset.mode` scopes GUI-only CSS (`:root[data-mode="gui"]`, the only place radius and hover are allowed). The GUI shell lives in `frontend/src/gui/`; `App.tsx` keeps one element tree
  (`.app-body` is `display: contents` in terminal) so switching never remounts panels. Every new function needs a category in `functions/categories.ts` (vitest). Toolbar buttons fire the panel's own keys via
  `dispatchPanelKey`; add per-function buttons in `gui/toolbars.ts`. Empty/loading/error states use `components/PanelNote.tsx`. **e2e and bench start in Terminal**: `openApp(page)` seeds localStorage
  `openterm.settings`; use `openApp(page, { mode: "gui", welcome: true })` for GUI tests. A real `OPENROUTER_API_KEY` in the shell makes the bench fail (409 env_locked): run it with the var unset.
- **GUI layout (2026-11-05):** GUI shows panels as browser-style tabs by default (`gui/TabStrip.tsx` in `App.tsx` above `TopBar`, `gui/tabsState.ts`, localStorage `openterm.guiTabs`, "0" = tiles; menu-bar Tiles/Tabs button). `Workspace` renders only the focused panel (`key={focus}`); "+" = `split("v")`. App class is `has-tabs`, never `tabs` (`styles.css` has a flex `.tabs`). Sidebar show/hide: `gui/sidebarState.ts` (`openterm.sidebarHidden`). Both are per-viewer localStorage, not synced settings. `openApp` seeds tabs OFF unless `{ tabs: true }`. The top-bar command line is always visible in GUI. The bottom status bar is hidden by default in GUI (`gui/statusBarState.ts`, localStorage `openterm.statusBarShown`, menu-bar "Status" button); terminal mode always shows it, and it holds the `ModeToggle`. `openApp` seeds it ON unless `{ statusBar: false }`. Logo: `frontend/public/logo.svg` (also the favicon). The status bar toggle and the font dropdown live in the Settings menu (`gui/MenuBar.tsx`, `data-testid` `statusbar-toggle` and `font-select`), not in the bar. README screenshots: `node scripts/screenshots.mjs [name]` against a throwaway live server (see its header).
- **Chart types and candle length (GUI GP toolbar):** `chart/chartTypes.ts` (CANDLE HOLLOW OHLC LINE AREA BASELINE HEIKIN; `settings/schema.ts` keeps its own copy of the list, update both), `chart/heikin.ts` (pure), dropdowns `gp-type` / `gp-interval` in `gui/PanelToolbar.tsx` (`withChartType` / `withInterval` in `functions/gpArgs.ts`). `ChartView` sets `lockVisibleTimeRangeOnResize` so a widened chart refits. Yahoo serves minute bars only for days/weeks, so 1Y + 15 min errors by design. Range keys 1-8 keep the chosen candle length. Minute-candle depth is per source (see the source-hierarchy bullet): the dropdown reads `GET /api/history/limits?symbol=X` through `functions/useHistoryLimits.ts`, labels each length "(up to N days)" and greys out lengths the range cannot use; a clash error (server message "... ONLY AVAILABLE FOR THE LAST N DAYS") offers "Use Auto candles" / "Show 1M instead".
- **Phase 17 (MCP, delivery, brief):** `openterm/mcp/` = hand-written JSON-RPC MCP server (no `mcp` SDK) over the AI tool registry (`ai/tools.REGISTRY` minus `doc_only`, run by `ToolRunner`); `POST /mcp` is
  loopback-only with an Origin guard; `python -m openterm.mcp` is a stdio bridge to it. The word "order" must not appear anywhere in `openterm/mcp/` (a test scans it). Delivery: `openterm/delivery/`
  (kv `delivery` settings, migration 15 `deliveries` log, channels email/telegram/webhook); it is triggered from the existing `/api/alerts/{id}/trigger` and `/api/newsalerts/{id}/trigger` routes on
  `changed: true` (background task, `delivery.spawn`). Tests inject senders via `app.state.delivery_senders`; fixture mode never sends. SMTP always verifies TLS (`delivery/email.smtp_connect`, also used by
  `keys._smtp_check`). Brief: `brief.py` + `brief_routes.py`, kv `brief:last`, apscheduler job id `brief` (`scheduler.schedule_brief`, rescheduled on `PUT /api/delivery`). Desktop notifications were
  already in `command/alerts.ts` (`desktopNotify`, gated by browser permission only). Panels `DLVR`, `BRIEF`. In fixture mode the brief's earnings section shows ERR (no recording for today).
- **Bench baselines on Windows:** a worktree under the scratchpad path breaks Python DLL loads (path too long: `httptools` ImportError). Put a baseline worktree at a short path such as `C:\otbase`.

- **Cloud session facts (2026-11-04):** on a 4-vCPU Linux box run the gate as `node scripts/gates.mjs --e2e-last` (timing tests in vitest/pytest flake
  when every suite runs at once; they pass alone). `bench.mjs` now spawns servers `detached` and refuses to start if 8000/4173 already answer (a leaked backend
  made every second run fail with "served from the cache"). Leftover servers: `ps -eo pid,cmd | grep -E "python3 -m openterm|vite preview"`.
- **Beginner suite:** `frontend/e2e/beginner.spec.ts` asserts <= 4 clicks per task in GUI mode; keep it green when changing the GUI. Glossary terms (`data-term`) must
  have an entry in `gui/glossary.ts` (vitest scans the source). `PanelNote` takes `plain`, `actions`, `onRetry` (GUI only). New GUI user = starter layout (`gui/starterLayout.ts`).
- **Intl.DateTimeFormat per bar is slow** (~4 us): SEAS went 12 -> 46 ms on 10k bars. Keep a UTC fast path when there is no exchange zone (`seasMath.localDay`).
- **Startup bundle (2026-11-05, `vite build` numbers; the 119.5 below came from another measurement, `fb87fcb` reads 118.0 here):** it had grown to 122.2 KB gz because `Panel.tsx` imported `gui/PanelToolbar.tsx` statically (dragging in `gpArgs.ts`, `chart/indicators.ts`, chart types). Now `gui/LazyPanelToolbar.tsx` loads it as its own chunk: 117.08 KB. Never import `PanelToolbar` or `gpArgs` from startup code; `useState(fn)` calls `fn`, store components as `useState(() => fn)`. See HANDOFF.md "Update 2026-11-05". To list what is in the entry chunk, add a throwaway vite plugin that reads `chunk.modules[id].renderedLength` in `generateBundle` (do not commit it).
- **Startup bundle was 119.5 KB gz (2026-11-04):** `vite.config.ts` `modulePreload.resolveDependencies` keeps only CSS deps (lazy chunks load their own imports); THEME/SETTINGS parsing (`settings/commands`), the shortcut sheet, PERF HUD, help drawer, welcome card and tour are lazy chunks (`components/LazyPiece.tsx`, `gui/LazyGui.tsx`, `functions/idlePreload.ts`). In e2e, wait for the visible result (`expect.poll`, `toBeVisible`) instead of reading state right after a command or page load.
- **Terminal grammar:** a sector word after the ticker maps symbols (`command/sectors.ts`); CORP / unmapped GOVT is an error. F5/F11/F12 stay unbound (browser).

## Conventions
- **Keep `docs/FUNCTIONS.md` current:** after any change to `functions/registry.ts`, `keys/keybindings.json` or `keys/keys.ts` labels (or the doc template in `scripts/gen_functions_doc.py`), run `python scripts/gen_functions_doc.py` before committing. `test_functions_doc.py` (pytest, so the gates) fails on a stale doc.
- Commits end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Commit only when the user says so. Remote `origin` is a private GitHub repo; push the working branch after each step.
- LF line endings (`.gitattributes`), except `*.ps1`.
- Tests never hit the network: record fixtures with real responses, and add a route in `providers/fixtures.py`.
