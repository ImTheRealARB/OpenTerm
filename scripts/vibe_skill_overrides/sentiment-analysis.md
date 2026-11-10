---
name: sentiment-analysis
description: Market sentiment analysis: fear and greed indices, put-call ratio, positioning and leverage signals, funding rates, and a social-media sentiment framework, combined into a contrarian score.
category: analysis
port_note: Translated from Chinese. The A-share turnover, margin-balance and northbound-flow sections are cut (no data source); replaced with US equivalents (VIX, put-call ratio, margin debt, fund flows) and crypto funding rates, read through `options_chain`, `crypto_funding`, `news`, `pred`, `history`.
---
# Market Sentiment Analysis

## Overview

Turn the subjective "greed and fear" into measurable indicators. Five dimensions: fear and greed indices, option sentiment, leverage and positioning, flows, and social sentiment. Sentiment indicators are usually read as contrarian indicators and are not precise timing tools.

Data you can pull: `options_chain` (put and call volume and open interest, implied volatility), `history` (price, volume, VIX or other volatility index symbols if available), `crypto_funding` (perpetual funding and open interest), `news` (headline tone), `pred` (prediction-market odds), `etf` and `quote` for flows context. State when an indicator needs data you cannot reach.

## Fear and greed index

### Crypto Fear and Greed Index (0 to 100)

| Score | State | Historical signal |
|---|---|---|
| 0 to 20 | Extreme fear | Bottom area (contrarian buy) |
| 20 to 40 | Fear | Leaning bottom |
| 40 to 60 | Neutral | Stand aside |
| 60 to 80 | Greed | Leaning top |
| 80 to 100 | Extreme greed | Top area (contrarian sell) |

Components: volatility (25%, BTC 30 and 90-day volatility), market momentum (25%, price versus 30 and 90-day moving averages), social media (15%), surveys (15%), BTC dominance (10%), search trends (10%). The index value itself must come from the user or a cited source; do not invent it.

### Equity fear and greed proxies

There is no single official index; combine: volatility index level and its term structure, put-call ratio, market breadth (advancers to decliners, share of stocks above their 200-day average), new highs versus new lows, junk-bond spread, and safe-haven demand. Define "extreme" relative to the indicator's own history.

### How to use it

Core idea: be careful when others are greedy, and constructive when others are fearful.

1. Extreme fear (under 20): a signal to build positions in stages (3 to 5 tranches), only if fundamentals support (the fear is not caused by a company-specific blow-up).
2. Extreme greed (over 80): a signal to reduce gradually, for example from 80% to 50% exposure. Do not short only on this: trends can run.
3. Neutral zone: the indicator has little value; look at other factors.

## Put-call ratio (PCR)

`PCR = put volume / call volume`. Contrarian reading:

| PCR | Meaning | Signal (contrarian) |
|---|---|---|
| above 1.5 | Extreme bearishness | Bullish (fear overdone) |
| 1.0 to 1.5 | Bearish | Leaning bullish |
| 0.7 to 1.0 | Neutral | No clear signal |
| 0.5 to 0.7 | Bullish | Leaning bearish |
| below 0.5 | Extreme bullishness | Bearish (greed overdone) |

Reference ranges differ by market: US equity index options normally 0.7 to 1.2 (extremes below 0.5 or above 1.5); BTC options normally 0.3 to 0.8 (extremes below 0.2 or above 1.2). Single-stock PCR is noisier. Compute it from `options_chain` volume or open interest and say which one.

PCR with the volatility index: high PCR and high volatility index is extreme panic (strong rebound signal); low PCR and low volatility index is extreme complacency (watch for black swans); high PCR with low volatility index is hedging demand (institutions protecting longs); low PCR with high volatility index is a mixed signal needing confirmation.

## Leverage and positioning

Margin debt (investor borrowing to buy stocks) is the standard leverage gauge in equities: the level matters less than its direction; month-on-month growth above about 10% suggests overheating, falling above 10% suggests panic. Rising margin debt after a bottom is confirming; accelerating at highs is overheating. Short interest (`research` fn `si`): a sharp rise shows bearish positioning; a large fall after a rise is short covering.

Crypto: perpetual funding rate and open interest (`crypto_funding`). Persistently high positive funding with rising open interest means crowded longs (squeeze risk down); deeply negative funding means crowded shorts (squeeze risk up). See the `perp-funding-basis` playbook.

## Flows

Fund and ETF flows (net creations into broad-market ETFs versus redemptions) show institutional allocation direction. Cross-check with margin debt and options positioning. Weekly or monthly cumulative flows are more reliable than single-day swings; large single-day flows can be hedging.

## Social media sentiment

Sources: English (X, Reddit, Telegram, Discord) and platform-specific communities. Quantify four dimensions: attention (mention count versus baseline), tone (share of positive, negative, neutral), intensity (mean positive minus mean negative), and change from the prior period.

| Indicator | Calculation | Contrarian signal |
|---|---|---|
| Attention index | search or mention volume versus 30-day average | a spike means overheating |
| Bullish share | bullish posts / all posts | above 80% is extreme optimism (beware) |
| Newcomer share | share of discussion from newly created accounts | above 50% means retail rush (top) |
| KOL consensus | agreement among large accounts | unanimous bullishness is dangerous |

Sentiment cycle: bottom (nobody talks, a few buy, debate); rise (talk grows, optimism spreads, newcomers arrive); top (everyone talks, extreme optimism, doubters are mocked); fall (debate, panic, silence, back to bottom). Bots and promotional accounts add noise: filter them. Use `news` for headlines tone; label it a headline sample, not a poll.

## Composite sentiment score

`composite = 0.25 x fear-greed + 0.20 x PCR + 0.20 x leverage + 0.20 x flows + 0.15 x social`, each normalised to 0 to 100 (0 to 20 extreme fear, 20 to 40 fear, 40 to 60 neutral, 60 to 80 greed, 80 to 100 extreme greed). Weights are a starting point; say so.

| Composite | Exposure idea | Action idea |
|---|---|---|
| 0 to 20 | 80% to 100% | Contrarian buying |
| 20 to 40 | 60% to 80% | Add gradually |
| 40 to 60 | 40% to 60% | Standard exposure |
| 60 to 80 | 20% to 40% | Reduce gradually |
| 80 to 100 | 0% to 20% | Contrarian exit |

These bands are an illustration of the framework, not advice for a person's account.

## Output format

A dashboard table (indicator, current value, percentile, signal), the composite score with its zone, a short reading of which indicators agree and which conflict, an exposure and hedging discussion, and risks. For every value name the tool or source and the date.

## Cautions

1. A contrarian indicator is not precise timing: sentiment can stay extreme for a long time.
2. Combine sentiment with trend: greed in an uptrend and fear in a downtrend are normal.
3. Thresholds differ by market (US equities, crypto, others).
4. Some sentiment data is paid (professional terminals, on-chain providers).
5. Social media is noisy; bots and promoters distort it.
6. Margin and short-interest data are published with a delay.
