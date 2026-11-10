# Phase 20: delivery, server-side alerts, briefs, wider AI, 30 Vibe presets, skills, MCP, Filings Intelligence (spec, 2026-11-05)

Status: written from the user's Phase 20 brief; defaults below are decided here (change only with the user).
Out of scope (do not touch): brokers, paper trading, order entry, JRNL / Shadow Account, China A-share data, Pixel Office, IM channels other than Telegram and email, Gildata, desktop / Docker packaging.
Inputs that already exist: `keys.py` (`telegram`, `smtp` keys with connection tests), `alerts` table (migration 7) and `news_alerts.py` (migration 11), `streaming/hub.py`,
`scheduler.py` (apscheduler), `ai/` (agent, 18 tools, swarm with 5 presets, skills with 5 files, audit ledger, store), SEC provider (`sec.py`), Phase 11 daily LLM spend cap.

## Rules that apply to every step
1. **Delivery is a convenience, not a source of truth.** A pushed message states the rule, the value, the data source, the data age and `OPENTERM · <local time>`. Never "buy" or "sell".
2. **Never alert on bad data.** Server-side alerts skip `STALE`, `SYNTHETIC` and fixture ticks. A skipped alert is recorded with its reason and shown in `ALRT`.
3. **Honest limits.** Server-side alerts run only while the backend runs; `ALRT` says `ACTIVE WHILE OPENTERM RUNNING`. No cloud relay.
4. **No double notification.** The backend is the only place that fires and records a trigger; the browser only shows state.
5. **Secrets** (bot token, SMTP password, chat id, recipients) never reach the frontend, a URL, a log, a trace, error text or command history (`redact()` on every error path). Email uses STARTTLS or SSL with certificate verification on; plain SMTP only on loopback.
6. **No order tools** in AI, swarm or MCP. A test scans tool names for `order trade gtt margin kill` and write-style `holdings`.
7. **AI rules unchanged:** `AI · <model> · <time>`, tool calls linked, `UNGROUNDED` without tool data, ledger records the run (hashes only, unless ai.storeText is on).
8. **A ported preset or skill never names a tool OpenTerm lacks.** A role that needs a missing tool makes the preset `PARTIAL` (capability shown on screen) or `UNAVAILABLE` (reason shown). No role runs ungrounded behind a complete-looking panel.
9. **Cost is shown before it is spent:** worst-case tokens and USD, daily cap checked, before any swarm run starts.
10. **Licences:** every ported file has a header naming source path and commit (`HKUDS/Vibe-Trading @ cb99dca`, MIT) and a `THIRD_PARTY.md` row (one per ported directory), plus Vibe's `NOTICE` wording where it applies. OpenTerminalUI is a design reference only: no code copied.
11. **Speed:** none of this touches a hot path. Delivery, swarm and filings code import lazily; all 37 bench budgets must hold.
12. **Tests never hit the network or a real LLM** (scripted `FakeGateway`, fake transports, recorded fixtures). Zero LLM spend in tests and demos.

