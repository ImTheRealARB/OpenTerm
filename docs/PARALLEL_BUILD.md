# OpenTerm parallel phase build: rules shared by every phase agent

You are one of five agents. Each builds one phase of OpenTerm (Phases 6-10) **in parallel**, each in its own git
worktree. Every worktree starts from commit `4b3814c` (Phases 1-5 done). The lead merges all five branches afterwards, so
**merge-friendliness is a hard requirement**.

## Before you write code
1. Read `CLAUDE.md` and `HANDOFF.md` in your worktree. They are short and hold the non-negotiables, gotchas and decisions.
2. Study one Phase 5 vertical slice end to end as your template, for example:
   backend `providers/crypto.py` → `service.py` → `api.py` `/api/crypto` → `config.yaml` → `providers/fixtures.py` → `tests/test_phase5.py`;
   frontend `net/api.ts` → `functions/CRYP.tsx` (or `MOV.tsx`, `N.tsx`, `WL.tsx`) → `functions/registry.ts` → `e2e/phase5.spec.ts`.
   Match its idioms: SWR envelopes `{data, source, as_of, age_s, stale, fallback_from}`, router fallback + circuit breaker,
   token buckets, TTLs in config.yaml, canvas `Grid`, `.grid .sr` mirror for Playwright, keyboard-only operation,
   STALE / ERR / PROVIDER DOWN states with source + age, never fake data.

## Hard rules
- **Work only inside your own worktree path** (given in your prompt). Never touch other worktrees or the main checkout.
- **Do not commit, do not create branches, do not push.** Leave everything uncommitted in your worktree. The lead commits.
- Free data only. Zero keys must work (a function that truly needs a key shows a clear "needs KEY_NAME" state, and the
  rest of the app still works). Never bypass bot checks or captchas. Respect each source's rate limits.
- Tests never hit the network. Record fixtures from real responses (live network is fine **for recording only**),
  store them under `backend/tests/fixtures/`, and add routes in `providers/fixtures.py`. Large real responses may be
  trimmed to the rows/tags you use; say so in the fixture filename or a comment in `fixtures.py`. Never invent values.
  Fixture format: `{"status", "body"}` (JSON) or `{"status", "content_type", "text"}` (XML/text).
- Write tests alongside the code: `backend/tests/test_phaseN.py` (pytest), vitest for pure parsers/math
  (keep them in files that do not import `net/api` or `perf/metrics`), and `frontend/e2e/phaseN.spec.ts`
  (Playwright, mocked routes like `e2e/phase5.spec.ts`).
- Windows: Python file writes use `encoding="utf-8"` and LF (`newline="\n"`). Avoid long bash heredocs; use the
  Write/Edit tools. PowerShell 5.1 has no `&&`.
- No new heavy dependencies. Small pure-Python / pure-TS code beats a library. If you truly need one, justify it in your notes.

## Merge-friendliness (shared files)
Five branches edit the same registries. Keep every edit to a shared file **additive and localized**:
- `frontend/src/functions/registry.ts`: edit **only the existing lines for your phase's function codes** (add `load`,
  adjust `argsSchema`/`title`). Do not reorder or reformat other lines.
- `backend/openterm/api.py`, `service.py`, `models.py`, `providers/__init__.py`, `providers/fixtures.py`,
  `config.yaml`, `frontend/src/net/api.ts`, `frontend/src/styles.css`, `frontend/src/format.ts`:
  **append** your additions at the end of the relevant list/class/file inside a block that starts with a comment
  `Phase N` (e.g. `# --- Phase 7: macro ---` / `// --- Phase 7 ---`). Do not reformat or move existing code.
  Where an append is impossible (e.g. one line inside an existing dict), change the minimum and mention it in your notes.
- **SQLite migrations are positional** (`db.py` `MIGRATIONS` list). Only Phase 8 adds migrations (it owns list
  positions 6 and 7). Everyone else: no new tables; use the existing `cache` (provider responses) or `kv` table.
- Existing tests that pin the provider set (`test_api.py`) or the migration list (`test_userdata.py`): change only the
  pinned line, and list the change in your notes.
- Do **not** edit `HANDOFF.md`, `CLAUDE.md`, `docs/PERFORMANCE.md` or `README.md`. The lead updates them. You may
  append a section to `docs/DATA_LIMITS.md` / `docs/ADDING_A_FUNCTION.md` for your new sources.
- Write your notes to `PHASE_N_NOTES.md` at your worktree root: what you built, every shared-file edit, data sources +
  their limits, decisions you made, tests written, what you could not finish or verify, gotchas for CLAUDE.md.

## Verification (light: the lead runs the full suite + bench after merging)
At the end, once: `cd backend; uv sync; uv run pytest -q -n 0; uv run ruff check .` and
`cd frontend; npm ci; npx tsc --noEmit; npx vitest run`. Fix failures. **Skip Playwright and the bench**
(the lead runs them after merging; write the e2e spec anyway). If you run out of time, say what is unverified.

## Your final reply
At most 10 lines: status, files added, shared files touched, tests written and whether pytest/tsc/vitest pass,
anything unfinished. The details go in `PHASE_N_NOTES.md`.
