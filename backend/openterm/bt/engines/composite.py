# Ported from HKUDS/Vibe-Trading @ d0db2e3, agent/backtest/engines/composite.py (MIT; see THIRD_PARTY.md).
# Changes: import paths; only the markets OpenTerm builds (decision C) get a rule engine, any other detected market
# raises a clear error; `market_of` classifies Yahoo-style symbols (`BTCUSDT.P`, `BRK-B`, `^GSPC`) that Vibe's
# `_detect_market` reads as China A; the one-currency check runs in `run()` (OpenTerm's in-memory entry point)
# instead of `run_backtest()`; PEP 585 annotations.
"""Composite cross-market backtest engine.

Manages a shared capital pool across multiple market engines. Sub-engines are used as stateless "rule books" for
market-specific calculations (commission, slippage, lot rounding, etc.). All state (capital, positions, trades) lives
in CompositeEngine.
"""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

from .base import BaseEngine
from .hooks import (
    _detect_market,
    _interval_span_hours,
    _is_china_futures,
    _liquidation_mark,
    _normalize_symbol,
    calc_crypto_funding_fee,
    calc_forex_swap,
    check_crypto_liquidation,
    code_currency,
)

#: Markets Vibe has engines for that OpenTerm does not build (China A, China futures, Korea, Vietnam, Brazil,
#: Argentina). A composite that contains one fails closed instead of using another market's rules.
NOT_BUILT = {"a_share": "CHINA A", "kr_equity": "KOREA", "vietnam_equity": "VIETNAM", "br_equity": "BRAZIL",
             "ar_equity": "ARGENTINA"}


_INDEX_MARKET = {"^GSPC": "us_equity", "^DJI": "us_equity", "^NDX": "us_equity", "^RUT": "us_equity",
                 "^NSEI": "india_equity", "^BSESN": "india_equity", "^NSEBANK": "india_equity",
                 "^FTSE": "uk_equity", "^HSI": "hk_equity", "^GSPTSE": "ca_equity"}
_US_CLASS_SHARE = re.compile(r"^[A-Z]{1,5}(-[A-Z])?$")
_FIXED_CURRENCY = {"us_equity": "USD", "india_equity": "INR", "uk_equity": "GBP", "ca_equity": "CAD", "crypto": "USD",
                   "futures": "USD"}


def market_of(code: str) -> str:
    """Vibe market name for an OpenTerm (Yahoo-style) symbol. Fails closed: a symbol no built market explains raises
    instead of falling through to Vibe's A-share default."""
    s = code.strip().upper()
    if s.endswith(".P"):  # Binance USD-M perpetual, e.g. BTCUSDT.P
        return "crypto"
    if s.startswith("^"):
        if s not in _INDEX_MARKET:
            raise ValueError(f"UNKNOWN INDEX {s}: NO ENGINE FOR ITS MARKET")
        return _INDEX_MARKET[s]
    market = _detect_market(s)
    if market == "a_share":  # Vibe's catch-all for symbols it cannot place
        if _US_CLASS_SHARE.match(s):
            return "us_equity"  # BRK-B and other class shares
        raise ValueError(f"CANNOT PLACE {s} IN A BUILT MARKET (US, UK, HK, CANADA, INDIA, CRYPTO, FOREX, FUTURES)")
    return market


def _currency(code: str, market: str) -> str:
    """Settlement currency; HK counters and forex quote currencies come from Vibe's `code_currency`."""
    return _FIXED_CURRENCY.get(market) or code_currency(code)


