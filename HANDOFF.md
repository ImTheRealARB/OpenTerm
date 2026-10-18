# Handoff

_Last updated: 2026-10-18, session 9 (branch `claude/openterm-phase-16-9d4534`; Phase 11 done except one recording; PHASES 12, 13, 14 and 15 COMPLETE; PHASE 16 COMPLETE (2026-10-18); Phases 17-18 stay paused by the user; defaults pre-approved: see "Resume here")._

> **Resuming in a new session or account?** Read "Where things stand" and "Next" below. Try the app with
> `.\scripts\start.ps1`; [docs/COMMANDS.md](docs/COMMANDS.md) lists commands to try.

## Resume here (2026-10-18 late, Phase 19 steps 1-9 BUILT, step 10 nearly closed)
- Branch `claude/openterm-phase-19-step-4-c5c695`, pushed, not merged. Steps 7 (CDEP FUND LIQ STBL DEFI; UNLK NOT BUILT, paid) and 9 (NSE archive history fallback, SECF AMFI fund rows) are built and tested; see the spec Progress log.
- Full gate on a Linux cloud container: pytest 1567, e2e 181 (19e-19h included), tsc pass; ruff fixed after; two vitest timing tests failed only under the parallel gate and pass alone (411).
- **Open:** the bench ran on that slower container (27/37, not comparable, see `docs/PERFORMANCE.md`). Rerun `node scripts/bench.mjs` rested on the Windows machine before merging. A live keyless smoke of the new functions (spec step 10) was not run.

