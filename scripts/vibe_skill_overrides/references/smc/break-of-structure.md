<!-- Translated into English from `agent/src/skills/smc/references/结构突破.md` @ 8172827, HKUDS/Vibe-Trading (MIT). See THIRD_PARTY.md. -->
# Break of Structure (BOS) and Change of Character (ChoCH)

## BOS (Break of Structure)

A break of structure is a signal that the market trend continues:
- **Bullish BOS**: price breaks above the previous swing high, confirming that the uptrend continues.
- **Bearish BOS**: price breaks below the previous swing low, confirming that the downtrend continues.

A BOS shows that the current trend direction is still valid and that institutional money is still working in the same direction.

## ChoCH (Change of Character)

A change of character is a signal that the trend may reverse:
- **Bullish ChoCH**: in a downtrend, price breaks above the previous swing high.
- **Bearish ChoCH**: in an uptrend, price breaks below the previous swing low.

A ChoCH is a stronger signal than a BOS, because it shows a fundamental change in market structure.

## Signal weight

In this engine:
- ChoCH signals carry the highest weight (trend reversal).
- BOS signals are used for confirmation (trend continuation).
- Both are combined with the FVG filter to reduce false signals.
