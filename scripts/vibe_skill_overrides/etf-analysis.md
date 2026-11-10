---
name: etf-analysis
description: ETF analysis: product screening, fee comparison, tracking error, liquidity checks, premium and discount, and strategy uses (core-satellite, sector rotation, leveraged-ETF decay).
category: asset-class
port_note: Translated from Chinese. Cut the China ETF tickers, Tushare code, QDII quota, China tax and index-family sections and the long code templates; US examples and OpenTerm tools substituted. The leveraged-ETF decay formula is corrected to L(L-1)/2 x variance x time (the original formula did not match its own example).
---
# ETF Analysis

## Role

ETFs are the main tool for passive investing and asset allocation. This playbook covers how to classify and compare ETFs, the metrics that matter (tracking error, premium or discount, liquidity, fees), and how ETFs are used in portfolios.

## 1. Product types

| Type | Examples | Notes |
|---|---|---|
| Broad-market | SPY, VOO, IVV, QQQ, IWM, VTI | Most liquid and cheapest; core holdings |
| Sector | XLK, XLF, XLE, XLV | Sector rotation tool; concentrated holdings |
| Thematic | ARKK, ICLN, BOTZ | Theme hype, often short life cycle |
| Strategy / smart beta | VIG (dividend growth), USMV (low volatility), QUAL (quality), MTUM (momentum) | Explicit factor exposure; fees a little above broad funds |
| Commodity | GLD, USO, DBA | Physical or futures-backed; watch roll cost on futures funds |
| Bond | TLT, IEF, LQD, HYG, AGG | Rate sensitive; duration is the key number |
| International | EFA, EEM, VWO, EWJ | Currency and trading-hours (premium) effects |
| Money market / T-bill | BIL, SGOV | Cash management, not an investment |

Structures: a plain ETF (in-kind creation and redemption keeps the price near NAV); an ETN (an unsecured bond of the issuer, so issuer credit risk); futures-based funds (roll cost, contango); leveraged and inverse funds (daily reset, see section 4).

## 2. Core metrics

### Tracking error

```
daily tracking error = std(ETF daily return - index daily return)
annualised tracking error = daily tracking error x sqrt(252)
```

Rule of thumb for broad developed-market equity ETFs: under 0.2% excellent, 0.2% to 0.5% acceptable, over 0.5% poor. Sources: fees accrued daily, dividend reinvestment timing, trading impact at index rebalances, cash drag from creations and redemptions, suspended or illiquid holdings (full replication versus sampling), and index methodology.

The information ratio of an index ETF is normally slightly negative because of fees: `IR = (ETF annual return - index annual return) / tracking error`; closer to zero is better.

### Premium and discount

```
premium or discount % = (market price - NAV or intraday indicative value) / NAV x 100
```

Authorised participants arbitrage a premium (create shares, sell the ETF) or a discount (buy the ETF, redeem). Persistent or large gaps show up for international funds when the underlying market is closed, for bond ETFs in stressed markets, and for funds holding thinly traded assets. Get the price and the NAV from tools; if NAV is not available, say so rather than guess.

### Liquidity

| Metric | Meaning | Rough guide |
|---|---|---|
| Average daily dollar volume | Ease of trading | Broad funds above $100M, sector funds above $20M |
| Bid-ask spread | Immediate cost | Under 0.05% is good |
| Book depth | Impact of a large order | Use depth, not just the quote |
| Underlying liquidity | What the ETF can really be traded against | ETF liquidity can exceed its holdings' |

### Fees and size

All-in cost is the expense ratio (management plus custody plus index licence); it excludes commissions and spread. Compounding: over N years the drag is about `1 - (1 - fee)^N`; a 0.50% fund versus a 0.15% fund costs roughly 3.5% of terminal wealth over 10 years and 6.8% over 20 years.

Size: a very small fund (tens of millions) carries closure risk and weak liquidity; above about $1B it is liquid and market makers are active. Warning signs of closure: assets shrinking for several quarters.

## 3. Choosing between ETFs on the same index

1. Size: drop very small products.
2. Fee: the lowest expense ratio when everything else is equal.
3. Tracking: compare 1-year and 3-year tracking error.
4. Liquidity: dollar volume and spread.
5. Issuer: index-fund track record and product range.

A score out of 100 (size 30, fee 25, tracking error 30, liquidity 15, each scaled linearly) can rank candidates; it is a ranking aid, not a verdict.

Tools: `etf` for holdings and weights, `history` for price series (compute tracking against the index or a peer from daily closes), `profile` and `quote` for the basic facts, `quant` (`ql`) for calculators.

## 4. Strategy uses

### Core-satellite

Core 70% to 80% in broad low-fee ETFs for market beta; satellite 20% to 30% in sector, thematic or smart-beta ETFs for tilts. Rebalance by calendar (quarterly or half-yearly) or by band (any asset more than 5 points from target).

### Sector rotation with ETFs

Momentum rotation: rank sector ETFs by trailing return over a lookback (for example 20 to 60 trading days, skipping the most recent days to avoid short-term reversal) and hold the top N. Macro-cycle map: recovery favours consumer discretionary, technology and small caps; overheating favours energy, materials and industrials; stagflation favours energy, utilities and staples; recession favours health care, utilities and bonds. Test any rule with `backtest_run` before relying on it. See also the `sector-rotation` playbook.

### Smart-beta factor exposure

Regress the ETF's daily returns on factor-return series (value, momentum, quality, low volatility, size) to see the loading (beta), t-statistic and R squared. Use `quant` (`fact`) for the factor regression of a symbol.

### Leveraged and inverse ETFs

A daily-reset fund with leverage L does not give L times the multi-period return. Approximate volatility decay: `L (L - 1) / 2 x sigma^2 x T`, with sigma the index volatility per year and T in years. Example: index volatility 20%, 2x fund, one year: `2 x 1 / 2 x 0.04 = 4%` of drag, before fees. Use them only as short-term tools (days to weeks); never as a long-term allocation.

### Relative value

Arbitrage of premium or discount needs creation and redemption rights and is institutional. At retail level, two ETFs on the same index should have a price ratio that mean-reverts; a rolling z-score of the ratio (60-day window) beyond 2 is something to study, not a trade by itself. See the `pair-trading` playbook.

## 5. Building ETF portfolios

Classic frameworks: 60/40 (broad equity and aggregate bond ETFs), all-weather style (equities, long and intermediate Treasuries, gold, commodities), barbell (broad core plus high-beta sector or thematic). Rebalancing cost is roughly `trade size x (commission + half spread + impact)`, about 0.05% to 0.15% for broad ETFs. Band rebalancing usually beats fixed-frequency rebalancing, and new cash or dividends can be directed to underweight assets to avoid selling.

## 6. Common requests

- Best ETF for an index: section 3, as a table of expense ratio, size, tracking error and spread.
- Sector rotation signal: rank the sector ETFs by momentum, exclude any with a large recent drop, and state the rule and the window.
- Portfolio test: `backtest_run` with the ETF weights if the tool supports it; otherwise compute return, volatility and drawdown from `history` and state the method.

## 7. Cautions

1. A large share of suspended or illiquid holdings makes the indicative value unreliable, so premium and discount means less.
2. International funds trade while their underlying markets are closed: part of any gap is timing.
3. Index reconstitution dates can create short-lived price pressure.
4. Never hold leveraged or inverse ETFs as a long-term position.
5. Money-market ETFs are cash tools, not investments.
6. Split large orders in thin ETFs over several days.
7. Distributions (dividends versus capital gains) are taxed differently; check the local tax rules.
