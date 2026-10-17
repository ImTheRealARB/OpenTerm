# OpenTerm: notes for Claude

Keyboard-first, open-source market terminal (amber on black, command line + tiled panels).
The full spec is the "SUPER PROMPT" the user gave in the first session. Its build plan, budgets and rules
are summarized in [HANDOFF.md](HANDOFF.md). Read HANDOFF.md first: it says what is done and what is next.

## Non-negotiables (from the spec)
- Speed over looks. No shadows, gradients, radii, transitions or web fonts. Color only carries meaning.
- Never fake data. A failure shows STALE / ERR / PROVIDER DOWN with source and age. Test data
  (fixtures, SYNTHETIC) is always labelled on screen.
- Every action works from the keyboard. Mouse is optional.
- Performance budgets are gated by `node scripts/bench.mjs`. A phase is not done if a budget regresses.
  Record before/after numbers in `docs/PERFORMANCE.md`.
- Free data only, zero keys must work. Never bypass bot checks or captchas.
- No Bloomberg name, logo or assets. The product name lives in `frontend/src/config.ts` and `backend/openterm/__init__.py`.

## Layout
- `backend/` Python 3.12, FastAPI, httpx (HTTP/2), orjson, aiosqlite (WAL), apscheduler, websockets. Managed by `uv`.
  - `providers/` adapters (yahoo, nasdaq, synthetic, fixtures, `news.py` = rss/yahoo_rss/gdelt, `crypto.py` = coingecko/binance).
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
- **The app's preview tool may still point at an old folder.** Start servers yourself and screenshot via a Playwright script (see HANDOFF.md).

## Conventions
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Commit only when the user says so. The repo has no remote yet.
- LF line endings (`.gitattributes`), except `*.ps1`.
- Tests never hit the network: record fixtures with real responses, and add a route in `providers/fixtures.py`.
