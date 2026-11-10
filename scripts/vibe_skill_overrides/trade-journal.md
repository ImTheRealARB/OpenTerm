---
name: trade-journal
description: Read the user's own trade journal (JRNL): round-trip statistics and four behaviour findings (disposition effect, overtrading, chasing, anchoring), reported as patterns in their history, never as advice.
category: tool
port_note: Translated from Chinese and rewritten for OpenTerm. The original reads a broker CSV through a file tool (Tonghuashun, Eastmoney, Futu formats, filter expressions, Phase 4c strategy extraction); OpenTerm has the JRNL function and the `journal` tool instead, so the file, format and strategy-extraction parts are cut and the metrics, thresholds, reporting rules and follow-ups are kept.
---
# Trade Journal Analysis

## Purpose

Give the user an honest, data-grounded picture of their own trading from the journal they imported in JRNL. Two layers:

- Profile: number of closed round trips, win rate, average win and loss, payoff ratio, expectancy, profit factor, total P&L, fees, average holding time, longest losing streak, maximum drawdown.
- Behaviour findings: disposition effect, overtrading, chasing momentum, anchoring, each with a status, a severity (low, medium, high) and numeric evidence.

## How to read it

Call the `journal` tool (optional `currency`). If it answers that no journal is imported, tell the user to import fills in JRNL and stop; do not invent figures. Statistics use first-in first-out lot matching; only closed round trips count toward win rate and payoff, and open positions are excluded. A journal with several currencies must be shown one currency at a time: never add P&L across currencies or average their ratios, and do not convert currencies unless a rate is given.

## Detection logic (explain it to the user in plain words)

| Bias | Metric | Medium | High |
|---|---|---|---|
| Disposition effect | average holding time of losers / of winners | 1.2 or more | 1.5 or more |
| Overtrading | (quiet-day P&L - busy-day P&L) / abs(quiet-day P&L), busy day 3 or more trades, quiet day 1 or fewer | 0.3 or more | 1.0 or more |
| Chasing | share of buys made after a rolling gain of more than 3% in the same symbol | 40% or more | 60% or more |
| Anchoring | share of symbols with 5 or more trades whose price stayed in a narrow band (coefficient of variation under 5%) | 33% or more | 66% or more |

Each is a pattern in the user's own history, not a diagnosis and not a forecast. Small samples (few round trips, few symbols) make every metric unreliable; say how many trades back each statement.

## Report template

Lead with the top-line numbers, then section by section, dense and short for a reader on a phone:

1. Overall: closed round trips, average holding time, win rate, payoff ratio, expectancy, total P&L, maximum drawdown, period covered.
2. Behaviour table: bias, severity, core evidence (take the evidence text from the tool result).
3. One-line observation from the data (overtrading? a very narrow set of symbols? one session of the day?).
4. Suggestions only for findings that are high or medium, framed as habits to consider: disposition high, write the exit rule before entering and do not cut winners early; overtrading high, a hard cap on trades per day; chasing high, wait for pullbacks and set a "no buy after a large same-day rise" rule; anchoring high, widen the price band you act on instead of a fixed personal reference price.

Guidance on what to flag:
- Win rate below 40% and payoff ratio below 1.0: losing on both; say so plainly and ask whether the user wants a cooling-off check or a review of the largest losers.
- Average holding under one day and more than 15 trades a week: an intraday-heavy pattern; minute-level data (`history` with a short interval) is the right basis for any follow-up test.
- Three or fewer symbols: concentration risk; offer a check of how correlated they are (`quant`).

## Follow-up dialogue

- A period or symbol deep-dive: the `journal` tool takes only a currency, so say that the tool reports the whole journal and that finer slices are done in JRNL itself.
- "What if I had used a strict stop": a hypothetical; describe how to test it with `backtest_run` on the same symbol, and label any number a test, not a result of the user's trades.
- Never place or suggest placing a trade; this playbook only describes history.

## Errors

- No journal imported: ask the user to import it in JRNL.
- A field missing from the result: say it is missing rather than estimate it.
