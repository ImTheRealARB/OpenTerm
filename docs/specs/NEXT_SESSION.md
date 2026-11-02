# OpenTerm next session: GUI mode, redesign, Phase 17, better strategy editor

Paste this file (or point the session at it) as the first message of a new **Opus** session.
Written 2026-11-02 after a planning interview with the user (Ankith). Every decision below is settled; do not re-ask them.

## Your role
You are the **orchestrator**. You plan, split work, review and run the gates. **Sonnet subagents build.**
- Read first: `HANDOFF.md` ("Resume here"), `CLAUDE.md`, `docs/PERFORMANCE.md`, `docs/ADDING_A_FUNCTION.md`, `docs/specs/` (Phase 17 spec if one exists; if not, build from the scope below).
- At most **2 Sonnet subagents at once**. Each gets a narrow brief (files, what done looks like), runs **targeted tests only**, and returns at most 10 lines (long findings go to a file).
  Use `haiku` for pure search. Do not spawn agents for work you can do in a few tool calls.
- You run the **full gate once per step**, output tail only: `node scripts/gates.mjs`, then `node scripts/bench.mjs` at the end of each part.
- Be judicious with tokens. Search (Grep/Glob) before reading; do not re-read files; no essays.
- **Stop rules:** pause at **60%** of the 5-hour window (write state to HANDOFF.md, commit only if the user asked, tell the user). If the same gate fails twice on the same problem, stop, write the exact state and next action to HANDOFF.md, and tell the user.
- This job overrides the "Sonnet only" usage rule in CLAUDE.md. **First action:** edit that rule in CLAUDE.md to say: Opus may orchestrate with at most 2 Sonnet subagents building; Opus does not build large changes itself.
- **Never commit or push unless the user says so.** Never deploy.

## Non-negotiables that still apply
Everything under "Non-negotiables" in CLAUDE.md: speed budgets (bench must stay **37/37**; a lone miss is often noise, rest and rerun once), no fake data, keyboard-complete, keys only in env/keyring/.env, AI output labelled, **order tools never appear in the MCP server or AI agent**, no Bloomberg name/logo/assets.
The user is pre-intermediate at software engineering: comment code heavily, define terms on first use, and close with one line on what to learn next.

## Part 1: GUI mode and visual redesign (do first)
**Decision: one app, two shells.** A **Terminal / GUI toggle** in the status bar, saved in settings (`settings/schema.ts`, kv key `settings`, no migration; GET/PUT sync as today). Same panels, data, backend and functions in both modes. Only the shell differs. Terminal mode stays exactly as it is now.
- **Default:** a new user (no saved settings) starts in **GUI mode** with a one-line banner "Switch to Terminal mode for keyboard speed". Existing saved settings stay in Terminal mode.
- **GUI shell, first pass (every function reachable by mouse):**
  - top **menu bar** with categories: Markets, Charts, News, Research, Portfolio, Backtest, Settings;
  - left **sidebar** listing every registered function by category, with a search box that does the same job as the command line;
  - a **toolbar on each panel** (add to watchlist, export CSV, change timeframe, etc.; reuse the existing panel keys/bindings underneath);
  - a **"?" help drawer** for the current panel (source it from `docs/FUNCTIONS.md` data / registry titles);
  - a **symbol picker** (search box).
  Not in first pass: redesigning internals of all 100+ panels.
- **First-run flow:** a welcome card with three big buttons: "Look up a stock", "See a chart", "Watch my stocks"; each opens the right panel with a sample symbol. A "Take the 2-minute tour" link highlights the menu bar, sidebar and mode toggle. Shown once, replayable from Help.
- **Per-panel polish, then, for the 8 most-used panels:** Q, GP, WL, N, WEI, FA, PORT, BT.
- **Visual rules (both modes):** keep the ban on shadows, gradients, transitions and web fonts. Polish through spacing, alignment, a tighter amber/blue/grey colour hierarchy, clearer panel title bars, better empty and loading states, system monospace. Look stays "terminal, amber on black", more refined and easier on the eye.
  **Only exception, GUI mode only:** small rounded corners and hover highlights on buttons. Themes are `:root[data-theme=...]` blocks; Grid and ChartView re-read CSS vars on `displayVersion` (see CLAUDE.md).
- Keep every action keyboard-reachable in GUI mode too. Watch the gotchas in CLAUDE.md (Ctrl+K in text inputs, panel keys vs bare modifier keys, Suspense/lazy ban, Windows case-insensitive imports, e2e must use `openApp()`).
- Tests: vitest for pure logic (keep parsers pure, no `net/api` imports), Playwright for the toggle, sidebar, tour and welcome card. Update `docs/FUNCTIONS.md` via `python scripts/gen_functions_doc.py` if registry/keybindings change. Add GUI-mode screenshots to `docs/screenshots/` and update the README when done.
- **Done when:** gate ALL PASS, bench 37/37, `docs/PERFORMANCE.md` updated with before/after numbers.

## Part 2: Phase 17, delivery, MCP server, alerts (after Part 1)
Read the Phase 17 spec in `docs/specs/` and the HANDOFF notes first. Build in this order:
1. **MCP server** (read-only tools over the app's data; **no order tools**, a test must scan for them).
2. **Alert delivery:** desktop notifications and email via SMTP; Telegram or a webhook are optional extras. Alerts are evaluated in the frontend today (`onRawTicks`); decide with the spec how delivery reaches the backend. Nothing is delivered anywhere unless the user turns it on; secrets only in env/keyring; all error text through `redact()`. Note the open SMTP TLS-verification item in `docs/review/DECISIONS_FOR_USER.md`: handle it properly here.
3. **Scheduled daily brief** (apscheduler is already a dependency).
Use tests-first with strict-xfail markers as CLAUDE.md describes. New migration tests must list tables in `TABLES_BY_VERSION`.

## Part 3: better strategy editor (last)
The editor already exists (`frontend/src/functions/BtEditor.tsx`: `BT EDIT/LOAD`, `BT SAVE`, `BT DEL`, `@name`). Improve it with:
- **CodeMirror 6** (syntax colours, line numbers). It must let Ctrl/Alt/Meta chords bubble (Ctrl+K gotcha). **Check the bundle size against startup and bench budgets**; if it regresses, lazy-load it only inside the editor via `loadModule()` style loading, not `React.lazy`.
- **Starter templates** (SMA cross, RSI mean reversion, breakout) in a list.
- **Inline sandbox errors** next to the offending line (the sandbox `bt.sandbox.check` is pure; reuse it).
- Not now: a plain-English rule builder (belongs to GUI mode later).

## Housekeeping (every part)
Per the user's global rules: after each part update `HANDOFF.md` (done / state / next) and `CLAUDE.md` (durable facts) editing only changed sections; update `README.md` when features or usage change; `CHANGELOG.md` and `docs/COMMANDS.md` as needed. Keep the rulebook in CLAUDE.md, never AGENTS.md. Windows PowerShell 5.1 syntax in anything you give the user (no `&&`).
When a part is done, tell the user in one line and recommend starting a fresh session for the next unrelated task.
