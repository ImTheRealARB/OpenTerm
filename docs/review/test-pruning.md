# Test pruning (agent 9, slug `test-pruning`)

Scope: every backend pytest (804 `def test_` in 52 files, parametrized cases not counted), vitest (437 in 45 files) and Playwright (192 in 25 specs) test, as of this branch.
Method: AST/regex scan for identical test bodies and identical names across files; read the full name list of every file for overlapping behaviour; grep for
`xfail`, `it.fails`, `test.fail()`, `skip`, `fixme`; grep the e2e specs for the dead panel-`Tab` cases named in CLAUDE.md. Playwright and the full pytest suite were not run (brief);
only the one edited backend file was run (`tests/test_phase14.py`, 39 passed, `-n 0`) and `quantArgs.test.ts` (12 passed).
Files named `test_review_*` and `*.review.test.ts` belong to other agents and were not classified or touched.

## Result in one paragraph
The suite is lean. The scan found **zero exact duplicates** (the only identical bodies are the parametrized `heston`/`credit` cross-checks, which read different Vibe case groups) and **zero dead tests**:
the panel-`Tab` cases in FA/FIL/MOV are dead code in the *source* (`FA.tsx`, `FIL.tsx`, `MOV.tsx`), no test exercises them; every e2e `Tab` press is autocomplete or layout-name completion, which is live.
Every `xfail(strict=True)` / `it.fails` / `test.fail()` marker was already removed by its build step; only one dead marker definition and several stale header comments remained. Nothing was removed that saves test time: **time saved: 0 s**.

## Commits
| Commit | What | Time saved |
|---|---|---|
| 1526ed0 | `test_phase14.py`: delete the dead `RATES = xf(...)` strict-xfail marker definition (applied to no test; step 6 landed). File re-run `-n 0`: 39 passed, 14.05 s total, slowest call 0.96 s. | 0 s (no test removed) |
| 5a0aeb2 | Comment-only: header docstrings in 8 backend test files, 3 e2e specs and `quantArgs.test.ts` said "strict-xfail / `test.fail()` / `it.fails` until the step lands"; the markers are long gone. | 0 s |

Logged in `docs/review/REMOVED_TESTS.md` (first row only; the second commit removed no test).

## Classification (KEEP unless stated)
Groups where every test is KEEP are one row. "Overlap checked" means I compared the tests that look alike and they assert different behaviour or different layers.

### Backend (pytest)
| File(s) | Verdict | Notes |
|---|---|---|
| test_adapters, test_api, test_app, test_core, test_streaming, test_userdata, test_phase5, test_phase6, test_phase7, test_phase8, test_phase9, test_phase10 | KEEP all | One behaviour each. `test_userdata` migration tests (`tables_by_version_lists_every_migration`, `migrations_upgrade_a_db_from_every_version`) are protected. |
| test_functions_doc | KEEP (protected) | `functions_doc_is_current`. |
| test_phase11 | KEEP all | Protected: `keyring_is_not_imported_at_startup`, `redact_known_secrets_and_common_shapes`, `secret_never_leaks_into_logs_perf_sources_or_errors`. `status_never_contains_the_value` / `api_keys_roundtrip_without_values` / the leak test overlap in intent but check different surfaces (status JSON, round trip, logs+perf+sources+errors); kept as redaction tests. |
| test_phase12 | KEEP all, 1 doubtful | Protected: `server_never_imports_pandas`. `migration_9_tables` is doubtful, see Decisions. `keyring_is_installed` is a dependency presence check, kept. |
| test_phase12_engines, _export, _import, _validation | KEEP all | |
| test_phase13, _corp, _funds, _iex, _keyed, _newsalerts, _valuation | KEEP all | `_keyed` holds redaction/never-echo-the-key tests (protected). |
| test_phase13_valuation_port | KEEP all | `the_valuation_package_never_imports_numpy_or_pandas` guards the pandas rule. |
| test_phase14, _btopt, _btrun, _quant, _rates, _surface | KEEP all | `_btopt::module_does_not_import_scipy` and `_quant::numerics_are_scipy_free` guard the scipy rule. `heston_matches_vibe` / `credit_matches_vibe` have identical bodies but different parametrized case groups (`heston.` / `credit.`): not duplicates. |
| test_phase15 | KEEP all | Protected: `server_never_imports_the_heavy_math_libraries`. |
| test_phase15_kite | KEEP all | Protected: `kite_has_no_order_surface_anywhere`. |
| test_phase15_quant | KEEP all | |
| test_phase16_agent | KEEP all | Protected: `tools_route_lists_the_registry_without_order_tools`, `history_is_sent_and_system_prompt_forbids_orders_and_demands_citations`. Four loop-guard tests look alike: the two `LoopGuard` unit tests and the two agent-loop tests cover different layers (guard object vs notice + closing round without tools), so none is a duplicate. |
| test_phase16_audit, _doc, _skills, _swarm | KEEP all | `_swarm::the_swarm_routes_expose_no_order_surface` is protected. |
| test_phase19_crypto, _drawings, _energy, _events, _holidays, _india, _macro, _pred, _secf, _ticks | KEEP all | `_pred::no_trading_or_account_surface_exists` protected. `_pred::recording_really_has_json_string_outcomes_and_prices` and `recording_prices_are_dollar_strings` are fixture-shape sanity tests that make the parser tests meaningful; kept. |

