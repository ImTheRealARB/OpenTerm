# Next features (agreed with the user 2026-11-04, cloud session, branch `claude/gui-simple-bugs-sp3hq5`)

Opus orchestrates, at most 2 Sonnet builders at once (CLAUDE.md usage rule). Every step: tests first where practical, targeted tests by
builders, then the main session runs the full gate (`node scripts/gates.mjs --keep-going --e2e-last`) and the bench twice, commits, pushes,
updates HANDOFF.md "Resume here". All non-negotiables in CLAUDE.md apply (never fake data, keyboard for everything, no trade dress,
startup bundle stays under 120 KB gz: new pieces load after first paint via `import()` / registry loader, never `React.lazy`).
Terminal mode stays fast for experts: exact codes (`AAPL GP`) always win over natural language.

## Decisions (settled, do not re-ask)
- Natural language engine: **rule-based**, built in, offline, no key, no AI. Ambiguity shows "Did you mean..." choices, never a guess.
- Custom indicators: **formula language** (e.g. `EMA(close,12) - EMA(close,26)`), evaluated in the existing chart indicator Web Worker. No user JavaScript.
- Indicator library: **~100 indicators**, each tested against known values and with a plain-English glossary line.
- Extras accepted: plain-English screener, compare in plain English, workspace templates, alert from the chart.

## Order
1. **Natural-language commands + Excel-style syntax hints** (shared parser).
   - "apple stock price chart" -> `AAPL GP`; "tesla news" -> `TSLA N`; "microsoft 5 year chart" -> `MSFT GP 5Y`; bare "apple" finds AAPL in GUI and Terminal.
     Company names from the screener universe (lazy, loaded on first non-code input); intent words -> function (chart/price/graph GP, news N,
     overview/profile DES, financials/earnings FA, ...). Pure parser module + vitest table of phrases; e2e in both modes.
   - Syntax hint line under the command box: function signature from registry `argsSchema`, current argument bold (like Excel's `SUM(number1, [number2], ...)`),
     plus value suggestions for the current argument (tickers, ranges, intervals, indicator names). Keyboard: Tab/arrow accept, Esc hides.
2. **Glossary tooltips on canvas grid column headers** (hover hit-test on the header row; keyboard: `?` on the current column), GUI mode only; terms in `gui/glossary.ts`.
3. **Indicator toggles without chart rebuild**: add/remove only that series, keep zoom/scroll. Risky (a ChartView rewrite was reverted: `docs/review/REVERTED.md`): build with a browser check, e2e asserts zoom range survives a toggle, all GP specs green.
4. **Indicator library (~100), formula-language custom indicators, presets**: library panel (search, add to chart), formula parser + evaluator (pure, vitest, runs in worker), named presets saved server-side (kv), load via panel or command. Each library indicator tested against reference values (port permissively licensed reference math only with THIRD_PARTY.md notice).
5. **Plain-English rule builder for BT** (GUI): sentence-shaped form ("Buy when [20-day average] [crosses above] [50-day average]; sell when ...") that writes the existing rule grammar and shows any rule back as a sentence. Round-trip vitest.
6. **Extras:** plain-English screener ("tech stocks with P/E under 20 and dividend yield above 2%" -> EQS filter, reuse step 1 parser); compare ("apple vs microsoft 1 year" -> GP compare); workspace templates (Long-term investor / Day trader / Macro / India, one click); alert from the chart (key or click at a price -> ALRT at that level).
