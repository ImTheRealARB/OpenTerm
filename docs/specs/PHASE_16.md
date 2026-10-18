# Phase 16: AI layer (spec, 2026-10-18)

Status: approved by the standing instruction "defaults pre-approved" (HANDOFF.md). Source: `docs/ROADMAP_PHASES_11-19.md` "Phase 16".
Inputs that already exist: the Phase 11 gateway (`openterm/llm/`: `Gateway.chat()` streams `Event`s, spend cap, KEY REQUIRED, redaction), the job
runner (`openterm/jobs/`), `POST /api/quant/{fn}`, `POST /api/bt/run`, `/api/bt/strategies` and every GET route the panels use.
OpenRouter key is set in APIKEYS (never printed, never in the repo, never reaches the frontend).

## Rules that apply to every step
- **AI output is model output, not data.** Every AI panel header says `AI · <model> · <time>` and lists the tool calls that grounded the answer. An answer with no
  tool data says `UNGROUNDED`. A number the model writes that matches no tool result is flagged `UNSOURCED` (grounding check, below).
- **Order tools never exist** in the AI tool registry (a test scans tool names and routes for `order`, `kite`, `gtt`, `margin`, `holding`). Kite has no tool at all.
- **No key = `KEY REQUIRED: set OPENROUTER_API_KEY in APIKEYS`.** Keys, prompts and tool results are never logged; error text goes through `redact`.
- **Tests never hit the network.** LLM calls in tests use recorded streams (`backend/tests/fixtures/llm_*.txt`) fed through a fake transport; the recordings are made once
  with the real key by `scripts/record_llm.py` (the pending Phase 11 recording is made in step 1).
- Speed: AI work never touches the hot path. The AI modules import lazily (the gateway is already built on first use); cold start and all existing budgets must not move.

## Defaults decided here (change only with the user)
| Topic | Decision |
|---|---|
| Transport | `POST /api/ai/chat` answers `text/event-stream` (SSE), consumed by `fetch` + `ReadableStream` in the panel. No `/ws` change. Loopback only (like strategy writes). |
| Default model | `deepseek/deepseek-v4-pro` on OpenRouter (tool calling, US$0.21 / 0.42 per million tokens on 2026-10-18). Vision (`AI CHART`): `deepseek/deepseek-v4.1-flash`. Both selectable in `SETTINGS AI` (setting `ai.model`, `ai.vision_model`, `ai.provider`); a model not on the price list is refused under the cap (existing gateway rule). Small / free models are selectable but the panel warns `LITE MODELS CALL TOOLS BADLY`. |
| Tool backend | In-process ASGI calls to the app's own `/api/...` routes (`httpx.ASGITransport`), through an allow-list in `ai/tools.py`. So tools return exactly what the panels show, with the same source / age / STALE labels. |
| Tool set | `quote`, `history`, `profile`, `fa` (financial statements), `filings`, `news`, `screener`, `options_chain`, `rates`, `macro`, `portfolio` (read), `backtest_run` (rule or code), `backtest_get`, `quant` (risk, fact, ql, alpha, regime). All read-only except `backtest_run`, which only writes a run (the existing BT store). |
| Loop | Max 8 model rounds and 24 tool calls per question. **Loop guard** (ported idea from Vibe-Trading): stop after 3 consecutive failed or empty tool calls, or the same call (name + canonical args) repeated 2 times; the answer then says `STOPPED: <reason>` and keeps what was gathered. |
| Context budget | Tool results are truncated to 6 000 characters each (head + tail, marked `...N ROWS OMITTED`); history is dropped oldest-first (tool results before user turns) to stay under 24 000 tokens (estimated chars/4). |
| Grounding check | After the answer, every number token in it (ignoring years, list indexes, tool-call ids) is matched against the numbers in this turn's tool results (tolerance 0.5% relative, percent and fraction forms). Unmatched numbers are listed under the answer as `UNSOURCED NUMBERS: ...`; zero tool calls = `UNGROUNDED`. The model is also told to cite `[T1]`, `[T2]` ids; the panel renders them as links to the tool-call list. This is a check, not a proof. |
| Spend | Gateway cap from Phase 11 applies; the panel header shows `US$ today / cap`. A turn's cost is the sum of its `usage` events. |
| Persistence | Chats live only in the browser panel (not saved) in step 2; the audit ledger (step 6) stores hashes and metadata, not prompts, unless the user turns on `ai.store_text`. |
| First-token budget | The model's own latency is network and not ours to gate. We budget what we control: **request to first SSE event from our server <= 60 ms** (cached prices, no blocking work before streaming) and **panel open (`AI` typed) to input ready <= 100 ms**, both gated in the bench with a fake model stream. |