## Defaults decided here
| Topic | Decision |
|---|---|
| Branch | Stay on the worktree branch `claude/openterm-phase-20-6aa57a`. No commit or push until the user says so. |
| Telegram | Bot API over `httpx`. MarkdownV2 with a tested escaper; messages split at 4,096 chars on line boundaries; 429 honours `retry_after`. Pairing: `NOTIFY PAIR` shows the bot link, polls `getUpdates` for `/start`, stores the chat id in settings (backend only; the frontend gets `paired: true`). |
| Email | stdlib `smtplib` in `asyncio.to_thread`; `ssl.create_default_context()` (verification on) for STARTTLS and SSL; plain only when host is loopback; plain-text part plus a simple HTML part. Closes the deferred "SMTP TLS verification" item. |
| Outbox | New migration (15 expected; confirm from `TABLES_BY_VERSION`): `outbox(id, channel, kind, body_hash, status queued/sent/failed/skipped, attempts, error redacted, created_at, sent_at)`. Retry with exponential backoff (30 s, 2 min, 10 min, then failed). Daily cap per channel (default 50). Body text is kept only until sent; the hash stays. |
| Fixture mode | Never sends: the outbox row is `skipped: FIXTURE MODE` and `NOTIFY` says so. |
| Alert syntax | `ALRT AAPL > 200 VIA TG,EMAIL`; no `VIA` = in-app only (existing rules unchanged). Migration adds `channels` column to `alerts` and `news_alerts`. |
| Alert engine | `alerts_engine.py` subscribes through the hub (refcounted, as a panel would), evaluates raw ticks and each news refresh, fires once per arm, writes `triggered_at`, enqueues delivery, pushes a WebSocket frame. Browser-side firing is removed for backend-owned rules. |
| Briefs | apscheduler cron, timezone from `SETTINGS` (default `Asia/Kolkata`). Built from panel data (no model). Optional AI paragraph labelled `AI · <model> · <time>`; skipped, with the reason in the brief, if the cap or key is missing. Four templates: pre-market, close, weekly portfolio check-up, earnings tracker. A run missed because the backend was down is NOT replayed; `BRIEF` shows `MISSED <time>` (stated, not hidden). |
| AI tools | New read-only tools: `indicators option_price option_payoff etf crypto_depth holders insiders calendar pred energy crypto_funding rigor` (+ `patterns` only if cheap on the backend). `web_search` / `read_url` are NOT built (prompt injection and SSRF surface): roles needing them are `PARTIAL: NO WEB ACCESS`. No shell, ever: `bash read_file write_file edit_file` are rewritten to `quant` or cut. Each tool: per-role allow-list, 6,000-char result cap, `redact()` on errors. |
| Swarm engine | Vibe's shape: `variables` (required ones validated), `tasks` DAG with `depends_on` / `input_from` (cycles rejected), topological order, 2 concurrent tasks max. Per-role defaults: `max_iterations` 8, timeout 120 s, one retry; per-run output-token cap. User presets from `<data dir>/presets/*.yaml`, validated, never executed. The 5 existing desks keep working as "LITE". |
| Preset codes | Uppercase, at most 14 chars, unique, no clash with `COMMITTEE RISK EARNINGS MACRO QUANT`; the mapping goes in `docs/COMMANDS.md`. |
| Coverage labels | `FULL` (all tools exist), `PARTIAL` (some capability cut, shown on screen), `UNAVAILABLE` (refuses with reason, for example journal analysis). |
| Skills | Ported by script. Index in the system prompt stays compact (name plus at most 80 chars); if it adds more than about 600 tokens, switch to a `skills` search tool. `skill` tool gains an optional `section` argument. Skip list in `docs/PHASE_20_SKIPPED.md`. |
| MCP | `openterm-mcp`, stdio transport, entry point in `pyproject.toml`. Exposes the read tools plus `backtest_run`. Talks to a running OpenTerm over loopback; if not running it says so. No order tools, no key reads, no settings writes. |
| REST docs | `docs/API.md` documents the routes MCP wraps, CSV export, the OpenAPI page, loopback binding, Excel Power Query and Python use. No client library over about 100 lines. |
| Filings Intelligence | Fetch filing text via `sec.py` (needs `SEC_USER_AGENT`), split by Item / section, index in SQLite FTS5 (no embeddings), retrieve top passages, model answers from passages only, then every returned quote is verified by exact normalised-substring match. Unverified quotes show `UNVERIFIED` and are excluded from the summary. MVP: `AI FILING <SYM> <question>` and `AI FILING <SYM> DRIVERS`. Stretch (budget permitting): guidance tracker, cited supplier / customer chain. Transcripts out (paid). |