def _build_rule_engines(config: dict, codes: list[str]) -> dict[str, BaseEngine]:
    """Instantiate one sub-engine per market type detected in codes."""
    from .crypto import CryptoEngine
    from .forex import ForexEngine
    from .global_equity import GlobalEquityEngine
    from .global_futures import GlobalFuturesEngine
    from .india_equity import IndiaEquityEngine

    markets = {market_of(c) for c in codes}
    engines: dict[str, BaseEngine] = {}

    for market in markets:
        if market in NOT_BUILT:
            raise ValueError(f"{NOT_BUILT[market]} MARKET IS NOT BUILT (US, UK, HK, CANADA, INDIA, CRYPTO, FOREX, FUTURES)")
        if market == "us_equity" or market == "index":
            engines[market] = GlobalEquityEngine(config, market="us")
        elif market == "hk_equity":
            engines[market] = GlobalEquityEngine(config, market="hk")
        elif market == "ca_equity":
            engines[market] = GlobalEquityEngine(config, market="ca")
        elif market == "uk_equity":
            engines[market] = GlobalEquityEngine(config, market="uk")
        elif market == "india_equity":
            engines[market] = IndiaEquityEngine(config)
        elif market == "crypto":
            engines[market] = CryptoEngine(config)
        elif market == "forex":
            engines[market] = ForexEngine(config)
        elif market == "futures":
            futures_codes = [c for c in codes if market_of(c) == "futures"]
            if any(_is_china_futures(c) for c in futures_codes):
                raise ValueError("CHINA FUTURES MARKET IS NOT BUILT (US, UK, HK, CANADA, INDIA, CRYPTO, FOREX, FUTURES)")
            engines["global_futures"] = GlobalFuturesEngine(config)

    return engines


def _reject_mixed_currency(codes: list[str]) -> None:
    """Refuse a code set whose members do not settle in one currency.

    The shared capital pool holds a single scalar of cash and sums position values into a single equity curve. With
    codes from two currency zones that curve adds CNY to USD to KRW as if the units matched, and every metric
    derived from it (return, Sharpe, drawdown) is meaningless. There is no FX translation layer yet, so this fails
    closed rather than reporting a number that looks fine.

    Args:
        codes: Instrument codes for the backtest.

    Raises:
        ValueError: If the codes span more than one settlement currency.
    """
    by_currency: dict[str, list[str]] = {}
    for code in codes:
        by_currency.setdefault(_currency(code, market_of(code)), []).append(code)
    if len(by_currency) <= 1:
        return
    breakdown = "; ".join(
        f"{currency}: {', '.join(sorted(members))}"
        for currency, members in sorted(by_currency.items())
    )
    raise ValueError(
        "composite backtest requires one settlement currency across all codes, "
        f"but got {len(by_currency)} - {breakdown}. The shared capital pool has "
        "no FX translation, so a mixed-currency equity curve would sum "
        "different units. Split the run by currency, or convert the inputs "
        "to one currency before loading."
    )