## Steps (tests first in each, then code; one full gate, commit and push per step)
1. **Core agent, backend only.** Tests first (`test_phase16_agent.py`, strict xfail until built): tool registry (allow-list, schemas, no order tools), ASGI tool calls against the fixtures, loop
   guard, context budget, grounding check, the agent loop over a scripted fake gateway, SSE route, `KEY REQUIRED`, key never in responses or logs. Record the pending Phase 11 OpenRouter
   stream and one tool-call round with the real key. Code: `openterm/ai/` (`tools.py`, `agent.py`, `ground.py`, `guard.py`, `context.py`), `POST /api/ai/chat`, `GET /api/ai/tools`.
2. **`AI` panel + `SETTINGS AI`.** Streaming chat panel (tokens, tool-call list with source and age, `[T1]` links, UNGROUNDED / UNSOURCED, spend, model, Esc cancels), settings for model and caps,
   KEY REQUIRED state, e2e with a recorded model, bench for the two budgets above.
3. **Skills + `AI BT` + `AI CHART`.** A short set of finance playbooks as prompt files (valuation, earnings, options, risk, macro) in `backend/openterm/ai/skills/*.md`, chosen by the agent via a `skill`
   tool; `AI BT <idea>` drafts a strategy (rule string or `SignalEngine` code), validates it with the existing sandbox, shows the code, and only runs it in `BT` on Enter; `AI CHART` sends
   the current `GP` chart (client-rendered PNG) to the vision model, labelled model output.
4. **`AI DOC`.** Filing text from the SEC provider, or an uploaded PDF / DOCX / XLSX (loopback upload, parsed locally with stdlib + the libraries already in the lock file; OCR optional and off),
   chunked, question answering with chunk citations.
5. **`SWARM` + `THESIS` + `AI AUTO`.** Preset multi-agent runs (investment committee, risk committee, earnings desk, macro desk, quant desk): a fixed DAG of agent roles over the same
   loop, each role with its own tool allow-list, step retry and replay from the stored run; `THESIS` notes per ticker (SQLite `theses`, status, invalidation rules, linked run cards);
   `AI AUTO` = hypothesis -> backtest -> evidence report.
6. **Audit.** Run manifest (prompt hash, skills, tool registry, versions) and a hash-chained ledger (`ai_ledger` table) for AI, SWARM and BT; `AUDIT` panel verifies the chain.
7. **Close.** Bench (29 + AI budgets), docs (COMMANDS, CHANGELOG, DATA_LIMITS, HANDOFF, roadmap, CLAUDE.md), push, report.

Scope control: if a step runs out of budget, steps are cut from the END (7 stays, 6 then 5 then 4 may be marked NOT BUILT in the roadmap with the reason). Steps 1-3 are the core.

## Done when (from the roadmap)
Recorded-response tests for the loop guard and grounding, an e2e with a recorded model, first-token budget recorded, no key = `KEY REQUIRED`, keys never reach the frontend.

## Progress log
- **Step 4 done (2026-10-18):** `ai/doc.py` (stdlib parsers for TXT / CSV / HTML / DOCX / XLSX, `pypdf` for PDF: the one new dependency, pure Python), `POST /api/ai/doc/upload|filing|ask`, `doc_search` tool (offered only to a DOC run), panel `AI DOC`, `U` upload.
  The filing fetch goes through the SEC provider (rate limit, User-Agent); in fixture mode only the filing LIST is recorded, so the document fetch is tested with a patched provider and has NOT been run against live SEC.
- **Step 3 done (2026-10-18):** `ai/skills/*.md` + `skill` and `strategy_check` tools, `POST /api/ai/bt` (BT_DRAFT line parsed, validated with `bt.rules`, `draft` / `draft_error` events, nothing run) and `POST /api/ai/chart` (image data URL to the vision model, no tools), panel modes `AI BT` and `AI CHART`,
  `chart/shot.ts` + `ChartHandle.screenshot()`. AI BT drafts rule strings only (no `SignalEngine` code): a code draft needs the sandbox review flow, left out.
- **Step 1 done (2026-10-18):** `openterm/ai/` (`tools.py` 14 tools via in-process ASGI, `agent.py`, `guard.py`, `context.py`, `ground.py`, `routes.py`), `POST /api/ai/chat` (SSE) and `GET /api/ai/tools`,
  27 tests in `test_phase16_agent.py`. Recorded with the real key: `llm_openrouter_stream.txt` (the pending Phase 11 recording; `deepseek/deepseek-v4-pro` is a reasoning model, so give it >= 400 output tokens),
  `llm_tool_turn1.txt` / `llm_tool_turn2.txt` (tool call, then answer; test tool whose argument is `symbol`). Full gate green: 1233 passed, 0 xfail.
- **Step 2 done (2026-10-18):** `AI` panel (`functions/AI.tsx`, pure logic in `aiStream.ts`), `SETTINGS AI MODEL|VISION|PROVIDER|RESET` (+ backend `ai` settings field), fixture-mode OpenRouter routes (price list + the two recorded turns, labelled RECORDED), e2e `phase16.spec.ts` (7), bench budgets in `docs/PERFORMANCE.md` "Phase 16 bench" (31 total; BT 10-year miss is machine throttling, controlled against `df5325e`).
