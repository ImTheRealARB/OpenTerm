# Ported from HKUDS/Vibe-Trading @ d0db2e3, agent/backtest/engines/china_a.py (MIT; see THIRD_PARTY.md).
# Changes: only `_blocked_by_limit` (shared by the India and global-futures engines), renamed `blocked_by_limit`;
# the A-share engine itself is not ported (decision C).
"""Daily price-limit (circuit band) check shared by the India and global futures engines."""

from __future__ import annotations

import pandas as pd


def blocked_by_limit(
    engine: object,
    symbol: str,
    direction: int,
    bar: pd.Series,
    limit: float,
    position_direction: int | None = None,
) -> bool:
    """Whether a price-limit band blocks a fill on this bar.

    Shared by every engine with a daily band (India, global futures). The band comes from a base price the market
    knew before the order, ``pre_close`` else the prior bar's close, and is compared against the price the engine
    would actually fill at, which is this bar's open plus slippage.

    The earlier implementation derived the day's move from the CURRENT bar's close, which is lookahead and wrong in
    both directions: a name that opened locked but drifted back by the close was allowed to trade at the locked
    open, and a name that opened freely but closed limit-up was refused a fill it would have got.

    Args:
        engine: Engine instance (needs the BaseEngine band helpers).
        symbol: Symbol being traded.
        direction: 1 (buy / open long), -1 (sell short), 0 (close).
        bar: Current bar.
        limit: Band half-width as a fraction (0.1 for +/-10%).
        position_direction: For ``direction == 0``, the direction of the position being closed: 1 closes a long
            (a sell, blocked at the lower band), -1 closes a short (a buy, blocked at the upper band). Defaults to
            a long close, which is the cash-equity case.

    Returns:
        True when the band blocks the fill. False when it does not, and also when no historical base price is
        reachable: an unknown band must not fabricate a block.
    """
    band = engine.limit_band(symbol, bar, limit)
    if band is None:
        return False
    lower, upper = band
    # BaseEngine books a close with the OPPOSITE of the position's direction, so slippage moves the price the other
    # way. Checking the raw open here would approve a fill that is then booked outside the band.
    fill_direction = -(position_direction or 1) if direction == 0 else direction
    fill = engine.prospective_fill_price(bar, fill_direction)
    if fill is None:
        return False

    # Relative tolerance: a fill within a rounding step of the band counts as touching it, matching the old check's
    # 0.1pp slack in percentage terms.
    tol = 1e-9 * max(abs(lower), abs(upper), 1.0)
    buying = direction == 1 or (direction == 0 and position_direction == -1)
    if buying:
        return fill >= upper - tol
    return fill <= lower + tol
