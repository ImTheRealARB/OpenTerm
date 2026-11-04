# OpenTerm cloud session: beginner-simple GUI, every known bug, Terminal closer to the classic terminal

Paste this whole file as the first message of a new **cloud** session running **Opus**.
Written 2026-11-04 after a planning interview with the user (Ankith). Every decision below is settled: do not re-ask them.
The user is away. Work continuously through Parts 0 to 5 in order. Stop only on a stop rule below.

## Your role and budget
You are the **orchestrator**. You plan, split work, review diffs and run the gates. **Sonnet subagents build.**
- The user has about **US$45 of cloud credits**, and an Opus main session is the most expensive part of this run.
  Neither of you can see the balance mid-run, so spend as if every message costs money:
  - Never read a file over ~150 lines whole. Grep or Glob first, then Read only the lines you need. Never re-read a file.
  - Subagents do the reading and building. Use **at most 2 Sonnet subagents at once**, and `haiku` for pure search.
    Each one gets a narrow brief (files, what done looks like, which targeted tests to run), writes long findings to a
    file under `docs/review/cloud/`, and returns at most 10 lines.
  - Command output: tail or filter it. Never print a whole test run, build log or `git log`.
  - Don't spawn an agent for something you can do in 3 tool calls.
- **Work in the order below.** Earlier parts are worth more, so if the credits run out, the most valuable work is already done.
- **Checkpoint after every step:** commit, push the branch, and update HANDOFF.md "Resume here" (what's done, what's
  next, the exact next action). That way a stop at any moment loses at most one step.
- The 5-hour-window pause rules in CLAUDE.md are replaced by the checkpoint rule. If you get a usage-limit or credit
  warning, checkpoint at once and stop.

