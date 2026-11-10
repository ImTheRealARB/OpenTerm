# Handoff

Last updated 2026-11-10. Branch with this file: `claude/gifted-galileo-w6y22a` (based on `main` at `b8a274a`).

## Resume here

Live branch: `claude/admiring-archimedes-7ibeha` (main + every patch below that is marked MERGED). Push there only; no PR unless asked.

**Status (2026-11-10, end of session): ALL 13 WORKSTREAMS MERGED** on `claude/admiring-archimedes-7ibeha` and pushed.
- Gates on the tip: ruff clean, pytest 4005 passed, typecheck + lint clean, vitest 1479 passed, Playwright 354/354, bench 39/39
  (tick to pixel p95 42.2 ms). Docs done: CHANGELOG, ROADMAP, FEATURE_GAP, PERFORMANCE, README badge, RELEASE_NOTES, DESKTOP.
- Local runs in this container need the preinstalled Chromium (`/opt/pw-browsers/chromium`): pass it as `executablePath` in a
  throwaway Playwright config / bench copy. Run e2e with NO backend on :8000 (stale settings there break GUI-mode tests).
  Never `scripts/start` / `npm ci` in a worktree whose `frontend/node_modules` is a symlink: it empties the shared copy.
- Left, needs the owner: (1) ORD (3) and JRNL (2) in-panel text boxes vs DESIGN.md "one text box per screen" (keep, or move to
  command-line entry?); (2) the HTML feature/command checklist to update: not found in this repo's branches, GitHub, Drive or
  artifacts, so ask where it is; (3) owner-only: updater signing key + Actions secrets, Apple / Windows certificates, a macOS run,
  first `v*` tag of `release.yml`, real Kite / Alpaca / IBKR / OpenRouter runs, running the two NSE MCP presets (ask first).
- Optional: settings sync per-field merge; Chinese `references/` of elliott-wave, harmonic, ichimoku; bundle the backend as a
  Tauri sidecar.

Setup: `cd backend && uv sync --extra ocr`, `cd frontend && npm ci`. Fixture UI check: `OPENTERM_FIXTURES=1 uv run uvicorn
openterm.main:app --port 8000` + `npx vite preview --port 4180` (proxies `/api`).

Owner's rules for this work (2026-11-10):
- **At most 3 subagents at a time** (Sonnet is fine). Be careful with usage: small batches; stop when the owner says usage is high.
  On reaching ~95% of the 5-hour limit: pause, update this file, give the owner a handoff prompt.
- Do not run third-party MCP server packages (`npx stock-nse-india`, `uvx nse-mcp`) without asking the owner first.
- Commit and push only to the session's designated branch; no PR unless asked.

## What the owner asked for (2026-11-10)

"Finish all the paused or unplanned work", build the things left out on purpose where possible, "all the other stuff" (unverified
builds, doc fixes), and check whether an NSE India MCP server can be added. Answers given:

- **NSE MCP:** yes, through an MCP *client* in OpenTerm (workstream 03). Two candidate servers, both shipped as disabled presets:
  `stock-nse-india` (MIT, github.com/hi-imcodeman/stock-nse-india, `npx -y stock-nse-india mcp`, stdio, ~30 tools) and `nse-mcp`
  (github.com/jugaad-py/nse-mcp on jugaad-data, `uvx nse-mcp`, stdio, ~24 tools). Both unofficial, not affiliated with NSE.
- **Left out on purpose:** web search / URL reading can be built safely and opt-in (09); OCR as an optional extra (08). Still not
  buildable: China A-share skills (no data), transcripts and segments (paid only), `UNLK` unless a free source with fair terms exists (12).
- **Needs the owner, not code:** real Kite and OpenRouter recordings (keys), signed installers (Windows / Apple certificates),
  a macOS run of the scripts.

## Workstreams

