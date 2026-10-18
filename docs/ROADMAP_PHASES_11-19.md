# Roadmap: Phases 11-19

Status: **in progress** (Phases 11, 12, 13, 14 and 15 done, Phase 15 including the read-only Kite Connect source; Phase 16 next; Phases 17 and 18 PAUSED by the user on 2026-10-18; order is 15, 16, 19). **Scope decided 2026-10-19:** full scope minus
paid-only data (`TRAN`, `SEG` removed); free sign-up keys allowed; OpenRouter (DeepSeek default) is the only paid
service; roadmap defaults pre-approved. Details: HANDOFF.md "Resume here".

Original status: plan only. Replaces the earlier `ROADMAP_PHASES_11-15.md` draft (which was written
from a partial README read). This version is based on the Vibe-Trading code itself (commit `d0db2e3`,
2026-10-17) and a function-by-function gap list: [FEATURE_GAP.md](FEATURE_GAP.md).

Goal: close the gaps that free or keyed APIs can fill, port the useful parts of
[HKUDS/Vibe-Trading](https://github.com/HKUDS/Vibe-Trading) (MIT), and add an optional AI layer over an
OpenRouter key. Do this without losing speed.

## Rule changes (edit CLAUDE.md when Phase 11 starts)
- Old: "Free data only, zero keys must work."
- New: **Zero keys still works. A key unlocks more.** A function that needs a key shows
  `KEY REQUIRED: set X in SETTINGS KEYS` instead of failing. Paid keys are allowed but never required.
- Keys live in `.env` or the local key store only. Never written to the repo, never in a URL query
  string sent to the frontend, redacted from logs, `/api/perf`, error text and AI traces.
- AI output is **model output, not data.** Every AI panel says `AI · <model> · <time>` and links the tool calls
  that grounded it. An AI answer that used no tool data says `UNGROUNDED`.
- Backtest results are labelled `HISTORICAL SIMULATION, NOT A FORECAST`, with data source, adjusted vs raw
  closes, fees and slippage.
- Orders: paper first. Live orders only if the user turns them on, behind a mandate (symbol allowlist,
  size caps, daily cap) and a kill switch. Order tools never appear in the MCP server or the AI agent.
- Still true: never fake data; test data is labelled; every action works from the keyboard; no Bloomberg
  name, logo or assets on screen; no bypassing bot checks or captchas.
- Ported Vibe-Trading code keeps its MIT notice; Qlib Alpha158 parts keep Apache-2.0 (`THIRD_PARTY.md`).

## Keys to create
Create them when the phase that needs them starts. Free tiers change: re-check limits in each phase spec.

| Key | Cost | Unlocks | Phase |
|---|---|---|---|
| OpenRouter | Pay per use (some free models) | `AI`, `SWARM`, `BRIEF`, AI strategy drafts | 16 (gateway in 11) |
| Finnhub | Free tier | Company and market news, recommendation trend and EPS surprises as an ANR / EEO fallback (built in 13; IPO, estimates and sentiment come keyless from Nasdaq / Yahoo) | 13 |
| Alpaca | Free | Real-time IEX last trades (`RT IEX`, built in 13), news (built in 13); paper trading is Phase 18 (paused) | 13, 18 |
| FMP | Free tier, paid for transcripts/segments | **Not wired** (useful endpoints are paid; Yahoo, Nasdaq and SEC cover Phase 13 keyless) | - |
| FRED | Free | Faster FRED API paths (CSV already works keyless); adapter built in Phase 7 | 7 |
| EIA | Free | Energy inventories (`NRG`) | 19 |
| OpenFIGI | Free (raises rate limit) | `SECF` identifier mapping | 19 |
| Tradier | Free sandbox | Options chain with Greeks fallback | 14 |
| Telegram bot token | Free | Push alerts and briefs | 17 (paused) |
| SMTP (app password) | Free | Email alerts and briefs | 17 (paused) |
| Zerodha Kite Connect | Plan-dependent | Read-only holdings sync, later orders (India) | 18 (paused) |
| IBKR | Free with an account | Read-only portfolio sync via TWS/Gateway | 18 (paused) |
| Optional: Tiingo, Alpha Vantage, Polygon.io, CoinGecko demo, Marketaux | Free tiers | Extra fallbacks in the router | as needed |

No key needed: SEC EDGAR (User-Agent only), FINRA Reg SHO files, CFTC, TreasuryDirect, DBnomics, World Bank,
IMF, OECD, ECB, Ken French library, Deribit, Binance/OKX public, Polymarket/Kalshi public, DefiLlama, NWS.

## Speed plan (every phase)
- **Lazy backend imports.** numpy, pandas/polars, numba, PDF/OCR and LLM clients load on first use, so startup
  and the cached-command budgets do not regress.
- **Heavy work runs as jobs** in a process pool (backtests, Monte Carlo, alpha scans, optimizers, AI runs).
  Progress streams over the existing `/ws`. The event loop and the UI never block.
- **Vectorized paths.** No per-bar Python loops in hot code; numba only where a loop cannot be avoided.
- **Results cached by hash** of strategy + data + parameters. A repeated run returns at once.
- **Large tables use the canvas `Grid`; series use `ChartView`.** No new DOM-heavy tables for big data.
- **Pure parsers/math in their own files** so vitest and pytest test them without `window` or network.
- **Every new function gets a bench budget** in `docs/PERFORMANCE.md`. A phase is not done if
  `node scripts/bench.mjs` regresses.
- **Keyed providers plug into `providers/router.py`** with the circuit breaker, SWR cache and
  `STALE` / `ERR` / `PROVIDER DOWN` / `KEY REQUIRED` labels.
- **AI streams tokens** to the panel; first token budget is set in the Phase 16 spec.

## Build rules
- Sonnet subagents only, 2-3 at a time. Stop at 90% of the 5-hour or weekly window and update HANDOFF.md.
- Each phase starts with a written spec for approval, then tests first, then code.
- One worktree per parallel piece; no two writers on the same files.
- Tests never hit the network: record fixtures from real responses (`providers/fixtures.py`). LLM calls in
  tests use recorded responses too.

## Order and why
11 is plumbing everything else needs. 12 (`BT`) was the most wanted item and reuses the most Vibe-Trading code.
13-15 close data and analytics gaps. 16 adds AI on top, once there are tools worth calling. 17-18 move work
off the screen (push, MCP, brokers). 19 is breadth.

```
11 Keys + jobs + LLM gateway
 ├─ 12 Backtester ─────────────┐
 ├─ 13 Equity research gaps    ├─ 15 Risk, quant, alphas ─┐
 └─ 14 Options, rates, futures ┘                          ├─ 16 AI layer ─ 17 Delivery + MCP ─ 18 Brokers
                                                          │
                                         19 Charting, macro, crypto (any time after 11)
```
12, 13 and 14 touch different files and can run in parallel worktrees (they were built one after another instead).

**Current order (2026-10-18): 11, 12, 13 done; next 14, then 15, 16, 19. 17 and 18 are PAUSED by the user and nothing in 14, 15, 16 or 19
depends on them.** Phase 16 needs the OpenRouter key (ask the user to set it in `APIKEYS` first).

---

## Phase 11: Foundations (keys, jobs, LLM gateway)
**Status: done** (one OpenRouter stream recording is still pending until the key exists; `KEY REQUIRED` and the gateway are tested with fixtures).
Small phase. No big user-facing function, but everything after it depends on it.

| Item | What |
|---|---|
| `APIKEYS` (was `SETTINGS KEYS`; `SETTINGS KEYS` now means keyboard shortcuts) | Enter, test and remove keys. Shows status per provider (OK / invalid / quota). Stored in the local key store (OS keyring if available, else `.env`), redacted everywhere. |
| `KEY REQUIRED` state | New panel state next to STALE / ERR / PROVIDER DOWN, naming the key and the command to set it. |
| Job runner | Process-pool jobs with id, progress over `/ws`, cancel (`Esc` in the panel), result cache by hash. `JOBS` panel lists running and finished jobs. |
| LLM gateway | One backend client for OpenAI-compatible endpoints: OpenRouter (default), Anthropic, OpenAI, Ollama (local, no key). Streaming, tool calls, token and cost accounting, per-day spend cap. No AI functions yet: `SOURCES` shows the gateway health. |
| `THIRD_PARTY.md` | MIT / Apache notices for ported code. |
| CLAUDE.md | Rule changes above. |

**Done when:** keys round-trip and never appear in logs or responses (test greps the log), a dummy job streams
progress and cancels, the gateway passes a recorded-response test, bench unchanged.

## Phase 12: Backtester (`BT`)
**Status: done** (spec `docs/specs/PHASE_12.md`; bench 24/24). The strategy-format decision below was adopted and built.
Port Vibe-Trading's backtest core. **Strategy format decision (proposed):** adopt its `SignalEngine` contract,
`generate(data_map) -> {symbol: Series in [-1, 1]}`, run in a sandboxed worker process (AST checks as in Vibe's
`runner.py`, no network, time and memory limits). Add a short rule syntax for the command line
(`BT AAPL SMA20>SMA50 1D 5Y`) that compiles to the same contract. Phase 16's AI writes the same contract.

| Function | What |
|---|---|
| `BT` | Strategy editor, equity + drawdown chart, trade list, metrics table, benchmark overlay, CSV export (`E` / Alt+X) |
| `BT WF` | Walk-forward folds and purged cross-validation |
| `BT MC` | Monte Carlo and bootstrap: drawdown, Sharpe distribution, p-values |
| `BT RUNS` | Run cards: hashed, reproducible execution records; compare two runs side by side |
| `BT EXPORT` | Pine Script and CSV (MT5 later if asked) |
| `IMPORT` | Bring-your-own bars from CSV/Parquet, labelled `LOCAL DATA` |

**Engine:** vectorized long/short, fees, slippage, position sizing, rebalance masks, `warmup_bars` /
`evaluation_start_date`. Engines in order: global equity (US/UK/EU), India equity (STT, stamp, SEBI, GST cost
stack), crypto spot + perps with funding, futures with multipliers and margin, forex, composite basket.
Options portfolio waits for Phase 14. 15 metrics from Vibe's `metrics.py` (CAGR, Sharpe, Sortino, Calmar, max
drawdown, profit factor, turnover, win rate, VaR/ES, ...).
**Data:** Yahoo/Nasdaq daily first (adjusted closes via `adj`), Binance/OKX for crypto; intraday limited by Yahoo
lookback (DATA_LIMITS.md).
**Done when:** engine unit tests match hand-computed cases and a few cross-checked Vibe-Trading runs, sandbox
escape tests fail closed, e2e for the panel, bench budgets recorded (proposed: 10-year daily single-symbol run
< 300 ms warm, 100-symbol 10-year run < 5 s).

