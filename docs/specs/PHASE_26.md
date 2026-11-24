# Phase 26: strategy lab (spec, 2026-11-24)

Built under the minimal test bar (owner decision 2026-11-24). Everything here is a historical simulation or play money:
nothing sends an order anywhere (NO LIVE ORDERS). Script strategies (Phase 25) are out: Phase 25 is deferred.

## Items

1. **Optimisation:** `BT OPT AAPL SMA{10..50:5}>SMA{50..200:25} 1D 10Y`. A `{lo..hi:step}` range (step 1 when left out;
   decimals allowed) is written in the rule; a saved Python strategy keeps valid code and gets its ranges on the command
   (`BT OPT AAPL @name FAST={10..50:5}` replaces the number in its line `FAST = 20`); each range is a parameter P1, P2, ...
   in order of appearance. Methods: `METHOD=GRID` (default, every combination, cap 2,000 runs),
   `METHOD=RANDOM N=200`, `METHOD=GA POP=40 GEN=25` (genetic: tournament selection, uniform crossover, mutation, two
   elites); `SEED=` makes RANDOM and GA reproducible (default 1). Fitness `FIT=SHARPE|SORTINO|CALMAR|PF|NET|RETURN`
   (default SHARPE). One job (`bt.opt`) runs every parameter set through the same engine, costs and labels as BT;
   a repeated command is a job-cache hit.
2. **Results:** sortable table of runs (S next sort column, Enter runs the selected parameter set as a normal BT), a heat
   map of two parameters (X cycles the pair; with more than two parameters each cell shows the best run over the
   others), and the best region: the winner's neighbours (one step either way) and their average fitness.
3. **Overfitting guards** next to the winner: number of trials, deflated Sharpe ratio (from the multiple-testing module),
   probability of backtest overfitting by combinatorially symmetric cross-validation (10 blocks, 252 splits, needs 2+
   runs), and `EDGE OF RANGE` when the winner sits on a range end.
4. **Walk-forward optimisation:** `WF=5` (rolling) or `WF=5 ANCHORED`: the history is cut into 6 equal parts; window k
   optimises on part k-1 (rolling) or parts 0..k-1 (anchored) and tests on part k. The out-of-sample parts are stitched
   into one equity line; walk-forward efficiency = out-of-sample annual return / in-sample annual return. Windows are
   sliced from each parameter set's full-history run (labelled: positions carry across window edges).
5. **Intrabar fills:** `STOP=5 TARGET=10` (percent from the entry price) on BT and BT OPT. When one daily bar reaches both,
   `FILL=INTRABAR` looks at 60-minute bars (fetched for the run's last two years) to see which came first; a bar with no
   intraday data, or without `FILL=INTRABAR`, takes the stop first. The run's labels count which rule decided each
   ambiguous bar. After a stop or target exit the strategy stays flat until its signal turns off and on again.
6. **Paper forward test:** `BT LIVE AAPL @name` starts a forward test of a saved strategy with play money (`BT LIVE` lists
   them, `BT LIVE STOP <id>` ends one). On every new completed bar the strategy's signal (computed from the bars known at
   that moment) is recorded and a change fills at the next bar's open in OpenTerm's own paper book (no broker, no ORD).
   The panel compares the forward result with a backtest of the same period on today's data; a different decision on a
   bar is shown as DIVERGED (a warning sign: look-ahead, repainting or revised data). Checked every 15 minutes while the
   server runs and whenever the panel refreshes; decisions made late are marked CATCH-UP.
7. **Return vs drawdown:** a scatter of the optimiser's runs (annual return vs max drawdown) with the efficient front
   (no other run has both more return and a smaller drawdown) highlighted.

## Tests (minimal bar)

Unit: range template parsing and rendering, grid count and cap, random and GA reproducibility with a fake fitness,
CSCV probability of overfitting (a pure-noise matrix scores high, a dominant column scores low), efficient front, edge
detection, walk-forward stitching, stop / target / intrabar resolution, the forward-test book. Smoke: `BT OPT`, `BT LIVE`.