## Steps (tests first, marked expected-to-fail until built; one targeted loop and one full gate per step)
0. **Spec** (this file).
1. **Delivery core:** `backend/openterm/delivery/` (`telegram.py email.py outbox.py`), migration, `NOTIFY` function (`NOTIFY`, `TEST TG|EMAIL`, `PAIR`, `ON|OFF TG|EMAIL`, `LOG`), `docs/FUNCTIONS.md` regenerated.
2. **Server-side alerts:** `alerts_engine.py`, `channels` migration, `VIA` syntax, remove browser firing for owned rules, `ALRT` panel shows engine state, last tick age, skip reasons.
3. **`BRIEF`:** scheduler jobs, four templates, `BRIEF ADD <template> <schedule> VIA TG,EMAIL | RUN NOW | DEL | history`.
4. **AI tool surface:** the new read-only tools above, allow-lists, caps; report the prompt-token delta.
5. **SWARM engine upgrade:** variables, DAG, concurrency 2, defaults, user presets, cost estimate and cap check, audit manifest covers the new fields.
6. **Port the 30 presets:** `scripts/port_vibe_presets.py` (structure, tool-name map, headers, coverage label, `docs/PHASE_20_PRESETS.md` report with flagged paragraphs); resolve flagged paragraphs in at most 2 Sonnet subagent batches.
7. **Port the skills:** `scripts/port_vibe_skills.py`, triage by available tools, `docs/PHASE_20_SKIPPED.md`, prompt-size guard.
8. **MCP + REST docs:** `openterm-mcp`, `docs/API.md`.
9. **Filings Intelligence:** `AI FILING`, FTS5 index, quote verification (stretch only if budget allows after 1-8).
10. **Close-out:** regenerate `docs/FUNCTIONS.md`; update `COMMANDS`, `DATA_LIMITS` (Telegram and SMTP limits, alerts need the backend running), `FEATURE_GAP`, `COMPETITOR_CHECKLIST`, `THIRD_PARTY`, `README` if needed, `CHANGELOG`, `HANDOFF`, `CLAUDE.md`; full gate and bench; record numbers in `docs/PERFORMANCE.md`.

## Test list
- **Delivery:** MarkdownV2 escaping; 4,096 split; token never in outbox, logs or errors; retry / backoff on scripted 429 and 5xx; daily cap; pairing; TLS context verifies (assert `check_hostname` and `CERT_REQUIRED`); plain SMTP refused off loopback; fixture mode skips; migration test (`TABLES_BY_VERSION`).
- **Alerts:** fires with no WebSocket client connected; no fire on stale / synthetic / fixture tick; once per arm; rearm; news match; persistence across restart; channel routing; no duplicate with the browser path (Playwright).
- **Brief:** schedule parsing; frozen-clock run gives expected text from fixtures; delivery enqueued; missed run shown as `MISSED`; AI paragraph skipped with reason when cap or key missing.
- **AI tools:** schema, result cap, error path redacted, fixture mode serves each; forbidden-name scan; prompt-token delta measured.
- **Swarm:** DAG order, cycle rejection, variable resolution, concurrency limit, cap refusal, replay equality, audit hash changes when a prompt changes, user preset validation.
- **Presets:** all 30 load; every tool named exists; DAG acyclic; every variable has a source; each `FULL` / `PARTIAL` preset runs to a chair answer under the scripted gateway; `UNAVAILABLE` refuses with its reason; audit manifest verifies.
- **Skills:** every skill parses, names only real tools, loads via `skill`, index size budget holds.
- **MCP / API:** tool listing, round trip with a test client, no forbidden tool name, refuses when OpenTerm is not running, not reachable off loopback.
- **Filings:** section split, retrieval ranking, verified quote passes, paraphrase fails, unverified excluded from summary, label rules.

## Done when
- With the browser closed and the backend running, a price alert and a news alert each reach Telegram and email (fake transports; a real send only if the user supplies keys and asks).
- `BRIEF` produces and delivers at least pre-market and weekly-portfolio briefs on a schedule.
- 30 Vibe presets plus the 5 desks are listed with a coverage label; every `FULL` / `PARTIAL` desk runs under the scripted gateway.
- Skill library ported with a published skip list; prompt-token delta reported.
- `openterm-mcp` lists and calls read tools from a test client; no order-like tool exists anywhere.
- `AI FILING` returns answers whose quotes are machine-verified.
- Full gate green, bench within budget, docs and handoff updated, nothing committed or pushed.

## Progress log
- Step 0 done (2026-11-05): this spec.
