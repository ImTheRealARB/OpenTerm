<!-- Translated into English from `agent/src/skills/smc/references/订单块与缺口.md` @ 8172827, HKUDS/Vibe-Trading (MIT). See THIRD_PARTY.md. -->
# Order Blocks and Fair Value Gaps (FVG)

## Order Blocks

An order block is an area where institutions build large positions. It usually shows up as:
- Price leaves a price area quickly.
- That area then becomes strong support or resistance.
- When price retests the order block, a reaction often follows.

### Bullish order block
The area of the last down (bearish) candle in a downtrend, after which price rises strongly.

### Bearish order block
The area of the last up (bullish) candle in an uptrend, after which price falls strongly.

## FVG (Fair Value Gap)

An FVG is a price gap in the middle of three candles:
- **Bullish FVG**: the low of the third candle is above the high of the first candle (a gap is left in the middle).
- **Bearish FVG**: the high of the third candle is below the low of the first candle.

An FVG shows an extreme imbalance between buying and selling pressure, and price usually comes back to "fill" the gap.

## Role in the signal

The FVG is used as a filter:
- When a bullish FVG exists, a long signal is more reliable (buyers are strong).
- When a bearish FVG exists, a short signal is more reliable (sellers are strong).
