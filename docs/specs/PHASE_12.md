# Phase 12 spec: backtester (`BT`)

Status: **spec written 2026-10-19, waiting for approval.** Tests come next, then code.
Source: [ROADMAP_PHASES_11-19.md](../ROADMAP_PHASES_11-19.md) "Phase 12", [FEATURE_GAP.md](../FEATURE_GAP.md) rows for
`agent/backtest/*`, and the Vibe-Trading code itself at commit `d0db2e3` (MIT; read 2026-10-19).

## Decisions (proposed defaults; change any of them before the tests step)

| # | Decision | Proposed default | Why |
|---|---|---|---|
| A | Engine shape | **Port Vibe's bar-loop engine** (`engines/base.py` `BaseEngine`: signals shifted one bar, filled at the **next bar's open**, then market-rule hooks `can_execute` / `round_size` / `calc_commission` / `apply_slippage` / `on_bar`). Signals, indicators and target weights stay vectorized (pandas); only order execution loops over bars | The roadmap said "vectorized", but Vibe's engine is event-driven per bar, and its lot rounding, T+1, circuit bands, funding and margin need the loop. A 10-year daily run is ~2,520 iterations, well inside the budget |
| B | New dependencies | **numpy + pandas** (Vibe's contract hands `pd.Series` around). Imported **only inside job workers**, never by the server process. No numba, no polars | Cold start and the server's import time stay unchanged; the job runner already keeps heavy imports in workers |
| C | Engines in Phase 12 | **Global equity (US, UK, HK, Canada), India equity (delivery cost stack), crypto spot + perpetuals (funding), forex, global futures (multipliers, margin), composite basket.** Skipped: China A, China futures, Korea, Vietnam, Brazil (unless you ask). Options portfolio waits for Phase 14 | Roadmap market priority: US first, India cost stack ported because it is cheap |
| D | Where data comes from | **The server fetches bars through the existing router** (Yahoo / Nasdaq daily, `adj` adjusted closes; Binance klines, keyless, new endpoint for crypto) and **passes arrays to the worker**. Workers never open a network connection | Reuses the SWR cache and fixtures; makes "no network in the sandbox" enforceable |
| E | Strategy sandbox | **Allowlist**, not Vibe's denylist: imports limited to `numpy`, `pandas`, `math`, `statistics`, `typing`, `dataclasses`, `functools`, `itertools`, `collections`, `datetime`; restricted builtins (no `open`, `exec`, `eval`, `compile`, `__import__`, `getattr` on dunders, `globals`); AST checks ported from Vibe's `runner.py` (no decorators, literal defaults, no class-level statements). The worker disables `socket` before running user code. Limits: **60 s per run**, **1 GB RSS** (watchdog in the job runner via `psutil`, a new small dependency; Windows has no `resource` module) | Defence in depth. It is not a kernel sandbox: code only runs from the user's own machine (loopback), and the docs say so |
| F | Rule syntax (command line) | `BT <SYMS> <RULE> [INTERVAL] [RANGE] [OPTS]`, e.g. `BT AAPL SMA20>SMA50 1D 5Y`, `BT SPY,QQQ RSI14<30 1D 10Y SHORT FEES=5 SLIP=5`. Terms: `CLOSE`, `OPEN`, `SMA<n>`, `EMA<n>`, `RSI<n>`, `HIGH<n>` / `LOW<n>` (rolling), `RET<n>` (n-bar return), numbers; comparisons `> < >= <=`, `CROSS>` / `CROSS<`; `AND` / `OR`. Long-only by default; `SHORT` allows -1. Options: `FEES=` and `SLIP=` (basis points), `CASH=`, `BENCH=` (default SPY for US, ^NSEI for India, BTC-USD for crypto), `MKT=` engine override. Compiles to the same `SignalEngine` contract | Phase 11 decision 1 (approved): one contract, two ways to write it |
| G | Storage | SQLite **migration 9**: `strategies (name PK, code TEXT, kind 'python'|'rule', created_at, updated_at)` and `bt_runs (id PK = run hash, strategy, config BLOB, data_fingerprint, metrics BLOB, equity BLOB, trades BLOB, created_at)`, trimmed to the **last 200 runs**. Equity and trades stored msgpack + zlib | Run cards must be reproducible and comparable after a restart |
| H | Metrics | Vibe's `calc_metrics` set: final value, total / annual return, max drawdown, Sharpe, Sortino, Calmar, win rate, profit/loss ratio, profit factor, max consecutive losses, average holding days, trade count, benchmark return, excess return, information ratio, tracking error, beta, average / total turnover; plus VaR 95 and ES 95 of bar returns | Same numbers as Vibe so cross-checks are exact |
| I | Validation in Phase 12 | `BT MC` = Vibe's `monte_carlo_test` (trade-order permutation) + `bootstrap_sharpe_ci`; `BT WF` = Vibe's `walk_forward_analysis`. **Purged cross-validation moves to Phase 15** with the quant library it lives in (`quantlib/crossvalidation.py`) | Keeps Phase 12 to the backtest folder |
| J | `BT EXPORT` | CSV (equity, trades, metrics) for every run; **Pine Script only for rule-syntax strategies** (Python code cannot be translated faithfully; the command says so) | No fake translations |
| K | `IMPORT` | **CSV only** (`date,open,high,low,close[,volume]`), stored per symbol in SQLite, labelled `LOCAL DATA` everywhere it appears. Parquet later (needs pyarrow, ~30 MB) | Small, keyless |
| L | Labels | Every BT result: `HISTORICAL SIMULATION, NOT A FORECAST`, data source(s) and age, `ADJ` or `RAW` closes, fees and slippage in bps, engine, warm-up bars. Synthetic or local data is labelled as such | CLAUDE.md rule |
| M | Keyring (Phase 11 finding) | `keyring` is **not installed** in the backend environment, so APIKEYS currently writes keys to `.env`. Proposed: add `keyring` to `pyproject.toml` in Phase 12 step 3 (lazy import already in `keys.py`) | Phase 11 decision B said new keys go to the OS keyring |

## 1. Strategy contract
```python
class SignalEngine:
    def generate(self, data_map: dict[str, pd.DataFrame]) -> dict[str, pd.Series]:
        """data_map: symbol -> DataFrame indexed by timestamp with open, high, low, close, volume (+ adj_close).
        Returns symbol -> Series of target weights in [-1, 1] on the same index (NaN = 0)."""
```
- Rule syntax compiles to a generated `SignalEngine` (pure function, `bt/rules.py`, parser in its own file so pytest
  covers it without pandas; the frontend has a matching parser for autocomplete and errors).
- Python strategies are typed in the BT editor (a `<textarea>` in the panel, not the command line) and saved by name
  (`BT SAVE name`, `BT LOAD name`, `BT DEL name`).
- Weights across symbols are normalized as in Vibe's `_align` (sum of |w| <= leverage). Optimizers (`backtest/optimizers`)
  wait for `PORT OPT` in Phase 15.

## 2. Engine (`backend/openterm/bt/`, runs in job workers)
- `bt/engine.py`: `BaseEngine` port (positions, fills, trades, equity snapshots, hold vs rebalance mode, rebalance
  tolerance, warm-up / `evaluation_start_date`, lot rounding, plan rejections reported in the metrics).
- `bt/engines/`: `global_equity.py`, `india_equity.py`, `crypto.py` (spot + perps funding, liquidation), `forex.py`,
  `futures.py` (multipliers, margin), `composite.py`. Default costs exactly as Vibe ships them (US zero commission,
  0.05% slippage; India STT 0.1% bilateral, exchange 0.00297%, SEBI 0.0001%, stamp 0.015% buy, GST 18%; UK SDRT 0.5%
  buy; HK stamp 0.1% + levies). The rates are config-driven and shown in the result header.
- `bt/metrics.py`: `calc_metrics`, `bar_returns`, turnover, by-symbol and by-exit-reason stats (ported).
- `bt/validation.py`: Monte Carlo, bootstrap Sharpe CI, walk-forward (ported).
- `bt/sandbox.py`: AST allowlist + restricted builtins + socket off (decision E).
- Job kinds registered in `jobs/registry.py`: `bt.run`, `bt.mc`, `bt.wf`. Hash = strategy code + config + data
  fingerprint (sha256 of the bars), so a repeated run returns at once (`cached: true`).
- Every ported file starts with a docstring naming its Vibe source file and commit; `THIRD_PARTY.md` gets one row each.

## 3. API
- `POST /api/bt/run` `{strategy | code | rule, symbols, interval, range | start/end, engine, options}` -> job (the
  server fetches bars first; `KEY REQUIRED` / `STALE` / `PROVIDER DOWN` surface before the job starts).
- `GET /api/bt/runs` (cards: id, strategy, symbols, period, headline metrics), `GET /api/bt/runs/{id}` (full result),
  `DELETE /api/bt/runs/{id}`. `GET/PUT/DELETE /api/bt/strategies[/{name}]`. `POST /api/bt/import` (CSV body).
  `GET /api/bt/runs/{id}/export?fmt=csv|pine`.
- Progress and results come through the existing `J` frames.

## 4. Frontend
- `BT` panel: header with labels (decision L); equity + drawdown + benchmark in `ChartView` (one chart, drawdown as a
  second pane); metrics table and trade list in the canvas `Grid`; `Tab` cycles CHART / METRICS / TRADES / CODE.
  Keys: `R` re-run, `S` save, `M` Monte Carlo, `W` walk-forward, `E` / Alt+X CSV, `X` cancel the running job.
- `BT RUNS`: run cards in a `Grid`; `Enter` opens, `C` marks two runs and shows them side by side (metrics diff, two
  equity lines).
- `BT MC` / `BT WF`: histogram / fold table views of the job result.
- `IMPORT`: paste or pick a CSV file, preview the first rows, `Enter` stores; `LOCAL DATA` label in GP/BT afterwards.
- Pure helpers for vitest: `bt/ruleParse.ts`, `bt/metricsFormat.ts`, `bt/csvImport.ts`.

## Tests (written first, in the tests step)
Backend (`tests/test_phase12.py`, no network):
- Engine against hand-computed cases: one long trade with next-bar-open fill, fees and slippage; a flip long -> short;
  hold vs rebalance mode; warm-up skip; lot rounding (HK board lot, India whole shares); India cost stack on a known
  notional; UK SDRT penny rounding; crypto funding on a perp position.
- Cross-checks: three runs (US SMA cross, India RSI, BTC perp) executed once with Vibe-Trading's own engine at
  `d0db2e3` on the same fixture bars (in a throwaway venv in the tests step); their metrics stored as expected values.
- Metrics: each metric on a fixed equity curve against hand-computed numbers.
- Rule parser: valid and invalid rules, error positions; compiled signals equal a hand-written `SignalEngine`.
- Sandbox: blocked import, `open`, `__import__`, dunder `getattr`, socket use, infinite loop (time limit), large
  allocation (memory watchdog) all fail closed with a clear error; an allowed strategy runs.
- Jobs: same strategy + data -> `cached: true`; changed data -> new hash.
- API: run, list, get, delete, strategies CRUD, CSV import round trip, export CSV and Pine for a rule run.
Frontend:
- vitest: rule parser, metrics formatting, CSV import parsing.
- Playwright `e2e/phase12.spec.ts` (mocked routes + `J` frames): `BT AAPL SMA20>SMA50 1D 5Y` shows progress then the
  labelled result; Tab through views; `E` exports; `BT RUNS` compare two runs; `IMPORT` preview + store; a bad rule
  shows the parser error at the right column.

## Recording needs (keyless)
- Yahoo `v8/chart` 10Y daily for AAPL, SPY, RELIANCE.NS, ^NSEI (adjusted closes included).
- Binance `api/v3/klines` BTCUSDT 1d (spot) and `fapi/v1/klines` + `fapi/v1/fundingRate` BTCUSDT (perps).
- No key is needed for Phase 12.

## Performance budgets
- Unchanged: every existing bench budget. The server never imports numpy/pandas (asserted in a test).
- New, gated in `scripts/bench.mjs`: 10-year daily single-symbol rule run, data cached, worker warm: **submit to done
  < 300 ms** server-side; cached run (same hash) **< 20 ms**; `BT` result open to first paint **< 100 ms**.
- Measured, reported: 100-symbol 10-year run (target **< 5 s**), worker cold start with pandas import.

## Steps (each one a commit)
1. Spec (this file). **Done when you approve it** (or change the defaults above).
2. Tests set: all tests above failing for the right reason; fixtures recorded; Vibe cross-check values generated.
3. Engine core: `bt/engine.py`, `metrics.py`, global equity engine, rule syntax, sandbox, job kinds, migration 9, API
   (`keyring` dependency if decision M stands).
4. `BT` panel (frontend) with chart, metrics, trades, code views and labels; bench budgets.
5. Engines: India, crypto (spot + perps), forex, futures, composite; Binance klines adapter.
6. `BT MC`, `BT WF`.
7. `BT RUNS` compare and `BT EXPORT` (CSV, Pine).
8. `IMPORT` (CSV, `LOCAL DATA`).
9. `THIRD_PARTY.md` rows, docs (`DATA_LIMITS.md`, `COMMANDS.md`, `ADDING_A_FUNCTION.md` if needed), phase verification.

Steps 3 and 4 (backend and frontend halves) can run as two Sonnet subagents at once; so can 5 and 6.
