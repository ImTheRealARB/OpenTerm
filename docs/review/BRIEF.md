# Review sprint brief (shared by all subagents)

Repo: OpenTerm. Worktree: `C:\Users\Asus\Documents\OpenTerm\.claude\worktrees\review-all-436aed`, branch `claude/review-all` (from `main`). Read the root `CLAUDE.md` (rules + gotchas) first. Windows, PowerShell 5.1 or Git Bash; no `&&` in PowerShell. Use absolute paths; do not `cd` out of the worktree.

## Your job
Audit your area for performance problems, bugs, duplicated logic, and (area 9 only) redundant tests. Fix the clear, low-risk findings yourself. Keep every change small and self-contained.

## Hard rules
- **No full gates.** Never run `gates.mjs`, `bench.mjs`, the full pytest suite, Playwright, or anything that binds ports 8000, 5173 or 4173. Run only the single targeted test file for the file you changed:
  - backend: `cd backend; uv run pytest tests/<file>.py -q -n 0`
  - frontend: `cd frontend; npx vitest run <path>` and `npx tsc --noEmit` (tsc is allowed, it is cheap enough once per change batch)
  - lint: `cd backend; uv run ruff check <files>`
- **Bugs:** write a failing test first, then fix. Name the test after the bug. Put new tests in a NEW file (`backend/tests/test_review_<area>.py`, or `<name>.review.test.ts` beside the code); never edit existing test files unless you are agent 9 (test pruning), who is the only one allowed to touch existing tests.
- **Performance changes** need a before/after measurement (micro-benchmark script in your scratchpad or a pytest timing; no servers) and a section "## Performance (before/after)" in your own `docs/review/<area>.md` (what changed, before, after, how measured). The lead merges these into `docs/PERFORMANCE.md`; do NOT edit `docs/PERFORMANCE.md` yourself. No measurement, no change.
- **Risky or user-visible changes are NOT done.** List them in a section "## Decisions for user" in your own `docs/review/<area>.md` (one bullet each: file:line, what, why, risk). The lead merges them into `DECISIONS_FOR_USER.md`; do NOT edit that file yourself.
- Never fake data; failures show STALE / ERR / PROVIDER DOWN. No keys or secrets anywhere. Tests never touch the network; never call GDELT. Any new error text goes through `redact()`.
- Never remove a guard or lower correctness. Never touch `main`. Never edit files outside your assigned area (listed in your prompt): two agents never write the same file.
- Ported Vibe-Trading files stay verbatim (see CLAUDE.md).

## Git (shared worktree, other agents commit at the same time)
- One change per commit, so any commit can be reverted alone.
- Stage and commit only your own paths: `git add <paths>` then `git commit -m "<msg>" -- <paths>` (the `-- paths` form ignores other agents' staged files). End the message with a blank line and `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- If you hit `index.lock`, wait 2 seconds and retry (up to 5 times). Never delete the lock by force while another git command might be running; never `git stash`, `git reset`, `git checkout --`, `git rebase`, or `git pull`.
- After each commit: `git push origin claude/review-all` (retry once on failure; a rejected push means another agent pushed first: just retry).

## Notes and report
- Write findings to `docs/review/<area>.md` (your area slug is in your prompt): what you checked, what you fixed (commit hash + test), what you left and why, anything UNVERIFIED because it needs a full gate or bench. Keep it under 150 lines; commit and push it.
- Your final reply to the lead: at most 10 lines: commits made, tests added, perf numbers, decisions deferred, unverified items.
- Time box: finish within about 20 minutes of wall-clock. Stop launching new work at 15 minutes. Prefer fewer, certain fixes over many speculative ones.