### Vitest (45 files)
| File(s) | Verdict |
|---|---|
| All files (bt/, chart/, command/, components/, functions/, keys/, markets/, net/, research/, settings/, state/, csvText) | KEEP all. Same-named test "reports anything else instead of guessing" exists in `derivArgs.test.ts` and `quantArgs.test.ts` but tests two different parsers. No `it.fails` left; `quantArgs.test.ts` header comment refreshed. |

### Playwright (25 specs)
| File(s) | Verdict |
|---|---|
| All specs | KEEP all. Close pairs checked: phase9 `EQS: bad terms and empty results...` vs `EQS: a valid filter with no matches says so` (the second asserts `NO SECURITIES MATCH THE FILTER`, which the first never reaches); phase9 `COMP: a peer whose history fails...` vs `COMP: NO PEERS FOUND...` (different failure paths); phase5 and phase7 `every ... function is listed as ready in HELP` (different function sets); phase13 vs phase11 KEY REQUIRED (different panels / sources). Since Playwright cannot be run here (ports), nothing was removed from e2e on inference alone. |

## Decisions for user
- `backend/tests/test_phase12.py::test_migration_9_tables` (about line 363): asserts `strategies` and `bt_runs` exist after startup. `test_userdata.py::test_migrations_upgrade_a_db_from_every_version` already recreates every table at every schema version, so this is probably redundant. Kept because it is a migration test (protected class) and costs about 1 s of client setup. Remove it if you agree.
- Dead helpers: `def xf(...)` (a strict-xfail marker factory) is now unused in `test_phase13.py`, `test_phase14.py`, `test_phase14_quant.py`, `test_phase15.py`, `test_phase15_kite.py`, `test_phase15_quant.py`. Harmless; left in place as the documented tests-first pattern (CLAUDE.md describes it). Delete them if tests-first markers will not be used again.
- Dead source code (not mine to edit, no test depends on it): the `case "Tab"` branches in `frontend/src/functions/FA.tsx:59`, `FIL.tsx:46`, `MOV.tsx:78` (Tab never reaches a panel, per CLAUDE.md).
- Real time savings in the test suite will not come from deleting tests: the largest costs seen in the one file measured were fixture setup (`test_phase14.py` first test: 3.6 s setup of the recorded-chain fixtures) rather than redundant tests. A full-suite `--durations=25` run (not allowed in this sprint) is the way to find them.

## Unverified
- Playwright specs were not run; only comments changed in them (3 files), no logic.
- The comment-only edits to test_phase11/12/13/14/15 files were checked with `py_compile`, not re-run.
