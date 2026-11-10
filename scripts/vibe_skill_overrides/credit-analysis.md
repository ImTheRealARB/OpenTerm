---
name: credit-analysis
description: Fixed income and credit analysis: ratings, Altman Z-score, Merton and KMV default models, bond pricing, duration and convexity, DV01, key-rate duration, immunization, ABS and MBS basics, and credit-spread analysis.
category: analysis
port_note: Translated from Chinese. Cut the local-government financing vehicle (LGFV) analysis, the China bond-market structure chapter, the quantlib code chapter and the China data-source table; ratings table kept for S&P and Moody's. Use `rates` for the government curve and `quant` (ql) for calculators.
---
# Fixed Income and Credit Analysis

## When to use

Bond pricing, yield to maturity, duration and convexity; issuer credit ratings and default probability; credit spread analysis and strategies; ABS and MBS credit; interest-rate risk (DV01, key-rate duration). The government curve comes from `rates`; calculators from `quant` (`ql`); issuer financials from `fa`; the user's holdings from `portfolio`.

## 1. Credit analysis framework

### 1.1 Ratings

Issuer rating (overall ability to pay) versus issue rating (a specific bond, reflecting collateral, seniority and covenants); an issue rating can be above or below the issuer rating.

| S&P | Moody's | Meaning |
|---|---|---|
| AAA | Aaa | Highest quality, extremely low default risk |
| AA+/AA/AA- | Aa1/Aa2/Aa3 | High quality |
| A+/A/A- | A1/A2/A3 | Upper medium |
| BBB+/BBB/BBB- | Baa1/Baa2/Baa3 | Lowest investment grade (the IG and high-yield dividing line) |
| BB+ and below | Ba1 and below | High yield, speculative |
| D | D | Default |

Read the outlook (positive, stable, negative) and watch lists together with the rating. Ratings lag the market; credit spreads often move first.

### 1.2 Altman Z-score

Predicts financial distress; the original model is for listed manufacturers: `Z = 1.2 X1 + 1.4 X2 + 3.3 X3 + 0.6 X4 + 1.0 X5`.

| Variable | Formula | Meaning |
|---|---|---|
| X1 | working capital / total assets | Liquidity |
| X2 | retained earnings / total assets | Accumulated profit |
| X3 | EBIT / total assets | Profitability |
| X4 | market value of equity / total liabilities | Leverage |
| X5 | sales / total assets | Asset efficiency |

Zones: Z above 2.99 safe; 1.81 to 2.99 grey; below 1.81 distress. Variants: Z' for private firms (X4 uses book equity; cut-offs 2.90 and 1.23); Z'' for non-manufacturers and emerging markets (drops X5; cut-offs 2.60 and 1.10). X4's denominator is total liabilities, not only interest-bearing debt. Limits: backward looking; not for financial firms; coefficients may need recalibration outside the original US sample. Compute with figures from `fa` and check them with `rigor`.

### 1.3 Merton structural model

Equity is a call option on the firm's assets with strike equal to the face value of debt D at maturity T. Asset value V follows geometric Brownian motion; default can happen only at T.

```
E = V N(d1) - D e^(-rT) N(d2)
d1 = [ln(V/D) + (r + sigma_V^2 / 2) T] / (sigma_V sqrt(T)),  d2 = d1 - sigma_V sqrt(T)
risk-neutral default probability = N(-d2)
distance to default DD = [ln(V/D) + (mu - sigma_V^2 / 2) T] / (sigma_V sqrt(T))
credit spread ~ -ln[ N(d2) + (V/D) e^(rT) N(-d1) ] / T
```

Unknowns V and sigma_V come from two equations: the equity formula above and `sigma_E E = N(d1) sigma_V V`.

### 1.4 KMV and expected default frequency

Commercial version of Merton. Steps: back out V and sigma_V from the equity price and volatility; default point `DP = short-term debt + 0.5 x long-term debt`; `DD = (V - DP) / (V x sigma_V)`; map DD to expected default frequency (EDF) through a historical default database (non-normal). Differences from Merton: the default point is not all debt, the mapping is empirical, and EDF is a real-world probability, not risk-neutral. Rough bands (indicative): EDF under 0.1% investment grade; 0.1% to 1% BBB to BB; 1% to 5% B; above 5% CCC and below. The bands are only an order-of-magnitude check, not calibrated default probabilities.

### 1.5 Scorecards (retail credit and ABS collateral)

Process: define the default label (for example 90+ days late); WOE encoding; select features by information value (keep IV above 0.02); logistic regression (or gradient boosting); convert to score `A - B ln(odds)`, usually base 600 with 20 points to double the odds. `WOE = ln(good share / bad share)`, `IV = sum (good share - bad share) x WOE`. IV under 0.02 no power; 0.02 to 0.1 weak; 0.1 to 0.3 medium; over 0.3 strong.

## 2. Fixed income products

### 2.1 Government curve

Spot (zero) curve from bootstrapping coupon bonds; forward rate `f(T1, T2) = [ (1 + r2)^T2 / (1 + r1)^T1 ]^(1/(T2 - T1)) - 1`. Term spreads: 10Y-2Y (inversion often precedes recession), 10Y-1Y, 30Y-10Y (long-end supply and demand). Shapes: normal (expansion expected), flat (turning point), inverted (recession signal), humped (liquidity layering). Pull the curve with `rates`; compute spreads from its points.

