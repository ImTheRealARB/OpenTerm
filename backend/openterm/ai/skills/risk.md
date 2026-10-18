# Playbook: risk

Goal: describe how much a portfolio or a stock can lose, what drives it, and how that held up in past stress.

1. `portfolio` with no name to list portfolios; with a name for positions. If the user has none, work on a single symbol with `history`.
2. `quant` fn `risk` with args {"portfolio": "<name>"}: value at risk, expected shortfall, volatility, beta, maximum drawdown, contribution by holding, stress replays, and the VaR backtest.
3. `quant` fn `fact` with args {"symbol": "<SYM>"} for factor exposures (market, size, value, momentum) when the question is about what drives returns.
4. `history` over 5Y for a single name: worst drawdown and how long it took to recover.

Report: the headline loss measure with its confidence level and horizon, the largest risk contributors, the stress results with their coverage, and the weakest assumption (for example a short history or a single currency base). Cite each number.

Limits: historical simulation, not a forecast; tail losses can exceed any VaR. Say if a result is not runnable. This is analysis, not personalised investment advice.
