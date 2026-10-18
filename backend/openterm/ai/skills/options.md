# Playbook: options

Goal: read an option chain: where the market expects the stock to move, how it prices risk, and where interest sits.

1. `quote` for the spot price. `options_chain` for the nearest expiry, and again with a later expiry date for the term structure.
2. From the table read: implied volatility at the money, the skew between out-of-the-money puts and calls, open interest and volume by strike, bid and ask spread as a liquidity check.
3. Expected move: spot times at-the-money implied volatility times the square root of days to expiry over 365. Show the inputs and the arithmetic; it is a rough one-standard-deviation range, not a forecast.
4. `history` over 1Y to compare implied volatility with how much the stock actually moved.
5. For a structure the user names (spread, straddle), describe payoff at expiry from strikes and premiums in the chain; `backtest_run` cannot test option structures here.

Report: spot, expiry, implied volatility, expected move, skew, the strikes with most open interest. Say when the chain is stale, thin or empty.

Limits: implied volatility is a market price of risk, not a prediction. This is analysis, not personalised investment advice.