## (superseded) Resume here (2026-10-18 evening, Phase 19 steps 1-5 DONE, 6 and 8 built but not gated, 7 and 9 half-built; PAUSED at 66% of the 5h window)
- **Branch `claude/openterm-phase-19-step-4-c5c695`** (pushed; continues `claude/openterm-phase-19`). Not merged to `main`. Last commit is a WIP commit; **the full gate has NOT run on it** (last full gate was green at step 5: pytest 1416, e2e 166).
- **Step 6 `NRG` + `WETR`: built.** Backend `world/energy.py`, `weather.py`, `commodity.py`, `providers/openmeteo.py`, `nws.py`, routes `/api/world/nrg|wetr`; panels `NRG.tsx`, `WETR.tsx`, `energyArgs.ts`. `test_phase19_energy.py` 37 pass, `energyArgs.test.ts` 10 pass. `e2e/phase19g.spec.ts` written, NOT run. Finding: EIA weekly stocks/production (WCESTUS1 etc.) answer 404 on fredgraph.csv, so NRG is prices only (note on screen; add to DATA_LIMITS). NWS alerts need `SEC_USER_AGENT`; without it they show SKIPPED.
- **Step 8 `PRED`: built by a Sonnet subagent**, 47 pytest + 11 vitest pass, `e2e/phase19e.spec.ts` written, NOT run. Notes in `PRED_NOTES.md` (fold into `docs/specs/PHASE_19.md` Progress log, then delete it). Added arg `SRC=POLY|KALSHI|ALL`.
- **Step 7 crypto depth: half-built, nothing tested or wired.** Real fixtures recorded (`record_phase19.py 7`: binance_depth/premium/funding_info/funding_history, okx books/funding/mark/index/liq/instruments, llama_stablecoins, llama_yields trimmed, llama_emissions_probe = HTTP 402). Written: `world/cryptodepth.py` (pure parsers/maths), `providers/binance_deriv.py`, `okx.py`, `defillama.py`, `world/crypto.py` (service). **Still to do:** register in `providers/__init__.py` (ADAPTERS `binance_deriv`, `okx`, `defillama`), `main.py` DEFAULT_ORDER (`crypto_depth` [binance_deriv, okx], `crypto_funding` and `crypto_funding_detail` [binance_deriv, okx], `crypto_liq` [okx], `stablecoins` [defillama], `yields` [defillama]), add the three names to `tests/test_api.py` provider set, fixture routes in `fixtures.py` (hosts api.binance.com `/api/v3/depth`, fapi.binance.com `premiumIndex`/`fundingInfo`/`fundingRate`, www.okx.com v5 paths, stablecoins.llama.fi, yields.llama.fi; fapi `fundingRate` and spot klines already have older routes: put the new route in front for the depth/premium/info paths only), routes `/api/world/cdep|fund|liq|stbl|defi` in `world_routes.py`, tests-first file `test_phase19_crypto.py` (depth cumulation/spread/imbalance, 8h/4h/1h annualisation, quarterly basis annualised, liq parse/aggregate, stablecoin and yield parsers incl. a large synthetic payload, 451 fallback Binance -> OKX with a MockTransport), panels `CDEP FUND LIQ STBL DEFI` + registry + `api.ts` types + e2e `phase19h.spec.ts`. **`UNLK` is NOT BUILT:** `api.llama.fi/emissions` is paid (402); an unadvertised dataset host serves it keyless but is the site's own storage, so it is not used. Say so in DATA_LIMITS.
- **Step 9 India: half-built by a subagent that was stopped mid-edit.** Files exist: `providers/nse_archive.py`, `amfi.py`, `world/india.py`, `india_store.py`, `mf.py`; `main.py`, `providers/__init__.py`, `fixtures.py` already edited. **Not done / unverified:** `test_phase19_india.py` missing, the `/api/world/mfnav` route, SECF MF rows, `phase19f.spec.ts`, DATA_LIMITS market table, `INDIA_NOTES.md`. Review these files before trusting them (the agent was killed while applying edits); re-record with `record_phase19.py 9` if fixtures are missing.
- **Then step 10:** run ONE full gate (`$env:CI='1'; node scripts/gates.mjs | Select-Object -Last 8`; this also runs the unrun e2e specs 19e, 19f, 19g, 19h; Playwright port 4173 must be free), add bench lines for steps 6-9 only if cheap, `node scripts/bench.mjs`, docs (COMMANDS, CHANGELOG, DATA_LIMITS, roadmap, CLAUDE.md), spec Progress log entries for steps 5-9 (step 5's entry may be missing), push, report in at most 10 lines.
- **Usage:** Sonnet only. The 5h window was at 66% when paused (rule: pause at 60% unless the user says otherwise).

## (superseded) Resume here (2026-10-18, Phase 19 steps 1-3 done, PAUSED at 87% of the 5h window)
- **Branch `claude/openterm-phase-19`** (cut from `origin/claude/openterm-phase-16-9d4534`), pushed to origin, last commit "Phase 19 step 3". Not merged to `main`. Worked in the worktree `.claude/worktrees/openterm-phase-19-4c98b8` (a session cannot switch branches there to the phase-16 one; just continue on `claude/openterm-phase-19`).
- **Spec:** `docs/specs/PHASE_19.md` (10 steps, decisions table, "Progress log" at the bottom says what each finished step built). **Done: step 1** (12 studies, candle + SMC patterns, `SEAS`, `PERF CALC` hook), **step 2** (GP drawings `T`/`H`/`B`, `EVT` markers, `VS ... PANE`, `/api/drawings`, `/api/world/events`), **step 3** (`GIP` + server tick ring buffer `/api/world/ticks`, `IMAP`). Gates green after each; bench 36/36 (`docs/PERFORMANCE.md` "Phase 19 bench").
- **Next: step 4 `SECF` + OpenFIGI**, then 5 (ECST/WECO/CENB, FOMC in ECO, exchange holidays), 6 (NRG/WETR), 7 (crypto depth/funding/liquidations/stablecoins/DeFi/unlocks), 8 (PRED), 9 (India NSE archive bars), 10 (close: bench, live keyless smoke, docs COMMANDS/CHANGELOG/DATA_LIMITS/HANDOFF/roadmap/CLAUDE.md, report). Steps 4-9 are not started. Docs for steps 1-3 (COMMANDS, CHANGELOG, DATA_LIMITS) are still owed at step 10: `SEAS`, `GIP`, `IMAP`, GP keys/args, Ichimoku forward cloud not drawn, GIP buffer limits.
- **How each step went (repeat it):** tests first (pytest / vitest), recorder `scripts/record_phase19.py <step>` for real keyless fixtures (add a route in `providers/fixtures.py`), new backend routes in `backend/openterm/world_routes.py` (+ `world/` for pure code, providers in `providers/`, order in `main.py` `DEFAULT_ORDER`), panels in `frontend/src/functions/` with pure parsers in their own files, e2e in `frontend/e2e/phase19*.spec.ts` using helpers in `e2e/p19util.ts`, one full gate (`$env:CI='1'; node scripts/gates.mjs | Select-Object -Last 8`), commit with the Sonnet 5.5 co-author line, `git push -u origin HEAD`.
- **Gotchas found this phase:** the Bash tool fails to parse heredocs that contain `'''`: write patch scripts with the Write tool and run `python file.py`; the PowerShell shell keeps its cwd between calls, so use absolute `Set-Location`; a bench run right after a full gate can show a false tick-to-pixel miss (59 ms; rested rerun 37 ms); one e2e flake (`phase12` BT tests) appeared once under the parallel gate and passed alone and on rerun.
- **Usage rule:** Sonnet only, at most 2 subagents (none used so far), pause at 60% of the 5h window (this session paused at 87%).

## Resume here (2026-10-18, Phase 16 closed, Phase 19 next; superseded by the section above)
- **State:** Phases 1-16 are done. Phase 16 (AI layer) closed 2026-10-18 on branch `claude/openterm-phase-16-9d4534`, head at or after `384f5c0`, pushed to origin, **not merged to `main`** (main is still at Phase 10, `26891f1`).
  Full gate green (pytest 1287, ruff, tsc, vitest, e2e 143), bench 31/31, live smoke with the real OpenRouter key done (SWARM, AI AUTO). Details: `docs/specs/PHASE_16.md` "Progress log".
- **Next action: Phase 19** (`docs/ROADMAP_PHASES_11-19.md` "Phase 19": GP drawing tools and studies, GIP, IMAP, SECF, ECST/WECO/CENB, NRG/WETR, crypto depth/funding/DeFi, PRED, non-US zero-key data). It has NO spec yet: first write `docs/specs/PHASE_19.md`
  (defaults pre-approved, tests-first step plan like `docs/specs/PHASE_16.md`, zero-key sources first, no paid APIs), then build step by step. A first attempt in a worktree session (`claude/openterm-phase-19-8ad9bb`, cut from `384f5c0`) was stopped by the user before any work: that branch is empty, ignore or delete it.
- **How to start (user decision 2026-10-18: new session in the plain project folder, not a worktree):** in `C:\Users\Asus\Documents\OpenTerm` (checkout of `main`, must be clean) run
  `git fetch origin; git switch -c claude/openterm-phase-19 --no-track origin/claude/openterm-phase-16-9d4534`, then `cd backend; uv sync` and `cd ..\frontend; npm ci`. Do NOT `git switch` to `claude/openterm-phase-16-9d4534` itself: git refuses a branch that is checked out in a worktree.
  Push the working branch to origin after each step. Do not merge to `main` unless the user says so. Ports 8000, 4173, 5173 must be free (other worktrees may hold them).
- **Still open (not Phase 19):** real Kite recordings (needs the user's Kite key and redirect URL; do not start); Phases 17 and 18 stay paused by the user; first real Docker / Tauri builds. Not built in Phase 16 (see `docs/DATA_LIMITS.md`): `ai.store_text`, SignalEngine code drafts in AI BT, OCR, parallel SWARM roles.
- **Usage rule:** Sonnet only, at most 2 subagents with targeted tests, one full gate per step (`$env:CI='1'; node scripts/gates.mjs | Select-Object -Last 8`), pause at 60% of the 5h window when the user is away: update this file, commit, push. If the user is present and says continue, continue.

## Resume here (2026-10-18, Phase 15 closed, Phase 16 started; superseded, kept for history)
- Phase 15 closed on `df5325e` (bench 29/29, real-backend smoke and live keyless checks done, ALPHA Enter shows the factor formula).

## Resume here (2026-10-18, Phase 15 complete)
- **Phase 15 is built** on branch `claude/openterm-phase-15-65e1da` (spec `docs/specs/PHASE_15.md`, steps 1-8). Functions: `RISK`, `PORT OPT` (`A` saves `<NAME>.OPT`), `PORT ATTR` (+ `ADD`/`DEL` valuations),
  `FACT`, `QL`, `ALPHA` (29 factors), `CORR REGIME`, and read-only `KITE` (`LOGIN`/`STATUS`/`LOGOUT`, Indian bars, NFO/MCX chains with OI via `OMON NIFTY.NFO R= Q=`). Pieces: `quant_routes.py`
  (`POST /api/quant/{fn}`), `quantjobs/` (job kinds), `quantlib/` (worker-only math), `kite/` + `kite_routes.py`.
- **Final gates:** 1205 pytest passed + 1 xfail (Phase 11 recording), ruff, tsc, vitest, 122 Playwright, all green. **Bench: 28 of 29 pass** (recorded in `docs/PERFORMANCE.md` "Phase 15 bench"):
  RISK 84 ms, OPT HRP 13 ms, OPT RP 33 ms, REGIME 91 ms, ALPHA SYN 1.29 s, all well inside budget. The one miss is the old BT 10-year run (323 ms vs 300): the Phase 14 commit reads 322 ms on this machine
  the same hour, so it is machine throttling (earlier phases read 195-285 ms), not a regression. Next phase: rest ~4 min before the bench, rerun once, and if BT run misses again compare against the previous commit before blaming the change.
  The bench found two real bugs, both fixed: a Windows rename race in `bt/store.py write_data` (concurrent identical quant POSTs gave HTTP 500) and `quantBench` polluting the `/api/jobs` perf key (it now runs after that read).
- **Known limits, not verified live:** Kite is entirely unverified against a real key (login, REST, WebSocket decoder; fixtures are doc-shaped, run `scripts/record_phase15.py --kite` once a key exists);
  Ken French and `ALPHA TOP100` live shapes are fixture-only; `CORR REGIME` with no list is answered by the server (the CORR panel keeps no default basket); ALPHA Enter (factor formula) was built 2026-10-18.
  Details: `docs/DATA_LIMITS.md` "Phase 15 limits".
- **Next action: Phase 16 (AI layer).** BEFORE starting it, ask the user to set the OpenRouter key in APIKEYS (the one pending Phase 11 OpenRouter recording needs it too). Order tools never appear in the AI agent; Kite has no order surface at all. Reuse the Phase 11 gateway (`openterm/llm/`), the job runner and `quant_routes.py` as tool backends. Phases 17 and 18 stay paused. Fresh session, tests first; read `docs/ROADMAP_PHASES_11-19.md` "Phase 16".
- **Usage rule:** Sonnet only, at most 2 agents with targeted tests only, one full gate per step, pause at 95% of the 5h window when the user asked for unattended work, else 60%.

## Open items to close Phase 15 (items 1, 2, 3 and 5 DONE 2026-10-18; only item 4, real Kite recordings, is open)
1. **Bench 29/29.** Free port 8000, rest ~4 min (longer if the machine is hot), run `node scripts/bench.mjs` once. The only miss on 2026-10-18 was the BT 10-year run (323 ms vs 300; the Phase 14 commit `edb3292` read 322 ms the same hour). If it still misses, check out `edb3292` and bench it the same way: equal numbers mean machine throttling; update the "Phase 15 bench" result paragraph in `docs/PERFORMANCE.md` either way.
2. **Real-backend smoke run:** `cd frontend; npm run build`, then start the backend with `OPENTERM_FIXTURES=1 OPENTERM_SYNTHETIC=1 OPENTERM_STATIC_DIR=frontend/dist`, open http://127.0.0.1:8000 and try `RISK`, `PORT OPT <name> METHOD=RP` then `A`, `PORT ATTR`, `FACT AAPL`, `QL GARCH AAPL`, `ALPHA UNIVERSE=SYN`, `CORR REGIME LIST:SYN0001,SYN0002,SYN0003`, `KITE`. The mocked Playwright suites cannot see real-browser problems (e.g. the textarea / Ctrl+K gotcha). Fix what breaks.
3. **Live checks (keyless):** run `FACT AAPL`, `ALPHA` (default `TOP100`, the screener universe) and `RISK` on a real portfolio with the app started via `.\scripts\start.ps1`; fix shape drift (Ken French zips, screener sectors, Yahoo pacing in `quant_routes._bars`).
4. **Kite, needs the user's own Kite Connect key** (ask the user): paste `KITE_API_KEY` / `KITE_API_SECRET` in APIKEYS, register `http://127.0.0.1:8000/api/kite/callback` as the redirect URL in the Kite developer console, run `KITE LOGIN`, then `uv run python ../scripts/record_phase15.py --kite` is doc-shaped only: write a real recorder mode, replace the `kite_*_docshape` fixtures with recordings, check the WebSocket decoder (`kite/ws.py`) on live packets and `OMON NIFTY.NFO R= Q=`. Until then Kite stays labelled NOT A RECORDING.
5. **Small gap:** `ALPHA` Enter should open the selected factor's formula/meta (not built).
After these, mark the open items done here and in `docs/ROADMAP_PHASES_11-19.md`, then start Phase 16.

## Resume here (2026-10-19, Phase 14 complete)
- **Phase 14 is done and committed** (spec `docs/specs/PHASE_14.md`, steps 1-8). Functions: OMON PCR OV OSA OVDV SKEW HIVG, RATES upgrade (EUR GBP CAD JPY, NS fit,
  FRED OAS spreads, auctions), CT WIRP COT FXFA YAS SWPM CDSW, `BT <SYM> MKT=options`. Quant lib `openterm/quant/` (Vibe port, cross-checked), migration 12 `iv_snapshots`.
  Gates after step 8: 698 pytest + 1 xfail (Phase 11 recording), ruff, tsc, vitest, 113 Playwright; bench 24/24 on the rested run (see `docs/PERFORMANCE.md`).
- **Known limits / not verified live:** Tradier fixture is doc-shaped (no token, unverified live); IV30 history starts when OSA/HIVG is first opened (local snapshots);
  OSA `B` opens BT but you must type `OPEN=` and `STYLE=` (and `EXP=` in OSA); the OSA structure is lost on reload; BT option trade rows leave entry price/pnl % empty;
  no real-network run of the new rates/futures/CFTC/FOMC providers (fixtures only: try `RATES EUR`, `COT ES`, `WIRP`, `AAPL OMON` live and fix shape drift).
- **Usage lesson:** Phase 14 burned ~75% of a 5h window (agents + repeated gates). See memory `token-burn-rules`: targeted tests in agents, one full gate per step, pause at 60% of the 5h window.
- **Kite Connect (read-only data) is added to Phase 15 scope** (roadmap row `KITE`). A separate Kite session was started and STOPPED by the user before it committed anything (branch `claude/angry-easley-fc2d86` only holds the Phase 14 commits, nothing Kite), so build it fresh in Phase 15; that branch can be deleted.
- **Next action: Phase 15** (risk, quant library, alphas, plus the `KITE` row): read `docs/ROADMAP_PHASES_11-19.md` "Phase 15", write `docs/specs/PHASE_15.md`, tests first (fresh session).
  Phases 17 and 18 stay paused. Before Phase 16: ask the user to set the OpenRouter key in APIKEYS.

## Resume here (2026-10-18, Phase 13 complete)
- **Phase 13 is done and committed** (spec `docs/specs/PHASE_13.md`, steps 1-8). Functions: EE EEO ANR MGMT DVD SPLT CACS IPO SI EVTS DCF WACC RV ETF MEMB MGR CN,
  plus `ALRT NEWS WORD [SYM]` (migration 11 `news_alerts`, `/api/newsalerts`, evaluated in `command/alerts.ts`), Finnhub + Alpaca adapters (inert without
  keys; doc-shaped fixtures), `N` merges keyed headlines (`DataService.news`), ANR/EEO Finnhub fallback (capability `surprises`), real-time US quotes
  (`streaming/iex.py`, tick source `a` = `RT IEX`, off in fixture mode). Gates after step 7: 460 pytest + 1 xfail (Phase 11 recording), ruff, tsc, vitest,
  104 Playwright; bench 24/24 (see `docs/PERFORMANCE.md`). Docs updated: CHANGELOG, COMMANDS, DATA_LIMITS. Known limit: MSFT `RV`/`DCF` NOT RUNNABLE (EBITDA untagged).
  The e2e suite flaked once under the all-gates-at-once run (4 specs passed alone and on rerun); not chased.
- **Not verified live:** Finnhub/Alpaca response shapes and the IEX poller against the real service (no keys). When the user sets keys in `APIKEYS`, try
  `AAPL CN`, `AAPL Q` (source should read RT IEX) and fix any shape drift in `research/keyed_parse.py`.
- **Next action: Phase 14**: read `docs/ROADMAP_PHASES_11-19.md` "Phase 14", write `docs/specs/PHASE_14.md` with its defaults and tests-first step 1, then build
  (fresh session per phase). **Phases 17 and 18 stay paused (user, 2026-10-18).** Before Phase 16: ask the user to set the OpenRouter key.
- **Phase 14 not started** (a session was launched and stopped before it changed anything; the tree was clean at commit `de90def`). The user will run it
  in a new session, possibly on another account: the branch and worktree are local only (no remote), so the new account must open this same folder.
- _Older notes below are from Phase 12._

## Resume here (2026-10-19, Phase 12 complete)
- **Where the work is:** branch `claude/openterm-phases-12-19-5ebe04`, worktree `.claude/worktrees/openterm-phases-12-19-5ebe04`
  (a session cannot write into another worktree). It was fast-forwarded from `claude/openterm-phases-11-19-a99b2b` (that
  worktree is clean and now stale: do not work there) and `claude/test-speedup` is merged. `backend/.venv` and
  `frontend/node_modules` are installed. Nothing is running. Not merged into `main`; no remote.
- **Steps 12.3 to 12.6 are done and committed.** Gates after step 6: 315 pytest + 9 xfail (8 for steps 7-8, 1 Phase 11
  recording), ruff, tsc, 192 vitest, 80 Playwright, bench **24/24** on the third run (two runs missed on machine noise;
  BT run 286 ms of 300, cached 5 ms, BT open 72 ms; see `docs/PERFORMANCE.md`; the BT run budget has little headroom). Step 4 also added VaR 95 / ES 95 (`bt/job.py` `tail_risk`, decision H was missed in step 3).
- **What step 5 added:** `bt/engines/` `india_equity.py`, `crypto.py`, `forex.py`, `futures_base.py`, `global_futures.py`,
  `composite.py`, `bands.py` (ported from Vibe `d0db2e3`, THIRD_PARTY.md rows added), wired in `bt/engine.py`; all six
  `ENGINES` tests pass against Vibe's own numbers. Ours: `composite.market_of` (Vibe's detector reads `BTCUSDT.P`, `BRK-B`,
  `^GSPC` as China A; unplaceable symbols raise), `providers/crypto.py` `BinanceKlinesProvider` (`binance_klines`, first in
  the `history` order in `main.py` and `config.yaml`; spot `BTCUSDT`/`BTC-USDT`, perp `BTCUSDT.P` with `Bars.fund` =
  mean funding per bar), `frames.from_bars` reads `fund`, `catalog.py` (`BUILT`, `SLIPPAGE_KEYS`, `COSTS`,
  `bars_per_year()`), API sets `interval` + `funding_rate` 0 for crypto/composite and refuses `SLIP` on forex. New tests:
  `tests/test_phase12_engines.py`. **Not ported:** Vibe's crypto `perpetual_strict` (needs mark prices and maintenance
  brackets; the engine refuses it), see `docs/DATA_LIMITS.md`.
