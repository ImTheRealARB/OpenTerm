# Review notes: devloop (agent 10)

Scope: `scripts/**`, `.github/**`, `CLAUDE.md`, `HANDOFF.md`, `docs/ADDING_A_FUNCTION.md`. Nothing was run beyond dry-runs and two tiny real runs of `check.mjs`.

## What changed
| Commit | Change |
|---|---|
| `7f9502b` | `scripts/new_function.py`: scaffolds panel, registry entry, vitest stub, regenerates `docs/FUNCTIONS.md`. |
| `5e107d3` | `scripts/gates.mjs` reworked; shared helpers in `scripts/lib/proc.mjs`. |
| `8268897` | `scripts/check.ps1`, `scripts/check.sh`, planner `scripts/check.mjs`. |
| `7a738ad` | `.github/workflows/ci.yml` follows the same stages. |
| `2ce0c86` | `CLAUDE.md`: stale phase status and pre-merge `test-speedup` wording removed, new commands added. |
| (this one) | `HANDOFF.md`: superseded Resume-here sections folded into one, `docs/ADDING_A_FUNCTION.md`, these notes. |

## check (changed-files runner)
- `check.ps1` and `check.sh` are thin wrappers; the logic is one Node file (`check.mjs`) so the two cannot drift. Flags: `-All/--all`, `-DryRun/--dry-run`, `-Base/--base`, `-NoE2e/--no-e2e`, `-Files/--files` (plan for given paths, used to test the planner).
- Changed files: `git diff --name-only $(git merge-base <base> HEAD)` (working tree included) plus untracked files.
- Backend: import graph of `backend/openterm` (relative and absolute imports, parent `__init__` edges). A test runs when it imports a changed module or something that depends on one, or when its file name contains the changed module's name. Propagation stops at `openterm.main` (it imports everything; otherwise every test that builds the app would run); a change that reaches it adds `test_app.py` + `test_api.py`. Registry / keybinding / `FUNCTIONS.md` / generator changes add `test_functions_doc.py`. `pyproject.toml`, `uv.lock`, `conftest.py`, `openterm/__init__.py` run all of pytest. Changed fixtures run the tests that mention the fixture's name.
- Frontend: import graph over `frontend/src` + `frontend/e2e`, type-only imports ignored. vitest: tests that depend on a change. Playwright: a changed spec, specs importing a changed e2e helper, specs naming a function code whose panel the change reaches (e.g. `energyArgs.ts` -> NRG, WETR -> `phase19g.spec.ts`); if the change reaches `App.tsx` / `main.tsx` (parser, store, api, styles) all specs run. Edges out of `registry.ts` are skipped so one panel does not pull in every other panel. Backend-only changes skip Playwright (its backend calls are mocked). Config files (`package.json`, lockfile, `tsconfig`, `vite.config.ts`) run everything on the frontend side.
- Stages: ruff (changed files only) + tsc in parallel and fail fast, then pytest + vitest in parallel, then Playwright, which first checks ports 4173 and 8000 are free and fails with the reason if not (silent testing of another worktree's build is a known trap). pytest gets `-n 0` when 2 files or fewer (xdist start-up costs more than it saves).
- Proven by dry-runs with `--files=` (energy.py -> 3 pytest files; `energyArgs.ts` -> 1 vitest + 1 spec; `net/api.ts` -> all specs; `docs/x.md` -> nothing; `--all`), and two real runs: `energyArgs.ts` (tsc 14.9 s + vitest 2.4 s) and `test_functions_doc.py` (ruff + pytest 2.5 s).
- Limits (heuristic, so `--all` / `gates.mjs` stay the pre-merge truth): tests that reach a module only through the `client` fixture and a route are found by name only (`test_phase19_energy.py` for `energy.py`); a module nothing imports or names gets a note and the smoke tests only. Dynamic Python imports (`importlib`) and string-built paths are invisible. Core utilities (`redact.py`) correctly select ~33 of 55 test files.

## gates.mjs
- Stage 1 `ruff` + `tsc` in parallel; a failure there skips the heavy suites (printed as `SKIP`; `--keep-going` runs them anyway). Stage 2 `pytest` + `vitest` + `e2e` in parallel (as before, ~2x faster than serial; pytest uses in-process TestClient, no ports). `e2e` is refused up front if 4173 or 8000 is busy. `--e2e-last` starts Playwright after the others for a loaded machine. `--list` prints the plan.
- Same exit codes (0 / 1) and the same per-gate line format and 40-line failure tails; the last line now also lists per-gate wall-clock: `ALL GATES PASS in 61.2 s  (pytest 40.3 s | ruff 2.0 s | ...)`. **Not run** (brief): verified with `--list` only.
- CI: `static` (ruff + tsc) -> `pytest`, `vitest`, `e2e` as parallel jobs -> `bench`. Added `concurrency` (cancel superseded runs) and job timeouts. The YAML parses; it has not run on GitHub.

## new_function.py
- Straightforward, so done. `python scripts/new_function.py FOO --title ".." [--security] [--args ".."] [--phase N] [--dry-run]`. Refuses when the code is in the registry or `FOO.tsx` / `FOO.test.ts` exist (case-insensitive). Writes LF bytes, inserts the entry before the end of the `defs` array, runs `gen_functions_doc.py`. The panel stub says `NOT IMPLEMENTED` and shows no numbers.
- **No keybinding step:** `keys/keybindings.json` holds only global actions; a function has no binding of its own (it is typed by code, panel keys are registered by the panel). Documented in `docs/ADDING_A_FUNCTION.md`.
- Proven in a scratch copy of the tree (real write, doc regenerated, second run refused); the real repo was only dry-run.

## Docs
- `CLAUDE.md`: status paragraph now says Phases 1-16 and 19 are on `main`; removed the "before/after `claude/test-speedup` is merged" wording (merged); Phase 19 bullet "in progress" -> "done"; Commands section lists `gates.mjs`, `check.ps1/.sh`, `new_function.py`. Every non-negotiable and gotcha kept.
- `HANDOFF.md` (513 -> 437 lines): the five superseded "Resume here" sections (Phases 19 evening/steps 1-3, 16, 15, 14, 13) and the stale "Next action" bullets (Phase 12 / 13, "not merged, no remote") replaced by one current "Resume here" with the still-open items carried forward (Kite, keyed adapters, live shapes, Phase 14/13 limits, stale branches). History of Phases 11-12 and 6-10 kept, retitled. Git history has the removed text.

## Decisions for user
- `scripts/gates.mjs` now stops after ruff/tsc failures (use `--keep-going` for the old always-run-all behaviour). Risk: none for correctness; a failing lint no longer shows test results in the same run.
- CI structure change (`ci.yml`): five jobs instead of three; `npm ci` now runs in three jobs (cached by `setup-node`). Risk: more runner minutes; not run on GitHub.
- `HANDOFF.md`: please confirm the listed stale branches (`claude/angry-easley-fc2d86`, `claude/openterm-phase-19-8ad9bb`) may be deleted; I did not touch any branch.

## Unverified
- `gates.mjs` end to end, Playwright stage of `check.mjs`, `check.sh` on Linux/macOS, CI on GitHub (brief forbids running them).
