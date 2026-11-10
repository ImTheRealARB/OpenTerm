# JRNL: the trade journal

`JRNL` reads the trades you already made and shows them back as round trips, statistics and a few behaviour patterns. It never places or changes anything at a broker. Your fills are stored in your own OpenTerm database (tables `journal_trades`, `journal_imports`) and go nowhere else. The AI sees only the statistics and the findings (tool `journal`), never individual trades, and the outside MCP server does not offer it at all.

## Files accepted

All four formats are written from each broker's published column names. The tests use small sample files labelled NOT A RECORDING; a real export from your account may differ, and a file that cannot be read stops the import and names the line.

| Format | What to export | Needs |
| --- | --- | --- |
| Zerodha | Console tradebook CSV | `symbol, trade_date, trade_type, quantity, price`; uses `exchange` (`.NS` / `.BO`), `segment`, `trade_id`, `order_id`, `order_execution_time`. Currency INR. No fees in the file, so none are counted. Only the `EQ` segment gets a daily-bar symbol. |
| IBKR Flex | Flex Query, trades section, CSV | `Symbol`, `DateTime` or `TradeDate`, `TradePrice`, `Buy/Sell` or a signed `Quantity`; uses `IBCommission`, `CurrencyPrimary`, `TradeID`, `IBOrderID`, `Multiplier`, `ListingExchange`. Section marker rows are skipped and counted. Each trade keeps its own currency. |
| Alpaca | Account activities CSV | `transaction_time, qty, price, side, symbol`; only `FILL` activities are trades, dividends and transfers are skipped and counted. UTC times are shown in New York time. Crypto pairs such as `BTC/USD` become `BTC-USD`. USD. |
| Generic | Any CSV, semicolon or tab separated too | You map your columns to `time` (or `date`), `symbol`, `qty`, `price`, optionally `side`, `fee`, `currency`, `order_id`. Without `side`, a negative quantity is a sell. |

Rules for every format: times are the file's own wall clock (no time zone is invented, except Alpaca's explicit UTC); a slash date is never guessed, you choose DMY or MDY; a fee is a positive cost; a row that cannot be read stops the import, nothing is half stored. A fill is de-duplicated by its broker trade id, or by all its fields when it has none, so importing a file twice (or two overlapping exports) adds each fill once. Limits: 50 000 rows and about 4 MB per import.

## Round trips

Fills are matched first in, first out, per symbol and currency. A closing fill makes one round trip, even if it closes several earlier lots; a closing order filled in parts makes several. A sell with nothing to close opens a short; a buy covers shorts first. Fees are split by quantity so each fee is counted once. Profit and loss is in the trade's own currency: nothing is converted, and `C` switches between currencies. Lots still open are listed as open positions and are not marked to any price.

Limits: corporate actions (splits, bonus issues) and option assignment are not adjusted, so a split in the middle of a position gives odd round trips. Futures use the `Multiplier` column when the file has one.

## Statistics

Win rate, average win and loss, payoff ratio, expectancy per trip, profit factor, net and gross P&L, fees, best and worst, time in a position (all, winners, losers), streaks, realised max drawdown (peak to trough of cumulative realised P&L, from a zero start, so it is in money not percent), and splits by symbol, weekday and hour of entry. A statistic that cannot be computed (a profit factor with no losses) shows `-`, not a number. Few trips means wide uncertainty; the panel does not hide that by rounding.

## Findings (heuristics)

Five fixed rules, deterministic, no model. Each prints its own rule and thresholds. A rule with too little history says `NOT ENOUGH HISTORY`. `FLAGGED` means the pattern is present in your history by that rule, marked `watch` or `high` depending on whether the pattern also cost you money. None of this is advice or a forecast, and a pattern can be coincidence, especially on small samples.

| Finding | Rule (defaults) | Needs | What it cannot tell you |
| --- | --- | --- | --- |
| Overtrading days | A day with at least 5 entries and at least 2x your median day | 10 trading days | Whether the extra trades were a plan (an event day) or a habit |
| Revenge trades | A loss closes, then within 30 minutes a trade at least 1.25x as big (price x quantity) opens | 10 round trips | Why you re-entered; a planned scale-in looks the same |
| Losers held longer | Losers held at least 1.5x as long as winners, on average | 5 winners and 5 losers | Whether it was a mistake; some strategies sit through losses by design |
| Size creep after wins | After 2 wins in a row, a trade at least 1.5x your median size so far; flagged from 3 such trades and 25% of the trades after win streaks | 10 round trips, 5 earlier for the median | Intended sizing changes (a growing account) |
| Off-hours entries | Entries at least an hour outside your usual window, in an hour holding under 5% of entries; usual window = hours with at least 10% of entries | 20 round trips | Time zones: the file's clock is used as is, so a mixed-market account can look odd |

## Shadow Account

Question: had you kept the same entries but used one fixed exit rule, how would you have done? Your real exits and the rule are both replayed through the backtester on the same daily bars with the same costs, as a job (watch it in `JOBS`). Rules: `hold` (every entry kept N trading days, default your median time in a position, at least 1) or `stop_target` (stop at your median loss in percent, target at twice that, at most 60 days, seen on daily closes).

It is a simplified comparison, and the result says so: positions are equal weight (your real sizes are not replayed), entries are at the open of the entry day, intraday round trips become one daily bar, a stop or target is only seen at a daily close, and at most the 8 most traded symbols are replayed (symbols with no bars are listed as skipped). Bars come from the usual data sources and are labelled with their source and age. `HISTORICAL SIMULATION, NOT A FORECAST`.

## Credit

The idea (journal import, behaviour diagnostics, a rule-based shadow account) comes from HKUDS/Vibe-Trading (MIT). The code is written fresh for the brokers OpenTerm supports.