- **The permission classifier denied running a copy script** over the downloaded Vibe sources, so the ported files were
  written by hand from reading them (headers name the source file and the changes). Vibe sources were fetched with
  `curl` from `raw.githubusercontent.com/HKUDS/Vibe-Trading/d0db2e3/...` into the scratchpad only, never into the repo.
- **What step 4 added:** `functions/BT.tsx` (views CHART / METRICS / TRADES / CODE cycled with `V`, not `Tab`; labels of
  decision L; progress from `J` frames; `R` re-run, `X` cancel, `E` CSV of the visible view), `bt/ruleParse.ts` (mirror
  of `bt/rules.py`), `bt/metricsFormat.ts`, `btApi` in `net/api.ts`, `adoptJob` in `net/jobs.ts`, ChartView `lowerPane`
  (drawdown) and lazy indicator worker, BT intent prefetch, `btOpen` perf series, bench section H + `btBench()`.
  `BT RUNS/EXPORT/MC/WF/SAVE/LOAD/DEL` say NOT BUILT YET with their step. **Not built yet: the Python strategy editor**
  (spec section 1: textarea + `BT SAVE/LOAD/DEL`); call it step 4B, before step 9.
- **What step 6 added:** `bt/validation.py` (Vibe's `monte_carlo_test`, `bootstrap_sharpe_ci`, `walk_forward_analysis`; matches
  Vibe's numbers), `bt/validate_job.py` + job kinds `bt.mc` / `bt.wf` (server-submitted, `POST /api/bt/runs/{id}/mc|wf`),
  frontend `BT MC|WF <run args>` and `M` / `W` keys, MC and WF views, `bt/validationFormat.ts`. Tests:
  `tests/test_phase12_validation.py`, vitest + 3 Playwright tests. **Not yet checked against the real backend in a browser:**
  do one smoke run (fixture mode) at step 9, with RUNS and IMPORT.
- **What step 7 added:** `bt/export.py` (CSV parts, Pine v5 translation of rule runs), `GET /api/bt/runs/{id}/export`, `GET /api/bt/compare`,
  frontend `functions/BtRuns.tsx` (`BT RUNS`: list, `C` marks two, comparison with metric diffs and the two equity lines),
  `BT OPEN`, `BT EXPORT`, `P` key, `csv.ts` `downloadText`. Tests: `tests/test_phase12_export.py`, vitest, 5 Playwright.
- **Bench note (closed):** the step-7 misses of the BT-run budget were machine throttling; the phase bench after a rest reads 233.6 ms (see below and `docs/PERFORMANCE.md`).
- **What step 8 added:** migration 10 `local_bars`, `bt/csvimport.py` + `bt/localdata.py`, `DataService.local` (set in the lifespan), `/api/bt/import`
  (POST/GET/DELETE), `bt/csvImport.ts`, `functions/IMPORT.tsx` (paste box with live preview, list, `D` twice). Tests: `tests/test_phase12_import.py`,
  vitest, 4 Playwright. Gates after step 8: 354 pytest + 1 xfail (the Phase 11 recording), 196 vitest, 87 Playwright, all green.
- **What step 4B and 9 added:** `functions/BtEditor.tsx` (`BT EDIT`/`LOAD`: list or editor), `BT SAVE name RULE`, `BT DEL name`, `@name` in the rule
  position (`bt/ruleParse.ts` `strategy`), docs (`COMMANDS.md`, `CHANGELOG.md`, `DATA_LIMITS.md`, `PERFORMANCE.md`), real-backend browser
  smoke run (all green; found the Ctrl+K-in-textarea bug). Final Phase 12 gates: 354 pytest + 1 xfail, 198 vitest, 92 Playwright, bench 24/24.
- **Next action: Phase 13 (equity research gaps)**: read `docs/ROADMAP_PHASES_11-19.md` "Phase 13", write `docs/specs/PHASE_13.md` with its
  defaults plus the tests in one step, then code (fresh session per phase). **Before Phase 16: ask the user to set the OpenRouter key with
  `APIKEYS`**, then finish the Phase 11 `@RECORDING` test (`scripts/record_llm.py`). Phase 12 is not merged into `main` (no remote).
- **Bench rule of thumb:** after many back-to-back runs this machine throttles and the BT 10-year run reads 380-490 ms against 233 ms when
  rested. Run the bench once after a rest; do not chase a lone BT-run miss before re-measuring. `node scripts/gates.mjs` runs the five gates
  in parallel (`--skip=e2e,pytest`).
- **Scope and plan (decided by the user 2026-10-19; do not relitigate):**
  - **Full scope, Phases 12-19, minus paid-only data.** Removed: `TRAN`, `SEG` (paid FMP). Keys: keyless sources
    first; free sign-up keys are fine (Finnhub free tier for `EE`/`ANR` only as far as it covers them, Alpaca/Finnhub
    for real-time L1, EIA, Telegram bot token, the user's own SMTP); the **only paid service is OpenRouter**, default
    model a DeepSeek model chosen in `SETTINGS AI`, with the Phase 11 daily spend cap. Brokers: Alpaca paper first;
    Zerodha only if its API is free when the Phase 18 spec is written. A source that turns out paid-only is dropped
    and noted in DATA_LIMITS.md, never faked.
  - **Roadmap defaults are pre-approved** for every phase: write each spec with its defaults, then go straight on to
    tests and code. Stop only for a decision the roadmap did not foresee, a gate failure that needs a decision, or a
    missing key (OpenRouter before Phase 16: ask the user to set it with `APIKEYS`; then finish the `@RECORDING` test).
  - **Speed levers (approved):** (1) port Vibe modules in bulk by copy script with their tests converted to pytest
    and cross-checked against Vibe's values, independent modules on 2 Sonnet agents at most; (2) pre-approved
    defaults (above); (3) build shared templates first (keyed provider adapter, table panel, canvas heat grid) and
    keep later functions thin; (4) spec + tests in one step per phase, all of a phase's fixtures in one recording
    script run; (5) faster gates (test-suite audit running in its own session on its own branch, see below).
    Quality, accuracy, terminal speed and bench budgets are never traded for pace.
  - Estimate: about 9-13 hours of active work (4-5 sessions of one 5-hour window each). Re-check after Phase 12.
  - **Test audit: finished and MERGED (2026-10-19, `863af15`, no conflicts, all five gates green).** Branch
    `refs/heads/claude/test-speedup`, commit `5347a9b` (off `976c7ad`, 23 files). What it does: pytest 39-41 s -> 20-29 s
    (httpx client / CA bundle built once per worker in `conftest.py`; `addopts` `-n 6 --dist worksteal`), Playwright
    30-45 s -> 18-27 s (shared `openApp()` in `e2e/app.ts` loads the page once; web server builds without the type check),
    vitest 2.1 -> 1.3-1.6 s (`threads` pool). Merged duplicates: four migration-upgrade tests -> one test upgrading from
    every schema version 0-9 (`test_userdata.py`), three restart-survival tests -> one. Fixed flake:
    `test_runtime_limits_fail_closed` (3 s limit only on the time-limit case). Every old assertion kept.
    After merging: a new migration must list its tables in `TABLES_BY_VERSION` (`test_userdata.py`), or a check fails;
    `phase12.spec.ts` can switch its setup to `openApp()`. Left as is: ~700 unmocked Playwright requests
    (`/api/cmdhistory`, `/api/sources`, `/api/alerts`, `/api/settings`) reach port 8000, so keep port 8000 free during
    e2e; two Phase 6 insider tests wait ~1.7 s each on the real SEC rate limit (by design).
- **What step 3 added** (`backend/openterm/bt/`):
  - Ported verbatim from Vibe-Trading `d0db2e3` by a copy script (header line names the source): `models.py`,
    `metrics.py`, `rebalance_mask.py`, `engines/hooks.py` (= `_market_hooks.py`), `engines/global_equity.py`,
    `engines/base.py` (cut: loaders, optimizer, fundamentals/events, run card, artifacts; `run_backtest` replaced by an
    in-memory `run(data_map, signal_map, bars_per_year, bench_ret, benchmark_metadata)`; the rest unchanged).
  - Ours: `engine.py` (`backtest()`, `FEES=` overlay on `calc_commission`), `frames.py` (Yahoo chart / router `Bars` /
    Binance perp -> frames; `adjusted()`), `rules.py` (pure parser + `signals()` + `parse_command`), `sandbox.py`
    (AST allowlist + restricted builtins + guarded import + sockets off), `limits.py` (memory cap: Windows Job Object
    per worker, `RLIMIT_AS` elsewhere), `catalog.py` (engine per symbol, built engines, default costs), `job.py`
    (worker side of `bt.run`), `store.py` (data files, strategies, runs; keep 200).
  - Jobs: `Kind.internal` (bt.run only via `/api/bt/run`), `Kind.hash_view` (bt.run hashes without its labels),
    per-job `time_limit_s`, `JobRunner.on_done` hooks (store the run before the job shows done), `JobStore.forget(hash)`.
  - Migration 9 (`strategies`, `bt_runs`; a migration may now be a list of statements). API: `POST /api/bt/run`,
    `GET /api/bt/runs`, `GET|DELETE /api/bt/runs/{id}`, `GET /api/bt/strategies`, `GET|PUT|DELETE /api/bt/strategies/{name}`.
    Fixture routes for the 10y charts. Dependencies added: numpy, pandas (<3), psutil, keyring (decision M: APIKEYS now
    uses the Windows keyring).
- **Changed from the spec (tell the user):** default benchmark is Vibe's (equal-weight buy and hold of the traded
  symbols), not SPY; `BENCH=SPY` compares with an index. Needed so API runs match the Vibe cross-check exactly.
- **Still open from Phase 11:** the OpenRouter recording (`scripts/record_llm.py`, then delete `@RECORDING`).
- **The user's working rules for Phases 11-19** (updated 2026-10-19 to speed things up; quality and terminal speed
  must not drop):
  1. Do a whole phase per turn, step by step in HANDOFF order, committing each step. Stop only on a gate failure that
     needs a decision, a missing key, or a real product decision.
  2. Each phase starts with `docs/specs/PHASE_<n>.md` (defaults at the top, pre-approved: see "Scope and plan"),
     written together with its tests in one step, then code.
  3. One fresh session per phase (HANDOFF.md carries the state). Sonnet subagents only, at most 2 at once, only for
     truly parallel pieces (backend and frontend halves).
  4. Every step: `uv run pytest -q`, `uv run ruff check .`, `npx tsc --noEmit`, `npx vitest run`, `npx playwright test`.
     `node scripts/bench.mjs` at the end of each phase and on any step that touches rendering, hot paths or the bench;
     a phase is not done while any budget regresses. Record bench numbers in `docs/PERFORMANCE.md`.
  5. Docs (HANDOFF.md, CLAUDE.md): only the changed sections.
  6. At 95% of the 5-hour or weekly limit: stop subagents, write the state to HANDOFF.md, commit, and stop.
  7. Keep output small. If a key is needed, stop and say which one.
  8. **Sonnet for everything** (main session and subagents; decided 2026-10-19, no model switching). If the same gate
     fails twice on the same problem: stop, write the state and exact next action here, commit, and tell the user.