Thirteen subagents started on 2026-11-10 and were stopped part-way (owner's request). Each one's work up to that point (committed and
uncommitted, against `b8a274a`) is saved as `handoff/patches/NN-*.patch`. Every patch applies cleanly to `main` on its own. Status is
the last thing each agent reported plus its file list: **verify by running its tests before trusting it.**

| # | Patch | Scope | State when stopped |
|---|---|---|---|
| 01 | `01-phase18-orders` | Phase 18 orders: `backend/openterm/orders/` (mandate, one-time confirm token, kill switch, hash-chained ledger, paper/live decided structurally), Alpaca paper + live, Kite live orders, `ORD` ticket + blotter, fills into PORT; AI never places orders | Backend core, broker adapters, doc-shaped fixtures written; was writing `test_phase18_orders.py`. **Not started:** frontend `ORD`, fills to PORT UI, `docs/specs/PHASE_18.md`, COMMANDS |
| 02 | `02-broker-sync` | Read-only Kite holdings + IBKR Client Portal Gateway (loopback only) sync into PORT; `SYNC` panel. No Alpaca (01 owns it) | Nearly done: backend, frontend, tests written; was about to run ruff and the full suite and commit |
| 03 | `03-mcp-client-nse` | MCP client (stdio + Streamable HTTP), `<data dir>/mcp_servers.yaml`, all servers off until enabled, per-tool allow-list, tools as `<server>.<tool>` in AI/SWARM, results wrapped as untrusted, ledger, order-name refusal, NSE presets | Backend client, routes, AI wiring, fake server and tests written. **Not started:** MCP panel/commands in the frontend, presets text + notice, `docs/MCP.md` client section, THIRD_PARTY entries |
| 04 | `04-jrnl` | `JRNL`: Zerodha / IBKR Flex / Alpaca / generic CSV parsers, FIFO round trips, stats, behaviour diagnostics, shadow account through BT jobs, read-only `journal` AI tool | Backend package and routes written. **Not started:** tests, frontend `JRNL`, docs |
| 05 | `05-sdk-source-pin` | `sdk/python` (`openterm-sdk`, DataFrames with source/as_of in `attrs`) and per-command source pin `SRC=` (no silent fallback when pinned; cache keys include the pin; `SETTINGS SOURCE ...`) | Backend pin + frontend `SRC=` parsing done; was writing vitest. **SDK barely started** (pyproject, errors.py); CI step not added |
| 06 | `06-extensions-hosting` | Extensions (entry points or `<data dir>/extensions/`, off until enabled, providers / read-only AI tools `ext.<name>.` / `/api/ext/<name>/` routes, generic `EXT` panel, example in `examples/extensions/hello/`) and self-hosted remote mode (`OPENTERM_REMOTE=1`, token login, cookies, MCP stays loopback, Caddy compose) | Extensions backend, `EXT` panel, example and tests written. **Remote/hosted mode not started**, no `docs/EXTENSIONS.md` / `docs/HOSTING.md` |
| 07 | `07-keyed-providers` | Twelve Data, Alpha Vantage, Polygon, FMP adapters (KeyedProvider), KEY_SPECS, hierarchy ranks, fixtures, `scripts/record_providers.py` | Adapters (`twelvedata.py`, `keyed_market.py`), fixtures (real ones only from the public `demo` keys) and recorder written. **Not wired** into `ADAPTERS` / `KEY_SPECS` / `hierarchy.py`; no tests; docs rows not updated |
| 08 | `08-ai-extras` | `ai.store_text` (side table, purge keeps the chain valid), optional OCR for AI DOC (tesseract if on PATH), `patterns` AI tool, AI BT SignalEngine code drafts, `AI FILING <SYM> GUIDANCE` / `CHAIN` | store_text, OCR and patterns with tests done. **Not started:** AI BT code drafts, GUIDANCE / CHAIN |
| 09 | `09-web-tools` | Opt-in `read_url` (SSRF guard: resolve and pin public IPs, re-check redirects, caps) and `web_search` (Brave / Tavily keys, optional SearXNG), untrusted wrapping, per-run caps, `SETTINGS AI WEB` default OFF, SWARM coverage computed | Netguard, fetcher, search, keys, settings, frontend settings written. **Not started:** tests (every SSRF refusal), SWARM coverage, `docs/AI_WEB.md` |
| 10 | `10-alpha-zoo` | Port the rest of Vibe-Trading's 478 alphas (data-driven), no-lookahead property test, `docs/ALPHA_SKIPPED.md`, crosscheck script | Large: ~436 factor files, port script, crosscheck, tests, skipped list. **Unverified:** tests not confirmed green, ALPHA job timing before/after not measured, THIRD_PARTY / spec counts not updated |
| 11 | `11-skills` | Port skipped Vibe skills: translate the non-China Chinese ones, map ones whose tools now exist (read_url, web_search, patterns, journal) | Only 6 English translations in `scripts/vibe_skill_overrides/`. **Not started:** port-script changes, regeneration, `docs/PHASE_20_SKIPPED.md` |
| 12 | `12-bt-exports-unlk` | `BT EXPORT` MT5 (MQL5), PDF report, XLSX; `UNLK` research | MQL5, PDF and XLSX exports, frontend and tests written; UNLK researched and written into `docs/DATA_LIMITS.md` (check its verdict). Needs ruff / full-suite run |
| 13 | `13-packaging` | Real Docker build + compose run, Tauri Linux build, Tauri updater + `release.yml`, run the Linux scripts | One Dockerfile change only; the build hit a **Docker Hub pull rate limit**. Tauri not started |

Merge notes: patches 01, 04 and 08 each append a migration to `MIGRATIONS` in `backend/openterm/db.py`; when applying more than one,
keep all of them, one after another. `main.py`, `ai/tools.py`, `registry.ts`, `categories.ts`, `toolbars.ts`, `keys.py`,
`settings_store.py` are touched by several patches; all edits were meant to be append-only, so keep both sides. Run
`python scripts/gen_functions_doc.py` after applying anything that touches the function registry (it regenerates `docs/FUNCTIONS.md`).

## After the workstreams

- Full gates: `uv run ruff check .`, `uv run pytest -q`, `npm run typecheck`, `npm run lint`, `npm test`, `npx playwright test`, then the
  bench (`scripts/bench`), including the tick-to-pixel rerun (last 55-59 ms vs a 50 ms budget).
- Docs: CHANGELOG entry; `docs/ROADMAP_PHASES_11-19.md` (Phases 17/18 status, Phase 19 says "not merged to main", stale);
  `docs/FEATURE_GAP.md` statuses; README benchmark badge says 37/37 while `docs/PERFORMANCE.md` has 39 budgets.
- Optional: settings sync is last-write-wins by `updated_at` (per-field merge would be better).

## Agent brief template (what each subagent was told)

Rules every brief included: read `DESIGN.md` and `docs/ADDING_A_FUNCTION.md` (and `docs/ADDING_A_PROVIDER.md` for data sources); never
fake data (`STALE` / `ERR` with source and age; test data labelled; doc-shaped fixtures say NOT A RECORDING; tests never hit the
network); zero keys still works (`KEY REQUIRED` via `KEY_SPECS`); secrets never reach the frontend, logs, URLs or error text
(`redact.redact()`); keyboard-first; new functions go in `registry.ts`, `categories.ts`, `gui/toolbars.ts`, lazy-loaded; no Python
per-bar loops in hot paths; heavy work in jobs. Run only targeted tests while others share the machine (`uv run pytest -n 2
tests/test_x.py`, `npx vitest run <path>`), then ruff, typecheck, lint and the full backend suite once. Append-only edits in shared
files. Agents do not edit CHANGELOG, README, RELEASE_NOTES, ROADMAP or FEATURE_GAP (the lead does). Commit messages end with the
session's attribution lines; no push from agents. Final report: commit, changelog bullets, tests and results, what is left and why.
