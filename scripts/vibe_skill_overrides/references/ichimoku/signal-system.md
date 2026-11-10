# Ichimoku Signal System

## TK cross (the core signal)

### Golden cross (bullish)
The conversion line crosses above the base line:
- **Strong golden cross**: the cross happens above the cloud
- **Neutral golden cross**: the cross happens inside the cloud
- **Weak golden cross**: the cross happens below the cloud

### Dead cross (bearish)
The conversion line crosses below the base line:
- **Strong dead cross**: the cross happens below the cloud
- **Neutral dead cross**: the cross happens inside the cloud
- **Weak dead cross**: the cross happens above the cloud

## Triple filter

This engine uses three filters to keep signal quality high:
1. **TK cross**: the trigger
2. **Price vs the cloud**: bullish with the price above the cloud, bearish below it
3. **Cloud direction**: Leading Span A > B is a bullish cloud, the reverse a bearish one

All three must agree before a signal is generated.

## Warm-up

At least 78 candles (52-period calculation + 26-period shift) are needed before a valid signal can be generated.