class CompositeEngine(BaseEngine):
    """Cross-market engine with shared capital pool.

    Sub-engines are stateless rule providers. All positions, capital, and trades live here (inherited from
    BaseEngine).

    Args:
        config: Backtest configuration dict.
        codes: List of instrument codes spanning multiple markets.
    """

    def __init__(self, config: dict, codes: list[str]):
        super().__init__(config)

        # Build symbol -> market mapping
        self._symbol_market: dict[str, str] = {c: market_of(c) for c in codes}

        # Build sub-engines (one per market type)
        self._rule_engines = _build_rule_engines(config, codes)

        # Crypto dedup state (owned by CompositeEngine, not sub-engine)
        self._funding_applied: set = set()
        self._funding_daily_done: set = set()

        # Forex dedup state
        self._last_swap_dates: dict = {}

        self._run_interval = str(config.get("interval", "1D"))

    def run(self, data_map: dict[str, pd.DataFrame], signal_map: dict[str, pd.Series], *args, **kwargs):
        """Run the pipeline, refusing a code set that spans currencies.

        The check lives here rather than in ``__init__`` because the damage is in the shared equity curve, not in
        constructing the rule-book engines.

        Raises:
            ValueError: If the codes span more than one settlement currency.
        """
        _reject_mixed_currency(sorted(c for c in signal_map if c in data_map))
        return super().run(data_map, signal_map, *args, **kwargs)

    def _engine_diagnostics(self) -> dict[str, Any]:
        """Carry sub-engine assumptions into the shared run's metrics.

        Returns:
            Per-market diagnostics, plus combined list-valued assumptions using the same keys as a single-market
            run.
        """
        by_market = {
            market: details for market, engine in self._rule_engines.items()
            if (details := engine._engine_diagnostics())
        }
        if not by_market:
            return {}
        result: dict[str, Any] = {"market_diagnostics": by_market}
        for details in by_market.values():
            for key, value in details.items():
                if isinstance(value, list):
                    result.setdefault(key, []).extend(value)
        return result

    def _rule_for(self, symbol: str) -> BaseEngine:
        """Get the sub-engine that provides rules for this symbol."""
        market = self._symbol_market.get(symbol, "us_equity")
        if market == "futures":
            market = "global_futures"
        engine = self._rule_engines.get(market)
        if engine is None:
            if not self._rule_engines:
                raise ValueError("No sub-engines available for composite backtest")
            engine = next(iter(self._rule_engines.values()))
        return engine

    # -- Stateless method dispatch --

    def can_execute(self, symbol: str, direction: int, bar: pd.Series) -> bool:
        """Market-rule check; India reads the shared run state (positions, close panel) the sub-engine lacks."""
        if self._symbol_market.get(symbol) == "india_equity":
            sub = self._rule_engines.get("india_equity")
            if sub is not None:
                from .india_equity import india_can_execute

                return india_can_execute(self, sub, symbol, direction, bar)

        # Delegate remaining checks (price limits, short-sell block, etc.)
        return self._rule_for(symbol).can_execute(symbol, direction, bar)

    def round_size(self, raw_size: float, price: float) -> float:
        """Delegate to active symbol's sub-engine."""
        sub = self._rule_for(self._active_symbol)
        # ForexEngine/GlobalFuturesEngine read their OWN _active_symbol (lot grids, per-symbol fee schedules): a
        # shared sub-engine instance keeps whatever symbol last synced it, so it must be refreshed on every
        # dispatch, not just in apply_slippage.
        sub._active_symbol = self._active_symbol
        return sub.round_size(raw_size, price)

    def calc_commission(
        self, size: float, price: float, direction: int, is_open: bool,
    ) -> float:
        """Delegate to active symbol's sub-engine."""
        sub = self._rule_for(self._active_symbol)
        sub._active_symbol = self._active_symbol
        return sub.calc_commission(size, price, direction, is_open)

    def apply_slippage(self, price: float, direction: int) -> float:
        """Delegate to active symbol's sub-engine."""
        sub = self._rule_for(self._active_symbol)
        sub._active_symbol = self._active_symbol
        return sub.apply_slippage(price, direction)

    # -- PnL / margin dispatch (route by symbol, not _active_symbol) --

    def _calc_pnl(
        self, symbol: str, direction: int, size: float,
        entry_price: float, exit_price: float,
    ) -> float:
        return self._rule_for(symbol)._calc_pnl(
            symbol, direction, size, entry_price, exit_price,
        )

    def _calc_margin(
        self, symbol: str, size: float, price: float, leverage: float,
    ) -> float:
        return self._rule_for(symbol)._calc_margin(symbol, size, price, leverage)

    def _calc_raw_size(
        self, symbol: str, target_notional: float, price: float,
    ) -> float:
        return self._rule_for(symbol)._calc_raw_size(symbol, target_notional, price)

    def _leverage_for_symbol(self, symbol: str) -> float:
        return self._rule_for(symbol)._leverage_for_symbol(symbol)

    # -- Stateful hooks (implemented directly, NO delegation) --

    def on_bar(self, symbol: str, bar: pd.Series, timestamp: pd.Timestamp) -> None:
        """Per-bar hooks dispatched by market type."""
        market = self._symbol_market.get(symbol)

        if market == "crypto":
            crypto_sub = self._rule_engines["crypto"]
            fee = calc_crypto_funding_fee(
                symbol, bar, timestamp, self.positions,
                crypto_sub.funding_rate,
                self._funding_applied, self._funding_daily_done,
                _interval_span_hours(self._run_interval),
            )
            self.capital -= fee

            if check_crypto_liquidation(symbol, bar, self.positions):
                pos = self.positions.get(symbol)
                if pos is not None:
                    # Fill at the same adverse mark the hook used for the check so a wick trigger never exits at
                    # a better price than the venue.
                    liq_price = crypto_sub.apply_slippage(_liquidation_mark(bar, pos), -pos.direction)
                    self._close_position(symbol, liq_price, timestamp, "liquidation")

        elif market == "forex":
            from .forex import _lot_units

            forex_sub = self._rule_engines["forex"]
            if forex_sub.swap_enabled:
                swap = calc_forex_swap(
                    symbol, timestamp, self.positions,
                    _lot_units(_normalize_symbol(symbol), forex_sub.lot_size),
                    self._last_swap_dates,
                )
                self.capital += swap
