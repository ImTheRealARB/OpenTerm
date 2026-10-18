# Ported from HKUDS/Vibe-Trading @ d0db2e3, agent/backtest/engines/base.py (MIT; see THIRD_PARTY.md).
# Changes: import paths, loaders/run card/artifacts removed, run_backtest -> run(); ruff fixes (PEP 585/604 annotations, re flag names; no behaviour change); per-bar row cache `_bar_row` (OpenTerm perf: same rows, built once per bar).
"""Base backtest engine with shared bar-by-bar execution loop.

All market engines inherit from BaseEngine and override market-rule methods.
OpenTerm keeps Vibe's core in run(): align target weights, bar-by-bar execution with
market rule enforcement, metrics. Loading, signals and artifacts live outside.
"""

from __future__ import annotations

import logging
import math
import re as _re
from abc import ABC, abstractmethod
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

import numpy as np
import pandas as pd

from ..metrics import (
    bar_returns,
    by_exit_reason_stats,
    by_symbol_stats,
    calc_fill_turnover_series,
    calc_metrics,
)
from ..models import EquitySnapshot, FillRecord, Position, TradeRecord
from ..rebalance_mask import (
    RebalanceMask,
    resolve_rebalance_dates,
    validate_rebalance_mask,
)


def _json_safe_scalar_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    """Scalar metrics for stdout JSON; non-finite floats become null."""
    return {
        k: (None if isinstance(v, float) and not math.isfinite(v) else v)
        for k, v in metrics.items()
        if not isinstance(v, dict)
    }

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _OpenOrder:
    """A fully priced opening order that can be committed atomically."""

    symbol: str
    direction: int
    price: float
    size: float
    leverage: float
    margin: float
    commission: float

    @property
    def cost(self) -> float:
        """Cash consumed by the fill."""
        return self.margin + self.commission


@dataclass(frozen=True)
class _ReductionOrder:
    before: Position
    target_size: float
    price: float
    released_margin: float
    realized_pnl: float
    exit_commission: float

    @property
    def capital_credit(self) -> float:
        return self.released_margin + self.realized_pnl - self.exit_commission


_CRYPTO_RE = _re.compile(
    r"^(?=[A-Z0-9]*[A-Z])[A-Z0-9]+-USDT$|^(?=[A-Z0-9]*[A-Z])[A-Z0-9]+/USDT$", _re.IGNORECASE
)
# Forex / metals in their explicit Yahoo notations, plus the bare-6-char
# whitelist for XAUUSD / XAGUSD / XPTUSD / XPDUSD and G10 currencies. Mirrors
# ``backtest.engines._market_hooks._MARKET_PATTERNS`` so the ffill-limit
# decision (``10`` for cross-market vs ``5`` for single-market) reflects the
# same market classification the engine composite would assign.
_FX_RE = _re.compile(
    r"^[A-Z]{3}/[A-Z]{3}$"
    r"|^[A-Z]{6}\.FX$"
    r"|^[A-Z]{6}=X$"
    r"|^(?:XAU|XAG|XPT|XPD|EUR|GBP|JPY|CHF|CAD|AUD|NZD|USD)[A-Z]{3}$",
    _re.IGNORECASE,
)


def _detect_market_for_align(code: str) -> str:
    """Lightweight market detection for ffill_limit calculation."""
    from .hooks import _detect_market

    market = _detect_market(code.strip().upper())
    if market == "crypto":
        return "crypto"
    if market == "forex":
        return "forex"
    return "equity"


# ─── Forward-fill helpers (numpy, avoid pandas overhead) ───


def _ffill_1d(col: np.ndarray, limit: int) -> None:
    """In-place forward-fill a 1D array with limit."""
    count = 0
    last_valid = np.nan
    for i in range(len(col)):
        if np.isnan(col[i]):
            count += 1
            if count <= limit and not np.isnan(last_valid):
                col[i] = last_valid
        else:
            last_valid = col[i]
            count = 0


def _ffill_2d(arr: np.ndarray, limit: int = 5) -> np.ndarray:
    """Forward-fill NaN values column-wise with limit."""
    out = arr.copy()
    for col in range(out.shape[1]):
        _ffill_1d(out[:, col], limit)
    return out


# ─── Signal alignment (reused from daily_portfolio logic) ───


def evaluation_start_index(config: dict[str, Any], dates: pd.DatetimeIndex) -> int:
    """Return the first bar index that counts as performance.

    A long-lookback indicator needs history before the period the user asked
    about — an MA200 strategy over ten years needs bars from before those ten
    years. Loading that history is correct; *grading* it is not. Without a
    declared boundary the extra bars silently join the evaluation: trades fire
    in them, the equity curve starts in them, and CAGR and the benchmark are
    computed over a window longer than the one that was requested. The run
    still succeeds and its metrics are still internally consistent, which is
    what makes it dangerous.

    Two spellings, because a strategy author knows one or the other: the number
    of warm-up bars the indicator needs, or the date the evaluation should
    start. Declaring both is refused rather than resolved — the two can
    disagree, and picking a winner would silently discard the author's other
    instruction.

    Args:
        config: Backtest configuration. Reads ``warmup_bars`` (int >= 0) and
            ``evaluation_start_date`` (``YYYY-MM-DD``); absent means the whole
            loaded window is evaluated, which is the historical behaviour.
        dates: The aligned bar index the backtest would otherwise run over.

    Returns:
        Index into ``dates`` of the first evaluated bar; ``0`` when nothing is
        declared.

    Raises:
        ValueError: Both keys declared, a malformed value, or a boundary that
            leaves fewer than two bars to evaluate.
    """
    warmup = config.get("warmup_bars")
    eval_start = config.get("evaluation_start_date")
    if warmup in (None, 0) and not eval_start:
        return 0
    if warmup not in (None, 0) and eval_start:
        raise ValueError(
            "declare warmup_bars or evaluation_start_date, not both — they can "
            "disagree, and resolving that silently would discard one of them"
        )

    if eval_start:
        boundary = pd.Timestamp(eval_start)
        if boundary.tz is None and dates.tz is not None:
            boundary = boundary.tz_localize(dates.tz)
        elif boundary.tz is not None and dates.tz is None:
            boundary = boundary.tz_localize(None)
        start = int(np.searchsorted(dates.values, boundary.to_datetime64(), side="left"))
        if start >= len(dates):
            raise ValueError(
                f"evaluation_start_date {eval_start} is after the last loaded bar "
                f"({dates[-1].date()}); nothing would be evaluated"
            )
    else:
        try:
            start = int(warmup)
        except (TypeError, ValueError):
            raise ValueError(f"warmup_bars must be an integer, got {warmup!r}") from None
        if start < 0:
            raise ValueError(f"warmup_bars must be non-negative, got {start}")

    if len(dates) - start < 2:
        raise ValueError(
            f"the evaluation window would hold {max(0, len(dates) - start)} bar(s) of "
            f"{len(dates)} loaded; widen start_date or shorten the warm-up"
        )
    return start