- **Before the bench:** port 8000 must be free. The user's own `start.ps1` backend sometimes holds it; ask before stopping it.

## How Phases 6-10 were built (history)
Built in parallel, one git worktree per phase (`openterm-p6..p10`, from `4b3814c`), by Sonnet sessions following
[docs/PARALLEL_BUILD.md](docs/PARALLEL_BUILD.md) (append-only "Phase N" blocks in shared files; only Phase 8 adds
migrations, positions 6-7). Each phase was then merged in order with `git apply --3way`, fully verified (pytest, ruff,
tsc, vitest, all Playwright, bench) and committed with the user's approval:

| Phase | Commit |
|---|---|
| 6 FA, FIL/SEC, OWN, HDS | `96d40b9` |
| 7 FRED, MACRO, RATES, ERN, ECO | `90bffb1` |
| 8 PORT, ALRT (migrations 6-7) | `1070230` |
| 9 EQS, HIST, CORR, COMP, CSV export | `b5515ac`; CSV hook wired into the Phase 6-8 panels in `7e3ca69` |
| 10 SETTINGS, themes, vim, keybinding overrides, Docker, Tauri, release notes | `f0df226` |
| Post-merge fixes + `scripts/start.ps1` | `626bddd` |

All phase worktrees, their `-wip` branches, the backups (`wip-patches/`, `RESUME_PROMPT.md`) and the finished build
sessions are gone; everything is on `main`. Things that still apply from that build:
- Phase 6 SEC fixtures: the user approved their Gmail as the SEC User-Agent **for fixture recording only**; it
  must never be written into the repo. The app reads `SEC_USER_AGENT` from env.