### 2.2 Bond pricing and yields

- Price: `P = sum C / (1 + y)^t + F / (1 + y)^n`, with coupon C, face F, yield y.
- Current yield: annual coupon / price.
- Yield to maturity approximation: `YTM ~ [C + (F - P) / n] / [(F + P) / 2]`.
- Modified duration: `MD = Macaulay duration / (1 + y / m)`; price change about `-MD x dy`.
- Convexity: `CX = sum t (t + 1) CF_t / (1 + y)^(t + 2) / P`; price change `dP / P ~ -MD dy + 0.5 CX dy^2`.
- Price at a coupon date is the clean price (accrued zero); between coupon dates add accrued interest for the dirty price. State the day-count convention (ACT/365, 30/360, ACT/ACT). Example check: face 100, coupon 5%, YTM 4%, 5 years, annual pay gives price about 104.45.

### 2.3 Convertible bond (bond floor only)

Bond floor = present value of coupons and face at the yield of a straight bond of the same rating and maturity. Conversion premium = (price - conversion value) / conversion value; bond-floor premium = (price - bond floor) / bond floor. Resetting the conversion price can dilute holders; weigh the issuer's incentive (forcing conversion versus put pressure).

### 2.4 ABS and MBS

Collateral quality: weighted-average coupon (WAC), weighted-average maturity (WAM), weighted-average loan-to-value, delinquency (30, 60, 90+ days), cumulative default rate. Prepayment: CPR (annualised) and SMM (monthly): `CPR = 1 - (1 - SMM)^12`, `SMM = 1 - (1 - CPR)^(1/12)`; PSA 100 is a ramp to 6% a year over 30 months, then constant. Tranches: senior (paid first, highest rating), mezzanine, junior or equity (absorbs losses first, gets excess spread). Credit enhancement = (pool - senior) / senior; excess spread = pool rate - senior funding cost - servicing fee.

## 3. Interest-rate risk

- Macaulay duration: `sum t CF_t / (1 + y)^t / P`, in years. Modified duration: the rate sensitivity. Effective duration for bonds with options (callables, MBS): `(P_down - P_up) / (2 P0 dy)` with repricing at shifted yields. Dollar duration `D_mod x P x face`.
- Convexity: positive convexity gains more when rates fall and loses less when they rise; callables and MBS have negative convexity.
- DV01 = `D_mod x P x 0.0001` per unit; portfolio DV01 is the sum of position DV01s. Hedge ratio = DV01 of the position / DV01 of the hedge instrument.
- Key-rate duration (KRD): sensitivity to a 1 bp move of a single key tenor (1Y, 2Y, 3Y, 5Y, 7Y, 10Y, 20Y, 30Y); the sum of KRDs about equals modified duration. Use to see curve exposure and hedge twists and butterflies.
- Immunization: match asset duration to liability duration (`sum w_i D_i = D_liability`), or match cash flows exactly (no reinvestment risk but costly), or contingent immunization (manage actively above a floor, switch to immunized at the floor). Rebalance quarterly or monthly and after large rate moves (over about 50 bp).

## 4. Credit spreads

Spread = default risk premium + liquidity premium (+ tax premium in some markets). Benchmarks: G-spread (versus government), I-spread (versus swaps), Z-spread (over the zero curve), OAS (option-adjusted: price `P = sum CF_t / (1 + r_t + OAS)^t` with embedded options removed). Components can be approximated from CDS quotes, models, bid-ask spreads and turnover.

Curve shapes: upward sloping (normal); flat or inverted (short-term liquidity or refinancing stress, a warning). In expansion spreads tighten; in recession or credit events they widen; in a flight to quality, government yields fall while spreads widen, which hurts high yield twice.

Drivers: macro (growth, PMI, monetary policy, default waves), sector (policy, cycle, refinancing environment) and issuer (rating changes, financials, maturity wall).

Strategies: spread tightening (long under-priced high-spread credit, short government to hedge duration; early recovery, easing); spread widening (short credit or buy CDS, long government; slowdown); cross-rating (long high yield and short investment grade when spreads compress, or the reverse); butterfly on the credit curve (long the middle, short the wings). Use government bond futures for duration hedges.

## 5. Quick reference

```
YTM approx = [C + (F - P) / n] / [(F + P) / 2]
dP = -D_mod x P x dy + 0.5 x CX x P x dy^2
DV01 = D_mod x P x 0.0001 x face held
credit spread = bond YTM - government YTM at the same maturity
Z-score: above 2.99 safe, 1.81 to 2.99 grey, below 1.81 distress
DD to EDF (indicative): DD above 4: under 0.1%; 2 to 4: 0.1% to 1%; 1 to 2: 1% to 5%; below 1: above 5%
```

## 6. Related playbooks

`macro-analysis` and `global-macro` for rate and credit cycle inputs; `risk-analysis` for portfolio-level credit risk; `valuation-model` for equity-side financial analysis (the Altman Z-score is useful on both sides); `hedging-strategy` for hedging.
