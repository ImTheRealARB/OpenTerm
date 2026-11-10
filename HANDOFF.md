# Handoff

Last updated 2026-11-10 (end of session). Everything is merged to `main` (PR #40, merge commit `6d1f172`); start new work
from `main`. The older copies of this file on `claude/gifted-galileo-w6y22a` and `claude/admiring-archimedes-7ibeha` are superseded.

## Resume here

Everything below is on `main` (merged through PR #40 after CI was green: static, pytest, sdk, vitest, e2e, bench). Work on the
session's designated branch and open a PR only when the owner asks.

**Status (2026-11-10, end of session): ALL 13 WORKSTREAMS MERGED TO `main`. Next: the owner pushes tag `v0.1.0` (step 2 below).**
- Gates on the tip: ruff clean, pytest 4005 passed, typecheck + lint clean, vitest 1479 passed, Playwright 354/354, bench 39/39
  (tick to pixel p95 42.2 ms). Docs done: CHANGELOG, ROADMAP, FEATURE_GAP, PERFORMANCE, README badge, RELEASE_NOTES, DESKTOP.
- Local runs in this container need the preinstalled Chromium (`/opt/pw-browsers/chromium`): pass it as `executablePath` in a
  throwaway Playwright config / bench copy. Run e2e with NO backend on :8000 (stale settings there break GUI-mode tests).
  Never `scripts/start` / `npm ci` in a worktree whose `frontend/node_modules` is a symlink: it empties the shared copy.
- Decided 2026-11-10: ORD and JRNL keep their in-panel text boxes (written into DESIGN.md as the only two exceptions).
  NSE MCP presets live-checked with the owner's approval (results in docs/MCP.md): 9 of 10 allowed tools answered, 1 got
  NSE's 403 from the cloud machine.
- **What is left (owner decisions of 2026-11-10, end of session):**
  1. ~~Merge to main~~: done (PR #40).
  2. **First release `v0.1.0`: NOT DONE YET, the owner runs it on their own computer** (any machine with a clone of OpenTerm; the owner moved from the Windows laptop to a MacBook on 2026-11-10).
     A Claude cloud session cannot do this step: its git proxy only accepts pushes to the session's own branch (a tag push
     gets HTTP 403), and its GitHub tools cannot create tags or releases. In Terminal (macOS), PowerShell or Git Bash, inside the OpenTerm folder:
     ```
     git checkout main
     git pull origin main
     git tag -a v0.1.0 -m "OpenTerm v0.1.0"
     git push origin v0.1.0
     ```
     `git pull` first so the tag lands on the merged `main` (commit `6db6c98` or later); `git log --oneline -1` should show
     "Merge pull request #41" or newer. No folder handy? On github.com: Releases -> Draft a new release -> "Choose a tag":
     type `v0.1.0`, "Create new tag on publish", target `main`, then **Publish release** (a draft does not create the tag).
     Either way GitHub Actions runs `release.yml` (Actions tab, workflow "release"): Linux, Windows and macOS builds into a
     DRAFT release (Option A) or into the published one (Option B). The app version is already 0.1.0 in
     `desktop/package.json` and `tauri.conf.json`; `release.yml` refuses a tag that does not match. This workflow has never
     run: check its logs, and if a build fails, paste the error into the next session to fix.
  3. **Updater signing key: later.** `npx tauri signer generate`, then the secrets `TAURI_SIGNING_PRIVATE_KEY` (+ password) in
     GitHub Settings -> Secrets and variables -> Actions. Without it releases build fine but do not self-update.
  4. **NO Apple / Windows signing certificates (owner decision).** OpenTerm is an open-source GitHub project, not an app-store
     app; unsigned installers are fine. Do not add certificate steps or ask again.
  5. **macOS run: later, on the owner's MacBook Air.** `scripts/setup` then `scripts/start` (and optionally the desktop build in
     `docs/DESKTOP.md`); report anything that breaks.
  6. **Paid / keyed live runs: later.** The owner has an OpenCode Go subscription: set `OPENCODE_API_KEY` in `APIKEYS`, then
     `SETTINGS AI PROVIDER OPENCODEGO`, and run AI, AI AUTO, SWARM and AI BT CODE once each against it (record with the
     recorder scripts, label recordings). Kite, Alpaca and IBKR live checks need those broker accounts; until then they stay on
     doc-shaped fixtures.
  7. **HTML feature/command checklist:** lives only on the owner's other laptop; the owner updates it from this branch's
     CHANGELOG entry of 2026-11-10 and `docs/COMMANDS.md`.
- Later items are listed under "Pending (owner decisions, later on 2026-11-10)" below.

## Pending (owner decisions, later on 2026-11-10)

Branch `claude/bold-tesla-0tk2ek` (not merged yet): skill reference translations, the ALPHA speed-up, `docs/ROADMAP_NEXT.md`.

- **Done on this branch:** the 6 Chinese `references/` files of the elliott-wave, harmonic and ichimoku skills are translated
  (`scripts/vibe_skill_overrides/references/`, mapped by `REF_TRANSLATIONS` in `scripts/port_vibe_skills.py`) and appear as
  `## Reference: ...` sections in those playbooks. Regenerate with the Vibe-Trading checkout at `8172827`.
- **Rust port: decided NO.** Server p95 is 0.3-2.5 ms; the time goes to network fetches and browser drawing, and the heavy math
  already runs in numpy/scipy (C/Fortran). Only port a hotspot (Polars or a PyO3 module) if a measured job proves slow.
- **REMIND THE OWNER: desktop app, pending, owner will do it later.** Bundle the backend as a Tauri sidecar so the desktop
  app is one install that starts and stops its own server (today it is the window only). Good companion: tear-off panel
  windows for multiple monitors.
- **Settings sync per-field merge: explained to the owner, waiting for a yes/no.** Today `frontend/src/settings/schema.ts`
  `reconcile()` keeps the whole settings document with the newest `updated_at`, so an edit made on a second device or tab
  in the meantime is lost. A per-field merge keeps both. Only matters with more than one browser/device (remote mode, desktop + browser).
- **Owner moved to a MacBook (2026-11-10).** The Windows laptop's Claude skills, plugins and connectors are not on the Mac. That
  does not change the code or its checks: the rules live in this repo (`DESIGN.md`, `docs/ADDING_A_FUNCTION.md`, this file) and
  the gates run in CI on every PR (static, pytest, sdk, vitest, e2e, bench). Keep merging through PRs so CI runs.
- **Owner, later:** the HTML feature checklist; the OpenCode Go, OpenRouter, broker and NSE MCP live tests (item 6 above).

### Next features: `docs/ROADMAP_NEXT.md`
The 25 features a professional terminal has and OpenTerm lacks (checked against the code: none exist yet), each with a proposed
code, data source, effort, speed rules and the suggested build order (wave 1: link groups, condition alerts, custom columns,
unified calendar). The owner will build these from another laptop; start there. Proposed codes must be checked against real
tickers first (`CAL`, `LINK`, `EPR`, `NOW` are taken).

### Speed audit of the 2026-11-10 work (done in this session)
- Backend start: importing the server takes the same time as before the workstreams (median 521 ms now vs 554 ms on `b8a274a`,
  same machine); scipy, pandas, the PDF/XLSX writers and the alpha zoo are not imported at server start.
- New panels (ORD, JRNL, SYNC, MCP, EXT...) are lazy chunks; the initial bundle grew 1.6 KB (125.2 KB of 400 KB).
- Fixed: `ALPHA FAMILY=ALL` spent about half its time in rolling argmax / argmin / product calling Python once per window
  (Vibe's base.py expects `bottleneck`, which OpenTerm does not ship). Now numpy, applied by the port script
  (`BASE_PATCHES`, `SPEED_PATCHES` in `scripts/port_vibe_alphas.py`), all 435 factors bit-for-bit identical, 29.9 s -> 15.6 s.
- BENCH_RESULT_PLACEHOLDER

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
