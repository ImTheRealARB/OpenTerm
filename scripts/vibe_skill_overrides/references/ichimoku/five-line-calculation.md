# Ichimoku Five-Line Calculation

## Conversion line (Tenkan-sen)
```
tenkan = (highest_high(9) + lowest_low(9)) / 2
```
The midpoint of the short-term (about 2 weeks) price range.

## Base line (Kijun-sen)
```
kijun = (highest_high(26) + lowest_low(26)) / 2
```
The midpoint of the medium-term (about 1 month) price range. The base line is also the price's "equilibrium point".

## Leading Span A (Senkou Span A)
```
span_a = (tenkan + kijun) / 2  # shifted forward 26 periods
```
Leading Span A is the average of the conversion line and the base line, plotted 26 periods ahead.

## Leading Span B (Senkou Span B)
```
span_b = (highest_high(52) + lowest_low(52)) / 2  # shifted forward 26 periods
```
Leading Span B is the 52-period midpoint, plotted 26 periods ahead.

## Lagging Span (Chikou Span)
```
chikou = close  # plotted 26 periods back
```
The current close, plotted 26 periods back. Used to confirm the trend: the lagging span above the price is bullish, below it is bearish.

## The cloud (Kumo)

The area between Leading Span A and Leading Span B is called the "cloud".
- A > B: a bullish cloud (usually drawn green)
- A < B: a bearish cloud (usually drawn red)
- The thickness of the cloud reflects the strength of support or resistance
