# Gate wall-clock, before and after (Windows, this machine, 2026-10-19, all gates in one `node scripts/gates.mjs` run)

| Gate | before (`main` 1e37af8) | after (`claude/review-all`) |
|---|---|---|
| pytest | 167.3 s (1568 passed) | 117.0 s (1628 passed, +60 review tests) |
| ruff | 4.5 s | 0.5 s |
| tsc | 21.4 s | 6.2 s |
| vitest | 4.8 s | 5.0 s |
| e2e | 130.4 s, **9 failed** (174 passed) | 74.7 s, 183 passed |
| **whole gate** | **167.4 s, FAILED** | **123.3 s, ALL PASS** |

Notes
- The "before" run is `main` in a temporary worktree, run once. Its 9 e2e failures (SOURCES, APIKEYS x3, JOBS, RISK, FACT, GP, command history) are load flakes: the default 10 Playwright workers on this 20-thread machine. Reruns of the failing specs alone pass.
- The branch saw the same flake before the fix (8 failures per run, a different set each run). `frontend/playwright.config.ts` now sets `workers: 4`: 183 pass in 74 s.
- Part of the gate-time change is machine load and cache state (ruff and tsc are not touched by any speed change), so only the e2e worker change and the new test count are attributable. pytest ran faster after, with 60 more tests; do not read that as a speedup caused by this review.
- Dev-loop: `scripts/check.ps1` ran `energyArgs.ts` (tsc + vitest) in 17 s and `test_functions_doc.py` (ruff + pytest) in 2.5 s.