def _align(
    data_map: dict[str, pd.DataFrame],
    signal_map: dict[str, pd.Series],
    codes: list[str],
    optimizer: Callable | None = None,
) -> tuple:
    """Build aligned date index, close matrix, target-position matrix, return matrix.

    Signal is shifted by 1 bar (next-bar-open semantics) then normalised so
    ``sum(abs(weights)) <= 1.0``.

    Args:
        data_map: code -> OHLCV DataFrame.
        signal_map: code -> signal Series.
        codes: Valid instrument codes.
        optimizer: Optional weight optimiser ``(ret, pos, dates) -> pos``.

    Returns:
        (dates, close_df, close_val_df, positions_df, returns_df). ``close_df``
        is the bounded-ffill trading view; ``close_val_df`` carries the last
        traded close through halts of any length and is only for valuation.
    """
    # Build unified sorted date index from all symbols' trading calendars.
    # Everything below works on int64 epochs, and ``asi8`` / ``view("i8")``
    # count in the index's own unit: a duckdb-backed local source arrives as
    # datetime64[us], which read as nanoseconds put the run in 1970 and, beside
    # a nanosecond source, matched none of its bars. One unit for all of them.
    ns_index = {
        c: idx if idx.unit == "ns" else idx.as_unit("ns")
        for c in codes
        for idx in (data_map[c].index,)
    }
    indexes = [ns_index[c] for c in codes]
    merged = np.unique(np.concatenate([index.asi8 for index in indexes]))
    common_tz = indexes[0].tz
    if all(index.tz == common_tz for index in indexes) and common_tz is not None:
        dates = pd.DatetimeIndex(pd.to_datetime(merged, utc=True).tz_convert(common_tz))
    else:
        dates = pd.DatetimeIndex(merged)

    n_dates = len(dates)
    n_codes = len(codes)

    # Use int64 view for O(log n) searchsorted lookups
    dates_i8 = dates.values.view("i8")
    # Daily panels usually share one calendar. Direct placement avoids two
    # binary-search passes per symbol over an already identical grid. Reuse
    # each irregular calendar's mapping for both prices and shifted signals.
    row_indexes = {
        c: slice(None) if ns_index[c].equals(dates)
        else np.searchsorted(dates_i8, ns_index[c].asi8)
        for c in codes
    }

    # ffill with limit to avoid masking long suspensions (e.g. 3-week halt)
    # Cross-market needs larger limit (Chinese New Year can be 9-10 bars)
    ffill_limit = 10 if len({_detect_market_for_align(c) for c in codes}) > 1 else 5

    # Build close matrix via numpy direct fill + searchsorted index mapping
    close_arr = np.full((n_dates, n_codes), np.nan)
    for j, c in enumerate(codes):
        series = data_map[c]["close"]
        close_arr[row_indexes[c], j] = series.values

    # Vectorized ffill with limit using pandas (C-optimized internals)
    _tmp = pd.DataFrame(close_arr)
    close_arr = _tmp.ffill(limit=ffill_limit).values
    # Valuation marks carry the last traded close through a halt of any
    # length; the bounded matrix above stays the trading/decision view.
    close_val_arr = _tmp.ffill().values

    # Drop symbols that are entirely NaN (no data overlap with date range)
    all_nan_mask = np.all(np.isnan(close_arr), axis=0)
    all_nan_cols = [codes[j] for j in range(n_codes) if all_nan_mask[j]]
    if all_nan_cols:
        logger.warning("Symbols dropped (no usable price data): %s", all_nan_cols)
        keep_mask = ~all_nan_mask
        codes = [codes[j] for j in range(n_codes) if keep_mask[j]]
        if not codes:
            raise ValueError("All symbols have no data in the requested date range")
        close_arr = close_arr[:, keep_mask]
        close_val_arr = close_val_arr[:, keep_mask]
        n_codes = len(codes)

    # Build position matrix: shift on each symbol's OWN calendar, then fill
    pos_arr = np.full((n_dates, n_codes), np.nan)
    for j, c in enumerate(codes):
        # Get signal values aligned to own trading calendar.
        # copy=True guarantees a writable array: with copy=False, an already
        # float64 source returns a read-only view (e.g. pandas copy-on-write),
        # which the in-place nan_to_num/clip below would reject.
        own_idx = data_map[c].index
        sig_vals = signal_map[c].reindex(own_idx).values.astype(np.float64, copy=True)
        # fillna(0) + clip in numpy
        np.nan_to_num(sig_vals, copy=False, nan=0.0)
        np.clip(sig_vals, -1.0, 1.0, out=sig_vals)
        # shift(1) + fillna(0): prepend 0, drop last
        shifted_vals = np.empty_like(sig_vals)
        shifted_vals[0] = 0.0
        shifted_vals[1:] = sig_vals[:-1]
        # Place into unified grid via searchsorted
        pos_arr[row_indexes[c], j] = shifted_vals

    # Vectorized ffill with limit using pandas (C-optimized)
    _tmp = pd.DataFrame(pos_arr)
    # ``.values`` may be a read-only view under pandas copy-on-write; take the
    # copy-returning nan_to_num (not in-place) so the fill never writes a
    # read-only destination.
    pos_arr = np.nan_to_num(_tmp.ffill(limit=ffill_limit).values, nan=0.0)

    # Construct DataFrames for return
    close = pd.DataFrame(close_arr, index=dates, columns=codes)
    close_val = pd.DataFrame(close_val_arr, index=dates, columns=codes)
    pos = pd.DataFrame(pos_arr, index=dates, columns=codes)
    ret = bar_returns(close, label="engine per-symbol returns")

    if optimizer is not None:
        pos = optimizer(ret, pos, dates)

    scale = pos.abs().sum(axis=1).clip(lower=1.0)
    pos = pos.div(scale, axis=0)

    return dates, close, close_val, pos, ret