## Git (this job only, overriding "commit only when the user says so")
- Work on your own branch, starting from `origin/main`. **Commit once per step** and **push the branch after every commit.**
  Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` (Sonnet-built steps may use
  `Claude Sonnet 5.5`).
- At the end, open a **draft PR** to `main` with a summary per part. **Never merge, never push to `main`, never deploy.**

## Stop rules
- The same gate fails twice on the same problem: write the exact state and next action to HANDOFF.md, commit, push, stop.
- A fix would change a ported Vibe-Trading file's behaviour (the cross-check tests exist to catch that): skip it, list it in the PR, move on.
- Anything that needs a real API key, a real mail server or a paid call: don't do it. Fixtures only.

## Read first (cheaply)
`HANDOFF.md` "Resume here" (top ~60 lines only), `CLAUDE.md` (all of it: the gotchas are real), `docs/review/DECISIONS_FOR_USER.md`,
`docs/specs/NEXT_SESSION.md` Part 1 (how GUI mode was built), `frontend/src/gui/` file list. Nothing else up front.

## Non-negotiables (unchanged, from CLAUDE.md)
Speed over looks: no shadows, gradients, transitions or web fonts. Radius and hover are allowed **only** under
`:root[data-mode="gui"]`. Color carries meaning. Never fake data: STALE / ERR / PROVIDER DOWN with source and age, and
fixtures / SYNTHETIC labelled on screen. Everything works from the keyboard. Keys only in env, keyring or `.env`. AI output labelled.
Order tools never appear in MCP or the AI agent. **Phase 18 stays paused.**
**No Bloomberg name, logo, fonts, screenshots, docs text or other assets anywhere** (code, UI, docs, commits, PR).
Borrow workflow conventions only, never trade dress.
The user is pre-intermediate at software engineering: comment code heavily and define terms on first use.

## Part 0: set up the cloud box and record a baseline (do first, keep it short)
- Linux cloud box: `cd backend; uv sync`, `cd frontend; npm ci`. For Playwright, follow the CLAUDE.md note on
  `PLAYWRIGHT_BROWSERS_PATH` and the `chrome-headless-shell` symlink. `.ps1` scripts don't apply here; use `node scripts/gates.mjs` and `node scripts/bench.mjs`.
- Run the full gate once on the untouched `origin/main`, and the bench twice. Record the numbers in `docs/PERFORMANCE.md`
  under "Cloud baseline 2026-11-04". **On this box the bench gate is "no budget worse than the baseline beyond noise"**:
  absolute budgets were set on the user's Windows machine, and cloud timings differ.
- Never call GDELT or any live provider from tests. Run with `OPENTERM_FIXTURES=1` / `OPENTERM_SYNTHETIC=1`.

## Part 1: GUI mode as simple as possible for a beginner (the main goal)
**Who the beginner is:** like a first-year finance student. They know what a stock, an index and a P/E ratio are, but they
have never used a terminal, a screener or a backtester, and they won't learn mnemonics like `GP` or `DES`.
**Split by mode (settled):** GUI mode is for this beginner. Terminal mode is for experts (Part 4). Changes in this part
must not change how Terminal mode looks or behaves (an e2e run in Terminal mode proves it).

### 1A. Measure first: beginner task suite
Before changing UI, write a Playwright spec `frontend/e2e/beginner.spec.ts` in GUI mode (`openApp(page, { mode: "gui", welcome: true })`).
It runs these tasks **with the mouse only, never typing a function code**, and counts clicks per task:
1. Look up Apple and see its price and P/E.
2. Chart Tesla over 1 year.
3. Make a watchlist with 3 stocks.
4. See today's top market news.
5. See how the major world indices are doing.
6. Set a price alert on a stock.
7. Track a small portfolio (2 positions) and see its value.
8. Run a sample backtest from a starter template.
9. Find out what a number on screen means (e.g. "EPS").
10. Recover from an error (e.g. an unknown symbol) without help.
Record clicks per task now (some tasks will fail at first: mark them `test.fail()` per the CLAUDE.md tests-first rule).
**Target:** every task passes in **4 clicks or fewer** plus typing a company name, and with no function code typed.

### 1B. Make the tasks pass. Design rules
- **Plain words first.** Menus, sidebar, panel titles and buttons say what the panel does ("Stock chart", "Company
  overview", "Top news"). The function code is shown small and grey beside it as a learning aid ("GP"), never on its own.
- **Search by company name.** The symbol picker (`gui/SymbolPicker.tsx`) and the sidebar search accept "apple", "tesla",
  "reliance" and suggest matching tickers (reuse `/api/resolve` and the screener universe, no new provider). Enter on a
  suggestion opens the overview.
- **Fewer choices at once.** Default sidebar shows a short "Start here" group (the tasks above). Everything else is under
  its category, collapsed. Nothing is removed: every function stays reachable.
- **A useful first screen.** A new GUI user gets a starter layout (e.g. a watchlist with a few large US stocks, a chart
  and top news) instead of an empty grid, plus the existing welcome card. Data is real or clearly labelled, never faked.
- **Explain the numbers.** Add a pure glossary file `frontend/src/gui/glossary.ts` (one plain-English line per term:
  P/E, EPS, market cap, OHLC, volume, dividend yield, beta, 52-week range, drawdown, Sharpe, etc.). In GUI mode a term in
  a column header or label shows its line on hover **and** on keyboard focus. Unit test: every term the GUI labels use has an entry.
- **Every error says what to do next.** In GUI mode, ERR / STALE / PROVIDER DOWN / KEY REQUIRED keep their exact text
  and source/age, plus one plain line ("Yahoo isn't answering. Data shown is 4 min old. It retries on its own.") and,
  where it helps, a button (retry, open APIKEYS). Wire `KeyRequiredLine` into DES, N, GP and every panel that still shows its own key error text.
  All of this goes through `components/PanelNote.tsx`.
- **Empty states point forward.** An empty watchlist, portfolio or alert list shows one button for the next step ("Add a stock").
- **The BT strategy editor fills its panel** instead of the fixed 22em.
- **Tour and help read live keybindings** (the tour names `Alt+H` literally today). The help drawer shows the current panel's
  purpose in one sentence, then its buttons, then its keys.
- **Restyle the FA statement table** for GUI mode (it's a canvas grid and was skipped; colours come from CSS vars that `Grid` re-reads).
- The user's design rule: *kill any label that only exists to explain the layout. If the screen needs a caption, the screen is broken.*
  Prefer a clearer layout over adding help text.
- **Budget:** the startup bundle (119.9 KB gz today) may grow by **at most 5 KB gz**. Lazy-load new GUI pieces via
  dynamic `import()` or the registry loader, never `React.lazy`.

### 1C. Review with fresh eyes
After 1B, one Sonnet subagent that has **not** built anything takes 1600x900 GUI-mode screenshots of each beginner task
(script against `OPENTERM_STATIC_DIR=frontend/dist`, fixtures on, temp `OPENTERM_DB_PATH`, a fresh browser context per shot)
and critiques them against the rules above in `docs/review/cloud/GUI_CRITIQUE.md` (findings ranked, at most 20).
Fix every high and medium finding. Put the final screenshots in `docs/screenshots/` and update the README's GUI section.

**Done when:** all 10 beginner tasks pass within 4 clicks, Terminal mode e2e unchanged, gate ALL PASS, bench no worse than the Part 0 baseline.

## Part 2: fix every known bug
Each bug gets a failing test first, then the fix (one commit per bug or per small group). The known list:
- `cache` table is never pruned, so the DB grows forever: prune by age and size on a schedule (apscheduler is already there).
- Yahoo quote batches over ~160 symbols trip the rate limit and put Yahoo in cooldown: chunk and pace them.
- `service._once`: if the leader request is cancelled, the waiters get `CancelledError`. Waiters must get the result or a real error.
- `DayStore.rows` decodes up to 250 days of msgpack on the event loop: move it off the loop (`asyncio.to_thread`).
- SWARM and AI panels never abort their paid SSE stream when closed. The earlier fix (`c820e22`) was reverted because
  maximize remounts the panel. Build a real close-vs-remount signal (e.g. the store's panel-closed event) and abort only on close.
- `quantjobs/attr.py` `return_measures`: Modified Dietz divides by zero or goes negative after large withdrawals; `xirr`
  bisection assumes a sign pattern and can return a wrong root (bracket the root properly, or return an explicit ERR).
- `quantjobs/risk.py` values holdings at each series' own last close: use the last common day, and say so in the output.
- `parse_deribit` forward uses the upper median for an even instrument count: use the true median.
- Command history isn't re-fetched when the backend comes back after being down at page load.
- Market-hours lights ignore holidays: add NYSE / NSE holiday rules as pure, tested code (computed rules, not a scraped list).
- Housekeeping bug: HANDOFF.md still calls the AI-providers work (commit `34533a1`) "uncommitted". Fix the line.
**Leave alone (decisions the user hasn't made):** the DLVR `DESKTOP` toggle behaviour, and the four "confirm or revert"
items at the top of `DECISIONS_FOR_USER.md`. Mark each fixed item there as DONE with its commit.

## Part 3: one bug audit
One Sonnet subagent audits `backend/openterm/` and `frontend/src/` for correctness bugs (not style), writes findings to
`docs/review/cloud/AUDIT.md` ranked high / medium / low with a file:line and a failure scenario each. You verify each
high and medium finding (reproduce it with a test) before fixing. Fix every confirmed high and medium one, test first.
List the low ones in `DECISIONS_FOR_USER.md` under "Deferred". **One audit pass only, no second round.**

## Part 4: Terminal mode closer to the classic market terminal (lowest priority)
For expert users. Borrow **workflow conventions only, never trade dress**:
- `SECURITY <market sector> FUNCTION <GO>` grammar: accept a sector word after the ticker (EQUITY, INDEX, CURNCY, COMDTY, GOVT, CORP)
  and map it to the right symbol form. Keep today's grammar working.
- Number-select in lists: typing `3` then Enter in a list panel opens row 3.
- Function keys F2-F12 as sector keys and a menu/back key, configurable through the existing keybinding overrides (browsers
  reserve some keys: check CLAUDE.md before binding).
- A function directory panel listing every function code with its one-line purpose.
- Align function codes with widely used terminal-style mnemonics where ours differ, **keeping the old code as an alias**. Never break a saved layout.
Every change gets a vitest for the parser and an e2e test. Run `python scripts/gen_functions_doc.py` after keybinding or registry changes.

## Part 5: wrap up
- Full gate, bench twice (vs the Part 0 baseline), `docs/PERFORMANCE.md` before/after table.
- HANDOFF.md "Resume here": what's done per part, what's not, what was never verified, decisions left to the user.
  CLAUDE.md: new durable facts and gotchas only. README: GUI section and screenshots.
- Draft PR to `main` with a per-part summary, the beginner-task click counts before and after, and the bench table. Then stop.
