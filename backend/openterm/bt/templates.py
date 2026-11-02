"""Starter strategies for the BT editor (`GET /api/bt/templates`).

This module is only text: it must not import pandas or numpy (the server process never loads them, and
`test_server_never_imports_pandas` guards that). The pandas code lives inside the strings, and only runs later in a
job worker, after `sandbox.check` has approved it.

Every template follows the same contract as any strategy: `class SignalEngine` with `generate(self, data_map)`,
returning one pandas Series of target weights per symbol. A weight of 1.0 means "fully long", 0.0 means "flat"
(no position), and -1.0 would mean "fully short". Orders fill at the NEXT bar's open, so a signal never trades on
the very bar that produced it (this avoids look-ahead bias, i.e. peeking at the future).
"""

from __future__ import annotations

# Plain `#` comments are used inside the strategy text (not docstrings) so the strings stay easy to quote.

SMA_CROSS = """\
import numpy as np
import pandas as pd


class SignalEngine:
    # data_map maps each symbol to a DataFrame with open, high, low, close, volume columns.
    # We return a dict: symbol -> Series of target weights on the same dates.
    def generate(self, data_map):
        out = {}
        for sym, df in data_map.items():
            # SMA = simple moving average: the mean of the last N closing prices.
            fast = df["close"].rolling(20).mean()
            slow = df["close"].rolling(50).mean()
            # When the short average is above the long one, the recent trend is up: be long (1.0).
            # Otherwise stay out (0.0). The first 50 bars have no slow average yet (NaN),
            # and a comparison with NaN is False, so we are flat there.
            out[sym] = pd.Series(np.where(fast > slow, 1.0, 0.0), index=df.index)
        return out
"""

RSI_MEAN_REVERSION = """\
import numpy as np
import pandas as pd


class SignalEngine:
    # Mean reversion: buy after a sharp drop and sell once price has recovered.
    # RSI (Relative Strength Index) scores recent moves from 0 to 100. Low means "sold off hard".
    def generate(self, data_map):
        out = {}
        for sym, df in data_map.items():
            change = df["close"].diff()
            gain = change.clip(lower=0.0)    # only the up moves (down moves become 0)
            loss = -change.clip(upper=0.0)   # only the down moves, as positive numbers
            # Wilder smoothing: an exponential average with alpha = 1/14 (what a 14-day RSI uses).
            avg_gain = gain.ewm(alpha=1 / 14, adjust=False).mean()
            avg_loss = loss.ewm(alpha=1 / 14, adjust=False).mean()
            rs = avg_gain / avg_loss         # relative strength: average gain per unit of average loss
            rsi = 100 - 100 / (1 + rs)

            # Start with "no opinion" (NaN) on every bar, then only write down the bars where
            # something happens. ffill() then carries the last decision forward, which is how we
            # hold a position between the entry and the exit.
            pos = pd.Series(np.nan, index=df.index)
            pos[rsi < 30] = 1.0   # oversold: go long
            pos[rsi > 50] = 0.0   # recovered: exit to flat
            # Bars before the first decision have nothing to carry, so they become 0.0 (flat).
            out[sym] = pos.ffill().fillna(0.0)
        return out
"""

BREAKOUT = """\
import numpy as np
import pandas as pd


class SignalEngine:
    # Breakout (trend following): buy when price pushes above its recent range, leave when it falls out the bottom.
    def generate(self, data_map):
        out = {}
        for sym, df in data_map.items():
            # Highest high of the PRIOR 20 bars. shift(1) moves it one bar later, so today's bar is
            # not part of its own comparison (otherwise a close could never beat a high that includes it).
            prior_high = df["high"].rolling(20).max().shift(1)
            # Lowest low of the prior 10 bars: the exit level.
            prior_low = df["low"].rolling(10).min().shift(1)

            # NaN means "no change today"; ffill() keeps the last decision while we are in between.
            pos = pd.Series(np.nan, index=df.index)
            pos[df["close"] > prior_high] = 1.0   # breakout above the range: go long
            pos[df["close"] < prior_low] = 0.0    # fell below the recent low: exit
            out[sym] = pos.ffill().fillna(0.0)    # flat until the first breakout
        return out
"""

TEMPLATES: list[dict] = [
    {"id": "sma_cross", "title": "SMA CROSS",
     "summary": "Long while the 20-day average is above the 50-day average, otherwise flat.",
     "code": SMA_CROSS},
    {"id": "rsi_mean_reversion", "title": "RSI MEAN REVERSION",
     "summary": "Buy when the 14-day RSI drops below 30, sell when it recovers above 50.",
     "code": RSI_MEAN_REVERSION},
    {"id": "breakout", "title": "BREAKOUT",
     "summary": "Buy a close above the prior 20-day high, exit below the prior 10-day low.",
     "code": BREAKOUT},
]
