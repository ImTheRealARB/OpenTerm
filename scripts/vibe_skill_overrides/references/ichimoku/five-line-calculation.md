<!-- Translated into English from `agent/src/skills/ichimoku/references/五线计算.md` @ 8172827, HKUDS/Vibe-Trading (MIT). See THIRD_PARTY.md. -->
# Ichimoku five-line calculation

## Conversion line (Tenkan-sen)
```
tenkan = (highest_high(9) + lowest_low(9)) / 2
```
The midpoint of the price over the short term (about 2 weeks).

## Base line (Kijun-sen)
```
kijun = (highest_high(26) + lowest_low(26)) / 2
```
The midpoint of the price over the medium term (about 1 month). The base line is also the "equilibrium point" of the price.

## Leading Span A (Senkou Span A)
```
span_a = (tenkan + kijun) / 2  # shifted forward 26 periods
```
Leading Span A is the average of the Tenkan-sen and the Kijun-sen, drawn 26 periods ahead.

## Leading Span B (Senkou Span B)
```
span_b = (highest_high(52) + lowest_low(52)) / 2  # shifted forward 26 periods
```
Leading Span B is the 52-period midpoint, drawn 26 periods ahead.

## Lagging Span (Chikou Span)
```
chikou = close  # drawn 26 periods back
```
The current closing price, drawn 26 periods back. It confirms the trend: a Lagging Span above the price is bullish, below the price is bearish.

## The cloud (Kumo)

The area between Leading Span A and Leading Span B is called the cloud (Kumo).
- A > B: bullish cloud (usually drawn in green)
- A < B: bearish cloud (usually drawn in red)
- The thickness of the cloud shows the strength of support or resistance.