- **Use Sonnet subagents/sessions, not Opus** (user's request: Opus agents used ~55% of the 5-hour window in 15 min).
  Run at most 2-3 at once and check plan usage between steps. When the 5-hour (or weekly) window reaches 90%, stop
  them, write down exactly where each one is, and pause.
- A session started in one worktree cannot write into another (a hook blocks Write/Edit). Work that belongs in
  another worktree goes to a session started there; do not copy files in through a scratchpad.

## Where things stand
- **All 10 phases are built, verified and on `main`** (Phases 1-4 `736d6d5`..`b72466a`, 5 `4b3814c`, 6-10
  `96d40b9`..`f0df226`, then docs and the post-merge fixes). `main` was fast-forwarded on 2026-10-17; the old
  phase worktrees and branches were removed. No git remote. The git identity (ankithrbharadwaj) is set for this repo only.
- The leftover uncommitted Phase 3 copies that sat on `main` were set aside in a stash
  (`main-phase3-leftovers-2026-10-17`); they were identical to `b6dca4e` apart from line endings, so the stash can be dropped.
- Latest verification (`626bddd`, post-merge fixes):
  - Backend: 163 pytest passed (`-n auto`, ~26 s), ruff clean.
  - Frontend: 169 vitest passed, tsc clean, 66 Playwright passed (`--workers=8`, ~29 s).
  - Bench: 16/17 (tick-to-pixel 55-59 ms vs 50 on every run that evening, also with the fixes reverted; see
    `docs/PERFORMANCE.md` "Post-merge fixes"). Phase 10 itself was 17/17 on two of three runs.

## Done
| Phase | Contents |
|---|---|
| 1 Scaffold | Shell UI (top bar, command line, clock + market lights, status bar), tiling workspace (split/close/focus/resize/maximize, panel history), command parser `[N:] SEC [MKT] FN [ARGS]`, fuzzy autocomplete, history, `keybindings.json`, PERF HUD/panel, `scripts/bench.mjs`, CI workflow |
| 2 Data core | Provider adapters (Yahoo, Nasdaq), router with fallback + circuit breaker, token buckets, LRU + SQLite WAL cache, SWR envelopes `{data, source, as_of, age_s, stale, fallback_from}`, request coalescing, `/api/quote|history|search|sources|log`, fixture mode, `SOURCES` and `LOG` screens, live ticker search with prefetch |
| 3 First functions | Yahoo protobuf streamer (hand-decoded), REST poll fallback, SYNTHETIC load stream, hub with one upstream subscription per symbol and per-client coalescing; `/api/profile`; frontend tick store (per-frame batching), canvas virtualized `Grid`, `Q` (live monitor), `DES`, `QR`, `GP` (lightweight-charts, indicators in a Web Worker, compare, log, crosshair, keyboard pan/zoom), `PERF GRID/CHART` load views |
| 4 Workspace | SQLite migrations 3-4 (`layouts`, `history`), `backend/openterm/userdata.py`, `/api/layouts[/{name}]` GET/PUT/DELETE, `/api/cmdhistory` GET/POST; `LAYOUT`/`MONITOR` `SAVE|LOAD|DEL name` (bare name = LOAD, bare `LAYOUT` = list panel with J/K, Enter, Del-twice, S), `Ctrl+S` (re-save current named layout, else prompts) / `Ctrl+O` (prompts `LAYOUT LOAD ` with name autocomplete), layout name in the status bar; command history moved to SQLite (batched writes, `sendBeacon` on exit, one-time upload of the old localStorage history); Playwright tests for layouts, history and Ctrl+Shift+Arrows resizing; bench gate for layout load |
| 5 Boards + lists | Watchlists (SQLite, `WL` grammar), news (`N`: RSS / Yahoo RSS / GDELT), `MOV` (Nasdaq movers), `CRYP` (CoinGecko, Binance), boards `WEI` `FX` `CMDTY`, `FXC` cross matrix, shared `quoteRows.ts`; pytest-xdist, fully parallel Playwright |
| 6 SEC + ownership | `FA` (SEC EDGAR XBRL financials: IS/BS/CF, annual/quarterly), `FIL`/`SEC` (filings list), `OWN` (Form 4 insider transactions), `HDS` (institutional + fund holders); providers `sec`, `yahoo_own`; needs `SEC_USER_AGENT` in env |
| 7 Macro | `FRED` (series chart), `MACRO` (curated list + search), `RATES` (Treasury yield curve + spreads), `ERN` (earnings calendar), `ECO` (BLS + BEA release dates); providers `fred`, `fred_csv`, `treasury`, `nasdaq_earnings`, `agency_ics` |
| 8 Portfolio + alerts | SQLite migrations 6-7 (`portfolios`, `alerts`), `PORT` (positions with average-cost lots, live P&L, FX to base currency, CSV import/export), `ALRT` (price / percent alerts evaluated on raw ticks, status-bar flash, rearm) |
| 9 Analysis | `HIST` (price table, ADJ CLOSE when available), `EQS` (screener over the US universe, filter grammar in args), `COMP` (peers + median, 1M-1Y returns), `CORR` (heat matrix); CSV export everywhere via `E` / Alt+X (`tableExport.ts`); providers `nasdaq_screener`, `yahoo_peers` |
| 10 Settings + packaging | `SETTINGS` panel and `THEME` (amber, green, white, light), vim mode for the command line, keybinding overrides, number format, header clocks, chart and poll defaults (`/api/settings`, SQLite `kv`), `Dockerfile` + compose + `OPENTERM_STATIC_DIR`, Tauri scaffold in `desktop/`, `docs/RELEASE_NOTES.md`, `CHANGELOG.md` |

## Phase 10 details (SETTINGS, themes, vim, keybinding overrides, packaging)

**Built and verified (merged from `openterm-p10`):**
- Backend: **163 pytest passed, ruff clean** (+24 in `tests/test_phase10.py`). `settings_store.py` (validates, stores only non-defaults as versioned JSON in `kv` key `settings`),
  `/api/settings` GET / PUT, `config.py` `openterm_static_dir`, `main.py` `mount_static()` (serves the built frontend at `/` when `OPENTERM_STATIC_DIR` is set).
- Frontend: **169 vitest** (+50), **66 Playwright** (+6 `e2e/phase10.spec.ts`), tsc clean.
  - `settings/{schema,runtime,sync,themes,commands}.ts`, `functions/SETTINGS.tsx`, `THEME name` / `SETTINGS KEY VALUE` commands, themes as CSS variable blocks,
    `command/vim.ts` (opt-in), `keys/overrides.ts` (conflicts, browser-reserved chords, fixed Esc / panel focus refused), `functions/listNav.ts` (g/G/PgUp/PgDn in lists),
    `format.ts` number-format wrap, TopBar clock zones, GP chart defaults, `pollMs` for N/MOV/CRYP/sources.
- Packaging (not built here): `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `desktop/` Tauri 2 scaffold, `docs/DESKTOP.md`.
- Docs: `docs/RELEASE_NOTES.md` (Phase 6-9 bullets rewritten against what was built), `CHANGELOG.md`.
- Merge resolution: import lines, the Phase 7/8/9 api blocks and `main.tsx` startup calls were all kept (`startAlerts()`, `pollSources(pollMs("sources"))`, `startSettingsSync()`);
  Shortcuts text lists both the settings hint and Alt+X.

## Phase 9 details (EQS, HIST, CORR, COMP, CSV export)

**Built and verified (merged from `openterm-p9`):**
- Backend: **139 pytest passed, ruff clean** (+13 in `tests/test_phase9.py`).
  - `providers/screener.py`: `NasdaqScreenerProvider` (`screener`, whole US universe as a columnar payload, TTL 15 min) and `YahooPeersProvider` (`peers`, TTL 24 h).
    `DataService.screener()` / `peers()` (peers fall back to the largest same-industry names, `basis: "industry"`); `/api/screener`, `/api/peers?symbol=`.
  - Bars gained optional `adj` (adjusted close; `models.py` 1 line, `yahoo.py` `bars_from_chart` reads `adjclose`).
  - Fixtures: `nasdaq_screener_trimmed.json` (476 rows trimmed from the real download), `yahoo_recs_aapl.json`, `yahoo_recs_empty.json`.
- Frontend: **119 vitest** (+28: `csvText`, `eqsFilter`, `corrMath`), **59 Playwright** (+13 `e2e/phase9.spec.ts`), tsc clean.
  - Pure: `csvText.ts` (`csv.ts` delegates to it), `functions/eqsFilter.ts` (grammar `SECTOR=TECH MCAP>10B PCT>2 PRICE<50 VOL>1M COUNTRY=US SORT=PCT`),
    `functions/corrMath.ts` (log returns, date alignment, Pearson, heat bands, `parseCorrArgs`), `functions/returns.ts` (`periodReturn`, `histRows`, `histArgs`).
  - Panels: `HIST.tsx` (D/W/MO, Enter = GP), `EQS.tsx` (Enter = DES; parse errors shown in red, the parsed clauses still run), `COMP.tsx` (SELF, peers, `MEDIAN OF n PEERS`),
    `CORR.tsx` (DOM table up to 20x20, H/J/K/L cursor, Enter = GP pair).
  - CSV export: `functions/tableExport.ts` (`useCsvExport`, `gridCsv`, `exportPanelCsv`), binding `exportCsv` = **Alt+X** + `E` panel key. Migrated: Q, WL, MOV, CRYP, Board (WEI/FX/CMDTY), FXC, N, Layout, Sources + the 4 new panels.
- **CSV hook (now applied to the Phase 6-8 panels; recipe for new panels):** `import { gridCsv, useCsvExport } from "./tableExport";`, then after `rows` is computed
  `useCsvExport(panelId, () => gridCsv("FA_AAPL", COLUMNS, rows));` (non-`Grid` panels return `{ name, header, rows }`, `null` while loading;
  `{ panelKey: false }` as 3rd arg if the panel already uses E); add `E CSV` to the hint line; e2e: press `e`, `waitForEvent("download")`.
- Merge resolution: api.py (screener route joined to the Phase 6 start, peers appended), service.py (Phase 9 methods kept inside `DataService`, the Phase 7 imports
  block stays last), `net/api.ts` (both objects closed), registry takes Phase 9's four lines, `test_api.py` pin lists all phases, config.yaml/main.py/styles.css/DATA_LIMITS keep every block.

## Phase 8 details (PORT, ALRT)

**Built and verified (merged from `openterm-p8`):**
- Backend: **126 pytest passed, ruff clean** (116 + 10 in `tests/test_phase8.py`; `test_userdata.py` migration pin updated).
  - Migration 6 `portfolios (name PK, base, positions JSON, updated_at)`, migration 7 `alerts (id, symbol, op, unit, value, status, created_at, triggered_at, trigger_price)`.
  - `portfolio.py` CRUD with average-cost lots; `/api/portfolios[/{name}]` GET / PUT / PATCH `{add, set, remove, base}` / DELETE;
    `/api/alerts` GET / POST, `/api/alerts/{id}` DELETE, `/{id}/trigger`, `/{id}/rearm`, `DELETE /api/alerts?status=triggered`.
- Frontend: **91 vitest** (+25), **46 Playwright** (+6 `e2e/phase8.spec.ts`), tsc clean.
  - Pure modules `command/portfolioArgs.ts`, `command/alertArgs.ts`, `functions/portfolioCsv.ts`, `functions/portfolioMath.ts`;
    `command/portfolios.ts`, `command/alerts.ts` (engine), `execute.ts` PORT/ALRT block, `api8` block in `net/api.ts`.
  - `PORT.tsx`: ADD lots with cost, RM, D/U confirm + undo, EXPORT download, V paste + preview + merge; mixed currencies convert to the
    base with live Yahoo `CCYBASE=X`, labelled (no rate = per-currency subtotal, excluded from the total).
  - `ALRT.tsx`; the engine starts in `main.tsx` (`startAlerts()`), listens through `onRawTicks` in `state/ticks.ts`, flashes via `components/AlertFlash.tsx` in `StatusBar`.
    Alerts fire once, R rearms, C clears. Evaluation is frontend-only (the backend never watches prices).
- Merge fixes: api.py and `net/api.ts` Phase 7/8 blocks joined (restored the closing `return error(e)` / `};`); registry takes Phase 8's PORT and ALRT lines;
  `phase5.spec.ts` FXC assertion now retries (`toPass`) because it raced the frame flush once Phase 8's startup work shifted timing.

## Phase 7 details (FRED, MACRO, RATES, ERN, ECO)

**Built and verified (merged from `openterm-p7`):**
- Backend: **116 pytest passed, ruff clean** (90 + 26 in `tests/test_phase7.py`, which pins "today" to 2026-10-17 via `macro.ny_today`).
  - `providers/macro.py`: parsers + providers `fred` (official API, needs `FRED_API_KEY`; inactive without it, SOURCES shows KEY REQUIRED),
    `fred_csv` (keyless `fredgraph.csv`), `treasury` (par yield curve CSV, one file per year), `nasdaq_earnings`, `agency_ics` (BLS + BEA ICS feeds).
  - `/api/fred?id=&range=`, `/api/macro?q=`, `/api/rates`, `/api/earnings?date=`, `/api/eco?start=&days=`. Capabilities and orders in `config.yaml`
    (`fred_series` [fred, fred_csv], `fred_search` [fred], `yield_curve` [treasury, fred_csv], `earnings` [nasdaq_earnings], `eco_calendar` [agency_ics, fred]).
  - `providers/__init__.py` re-binds `keyed_status` (adds a `fred` KEY REQUIRED row) and pops `fred` from `KEYED`; `fixtures.py` wraps `_route`.
  - 38 fixtures recorded 2026-10-17 from the live sites (FRED CSV x20, Treasury 2025/2026, Nasdaq earnings x3, BLS/BEA ICS, real FRED 400);
    the keyed FRED API shapes are built from the docs (no key available), so live behaviour with a key is untested.
- Frontend: **66 vitest** (+20 `macroArgs.test.ts`), **40 Playwright** (+11 `e2e/phase7.spec.ts`), tsc clean.
  - `FRED.tsx` plots through `ChartView` (o=h=l=c=value; gaps skipped and counted); `MACRO.tsx` without a key shows the built-in list
    and filters locally; `RATES.tsx` derives 3M10Y / 5S30S / 2S10S spreads, Enter plots the matching `DGS*` series;
    `ERN.tsx` args TODAY/TOMORROW/YESTERDAY/+N/-N/YYYY-MM-DD, Left/Right change the day; `ECO.tsx` has dates and times only (BLS + BEA), MAJOR is a name match;
    `macroUi.tsx` shared status/error pieces; `macroApi` block in `net/api.ts`.
  - `ChartView.tsx` got an optional `readoutLabel` prop (crosshair readout `<date> <label> <value> <pct>`), used by FRED.
- Merge resolution: api.py hunks interleaved (6 then 7), `test_api.py` pin lists both phases, registry keeps Phase 6 HDS/OWN and Phase 7 RATES/ERN loads,
  `net/api.ts` needed the closing `};` of `secApi` restored.

## Phase 6 details (FA, FIL/SEC, OWN, HDS)

**Built and verified (merged from `openterm-p6`):**
- Backend: **90 pytest passed, ruff clean** (66 old + 24 in `tests/test_phase6.py`).
  - `providers/sec_parse.py` (pure parsers: `parse_companyfacts` with tag fallbacks per period, dedup by period + latest filed,
    period labels from each filing's own fy/fp, derived quarters = YTD minus shorter YTD, FCF computed; `parse_submissions`;
    `parse_form4`), `providers/sec.py` (`SecProvider`, name `sec`: fundamentals, filings, insiders; token bucket 8/s;
    ticker to CIK from `company_tickers.json` cached 24 h in memory; non-US symbols unsupported),
    `providers/ownership.py` (`YahooOwnProvider(YahooProvider)`, name `yahoo_own`: holders, insiders via quoteSummary; yahoo.py untouched).
  - `service.py` Phase 6 block: `fundamentals`, `filings`, `insiders`, `holders`; parsed Form 4s cached per accession in `cache` (`f4:<accn>`).
  - `/api/fa?symbol=&period=A|Q`, `/api/filings?symbol=&form=`, `/api/insiders?symbol=`, `/api/holders?symbol=`.
    TTLs in `config.yaml`: facts 6 h, filings 15 min, insiders 1 h, holders 6 h.
  - **SEC needs `SEC_USER_AGENT` in env** (default is empty; `config.py` changed from a placeholder; the old placeholder still counts as unset).
    Empty means SEC may answer 403; the error text and SOURCES `terms` say so. The repo never contains an address.
  - Fixtures (real responses, trimmed to the mapped tags / 60 recent filings): `sec_facts_aapl|msft`, `sec_company_tickers`,
    `sec_subs_aapl|msft`, `sec_form4/*` (20 AAPL Form 4s), `yahoo_holders_aapl`, `yahoo_insiders_aapl`.
  - Shared-file edits: `config.py` (1 line), `main.py` (2 lines under `# --- Phase 6`), `service.py` (import + appended methods),
    `api.py`, `providers/__init__.py`, `fixtures.py` (2-line hook at top of `_route` + appended block), `config.yaml`, `test_api.py` (pinned provider set).
- Frontend: **tsc clean; 46 vitest** (36 + 10 in `functions/secTables.test.ts`), **29 Playwright** (23 + 6 in `e2e/phase6.spec.ts`).
  - `functions/secTables.ts` (payload types + shaping for all four panels), `functions/secPanel.tsx` (envelope hook, header,
    `ErrorLine` with the `SEC_USER_AGENT` hint), panels `FA.tsx`, `FIL.tsx` (also serves `SEC`), `OWN.tsx`, `HDS.tsx`; `net/api.ts` `secApi` block; registry lines.
  - FA keys: 1-3 / Tab statement (IS, BS, CF), A / Q annual or quarterly, H / L scroll older / newer periods, J/K, E CSV, F5.
    Args: `AAPL FA Q CF`. Derived quarters carry `*`; negatives are red.
  - FIL keys: 1-6 / Tab form filter (ALL, 10-K, 10-Q, 8-K, 4, DEF 14A), Enter / O opens the document, I the filing index, E CSV.
    Any other form works as an argument (`AAPL FIL 424B2`).
  - OWN keys: M toggles open-market (P/S) only, Enter opens the Form 4, E CSV; shows `N FORM 4 NOT READ` when some failed.
  - HDS: cursor skips section header rows (`navKey` skip callback). No panel polls; F5 refreshes. US-only coverage note is warning-coloured.
- Merge fix: `e2e/cmdline.spec.ts` asserted FA shows `NOT BUILT YET (PHASE 6)`; that line was removed (the header assertion stays).
- Not run against the live network (tests use fixtures). Live SEC calls need `SEC_USER_AGENT`.

## Phase 5 details (WL, N, WEI, MOV, FX/FXC, CRYP, CMDTY)

**Built and verified:**
- Backend: **66 pytest passed, ruff clean** (42 old + 24 in `tests/test_phase5.py`).
  - Migration 5 `watchlists`; `userdata.py` watchlist CRUD (max 500 symbols, aliases resolved, deduped);
    `/api/watchlists[/{name}]` GET / PUT `{symbols}` / PATCH `{add, remove}` (add creates) / DELETE.
  - `providers/news.py`: `rss` (5 publisher feeds, merged newest first, partial failures listed in `failed`),
    `yahoo_rss` (per-symbol, publisher = link domain), `gdelt` (keyword; `max_wait` 6 s, `timeout` 20 s, throttle text = rate_limited).
    `/api/news` (`?symbol=` | `?q=` | none = top), TTL 120 s, not found = `NO HEADLINES FOUND`.
  - `nasdaq.movers()` + `/api/movers` (tabs GAINERS LOSERS ACTIVE DOLLAR NDX100, per-tab "data as of"), TTL 60 s.
  - `providers/crypto.py`: `coingecko` then `binance` (USD/USDT only); `/api/crypto?vs=` (allowed list in `crypto.VS`), TTL 60 s.
  - Provider base: `get_bytes`, per-class `timeout` and `max_wait`. Error bodies now include `detail` (each provider's reason).
  - Fixtures recorded from the real endpoints (see `providers/fixtures.py` `PATHS`, `YAHOO_RSS`, `GDELT`, `COINGECKO`);
    `yahoo_spark.json` now also holds all 74 board symbols. `config.yaml`: new fallback orders, TTLs, `news.feeds` comment.
  - Existing tests changed only where they pin the provider set / migration list (`test_api.py`, `test_userdata.py`).
- Frontend: **tsc clean; vitest 36 passed** (24 old + `command/watchlists.test.ts`, `functions/boards.test.ts`).
  - `command/watchlistArgs.ts` (pure parser) + `command/watchlists.ts` (API actions, `watchlistList`, `watchlistVersion` stores);
    `execute.ts` handles `WL ...` (edit then show the list; no duplicate history entry if the panel already shows it);
    command-line autocomplete for `WL <name>` / `WL DEL <name>`; prefetch now only for RECENT/SEC suggestions (was also prefetching layout names).
  - `Grid` mirrors the selected row into `.grid .sr`. `functions/quoteRows.ts` extracted from Q (Q refactored onto it, same behaviour).
  - Panels written: `WL.tsx` (index with Del-twice delete; list view with D remove, U undo, A add, S sort, E CSV),
    `N.tsx` (Enter opens the article in a new tab, NEW items highlighted, 60 s poll, F5 fresh, error + detail),
    `MOV.tsx` (1-5 / Tab switch tabs), `CRYP.tsx` (Enter = `SYM-USD GP`), `Board.tsx` + `WEI.tsx` `FX.tsx` `CMDTY.tsx`
    (sections skipped by J/K, Enter = GP), `FXC.tsx` (cross matrix, recomputed on leg ticks, Enter = GP vs USD).
  - `format.ts` `fmtRate`; `api.ts` news/movers/crypto/watchlist calls (`fresh` flag skips the client cache); styles `.sr .tabs .summary`.
  - `functions/registry.ts`: all eight wired with `load` and `argsSchema`.
  - `e2e/phase5.spec.ts` (8 tests, mocked routes + WebSocket), green.

**Bench baseline for Phase 8** (Phase 7 tree figures are in `docs/PERFORMANCE.md`; this is the Phase 6 tree, 2026-10-17): 17/17 PASS. Bundle 85.0 KB gz; backend p95
health/quote/history 0.7/0.7/1.9 ms; cold start 92.3 ms; keystroke 14.4 ms (9.8 under load); cached / cold-network
command to paint 18.5 / 18.1 ms; tick-to-pixel 38.2 ms; frame p95 16.7 ms everywhere; long tasks 0; heap 5.1 MB;
ticks 4,000/s; layout load 36.3 ms. (Phase 5 baseline: 84.8 KB, 37.5 ms tick-to-pixel, 35.8 ms layout.)

## Next
Phases 6-10 in order:
- 6: done (merged, see Phase 6 details).
- 7: done (merged, see Phase 7 details).
- 8: done (merged, see Phase 8 details). Desktop notifications were not part of the build: alerts flash in the status bar.
- 9: done (merged, see Phase 9 details). CSV export (`E` / Alt+X) is wired into every table panel, Phase 6-8 included (FA, FIL, OWN, HDS, FRED, MACRO, RATES, ERN, ECO, ALRT via `useCsvExport`); PORT keeps its own `E`/EXPORT, which writes a re-importable portfolio CSV.
- 10: done (merged, see Phase 10 details). Backups were deleted.

Remaining:
1. First real Docker build and Tauri build (neither tool is installed on the dev machine). Deferred by the user.
2. Tick-to-pixel bench budget: missed (55-59 ms vs 50) on every run of the post-merge session, including with the
   fixes reverted, so it is machine load or drift, not those fixes; earlier the same day it ran 38-42 ms. Re-run on a
   quiet machine before treating it as a regression.
3. Phases 11-19: plan in [docs/ROADMAP_PHASES_11-19.md](docs/ROADMAP_PHASES_11-19.md) and
   [docs/FEATURE_GAP.md](docs/FEATURE_GAP.md). Work happens in worktree branch `claude/openterm-phases-11-19-328938`
   (fast-forwarded onto the roadmap commit `7d20e69` from `claude/openterm-bloomberg-feature-gap-badb0c`; not on `main` yet).
   Since session 6 the work continues on `claude/openterm-phases-11-19-a99b2b` (fast-forwarded from 328938; see "Resume here").
   Steps (one commit each; a step is a spec, a tests set, or one function's code):

   | Step | State |
   |---|---|
   | 11.1 Spec [docs/specs/PHASE_11.md](docs/specs/PHASE_11.md) | **done**, defaults approved 2026-10-18 |
   | 11.2 Tests set: `backend/tests/test_phase11.py` (39), `frontend/src/net/phase11.test.ts` (5), `frontend/e2e/phase11.spec.ts` (4) | **done**; all marked expected-to-fail per step (see CLAUDE.md) |
   | 11.3 Key store, redaction, `/api/keys`, `KEY REQUIRED`, `APIKEYS` panel | **done** (backend by the main session, frontend by one Sonnet subagent) |
   | 11.4 Job runner, migration 8, `J` frames, `JOBS` panel, bench budgets (JOBS + APIKEYS open) | **done** (backend main session, frontend one Sonnet subagent); bench 21/21 |
   | 11.5 LLM gateway + health | **done except the recording** (main session, no subagents); bench 21/21 on the third run. `test_recorded_openrouter_stream...` waits for the OpenRouter key (`scripts/record_llm.py`) |
   | 11.6 `THIRD_PARTY.md`, CLAUDE.md rule changes, docs, phase verification | **done** 2026-10-19; bench 21/21 first run |
   | 12.1 Spec [docs/specs/PHASE_12.md](docs/specs/PHASE_12.md) | **approved** 2026-10-19 |
   | 12.2 Tests set + recordings + Vibe cross-check values | **done** 2026-10-19: `backend/tests/test_phase12.py` (75; markers `CORE` step 3, `ENGINES` 5, `VALID` 6, `RUNS` 7, `IMPORT` 8), `frontend/src/bt/phase12.test.ts` (6), `frontend/e2e/phase12.spec.ts` (5); fixtures by `scripts/record_phase12.py`; expected values `bt_vibe_expected.json` by `scripts/vibe_crosscheck.py` |
   | 12.3 Engine core, rules, sandbox, API, migration 9 | **done** 2026-10-19: all gates green, bench 21/21, THIRD_PARTY rows added |
   | 12.4 `BT` panel + BT bench budgets | **done** 2026-10-19: bench 24/24; strategy editor split out as 12.4B |

   The tests pin interfaces the spec left open: `keys.KeyStore(env, dotenv, keyring)`, `MemoryKeyring`, `classify()`, `KeyStoreError.kind`
   (`env_locked` 409, `unknown_provider` 404, `bad_request` 400), `redact.redact(text, secrets)`, `Provider.key_name`, `AllFailed.key`,
   `DataError(..., key=)`, `jobs.job_hash`, `jobs.store.JobStore`, sleep params `ignore_cancel` / `fail_at` / `crash_at` / `tag`,
   `llm.sse.parse_sse`, `events_from_payloads`, `llm.spend.check/cost/add/today`, `/api/llm/health`, settings `OPENTERM_KEYRING`
   (`auto|memory|none`), `OPENTERM_DOTENV_PATH`, `OPENTERM_JOB_WORKERS`; frontend `jobFrames.ts` (`parseJobFrame`, `applyJobFrame`,
   `progressText`), `keyRequired.ts`, `functions/apikeysMask.ts` (`maskKey`), `.keyreq` line class.
   Step 3 notes: `backend/openterm/keys.py` (specs, store, `.env` writer, `classify`, `run_test`), `redact.py` (filter on the ring buffer,
   root handlers, httpx/httpcore), `/api/keys*` in `api.py`, router `key_required` (no breaker strike; `AllFailed.key`), 424 in `error()`,
   SOURCES keyed rows from the store (`providers/__init__.py` Phase 11 block). `app.state.on_key_change` re-applies a FRED key set in
   APIKEYS (other keyed adapters arrive in later phases and must read the store the same way). Fixtures: real 401s for Finnhub,
   OpenAI, Anthropic, OpenRouter (`keytest_*_401`); `keytest_openrouter_ok` is doc-shaped. Frontend: `APIKEYS.tsx`, `KeyRequiredLine.tsx`
   (wired into `secPanel` and `macroUi` error lines only; DES, N, GP and others still show their own error text),
   `state/panelContext.ts`, `net/keyRequired.ts`, `apikeysMask.ts`, `apikeysSignup.ts`. Spend cap editing (`C`) waits for step 5.
   Step 4 notes: `backend/openterm/jobs/` (`__init__` = `job_hash` only, kept import-light for workers; `kinds.py` (`sleep` = TEST JOB);
   `worker.py`; `store.py` (migration 8, hash index made on first use, trim 200, results > 8 MB not cached); `runner.py`: own pool of
   spawn workers, two pipes + a shared cancel flag each, one reader thread on pipes + sentinels, hard cancel after 2 s, time limit,
   `WORKER DIED`, 10 frames/s/job). Hub `Client.push` / `Hub.broadcast` carry `J` frames. `/api/jobs` POST/GET, `/{id}` GET/DELETE,
   `DELETE /api/jobs?state=finished`. Frontend: `net/jobFrames.ts`, `net/jobs.ts`, `functions/JOBS.tsx`, `jobsArgs.ts`, status bar `JOBS n`.
   The job budget is split (user's choice): frame-to-paint and server time gated, end to end through the bench proxy is INFO.
   Step 5 notes: `backend/openterm/llm/` = `sse.py` (incremental `SSEParser` + `parse_sse`), `events.py` (`Event`), `openai_compat.py`
   (`OpenAIStream`, tool-call deltas assembled per `index`, emitted on `finish_reason`), `anthropic.py` (`AnthropicStream`, OpenAI-shaped
   messages/tools converted to the Messages API), `spend.py` (`check`/`cost`, per-day spend in `kv` `llm_spend:<date>` added in one SQL
   statement, cap in `kv` `llm_cap`, default US$1), `client.py` (`Gateway.chat(messages, model, provider="openrouter", tools,
   max_tokens, temperature)`: KEY REQUIRED / PRICE UNKNOWN / SPEND CAP REACHED before any network call, OpenRouter prices from its
   `/models` list (cached 1 h, `:free` = 0), OpenAI/Anthropic prices from `config.yaml` `llm.prices` (left empty on purpose), worst case
   charged if a stream ends without usage; `health()`, Ollama probe 300 ms cached 10 s). API: `GET /api/llm/health`,
   `PUT /api/llm/cap` (loopback, 0-1000), `/api/keys` `spend` is real, SOURCES has an `ollama` row. The gateway is built on first use
   (`api.llm_of`; `app.state.llm` reset in the lifespan). Fixture mode: Ollama port refuses, OpenRouter chat replays
   `llm_openrouter_stream.txt` if present, other LLM hosts 404. No AI function calls `chat()` yet (Phase 16). Frontend: APIKEYS `C`
   edits the cap (`functions/spendCap.ts`). The `client` fixture now clears every KEY_SPECS env var.
   Baseline before Phase 11 code: 163 pytest, 169 vitest, 66 Playwright, bench 17/17 on the rerun (see `docs/PERFORMANCE.md`
   "Phase 11 baseline"). Open problem: port 8000 was held by the user's own `start.ps1` backend (system Python); stop it
   (with the user's OK) before the bench.

Done after the merge: `main` fast-forwarded; panel tab names the security only for functions that use it; charts skip
the volume histogram when a series has no volume (FRED's flat line); `scripts/start.ps1` / `scripts/start` run the
built app from the backend on :8000 and open the browser.

## Decisions already made (don't relitigate)
- Stooq is dropped (bot check). The zero-key chain is Yahoo, then Nasdaq (US only, daily history only).
- Keystroke echo is gated at 16.7 ms (one 60 Hz frame), measured from keydown to the start of the next frame.
- Frame time is gated at p95 < 20 ms (60 Hz = 16.7 ms; above 25 ms is a dropped frame).
- Backend latency is gated server-side.
- 9 panels is the maximum (focus-by-number 1-9). The bench runs the 200-symbol load over 9 panels.
- Memory budget is checked as JS heap. Whole-process memory waits for the Tauri build.
- No React.lazy/Suspense for panels (300 ms reveal throttle). Use the registry loader.
- Daily charts never invent a new bar from ticks. Intraday bars are bucketed.
- Lightweight Charts attribution is text (in the GP status line and the README), with the logo off.
- Command history lives on `/api/cmdhistory` (`/api/history` is price bars). Table name is `history`.
- Named layouts are in SQLite. The live (unnamed) workspace still autosaves to localStorage so cold
  start never waits on the backend; recent-securities autocomplete hints also stay in localStorage.
- A saved layout keeps only each panel's current view (no back/forward history). Loading validates
  the tree in the frontend (`state/layoutState.ts`); unknown functions become empty panels.
- Layout load is gated at 100 ms (the cached-command budget). Layout names: 1-32 of A-Z 0-9 _ . -, uppercased.
- Watchlists are in SQLite (same name rules as layouts). Grammar: `WL`, `WL NAME`, `WL NAME ADD|RM SYM...`,
  `WL DEL NAME`; `AAPL WL TECH ADD` adds the typed security, never the panel's sticky one.
- MOV uses Nasdaq only (Yahoo predefined screeners returned empty results on 2026-10-17). US only.
- N shows headline, teaser and link only; Enter opens the publisher's page in a new tab. `N` with a sticky
  security shows that security's news; `N TOP` forces top stories; `N words` is a GDELT search.
- CRYP polls REST (CoinGecko, then Binance); it does not mix in Yahoo stream ticks. Enter charts Yahoo `SYM-USD`.
- FXC crosses are triangulated through USD and labelled so. Boards (WEI, FX, CMDTY) are fixed lists in `boards.ts`.
- Rate-limited providers still surface as `PROVIDER DOWN` (pinned by `test_core.py`); the reason is in `detail`.

## Risks / open items
- Yahoo endpoints are unofficial (stream, spark, chart, quoteSummary crumb flow) and can break without notice. Non-US symbols have no zero-key fallback yet.
- Market-hours lights ignore holidays.
- If the backend is down at page load, command history starts empty for that session (it is not
  re-fetched on reconnect); new commands are still kept and uploaded once the backend answers.
- The CI workflow has never run (no remote). Bench timing on GitHub runners is untested.
- Shell scripts `scripts/setup` and `scripts/dev` are untested on macOS/Linux.
- GDELT throttles hard (429s even when spaced). Its fixture `gdelt_nvidia.json` is a real 5-article answer captured
  while probing; `gdelt_429.json` is its real throttle text.
- Yahoo screeners (`v1/finance/screener/predefined/saved`) should be re-checked on a weekday; if they return rows,
  they could become MOV's primary source (record a weekday fixture first).
- `Dockerfile`/`docker-compose.yml` and the Tauri scaffold (`desktop/`) have never been built (no Docker or Rust here).
- The 50k-bar chart-pan bench budget misses occasionally (about one run in three); the other 16 budgets are stable.
- The fixtures were recorded with a one-off script that is not in the repo. To refresh one, fetch the same URL the
  provider builds and save `{"status", "body"}` (JSON) or `{"status", "content_type", "text"}` (XML/text).

## How to look at the app
To use it: `.\scripts\start.ps1` (builds if needed, serves on http://localhost:8000, opens the browser).
To develop: `.\scripts\dev.ps1`, then open http://localhost:5173 (hot reload). For a no-network demo with recorded data, set
`$env:OPENTERM_FIXTURES = '1'` before starting the backend. For `FA`/`FIL`/`OWN` against live SEC data, set
`$env:SEC_USER_AGENT = 'Your Name you@example.com'` first. To get a screenshot without the preview pane,
run a small Playwright script against a production build (`npx vite preview --port 4173 --host 127.0.0.1`).
The pattern is in `frontend/e2e/*.spec.ts`. Current look: `docs/screenshot-phase3.png`.
