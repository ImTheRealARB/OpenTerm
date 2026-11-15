<!-- Translated into English from `agent/src/skills/ichimoku/references/信号系统.md` @ 8172827, HKUDS/Vibe-Trading (MIT). See THIRD_PARTY.md. -->
# Ichimoku signal system

## TK cross (the core signal)

### Bullish cross
The Tenkan-sen crosses the Kijun-sen from below:
- **Strong bullish cross**: the cross happens above the cloud.
- **Medium bullish cross**: the cross happens inside the cloud.
- **Weak bullish cross**: the cross happens below the cloud.

### Bearish cross
The Tenkan-sen crosses the Kijun-sen from above:
- **Strong bearish cross**: the cross happens below the cloud.
- **Medium bearish cross**: the cross happens inside the cloud.
- **Weak bearish cross**: the cross happens above the cloud.

## Triple filter

This engine uses a triple filter to keep signal quality high:
1. **TK cross**: the trigger.
2. **Price against the cloud**: price above the cloud is bullish, below the cloud is bearish.
3. **Direction of the cloud**: Leading Span A > B is a bullish cloud, the opposite is a bearish cloud.

A signal is generated only when all three conditions agree.

## Warm-up requirement

At least 78 candles are needed (52 periods of calculation plus a 26-period shift) before a valid signal can be generated.
