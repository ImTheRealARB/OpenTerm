# Playbook: macro

Goal: describe the rates and economic backdrop with data, and link it to what the user asked about.

1. `rates` for the USD yield curve (other currencies by `ccy`): level, the 2s10s spread, and whether the curve is inverted.
2. `macro` with a short query such as "cpi", "unemployment", "gdp", "payrolls" for the series the catalog offers; note when a series needs a FRED key (the tool says so) and stop there instead of guessing a value.
3. `history` of a relevant index or ETF (SPY, TLT, UUP) over 1Y for how markets reacted.
4. `news` with a query for the latest releases when the user asks what just happened.

Report: current levels with dates, the direction since the previous reading, the one or two relationships that matter to the question (rates and growth stocks, inflation and real yields). Mark every number with its tool call and its date.

Limits: macro data is revised and lagged; say which release date each figure has. This is analysis, not personalised investment advice.
