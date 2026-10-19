# backend-quant review (agent 11, second wave)

Scope read: `rates/parse.py`, `rates/service.py`, `secf/ids.py`, `options/{chain,pricer,hivg}.py`, `quantjobs/{common,regime,sectors,attr}.py`,
`quantjobs/risk.py` (first 170 lines), `quant/options.py` (BS, Greeks, IV solver). Not read line by line: `valuation/*`, `quantlib/*`,
`quant/fixedincome|payoff|credit|swap|heston|numerics`, `quantjobs/{opt,fact,ql,alpha}`, rest of `risk.py`.

## Fixed (tests in `backend/tests/test_review_backend_quant.py`)
- `options/chain.py` `parse_deribit`: one bad row killed the whole option book (KeyError on a missing `underlying_price`, TypeError on a
  text `mark_iv`, ValueError on Deribit's `2d5` decimal strikes used by USDC options). Rows are now skipped, `d` read as a decimal point.
  Tests: `test_deribit_*` (3). Commit 8401df7.
- `rates/parse.py` `parse_mof`: an impossible date row (`2026/2/30`) raised a bare ValueError for the whole JGB curve; the row is skipped.
  Test: `test_mof_impossible_date_row_is_skipped_not_fatal`. Commit 8401df7.

## Performance (before/after)
- `options/hivg.py` `rolling_cc` (HIVG RV20 chart): passed `rets[:i+1]` to `cc_vol` at every step, copying the whole prefix (quadratic).
  Now passes only the n-bar window. 5000 returns, n=20, best of 5: 44.1 ms -> 19.1 ms (remaining time is `cc_vol` itself). Same values
  (test `test_rolling_cc_same_values_as_the_prefix_slicing_version`, includes a None in the series). Measured with a scratchpad script, no server.

## Checked, no change
- ISIN/CUSIP/SEDOL check digits, OAS percentile and d1/d5/d21 offsets, BoE/ECB/BoC parsers, `years_to_expiry`, ATM IV interpolation,
  `quantjobs.common.series/align/asof`, regime edge density job, BS/Greeks/implied vol edge handling (T<=0, sigma<=0, no-arbitrage bounds).
- No server-process imports of pandas/numpy/scipy in the files read (quant, scipy and pandas are imported inside functions or in job modules).

## Left (not proven by a failing test, low risk)
- `quantjobs/attr.py` `return_measures`: Modified Dietz divides by `v0 + weighted flows`; large withdrawals could make it zero or negative
  (ZeroDivisionError). `check_vals` guarantees positive values only. Needs a decision on what to show (NOT DEFINED).
- `quantjobs/attr.py` `xirr` bisection assumes f decreasing in r (true when the terminal flow is positive and dominant); unusual flow patterns
  can return a wrong root.
- `quantjobs/risk.py` holding market value uses each series' own last close, not the last common day (small if bars are fresh).
- `parse_deribit` forward is the upper median for an even count of instruments (docstring says median).
- UNVERIFIED: nothing here needed a full gate or bench.
