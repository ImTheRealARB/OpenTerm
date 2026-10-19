# Removed tests and markers (review sprint, agent 9 `test-pruning`)

One line per removal; each has its own commit.

| File | Test / marker | Why redundant | Covered by | Time saved |
|---|---|---|---|---|
| backend/tests/test_phase14.py | `RATES = xf("rates and calculators", 6)` (strict-xfail marker definition, applied to no test) | Stale tests-first marker: step 6 landed long ago and no test uses `@RATES`; nothing was xfail. No test removed. | the RATES/CALC tests in the same file run unmarked (39 passed with `-n 0`) | 0 s (no test removed) |