## Phase 13: Equity research gaps
**Status: done** (spec `docs/specs/PHASE_13.md`, actual sources in `docs/DATA_LIMITS.md`; bench 24/24). The Source column below is the original
plan: everything shipped keyless (Yahoo `quoteSummary`, Nasdaq, FINRA, SEC); Finnhub and Alpaca are keyed additions only; FMP is not wired.
`ALRT NEWS` lives in the Phase 13 build; the Phase 17 delivery of alerts (push, email) stays paused. Finnhub and Alpaca shapes are doc-shaped
fixtures, unverified against the live services until a key is set.

| Function | What | Source |
|---|---|---|
| `EE`, `EEO` | Estimates, revisions, EPS surprise history | Finnhub, FMP |
| `ANR` | Ratings and target prices | Finnhub, Yahoo `quoteSummary` |
| `DVD`, `SPLT`, `CACS` | Dividends, splits, corporate actions | Yahoo events, Nasdaq |
| `IPO` | IPO calendar | Nasdaq, Finnhub |
| `SI` | Short interest + daily short volume | FINRA |
| `MGMT` | Officers, board, pay | Yahoo, SEC DEF 14A |
| `EVTS`, `CN` | Company events and news (8-K items, news with sentiment) | SEC, Finnhub, Alpaca |
| `DCF`, `WACC`, `RV` | Valuation from Vibe's engine: a missing input makes the model `NOT RUNNABLE`, never a silent default | FA + EQS data |
| `ETF`, `MEMB` | ETF holdings look-through, index members via ETF proxies | SEC N-PORT, FMP |
| `HDS` diffs | 13F quarter-over-quarter position changes | SEC (port Vibe's diff logic) |
| ~~`TRAN`, `SEG`~~ | **Removed 2026-10-19** (paid FMP only; the user takes no paid data APIs) | - |
| Real-time L1 | Undelayed US quotes in Q / WL / GP; label `RT IEX` vs `DELAYED` | Alpaca, Finnhub websocket |
| News upgrades | Finnhub/Alpaca news sources, keyword alerts | Finnhub, Alpaca |

**Done when:** each provider has recorded fixtures and a DATA_LIMITS entry, each function has e2e coverage
with and without its key (`KEY REQUIRED` path), bench unchanged.

## Phase 14: Options, rates, futures
**Status: done** (spec `docs/specs/PHASE_14.md`, actual sources in `docs/DATA_LIMITS.md`; bench in `docs/PERFORMANCE.md`). Everything shipped keyless except Tradier (optional `TRADIER_TOKEN`, doc-shaped fixture).
| Function | What | Source |
|---|---|---|
| `OMON` | Chain with Greeks, OI, volume; `PCR` put/call | Yahoo options (crumb), Tradier fallback |
| `OV` | Pricer: Black-Scholes, binomial, Heston, barrier; IV solver | Vibe `quantlib.options`, `volatility` |
| `OVDV`, `SKEW` | IV surface (canvas heat grid + smile chart) | Fitted from the chain; crypto from Deribit |
| `HIVG` | Realized vs implied vol | Bars + chain |
| `OSA` | Multi-leg payoff, scenario grid, Greeks by leg; feeds the `BT` options engine | Vibe `options_payoff` |
| `YAS` | Bond price/yield, duration, convexity, key-rate duration | Vibe `quantlib.fixedincome` |
| `SWPM`, `CDSW` | Swap and ISDA-style CDS calculators (user inputs, no market quotes) | Vibe `quantlib.credit` |
| `WIRP` | Implied policy path from fed funds futures | Yahoo per-contract quotes |
| `RATES` upgrade | Non-US curves (ECB, BoE, others where daily data exists), Nelson-Siegel fit, credit spreads (FRED OAS), Treasury auctions | ECB, BoE, FRED, TreasuryDirect |
| `CT` | Futures term structure, contango/backwardation, roll yield | Yahoo per-contract |
| `COT` | CFTC positioning with history chart | CFTC |
| `FXFA` | FX forwards from rate differentials (labelled as a CIP estimate) | Computed |

**Done when:** pricer tests match textbook values, surface fit tested on a recorded chain, e2e, bench budget
for the surface render recorded.

## Phase 15: Risk, quant library, alphas (DONE 2026-10-18)
**Built** (spec `docs/specs/PHASE_15.md`, steps 1-8; bench budgets in `docs/PERFORMANCE.md`). Kite is built read-only; its fixtures are doc-shaped, a real recording is pending a key (`scripts/record_phase15.py --kite`). `ALPHA` ships 29 factors; the other ~450 of the 478 are not ported.

| Function | What |
|---|---|
| `RISK` | Portfolio X-ray on `PORT`: VaR/ES (historical, parametric, EVT), beta, drawdown, tail risk, stress replays (2008, 2020, 2022) |
| `PORT OPT` | Optimizers: equal vol, risk parity, mean-variance, max diversification, turnover-aware, HRP; constraints and caps; preview trades before applying |
| `PORT ATTR` | Brinson-Fachler attribution; TWR / MWR / Modified Dietz / XIRR |
| `FACT` | Factor exposures vs Fama-French 5 + momentum (Ken French library) |
| `QL` | Calculator panel over the ported `quantlib` (only functions with tests): GARCH, cointegration, OU fit, copulas, VPIN/Roll/Amihud/Kyle, event study, deflated Sharpe |
| `ALPHA` | Alpha Zoo: start with 20-30 factors, measure, then port the rest of the 478 (Qlib158, Alpha101, GTJA191, academic, fundamental). IC / IR / decay over the `EQS` universe; alive / reversed / dead labels |
| `CORR REGIME` | Correlation regime timeline (edge density + hysteresis) on `CORR` |
| `KITE` data source | Zerodha Kite Connect, READ-ONLY (user decision 2026-10-19, overrides "no paid data APIs" for this one source): keys `KITE_API_KEY` / `KITE_API_SECRET` pasted in `APIKEYS`; daily login flow (loopback redirect, one-day access token, `KITE LOGIN EXPIRED` status, never automated); instrument-token cache; WebSocket ticks (`RT KITE`) into the streaming hub; Indian historical bars; NSE/NFO/MCX option chains and futures with OI for `OMON` (Greeks computed with `openterm/quant`, labelled). NO order placement, no order tools anywhere. Inert without a key (`KEY REQUIRED: set KITE_API_KEY in APIKEYS`). Doc-shaped fixtures, labelled NOT a recording |

**Done when:** ported functions carry their Vibe tests (rewritten to pytest without network), alpha scans run as
jobs with a bench budget, lookahead sentinel test ported, e2e.

## Phase 16: AI layer (OpenRouter key)
Off until a key is set. The agent calls OpenTerm's own backend APIs as tools, so answers rest on the same data
the panels show.

| Function | What |
|---|---|
| `AI` | Research chat panel. Tools: quotes, history, FA, filings, news, screener, options chain, backtest, portfolio, quantlib. Port Vibe's loop guard (stop after repeated failed or empty tool calls), context budget and grounding checks. Streams tokens; every number cites its tool call |
| `AI BT` | Natural language to a `SignalEngine` strategy, then run in `BT`; shows the code before running |
| `AI DOC` | Read a filing or uploaded PDF/DOCX/XLSX (OCR optional) and answer questions about it |
| `AI CHART` | Describe the current `GP` chart with a vision model (labelled as model output) |
| `SWARM` | Multi-agent presets ported from Vibe (start with investment committee, risk committee, earnings desk, macro desk, quant desk); step retry and replay |
| `THESIS` | Notes and theses per ticker with status, linked run cards, invalidation rules; `AI AUTO` runs hypothesis -> backtest -> evidence report |
| Skills | Port a short list of Vibe's 90 finance playbooks as prompt files (valuation, earnings, options, risk, macro) |
| Audit | Run manifest (prompt, skills, tool registry, versions hashed) and hash-chained audit ledger for AI, BT and orders |

Model choice: any OpenRouter model, set in `SETTINGS AI`. Vibe-Trading's own guidance applies: small or "lite"
models call tools badly and answer from memory, so the default should be a strong tool-calling model, with a
cheaper one selectable. Spend cap per day from Phase 11.
**Done when:** recorded-response tests for the loop guard and grounding, an e2e with a recorded model, first
token budget recorded, no key = `KEY REQUIRED`, and keys never reach the frontend.

## Phase 17: Delivery, MCP, API

**PAUSED (2026-10-18):** the user does not need real-time alerts or delivery. Do not spec or build unless asked.
| Item | What |
|---|---|
| Server-side alerts | Backend evaluates `ALRT` rules so they fire with the tab closed; frontend alerts stay as the fast path |
| Push | Telegram bot, email (SMTP), desktop notification (Tauri or browser Notification API) |
| `BRIEF` | Scheduled briefs (pre-market, close, weekly portfolio) built from panel data, optional AI summary |
| MCP server | Exposes read tools (quotes, history, FA, filings, news, screener, options, backtest, portfolio read). No order tools |
| MCP client | Optional: load tools from other MCP servers into `AI` |
| API | REST + CSV + a small Python client so scripts and Excel (Power Query) pull OpenTerm data |
| `JRNL` | Import a broker trade journal (Zerodha, IBKR, Alpaca CSV), behaviour diagnostics, Shadow Account comparison vs a rule-based version |

**Done when:** alerts fire with no browser open (test), MCP tools listed and called by a test client, e2e.

## Phase 18: Brokers and orders

**PAUSED (2026-10-18):** same reason as Phase 17. Phase 19 has no dependency on 17 or 18.
In this order, each one a separate approval:
1. **Paper trading** (Alpaca paper): `ORD` ticket, blotter, fills into `PORT`.
2. **Read-only sync**: Zerodha Kite holdings, IBKR via TWS/Gateway, Alpaca live account read.
3. **Live orders** only if the user asks: mandate (allowlist, size and exposure caps, daily trade cap), confirm
   step per order, kill switch (one key, cancels all and blocks new orders), every order in the audit ledger.
   Paper vs live decided by a structural broker check (host or account type), never a flag the AI can set.

## Phase 19: Charting, discovery, macro, crypto
| Area | Items |
|---|---|
| `GP` | Drawing tools (trend line, horizontal, fib), event markers (earnings, dividends, splits), multi-pane compare, more studies, pattern overlays (candlestick, Ichimoku, SMC), `SEAS` seasonality |
| `GIP` | Intraday tick chart from live ticks since the session open |
| `IMAP` | Sector / market-cap heat map from `EQS` (canvas) |
| `SECF` | Fuzzy finder with FIGI mapping (OpenFIGI) |
| Macro | `ECST` / `WECO` world stats (DBnomics, World Bank, IMF, OECD, ECB); `CENB` central bank calendars; FOMC dates in `ECO`; exchange holidays in market lights |
| Commodities | `NRG` (EIA), `WETR` (NWS / Open-Meteo) |
| Crypto | Order book depth (Binance/OKX), perp funding and basis, liquidations, stablecoin supply, DeFi yields (DefiLlama), token unlocks |
| `PRED` | Prediction market odds (Polymarket, Kalshi public APIs), labelled as market-implied probability |
| Non-US data | Zero-key fallbacks for India (.NS/.BO) and other markets beyond Yahoo |

---

## Open decisions (settle in the Phase 11 or 12 spec)
1. **Strategy format:** decided and built in Phase 12 (Vibe's `SignalEngine` contract + a rule shortcut).
2. **Default AI model** on OpenRouter, and the daily spend cap.
3. **Market priority:** US first, or US + India together (the India cost model and Zerodha sync are ready to port).
4. **Live orders:** Phase 18 is paused by the user (2026-10-18); decide when it is unpaused.
5. **Paid keys:** decided 2026-10-19: skip them (`TRAN`, `SEG` removed).

## Gaps vs OpenBB with no phase (2026-10-18)
Python SDK / DataFrame API, third-party extension system, user-facing provider switch (same command on Yahoo, FMP, Polygon),
hosted workspace. The SDK and REST API would build on the paused Phase 17 API work. Decide before unpausing 17.

## Not reachable even with keys
See the end of [FEATURE_GAP.md](FEATURE_GAP.md).

## Deferred from earlier phases (still open)
1. First real Docker and Tauri builds.
2. Re-run the tick-to-pixel bench on a quiet machine (55-59 ms vs 50 budget in the last session).