class BaseEngine(ABC):
    """Abstract base for all market engines.

    Subclasses override market-rule methods:
      - can_execute: whether a trade is allowed by market rules
      - round_size: lot-size rounding
      - calc_commission: fee structure
      - apply_slippage: slippage model
      - on_bar: per-bar hooks (funding fees, liquidation, etc.)
    """

    def __init__(self, config: dict):
        self.config = config
        self.initial_capital: float = config.get("initial_cash", 1_000_000)
        self.default_leverage: float = config.get("leverage", 1.0)
        self.position_adjustment = str(config.get("position_adjustment", "hold")).lower()
        if self.position_adjustment not in {"hold", "rebalance"}:
            raise ValueError("position_adjustment must be 'hold' or 'rebalance'")
        self.rebalance_mask: RebalanceMask = validate_rebalance_mask(
            config.get("rebalance_mask")
        )
        if self.rebalance_mask is not None and self.position_adjustment != "rebalance":
            raise ValueError(
                "rebalance_mask requires position_adjustment='rebalance'"
            )
        self.rebalance_bars_executed = 0
        # Relative drift band around the target weight. Zero reproduces the
        # historical behaviour, where the only thing separating "resize" from
        # "leave it alone" was the slippage width -- measured, a 0.01% daily
        # move re-pinned the position on 19 of 30 bars, which is noise being
        # traded, not a decision being executed.
        self.rebalance_tolerance = float(config.get("rebalance_tolerance", 0.0) or 0.0)
        if not math.isfinite(self.rebalance_tolerance) or self.rebalance_tolerance < 0.0:
            raise ValueError("rebalance_tolerance must be a finite, non-negative fraction")
        # Markets that clear at or below zero (e.g. EU day-ahead power) opt in
        # to opening on negative-price bars. Default False preserves the legacy
        # "reject any open_price <= 0" behavior. An exactly-zero open is always
        # rejected (undefined size = notional / price); negatives are handled by
        # abs()-based sizing and margin below.
        self.allow_nonpositive_prices: bool = bool(
            config.get("allow_nonpositive_prices", False)
        )
        #: Bar fields consulted, in order, for the price-limit base price.
        #: Futures engines put ``pre_settle`` first: exchanges set the band off
        #: the previous settlement, not the previous close.
        self.base_price_fields: tuple[str, ...] = ("pre_close",)
        self.capital: float = self.initial_capital
        self.positions: dict[str, Position] = {}
        self.fill_records: list[FillRecord] = []
        self.trades: list[TradeRecord] = []
        self.equity_snapshots: list[EquitySnapshot] = []
        # Per-bar, post-fill portfolio weights.  These are deliberately kept
        # separate from ``target_pos``: market rules, lot rounding, fees, and
        # insufficient cash can all make the executed book differ from the
        # optimiser's request.
        self.actual_position_snapshots: list[tuple[pd.Timestamp, dict[str, float]]] = []
        # Hold mode executes a target change only when the direction flips or
        # the target reaches zero, so a same-direction resize is dropped. That
        # is a legitimate mode -- it is what "enter once, hold to exit" means --
        # but dropping a request the strategy actually made must not be silent
        # (#918). The previous target is what makes the difference visible:
        # comparing against the CURRENT weight would fire on every bar of a
        # buy-and-hold position, whose weight drifts with price by design.
        self._last_target_weight: dict[str, float] = {}
        self.dropped_target_adjustments: list[dict[str, Any]] = []
        # Opening plans the engine wanted but could not take, keyed
        # (symbol, reason). A sleeve whose target notional rounds below one
        # lot trades zero times while the run reports a normal result
        # (#1235); counting the causes is what makes that visible in the
        # metrics instead of only to a subclass that overrode the hook.
        self.plan_rejections: Counter = Counter()
        self._bar_idx: int = 0
        # OpenTerm: rows of the current bar, built once per (frame, ts). `df.loc[ts]` was half the run time.
        self._row_ts = None
        self._row_cache: dict[int, Any] = {}
        self._active_symbol: str = ""  # set by _rebalance/_close_position for subclass use

    # ── Market rule interface (subclass must implement) ──

    @abstractmethod
    def can_execute(self, symbol: str, direction: int, bar: pd.Series) -> bool:
        """Whether market rules allow this trade.

        Args:
            symbol: Instrument identifier.
            direction: 1 (long), -1 (short), 0 (close).
            bar: Current bar data (OHLCV + extras).

        Returns:
            True if allowed.
        """

    @abstractmethod
    def round_size(self, raw_size: float, price: float) -> float:
        """Round position size per market lot rules.

        Args:
            raw_size: Desired size.
            price: Current price.

        Returns:
            Rounded size.
        """

    @abstractmethod
    def calc_commission(self, size: float, price: float, direction: int, is_open: bool) -> float:
        """Calculate commission for a trade.

        Args:
            size: Trade size.
            price: Execution price.
            direction: 1 or -1.
            is_open: True for opening, False for closing.

        Returns:
            Commission amount.
        """

    @abstractmethod
    def apply_slippage(self, price: float, direction: int) -> float:
        """Apply slippage to execution price.

        Args:
            price: Raw price.
            direction: 1 (buying / covering short) or -1 (selling / shorting).

        Returns:
            Slipped price.
        """

    def historical_base_price(self, symbol: str, bar: pd.Series) -> float | None:
        """Return a reference price that is known before this bar's fill.

        Price-limit bands must be derived from a base price the market already
        knew when the order was placed. ``can_execute`` runs before the fill,
        and this engine fills at the CURRENT bar's open, so the current bar's
        close is not available information: using it is lookahead.

        Both sources here are strictly historical:
          1. the first field of :attr:`base_price_fields` present on the bar —
             ``pre_close`` for cash equity, ``pre_settle`` first for futures,
             whose exchanges set the band off the previous settlement;
          2. the previous row of the close panel the run pre-extracts, which is
             absent in a cross-market composite run (its sub-engines are
             stateless rule books with no panel of their own).

        Args:
            symbol: Symbol whose base price is wanted.
            bar: Current bar.

        Returns:
            The base price, or None when no historical close is reachable
            (first bar of a run, or a composite sub-engine).
        """
        for field in self.base_price_fields:
            if field in bar.index:
                raw = bar[field]
                if pd.notna(raw) and float(raw) > 0:
                    return float(raw)

        close_arr = getattr(self, "_close_arr", None)
        col = getattr(self, "_code_to_col", {}).get(symbol)
        row = getattr(self, "_bar_idx", 0) - 1
        if close_arr is not None and col is not None and row >= 0:
            value = close_arr[row, col]
            if pd.notna(value) and float(value) > 0:
                return float(value)

        # Last resort: reconstruct the prior close from tushare's pct_chg, which
        # is in percentage points. Both inputs sit on the current bar, but their
        # ratio is the PREVIOUS close, so the result is still historical.
        if "pct_chg" in bar.index and "close" in bar.index:
            pct, close = bar["pct_chg"], bar["close"]
            if pd.notna(pct) and pd.notna(close) and float(close) > 0:
                denominator = 1.0 + float(pct) / 100.0
                if denominator > 0:
                    return float(close) / denominator
        return None

    def prospective_fill_price(self, bar: pd.Series, direction: int) -> float | None:
        """Return the price this engine would fill at on this bar.

        Mirrors the sizing path: the bar's open, with slippage applied in the
        trade direction. Comparing THIS against a price-limit band keeps the
        simulation from ever transacting outside the exchange's legal range.

        Args:
            bar: Current bar.
            direction: 1 (buy / cover), -1 (sell / short), 0 (close).

        Returns:
            The prospective fill price, or None when the bar has no usable open.
        """
        raw = bar.get("open", bar.get("close"))
        if raw is None or pd.isna(raw):
            return None
        price = float(raw)
        if price <= 0 and not self.allow_nonpositive_prices:
            return None
        return self.apply_slippage(price, direction)

    def limit_band(
        self, symbol: str, bar: pd.Series, limit: float
    ) -> tuple[float, float] | None:
        """Return the (lower, upper) legal price band for this bar.

        Args:
            symbol: Symbol whose band is wanted.
            bar: Current bar.
            limit: Band half-width as a fraction (0.1 for +/-10%).

        Returns:
            The (lower, upper) band, or None when no historical base price is
            reachable — in which case the caller must not fabricate a block.
        """
        base = self.historical_base_price(symbol, bar)
        if base is None or base <= 0 or not limit:
            return None
        return base * (1.0 - float(limit)), base * (1.0 + float(limit))

    def on_bar(self, symbol: str, bar: pd.Series, timestamp: pd.Timestamp) -> None:
        """Per-bar market-rule hook (funding fees, liquidation, etc.).

        Default: no-op. Override in subclass as needed.
        """

    def before_rebalance_bar(
        self,
        timestamp: pd.Timestamp,
        data_map: dict[str, pd.DataFrame],
        codes: list[str],
    ) -> bool:
        """Run pre-execution hooks; return True to stop after this snapshot."""
        return False

    def after_rebalance_bar(
        self,
        timestamp: pd.Timestamp,
        data_map: dict[str, pd.DataFrame],
        codes: list[str],
    ) -> bool:
        """Run the legacy post-fill bar hooks; return True to stop."""
        for code in codes:
            row = self._bar_row(data_map[code], timestamp)
            if row is not None:
                self.on_bar(code, row, timestamp)
        return False

    def after_position_adjustment(
        self,
        *,
        action: str,
        timestamp: pd.Timestamp,
        before: Position,
        after: Position,
        execution_price: float,
        trading_fee: float,
        realized_pnl: float = 0.0,
        released_margin: float = 0.0,
    ) -> None:
        """Allow engines to update risk state/evidence after a committed delta fill."""
        return

    #: Rejection causes that mean the engine WANTED a position and could not
    #: take it. ``no_target_weight`` and ``already_held`` are excluded: they
    #: mean nothing was wanted, which is not a finding.
    UNFILLED_PLAN_REASONS = (
        "no_data",
        "no_bar",
        "execution_blocked",
        "invalid_price",
        "zero_size",
        "insufficient_capital",
    )

    def _bar_row(self, frame: pd.DataFrame, ts: pd.Timestamp):
        """``frame.loc[ts]`` or None when ``ts`` is not in ``frame.index``, cached for the current bar
        (OpenTerm addition; hooks never mutate the row, so sharing it within a bar is safe)."""
        if ts is not self._row_ts and ts != self._row_ts:
            self._row_ts = ts
            self._row_cache = {}
        key = id(frame)
        if key in self._row_cache:
            return self._row_cache[key]
        row = frame.loc[ts] if ts in frame.index else None
        self._row_cache[key] = row
        return row

    def _plan_rejection_metrics(self) -> dict[str, Any]:
        """Summarise opening plans the engine wanted but could not take.

        A rejected plan is invisible in the result otherwise: the run reports a
        normal equity curve over the symbols that did fill, so a sleeve whose
        target notional never clears one lot silently drops out of the book and
        the configuration is graded as if it had never contained that sleeve
        (#1235). Only the causes that mean "wanted but unfillable" are counted.

        Returns:
            ``unfilled_plan_rejections`` (total) and
            ``unfilled_plan_rejections_by_symbol`` (``{symbol: {reason: n}}``),
            the latter empty when nothing was rejected.
        """
        by_symbol: dict[str, dict[str, int]] = {}
        total = 0
        for (symbol, reason), count in self.plan_rejections.items():
            if reason not in self.UNFILLED_PLAN_REASONS:
                continue
            by_symbol.setdefault(symbol, {})[reason] = count
            total += count
        return {
            "unfilled_plan_rejections": total,
            "unfilled_plan_rejections_by_symbol": by_symbol,
        }

    def _engine_diagnostics(self) -> dict[str, Any]:
        """Per-engine facts about how this run was priced.

        Default empty. An engine overrides this to state something the metrics
        cannot be derived from — currently ChinaFuturesEngine reporting which
        products it priced on a generic default instead of a table entry
        (#1393), where the alternative is a number that looks like data.

        Returns:
            Extra keys merged into the metrics dict; empty when there is
            nothing to declare.
        """
        return {}

    def _on_plan_rejected(self, symbol: str, reason: str, timestamp: pd.Timestamp) -> None:
        """Observe a silently rejected opening-order plan.

        ``_plan_open_order`` returns ``None`` for several distinct reasons —
        nothing wanted, already held, missing data, missing bar, market rule
        block, unusable price, or a target too small to fill after lot
        rounding. Callers only see ``None``, so this hook is the only way for
        an engine subclass to tell "nothing to do" apart from "wanted but
        unfillable".

        The capital fit reports one more cause after the planner: a sleeve that
        was a real order at full scale and left the basket when every opening
        order was scaled down to the cash available is ``insufficient_capital``
        (#1470), reported once per bar — never the trial plans of the search.

        Args:
            symbol: Instrument the plan was for.
            reason: Machine-readable cause: ``no_target_weight``,
                ``already_held``, ``no_data``, ``no_bar``,
                ``execution_blocked``, ``invalid_price``, ``zero_size`` or
                ``insufficient_capital``.
            timestamp: Decision bar timestamp.
        """
        self.plan_rejections[(symbol, reason)] += 1

    def execution_open(self, bar: pd.Series) -> float:
        """Return the normal market-fill price for a bar."""
        return float(bar.get("open", bar.get("close", 0)))

    def valuation_open(self, bar: pd.Series) -> float:
        """Return the price observable when open orders are sized."""
        return float(bar.get("open", bar.get("close", 0)))

    # ── PnL / margin calculation hooks ──
    # Override in FuturesBaseEngine to inject contract multiplier.

    def _calc_pnl(
        self, symbol: str, direction: int, size: float,
        entry_price: float, exit_price: float,
    ) -> float:
        """Realised PnL for a closed position."""
        return direction * size * (exit_price - entry_price)

    def _calc_margin(
        self, symbol: str, size: float, price: float, leverage: float,
    ) -> float:
        """Margin (collateral) required for a position.

        ``abs(price)`` so collateral stays positive when the entry price is
        negative; for the usual positive price this is unchanged.
        """
        return size * abs(price) / leverage

    def _calc_raw_size(
        self, symbol: str, target_notional: float, price: float,
    ) -> float:
        """Convert target notional exposure to number of units/contracts.

        Size is a positive magnitude — direction carries the sign elsewhere —
        so divide by ``abs(price)``; a negative entry price must not flip the
        size negative (which the ``size <= 0`` guard would then reject). For a
        positive price this is unchanged.
        """
        return target_notional / abs(price)

    def _leverage_for_symbol(self, symbol: str) -> float:
        """Return leverage used to size and margin one symbol."""
        del symbol
        return self.default_leverage

    # ── Main entry ──

    def run(
        self,
        data_map: dict[str, pd.DataFrame],
        signal_map: dict[str, pd.Series],
        bars_per_year: int | None = 252,
        bench_ret: pd.Series | None = None,
        benchmark_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """In-memory core of Vibe's ``run_backtest`` (OpenTerm: data loading, signal generation, artifacts and the
        run card live outside the engine). Steps 3-6 are unchanged: align, warm-up cut, bar loop, metrics.

        ``bench_ret``: per-bar benchmark returns; None = equal-weight basket of the traded symbols (Vibe's default).
        """
        for code, sig in signal_map.items():
            if not isinstance(sig, pd.Series):
                raise ValueError(f"SignalEngine.generate() returned {type(sig).__name__} for {code!r}, expected a Series")  # noqa: TRY004
        valid_codes = sorted(c for c in signal_map if c in data_map)
        if not valid_codes:
            raise ValueError("NO SIGNALS: the strategy returned no series for the loaded symbols")

        dates, close_df, close_val_df, target_pos, ret_df = _align(data_map, signal_map, valid_codes)
        valid_codes = [c for c in valid_codes if c in target_pos.columns]
        warmup_end = evaluation_start_index(self.config, dates)
        if warmup_end:
            dates = dates[warmup_end:]
            close_df = close_df.iloc[warmup_end:]
            close_val_df = close_val_df.iloc[warmup_end:]
            target_pos = target_pos.iloc[warmup_end:]
            ret_df = ret_df.iloc[warmup_end:]
        self._execute_bars(dates, data_map, close_df, target_pos, valid_codes, close_val_df=close_val_df)
        actual_pos = self._actual_positions_frame(valid_codes)
        equity_series = pd.Series(
            [s.equity for s in self.equity_snapshots],
            index=[s.timestamp for s in self.equity_snapshots],
        )
        if bench_ret is None:
            bench_ret = ret_df.mean(axis=1) if ret_df.shape[1] > 0 else pd.Series(0.0, index=dates)
        else:
            bench_ret = bench_ret.reindex(dates).fillna(0.0)
        realized_turnover = calc_fill_turnover_series(self.fill_records, equity_series)
        m = calc_metrics(
            equity_series,
            self.trades,
            self.initial_capital,
            bars_per_year,
            bench_ret,
            actual_pos,
            turnover_series=realized_turnover,
        )
        if benchmark_metadata:
            m.update(benchmark_metadata)
            if "benchmark_return" in benchmark_metadata:
                m["benchmark_return"] = round(benchmark_metadata["benchmark_return"], 6)
                m["excess_return"] = round(m["total_return"] - benchmark_metadata["benchmark_return"], 6)
        m.update(self._plan_rejection_metrics())
        m.update(self._engine_diagnostics())
        if self.rebalance_mask is not None:
            m["rebalance_mask"] = self.rebalance_mask
            m["rebalance_bars_executed"] = self.rebalance_bars_executed
        m["by_symbol"] = by_symbol_stats(self.trades)
        m["by_exit_reason"] = by_exit_reason_stats(self.trades)
        m["position_adjustment"] = self.position_adjustment
        m["rebalance_tolerance"] = self.rebalance_tolerance
        m["dropped_target_adjustment_count"] = len(self.dropped_target_adjustments)
        self.equity_series = equity_series
        self.bench_ret = bench_ret
        self.target_pos = target_pos
        return m

    def _execute_bars(
        self,
        dates: pd.DatetimeIndex,
        data_map: dict[str, pd.DataFrame],
        close_df: pd.DataFrame,
        target_pos: pd.DataFrame,
        codes: list[str],
        close_val_df: pd.DataFrame | None = None,
    ) -> None:
        """Bar-by-bar execution with market rule enforcement."""
        # Pre-extract numpy arrays for O(1) indexed access instead of DataFrame.at[]
        # Explicit column reindex ensures array column order matches codes parameter,
        # regardless of DataFrame internal column ordering (which may be alphabetical).
        _target_arr = target_pos[codes].values  # (n_dates, n_codes) ndarray
        _close_arr = close_df[codes].values  # (n_dates, n_codes) ndarray
        if close_val_df is None:
            close_val_df = close_df.ffill()
        _val_arr = close_val_df[codes].values  # unbounded ffill, valuation only
        _code_to_col = {c: j for j, c in enumerate(codes)}
        # Store as instance attrs for use in _calc_equity / _safe_price
        self._close_arr = _close_arr
        self._val_arr = _val_arr
        self._code_to_col = _code_to_col
        self.actual_position_snapshots = []
        execution_dates = resolve_rebalance_dates(self.rebalance_mask, dates)
        self.rebalance_bars_executed = 0

        for i, ts in enumerate(dates):
            self._bar_idx = i

            stop_run = self.before_rebalance_bar(ts, data_map, codes)
            execute_targets = execution_dates is None or ts in execution_dates

            # a. Value the book at prices observable when orders execute.
            # Rebalances happen at the bar open, so using close_df[ts] here
            # would let the yet-unknown decision-bar close affect order size.
            equity = self._calc_open_equity(data_map, close_df, ts)
            target_weights: dict[str, float | None] = {}
            for c in codes:
                try:
                    val = _target_arr[i, _code_to_col[c]]
                    target_weights[c] = (
                        None
                        if stop_run or not execute_targets
                        else (float(val) if not np.isnan(val) else 0.0)
                    )
                except Exception as exc:  # noqa: BLE001
                    target_weights[c] = None
                    logger.warning("Target weight failed for %s at %s: %s", c, ts, exc)

            if self.position_adjustment == "rebalance":
                if execute_targets and not stop_run:
                    self._execute_target_rebalance(
                        target_weights, data_map, ts, equity, codes
                    )
                    self.rebalance_bars_executed += 1
                target_weights = {}
            else:
                self._record_dropped_target_adjustments(target_weights, ts)

            # b. In legacy hold mode, release capital before opening replacement
            # positions or increasing other positions.  A
            # single mixed close/open pass makes rotations depend on symbol
            # iteration order when the new name is visited before the old one.
            for c in codes:
                target_w = target_weights.get(c)
                current_pos = self.positions.get(c)
                if target_w is None or current_pos is None:
                    continue
                target_dir = 1 if target_w > 1e-9 else (-1 if target_w < -1e-9 else 0)
                if target_dir == 0 or target_dir != current_pos.direction:
                    try:
                        self._rebalance(c, 0.0, data_map.get(c), ts, equity)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "Rebalance close failed for %s at %s: %s", c, ts, exc
                        )

            # c. Price every opening order before committing any of them.  If
            # the requested basket does not fit after fees/lot rounding, apply
            # one common scale factor to all target weights.  This preserves
            # portfolio proportions and makes fills independent of input code
            # order; sequential cash clipping would privilege the first name.
            open_targets: list[tuple[str, float, pd.DataFrame | None]] = []
            for c in sorted(codes):
                target_w = target_weights.get(c)
                if target_w is None:
                    continue
                target_dir = 1 if target_w > 1e-9 else (-1 if target_w < -1e-9 else 0)
                current_pos = self.positions.get(c)
                if current_pos is not None and (
                    target_dir == 0 or target_dir != current_pos.direction
                ):
                    continue
                if current_pos is None and target_dir != 0:
                    open_targets.append((c, target_w, data_map.get(c)))

            def _plans(scale: float, *, observe: bool) -> list[_OpenOrder]:
                result: list[_OpenOrder] = []
                for c, target_w, frame in open_targets:  # noqa: B023
                    try:
                        order = self._plan_open_order(
                            c, target_w * scale, frame, ts, equity, observe=observe  # noqa: B023
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "Rebalance open plan failed for %s at %s: %s",
                            c,
                            ts,  # noqa: B023
                            exc,
                        )
                        continue
                    if order is not None:
                        result.append(order)
                return result

            planned = _plans(1.0, observe=True)
            if sum(order.cost for order in planned) > self.capital + 1e-9:
                # The trial plans of the search are not findings: one starved
                # open used to be booked as a zero_size rejection on every
                # bisection step (#1470). The sleeve that leaves the basket is
                # reported once, after the search, as the rebalance path does.
                wanted = [order.symbol for order in planned]
                # Nothing fits until a candidate proves it does: with cash below
                # zero (a funding debit leaves it there) not even the empty plan
                # fits, and the full-scale plan used to fall through to
                # _execute_open_order and abort the run (#1542).
                fitting: list[_OpenOrder] = []
                low, high = 0.0, 1.0
                for _ in range(50):
                    mid = (low + high) / 2.0
                    candidate = _plans(mid, observe=False)
                    if sum(order.cost for order in candidate) <= self.capital + 1e-9:
                        low, fitting = mid, candidate
                    else:
                        high = mid
                planned = fitting
                fitted = {order.symbol for order in planned}
                for symbol in wanted:
                    if symbol not in fitted:
                        self._on_plan_rejected(symbol, "insufficient_capital", ts)

            for order in planned:
                self._execute_open_order(order, ts)

            # d. Apply post-execution hooks after all normal market fills.
            if not stop_run:
                stop_run = self.after_rebalance_bar(ts, data_map, codes)

            # e. Record equity snapshot
            snap_equity = self._calc_equity(close_df, ts)
            self.actual_position_snapshots.append(
                (ts, self._actual_weights(close_df, ts, codes, snap_equity))
            )
            if self.positions and type(self)._calc_pnl is BaseEngine._calc_pnl:
                _syms = list(self.positions.keys())
                _eps = np.array([p.entry_price for p in self.positions.values()])
                _dirs = np.array([p.direction for p in self.positions.values()])
                _sizes = np.array([p.size for p in self.positions.values()])
                _cps = np.array([
                    self._safe_price(
                        close_df, ts, s, ep,
                        _arr=_close_arr, _row=i, _col=_code_to_col.get(s),
                        _val_arr=_val_arr,
                    )
                    for s, ep in zip(_syms, _eps)
                ])
                total_unrealized = float(np.sum(_dirs * _sizes * (_cps - _eps)))
            else:
                total_unrealized = 0.0
                for p in self.positions.values():
                    cp = self._safe_price(
                        close_df, ts, p.symbol, p.entry_price,
                        _arr=_close_arr, _row=i, _col=_code_to_col.get(p.symbol),
                        _val_arr=_val_arr,
                    )
                    total_unrealized += self._calc_pnl(p.symbol, p.direction, p.size, p.entry_price, cp)
            self.equity_snapshots.append(EquitySnapshot(
                timestamp=ts,
                capital=self.capital,
                unrealized=total_unrealized,
                equity=snap_equity,
                positions=len(self.positions),
            ))

            if stop_run:
                break

        # f. Force close all remaining positions
        if len(dates) > 0:
            _last_row = min(self._bar_idx, len(dates) - 1)
            last_ts = dates[_last_row]
            for c in list(self.positions.keys()):
                pos = self.positions[c]
                mark_price = self._safe_price(
                    close_df, last_ts, c, pos.entry_price,
                    _arr=_close_arr, _row=_last_row, _col=_code_to_col.get(c),
                    _val_arr=_val_arr,
                )
                self._active_symbol = c
                exit_price = self.apply_slippage(mark_price, -pos.direction)
                self._close_position(c, exit_price, last_ts, "end_of_backtest")

            # The final snapshot feeds metrics and artifacts.  Replace its
            # pre-liquidation mark with post-liquidation cash so terminal
            # slippage and exit commission are reflected in reported equity.
            if self.equity_snapshots:
                self.equity_snapshots[-1] = EquitySnapshot(
                    timestamp=last_ts,
                    capital=self.capital,
                    unrealized=0.0,
                    equity=self.capital,
                    positions=0,
                )
            if self.actual_position_snapshots:
                self.actual_position_snapshots[-1] = (
                    last_ts, {code: 0.0 for code in codes}
                )

        # Clean up temporary instance attributes
        self._close_arr = None
        self._val_arr = None
        self._code_to_col = None

    def _calc_open_equity(
        self,
        data_map: dict[str, pd.DataFrame],
        close_df: pd.DataFrame,
        ts: pd.Timestamp,
    ) -> float:
        """Value current positions at the execution bar's observable open.

        For a symbol that has a bar at ``ts``, its open is the mark available
        when next-bar-open orders execute.  Symbols without a bar on the
        unified calendar retain the aligned close fallback, which is the most
        recent price carried by ``_align``.
        """
        if not self.positions:
            return self.capital

        equity = self.capital
        for sym, pos in self.positions.items():
            _arr = getattr(self, "_close_arr", None)
            _varr = getattr(self, "_val_arr", None)
            _row = getattr(self, "_bar_idx", None)
            _c2c = getattr(self, "_code_to_col", None)
            current_price = self._safe_price(
                close_df, ts, sym, pos.entry_price,
                _arr=_arr, _row=_row, _col=(_c2c.get(sym) if _c2c else None),
                _val_arr=_varr,
            )
            frame = data_map.get(sym)
            row = self._bar_row(frame, ts) if frame is not None else None
            if row is not None:
                open_price = self.valuation_open(row)
                if (
                    pd.notna(open_price)
                    and float(open_price) > 0
                ):
                    current_price = float(open_price)

            margin = self._calc_margin(sym, pos.size, pos.entry_price, pos.leverage)
            unrealized = self._calc_pnl(
                sym, pos.direction, pos.size, pos.entry_price, current_price
            )
            equity += margin + unrealized
        return equity

    def _calc_equity(self, close_df: pd.DataFrame, ts: pd.Timestamp) -> float:
        """Total equity = free cash + sum(margin + unrealised) per position.

        Uses vectorized numpy path when _calc_pnl/_calc_margin are not
        overridden by a subclass (FuturesBaseEngine, CompositeEngine).
        """
        if not self.positions:
            return self.capital

        _base_pnl = type(self)._calc_pnl is BaseEngine._calc_pnl
        _base_margin = type(self)._calc_margin is BaseEngine._calc_margin

        # Use array fast-path when available
        _arr = getattr(self, "_close_arr", None)
        _varr = getattr(self, "_val_arr", None)
        _row = getattr(self, "_bar_idx", None)
        _c2c = getattr(self, "_code_to_col", None)

        if _base_pnl and _base_margin:
            syms = list(self.positions.keys())
            sizes = np.array([p.size for p in self.positions.values()])
            entry_prices = np.array([p.entry_price for p in self.positions.values()])
            directions = np.array([p.direction for p in self.positions.values()])
            leverages = np.array([p.leverage for p in self.positions.values()])

            current_prices = np.array([
                self._safe_price(
                    close_df, ts, s, ep,
                    _arr=_arr, _row=_row, _col=(_c2c.get(s) if _c2c else None),
                    _val_arr=_varr,
                )
                for s, ep in zip(syms, entry_prices)
            ])

            margins = sizes * entry_prices / leverages
            pnls = directions * sizes * (current_prices - entry_prices)
            return self.capital + float(np.sum(margins + pnls))

        equity = self.capital
        for sym, pos in self.positions.items():
            cp = self._safe_price(
                close_df, ts, sym, pos.entry_price,
                _arr=_arr, _row=_row, _col=(_c2c.get(sym) if _c2c else None),
                _val_arr=_varr,
            )
            margin = self._calc_margin(sym, pos.size, pos.entry_price, pos.leverage)
            unrealized = self._calc_pnl(sym, pos.direction, pos.size, pos.entry_price, cp)
            equity += margin + unrealized
        return equity

    def _rebalance(
        self,
        symbol: str,
        target_weight: float,
        df: pd.DataFrame | None,
        ts: pd.Timestamp,
        equity: float,
    ) -> None:
        """Adjust position for *symbol* toward *target_weight*."""
        self._active_symbol = symbol
        target_dir = 1 if target_weight > 1e-9 else (-1 if target_weight < -1e-9 else 0)
        current_pos = self.positions.get(symbol)

        # Nothing to do
        if current_pos is None and target_dir == 0:
            return
        bar = self._bar_row(df, ts) if df is not None else None
        if bar is None:
            return

        # Close if target is flat or direction changed
        if current_pos is not None:
            need_close = target_dir == 0 or target_dir != current_pos.direction
            if need_close:
                if self.can_execute(symbol, 0, bar):
                    open_price = self.execution_open(bar)
                    price = self.apply_slippage(open_price, -current_pos.direction)
                    self._close_position(symbol, price, ts, "signal")
                else:
                    return  # blocked (e.g. limit-down can't sell)

        if target_dir != 0 and symbol not in self.positions:
            order = self._plan_open_order(symbol, target_weight, df, ts, equity)
            if order is not None and order.cost <= self.capital + 1e-9:
                self._execute_open_order(order, ts)

    def _plan_open_order(
        self,
        symbol: str,
        target_weight: float,
        df: pd.DataFrame | None,
        ts: pd.Timestamp,
        equity: float,
        *,
        allow_existing: bool = False, require_positive_price: bool = False,
        observe: bool = True,
    ) -> _OpenOrder | None:
        """Price an opening order without mutating portfolio state.

        ``observe=False`` plans a trial inside a capital-fit search: a rejection
        there is not a finding and is not reported to ``_on_plan_rejected``.
        """
        self._active_symbol = symbol

        def rejected(reason: str) -> None:
            if observe:
                self._on_plan_rejected(symbol, reason, ts)

        direction = 1 if target_weight > 1e-9 else (-1 if target_weight < -1e-9 else 0)
        if direction == 0:
            rejected("no_target_weight")
            return None
        if symbol in self.positions and not allow_existing:
            rejected("already_held")
            return None
        if df is None:
            rejected("no_data")
            return None
        bar = self._bar_row(df, ts)
        if bar is None:
            rejected("no_bar")
            return None
        if not self.can_execute(symbol, direction, bar):
            rejected("execution_blocked")
            return None
        open_price = self.execution_open(bar)
        if require_positive_price:
            self._validate_rebalance_values(open_price, positive=True)
        # Zero is always rejected (size = notional / price is undefined);
        # negatives are rejected unless this engine opted into non-positive
        # prices, in which case abs()-based sizing/margin below handle them.
        elif open_price == 0 or (open_price < 0 and not self.allow_nonpositive_prices):
            rejected("invalid_price")
            return None
        price = self.apply_slippage(open_price, direction)
        if require_positive_price:
            self._validate_rebalance_values(price, positive=True)
        leverage = self._leverage_for_symbol(symbol)
        target_notional = abs(target_weight) * equity * leverage
        size = self.round_size(
            self._calc_raw_size(symbol, target_notional, price), price
        )
        if size <= 0:
            rejected("zero_size")
            return None
        margin = self._calc_margin(symbol, size, price, leverage)
        commission = self.calc_commission(
            size, price, direction, is_open=True
        )
        return _OpenOrder(
            symbol=symbol,
            direction=direction,
            price=price,
            size=size,
            leverage=leverage,
            margin=margin,
            commission=commission,
        )

    # A target move smaller than this is optimiser float noise, not a decision.
    _TARGET_CHANGE_EPSILON = 1e-6
    # Detail lines are logged for the first few only; the rest are counted.
    _DROPPED_ADJUSTMENT_LOG_LIMIT = 3

    def _record_dropped_target_adjustments(
        self, target_weights: dict[str, float | None], ts: pd.Timestamp
    ) -> None:
        """Note every same-direction resize that hold mode is about to drop.

        Only a change in the TARGET counts. A held position's weight drifts
        with price on its own, so comparing the target against the current
        weight would report a buy-and-hold position as a dropped request on
        every bar.

        Args:
            target_weights: This bar's target per symbol; ``None`` means the
                strategy produced no decision and nothing is dropped.
            ts: The decision timestamp, recorded with each dropped request.
        """
        for symbol, target_w in target_weights.items():
            if target_w is None:
                continue
            previous = self._last_target_weight.get(symbol)
            self._last_target_weight[symbol] = target_w
            if previous is None or abs(target_w - previous) <= self._TARGET_CHANGE_EPSILON:
                continue
            position = self.positions.get(symbol)
            if position is None:
                continue
            target_dir = 1 if target_w > 1e-9 else (-1 if target_w < -1e-9 else 0)
            # A flip or an exit IS executed in hold mode; only a same-direction
            # resize is dropped.
            if target_dir == 0 or target_dir != position.direction:
                continue
            self.dropped_target_adjustments.append(
                {
                    "timestamp": ts,
                    "symbol": symbol,
                    "previous_target_weight": previous,
                    "requested_target_weight": target_w,
                    "direction": position.direction,
                }
            )
            if len(self.dropped_target_adjustments) <= self._DROPPED_ADJUSTMENT_LOG_LIMIT:
                logger.warning(
                    "position_adjustment='hold' dropped a resize: %s at %s asked for "
                    "weight %.6f (was %.6f) and the position was left unchanged. "
                    "Set position_adjustment='rebalance' to execute target changes.",
                    symbol,
                    ts,
                    target_w,
                    previous,
                )

    def _execute_target_rebalance(
        self,
        target_weights: dict[str, float | None], data_map: dict[str, pd.DataFrame],
        ts: pd.Timestamp, equity: float, codes: list[str],
    ) -> None:
        """Plan every target delta, preflight capital, then commit the basket."""
        reductions: list[_ReductionOrder] = []
        opens: list[_OpenOrder] = []

        for symbol in sorted(codes):
            target_weight = target_weights.get(symbol)
            if target_weight is None:
                continue
            self._validate_rebalance_values(target_weight)

            self._active_symbol = symbol
            before = self.positions.get(symbol)
            target_direction = 1 if target_weight > 1e-9 else (-1 if target_weight < -1e-9 else 0)
            frame = data_map.get(symbol)
            bar = self._bar_row(frame, ts) if frame is not None else None
            if bar is None:
                continue

            if before is None or target_direction != before.direction:
                if before is not None:
                    if not self.can_execute(symbol, 0, bar):
                        continue
                    raw_price = self.execution_open(bar)
                    self._validate_rebalance_values(raw_price, positive=True)
                    price = self.apply_slippage(raw_price, -before.direction)
                    self._validate_rebalance_values(price, positive=True)
                    reductions.append(self._plan_reduction(before, 0.0, price))
                    if target_direction == 0:
                        continue
                order = self._plan_open_order(
                    symbol,
                    target_weight,
                    frame,
                    ts,
                    equity,
                    allow_existing=before is not None,
                    require_positive_price=True,
                )
                if order is not None:
                    self._validate_rebalance_values(
                        order.price, order.leverage, order.size, order.margin, order.commission
                    )
                    opens.append(order)
                continue

            raw_price = self.execution_open(bar)
            self._validate_rebalance_values(raw_price, positive=True)
            leverage = self._leverage_for_symbol(symbol)
            self._validate_rebalance_values(raw_price, before.leverage, leverage)
            target_notional = abs(target_weight) * equity * before.leverage
            prices = (
                self.apply_slippage(raw_price, before.direction),
                self.apply_slippage(raw_price, -before.direction),
            )
            self._validate_rebalance_values(*prices, positive=True)
            sizes = tuple(
                self.round_size(
                    self._calc_raw_size(symbol, target_notional, price), price
                )
                for price in prices
            )
            self._validate_rebalance_values(*prices, *sizes)
            # Tolerance band. The held size is compared against the size the
            # target implies at the unslipped price -- keeping the slippage side
            # out of a drift question is the principled choice, though its
            # practical effect is one slippage width and only reaches the
            # outcome within that distance of the band edge, which is why no
            # test pins it: such a test would assert a coincidence.
            # A changed target moves this reference far past any sane band, so
            # target changes still execute at every tolerance.
            if self.rebalance_tolerance > 0.0:
                reference_size = self.round_size(
                    self._calc_raw_size(symbol, target_notional, raw_price), raw_price
                )
                if abs(before.size - reference_size) <= self.rebalance_tolerance * abs(
                    reference_size
                ):
                    continue

            increase = sizes[0] > before.size + 1e-9
            reduction = sizes[1] < before.size - 1e-9
            # Both or neither means the target lies inside the fill-price band.
            if increase == reduction:
                continue
            target_size, price = (sizes[0], prices[0]) if increase else (sizes[1], prices[1])
            if not math.isclose(leverage, before.leverage, rel_tol=1e-9, abs_tol=1e-9):
                raise ValueError("cannot rebalance a position with changed leverage")
            if increase:
                if not self.can_execute(symbol, target_direction, bar):
                    continue
                size = target_size - before.size
                order = _OpenOrder(
                    symbol=symbol,
                    direction=before.direction,
                    price=price,
                    size=size,
                    leverage=leverage,
                    margin=self._calc_margin(symbol, size, price, leverage),
                    commission=self.calc_commission(
                        size, price, before.direction, is_open=True
                    ),
                )
                self._validate_rebalance_values(
                    order.price, order.leverage, order.size, order.margin, order.commission
                )
                opens.append(order)
            elif self.can_execute(symbol, 0, bar):
                reductions.append(self._plan_reduction(before, target_size, price))

        projected_capital = (
            self.capital
            + sum(order.capital_credit for order in reductions)
            - sum(order.cost for order in opens)
        )
        self._validate_rebalance_values(projected_capital)
        if projected_capital < -1e-9:
            fitted = self._fit_rebalance_opens(opens, reductions, ts)
            if fitted is None:
                if sum(order.capital_credit for order in reductions) < 0:
                    # The reductions themselves consume cash (a close whose loss
                    # exceeds its margin): no dropping of opens repairs that, so
                    # the bar aborts atomically as #1274 decided.
                    raise ValueError("insufficient capital for position rebalance")
                # Cash was already below zero (a funding debit can leave it
                # there) and the reductions only release it: drop every open,
                # still run the reductions, and report each open (#1542).
                for order in opens:
                    self._on_plan_rejected(order.symbol, "insufficient_capital", ts)
                if opens:
                    logger.warning(
                        "Cash below zero at %s; no open or increase fits, dropped: %s",
                        ts,
                        ", ".join(sorted({order.symbol for order in opens})),
                    )
                fitted = []
            opens = fitted

        for order in reductions:
            if order.target_size <= 1e-9:
                self._close_position(order.before.symbol, order.price, ts, "signal")
            else:
                self._execute_partial_reduction(order, ts)
        for order in opens:
            if order.symbol in self.positions:
                self._execute_position_increase(order, ts)
            else:
                self._execute_open_order(order, ts)

    def _fit_rebalance_opens(
        self,
        opens: list[_OpenOrder],
        reductions: list[_ReductionOrder],
        ts: pd.Timestamp,
    ) -> list[_OpenOrder] | None:
        """Scale the open sleeve by one common factor so the basket fits.

        #1274: a fully invested target basket plus commission overdrafts by a
        hair and used to abort atomically. Instead, mirror the open-basket
        path's fairness behavior: reductions commit as planned (they release
        capital toward the targets), and every capital-consuming sleeve —
        fresh opens and same-direction increases alike — scales by one common
        factor, preserving portfolio proportions on sizes/notionals (post-fee
        capital weights shift by each sleeve's fee, as with the open path).
        Sizes re-round per market lot rules; a sleeve whose rounded size hits
        zero is dropped and recorded via ``_on_plan_rejected`` as
        ``insufficient_capital`` — it was a real order at full scale, so it is
        the cash that failed, not the lot rule (#1470) — so run-card
        diagnostics see the dropped leg.

        Returns the fitted orders, or ``None`` when no scale fits — not even
        an empty open sleeve; nothing has been committed at that point. The
        caller aborts atomically when the reductions themselves consume cash
        (#1274), and otherwise — cash was already below zero — drops every
        open and still runs the reductions (#1542).
        """
        released = sum(order.capital_credit for order in reductions)

        def _fits(candidate: list[_OpenOrder]) -> bool:
            projected = self.capital + released - sum(order.cost for order in candidate)
            self._validate_rebalance_values(projected)
            return projected >= -1e-9

        def _at_scale(scale: float) -> list[_OpenOrder]:
            scaled: list[_OpenOrder] = []
            for order in opens:
                # round_size/calc_commission dispatch on the active symbol
                # (lot grids, per-symbol fee schedules) — same contract as
                # _plan_open_order.
                self._active_symbol = order.symbol
                size = self.round_size(order.size * scale, order.price)
                if size <= 0:
                    continue
                candidate = _OpenOrder(
                    symbol=order.symbol,
                    direction=order.direction,
                    price=order.price,
                    size=size,
                    leverage=order.leverage,
                    margin=self._calc_margin(
                        order.symbol, size, order.price, order.leverage
                    ),
                    commission=self.calc_commission(
                        size, order.price, order.direction, is_open=True
                    ),
                )
                self._validate_rebalance_values(
                    candidate.price,
                    candidate.leverage,
                    candidate.size,
                    candidate.margin,
                    candidate.commission,
                )
                scaled.append(candidate)
            return scaled

        fitted: list[_OpenOrder] | None = None
        low, high = 0.0, 1.0
        for _ in range(50):
            mid = (low + high) / 2.0
            candidate = _at_scale(mid)
            if _fits(candidate):
                low, fitted = mid, candidate
            else:
                high = mid
        if fitted is not None and len(fitted) < len(opens):
            dropped_symbols = sorted(
                {order.symbol for order in opens}
                - {order.symbol for order in fitted}
            )
            for symbol in dropped_symbols:
                self._on_plan_rejected(symbol, "insufficient_capital", ts)
            logger.warning(
                "Rebalance basket scaled to fit capital; sleeves rounded to "
                "zero and dropped: %s. Set position_adjustment='hold' or "
                "reduce targets if these fills are required.",
                ", ".join(dropped_symbols),
            )
        return fitted

    @staticmethod
    def _validate_rebalance_values(*values: float, positive: bool = False) -> None:
        if all(
            math.isfinite(float(value)) and (not positive or float(value) > 0)
            for value in values
        ):
            return
        raise ValueError(
            "rebalance requires a finite positive execution price"
            if positive
            else "non-finite position rebalance value"
        )

    def _plan_reduction(self, before: Position, target_size: float, price: float) -> _ReductionOrder:
        closed_size = before.size - target_size
        released_margin = self._calc_margin(
            before.symbol, closed_size, before.entry_price, before.leverage
        )
        realized_pnl = self._calc_pnl(
            before.symbol, before.direction, closed_size, before.entry_price, price
        )
        exit_commission = self.calc_commission(
            closed_size, price, before.direction, is_open=False
        )
        self._validate_rebalance_values(
            target_size,
            price,
            released_margin,
            realized_pnl,
            exit_commission,
        )
        return _ReductionOrder(before, target_size, price, released_margin, realized_pnl, exit_commission)

    def _execute_position_increase(self, order: _OpenOrder, ts: pd.Timestamp) -> None:
        """Commit a same-direction opening delta."""
        before = self.positions[order.symbol]
        if order.direction != before.direction:
            raise ValueError("position increase direction must match the open position")
        if order.cost > self.capital + 1e-7:
            raise RuntimeError(
                f"planned order for {order.symbol} exceeds available capital"
            )
        new_size = before.size + order.size
        after = replace(
            before,
            entry_price=(before.size * before.entry_price + order.size * order.price) / new_size,
            size=new_size,
            entry_commission=before.entry_commission + order.commission,
        )
        self.capital -= order.cost
        self.positions[order.symbol] = after
        self._record_fill(
            symbol=order.symbol,
            timestamp=ts,
            action="increase",
            signed_quantity=order.direction * order.size,
            execution_price=order.price,
            fee=order.commission,
            margin=order.margin,
            leverage=order.leverage,
            reason="target_rebalance",
        )
        self.after_position_adjustment(
            action="increase",
            timestamp=ts,
            before=before,
            after=after,
            execution_price=order.price,
            trading_fee=order.commission,
        )

    def _execute_partial_reduction(self, order: _ReductionOrder, ts: pd.Timestamp) -> None:
        """Commit a same-direction closing delta."""
        before = self.positions[order.before.symbol]
        closed_size = before.size - order.target_size
        entry_commission = before.entry_commission * closed_size / before.size
        after = replace(
            before,
            size=order.target_size,
            entry_commission=before.entry_commission - entry_commission,
        )
        exit_margin = self._calc_margin(
            before.symbol, closed_size, order.price, before.leverage
        )
        pnl_pct = (
            order.realized_pnl / order.released_margin * 100
            if order.released_margin > 1e-9
            else 0.0
        )
        holding_bars = self._weighted_holding_bars(before)
        self.capital += order.capital_credit
        self.positions[before.symbol] = after
        self.trades.append(TradeRecord(
            symbol=before.symbol,
            direction=before.direction,
            entry_price=before.entry_price,
            exit_price=order.price,
            entry_time=before.entry_time,
            exit_time=ts,
            size=closed_size,
            leverage=before.leverage,
            pnl=order.realized_pnl,
            pnl_pct=pnl_pct,
            exit_reason="target_rebalance",
            holding_bars=holding_bars,
            commission=entry_commission + order.exit_commission,
            entry_margin=order.released_margin,
            exit_margin=exit_margin,
            open_price=before.open_price,
            open_size=before.open_size,
        ))
        self._record_fill(
            symbol=before.symbol,
            timestamp=ts,
            action="reduce",
            signed_quantity=-before.direction * closed_size,
            execution_price=order.price,
            fee=order.exit_commission,
            margin=exit_margin,
            leverage=before.leverage,
            reason="target_rebalance",
            holding_bars=holding_bars,
        )
        self.after_position_adjustment(
            action="partial_reduction",
            timestamp=ts,
            before=before,
            after=after,
            execution_price=order.price,
            trading_fee=order.exit_commission,
            realized_pnl=order.realized_pnl,
            released_margin=order.released_margin,
        )

    def _execute_open_order(self, order: _OpenOrder, ts: pd.Timestamp) -> None:
        """Commit a previously priced opening order."""
        if order.cost > self.capital + 1e-7:
            raise RuntimeError(
                f"planned order for {order.symbol} exceeds available capital"
            )
        self.capital -= order.cost
        self.positions[order.symbol] = Position(
            symbol=order.symbol,
            direction=order.direction,
            entry_price=order.price,
            entry_time=ts,
            size=order.size,
            leverage=order.leverage,
            entry_bar_idx=self._bar_idx,
            entry_commission=order.commission,
            open_price=order.price,
            open_size=order.size,
        )
        self._record_fill(
            symbol=order.symbol,
            timestamp=ts,
            action="open",
            signed_quantity=order.direction * order.size,
            execution_price=order.price,
            fee=order.commission,
            margin=order.margin,
            leverage=order.leverage,
            reason="signal",
        )

    def _actual_weights(
        self,
        close_df: pd.DataFrame,
        ts: pd.Timestamp,
        codes: list[str],
        equity: float,
    ) -> dict[str, float]:
        """Return post-fill, mark-to-market weights for the currently held book."""
        weights = {code: 0.0 for code in codes}
        if abs(equity) <= 1e-12:
            return weights
        for symbol, pos in self.positions.items():
            price = self._safe_price(
                close_df,
                ts,
                symbol,
                pos.entry_price,
                _arr=getattr(self, "_close_arr", None),
                _row=getattr(self, "_bar_idx", None),
                _col=getattr(self, "_code_to_col", {}).get(symbol),
                _val_arr=getattr(self, "_val_arr", None),
            )
            margin_value = self._calc_margin(
                symbol, pos.size, price, pos.leverage
            )
            weights[symbol] = pos.direction * margin_value / equity
        return weights

    def _actual_positions_frame(self, codes: list[str]) -> pd.DataFrame:
        """Materialize recorded post-fill weights as an artifact-ready frame."""
        if not self.actual_position_snapshots:
            return pd.DataFrame(columns=codes, dtype=float)
        frame = pd.DataFrame(
            [weights for _, weights in self.actual_position_snapshots],
            index=[timestamp for timestamp, _ in self.actual_position_snapshots],
            columns=codes,
            dtype=float,
        )
        frame.index.name = "timestamp"
        return frame

    def _close_position(
        self,
        symbol: str,
        exit_price: float,
        exit_time: pd.Timestamp,
        reason: str,
    ) -> None:
        """Close position, record trade, return capital."""
        self._active_symbol = symbol
        pos = self.positions.pop(symbol, None)
        if pos is None:
            return

        pnl = self._calc_pnl(symbol, pos.direction, pos.size, pos.entry_price, exit_price)
        margin = self._calc_margin(symbol, pos.size, pos.entry_price, pos.leverage)
        exit_margin = self._calc_margin(symbol, pos.size, exit_price, pos.leverage)
        pnl_pct = pnl / margin * 100 if margin > 1e-9 else 0.0
        exit_comm = self.calc_commission(pos.size, exit_price, pos.direction, is_open=False)

        self.capital += margin + pnl - exit_comm

        holding_bars = self._weighted_holding_bars(pos)

        self.trades.append(TradeRecord(
            symbol=symbol,
            direction=pos.direction,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            entry_time=pos.entry_time,
            exit_time=exit_time,
            size=pos.size,
            leverage=pos.leverage,
            pnl=pnl,
            pnl_pct=pnl_pct,
            exit_reason=reason,
            holding_bars=holding_bars,
            commission=pos.entry_commission + exit_comm,
            entry_margin=margin,
            exit_margin=exit_margin,
            open_price=pos.open_price,
            open_size=pos.open_size,
        ))
        self._record_fill(
            symbol=symbol,
            timestamp=exit_time,
            action="close",
            signed_quantity=-pos.direction * pos.size,
            execution_price=exit_price,
            fee=exit_comm,
            margin=exit_margin,
            leverage=pos.leverage,
            reason=reason,
            holding_bars=holding_bars,
        )

    def _record_fill(
        self,
        *,
        symbol: str,
        timestamp: pd.Timestamp,
        action: str,
        signed_quantity: float,
        execution_price: float,
        fee: float,
        margin: float,
        leverage: float,
        reason: str,
        holding_bars: float | None = None,
    ) -> None:
        """Append execution evidence without making it account state."""
        self.fill_records.append(FillRecord(
            symbol=symbol,
            timestamp=timestamp,
            bar_idx=self._bar_idx,
            action=action,
            signed_quantity=signed_quantity,
            notional=margin * leverage,
            execution_price=execution_price,
            fee=fee,
            margin=margin,
            reason=reason,
            holding_bars=holding_bars,
        ))

    def _weighted_holding_bars(self, position: Position) -> float:
        """Derive compressed-position age from immutable fill evidence.

        Reductions consume every accumulated opening delta proportionally,
        matching the weighted-average entry accounting used by this engine.
        Only the active position lifecycle matters; stopping at its preceding
        full close avoids rescanning the entire fill ledger on every exit.
        """
        active_fills: list[FillRecord] = []
        for fill in reversed(self.fill_records):
            if fill.symbol != position.symbol:
                continue
            if fill.action == "close":
                break
            active_fills.append(fill)

        lots: list[list[float]] = []
        for fill in reversed(active_fills):
            quantity = abs(fill.signed_quantity)
            if fill.action in {"open", "increase"}:
                lots.append([quantity, float(fill.bar_idx)])
                continue
            if fill.action not in {"reduce", "close"}:
                continue
            total = sum(lot[0] for lot in lots)
            if total <= 1e-12 or quantity >= total - 1e-12:
                lots.clear()
                continue
            remaining_ratio = (total - quantity) / total
            for lot in lots:
                lot[0] *= remaining_ratio

        total = sum(lot[0] for lot in lots)
        if total <= 1e-12:
            return float(max(self._bar_idx - position.entry_bar_idx, 0))
        return sum(
            quantity * max(self._bar_idx - int(bar_idx), 0)
            for quantity, bar_idx in lots
        ) / total

    # ── Artifacts ──

    @staticmethod
    def _safe_price(
        close_df: pd.DataFrame,
        ts: pd.Timestamp,
        symbol: str,
        fallback: float,
        *,
        _arr: np.ndarray | None = None,
        _row: int | None = None,
        _col: int | None = None,
        _val_arr: np.ndarray | None = None,
    ) -> float:
        """Get close price with fallback. Uses array fast-path when available.

        Valuation call sites pass ``_val_arr`` (unbounded ffill) so a halted
        position marks at its last traded close instead of ``fallback`` once
        the bounded matrix goes NaN past the ffill limit.
        """
        # Fast path: pre-computed array indexing (O(1) vs DataFrame.at hash lookup)
        if _arr is not None and _row is not None and _col is not None:
            val = _arr[_row, _col]
            if not np.isnan(val):
                return float(val)
            if _val_arr is not None:
                vval = _val_arr[_row, _col]
                if not np.isnan(vval):
                    return float(vval)
            return fallback
        # Original path (backward compatible for subclasses)
        if ts in close_df.index and symbol in close_df.columns:
            val = close_df.at[ts, symbol]
            if pd.notna(val):
                return float(val)
        return fallback
