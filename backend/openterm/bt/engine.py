"""One entry point over the market engines: `backtest(data_map, signal_map, config, engine=...)`.

Worker-side only (pandas). Engine names: us, uk, hk, ca (global equity), india, crypto (perpetuals), forex,
futures (global) and composite (a shared-capital basket across those markets).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import pandas as pd

from .engines.base import BaseEngine
from .engines.composite import CompositeEngine
from .engines.crypto import CryptoEngine
from .engines.forex import ForexEngine
from .engines.global_equity import GlobalEquityEngine
from .engines.global_futures import GlobalFuturesEngine
from .engines.india_equity import IndiaEquityEngine
from .models import FillRecord, TradeRecord

FACTORIES: dict[str, Callable[[dict, list[str]], BaseEngine]] = {
    m: (lambda cfg, codes, m=m: GlobalEquityEngine(cfg, market=m)) for m in ("us", "uk", "hk", "ca")
}
FACTORIES.update({
    "india": lambda cfg, codes: IndiaEquityEngine(cfg),
    "crypto": lambda cfg, codes: CryptoEngine(cfg),
    "forex": lambda cfg, codes: ForexEngine(cfg),
    "futures": lambda cfg, codes: GlobalFuturesEngine(cfg),
    "composite": lambda cfg, codes: CompositeEngine(cfg, codes),
})
BARS_PER_YEAR = {"us": 252, "uk": 252, "hk": 252, "ca": 252, "india": 252, "forex": 252, "futures": 252, "crypto": 365,
                 "composite": 252}


@dataclass
class BacktestResult:
    equity: pd.Series
    trades: list[TradeRecord]
    fills: list[FillRecord]
    metrics: dict
    benchmark: pd.Series
    engine: str
    extra: dict = field(default_factory=dict)


def make_engine(engine: str, config: dict, codes: list[str]) -> BaseEngine:
    if engine not in FACTORIES:
        raise ValueError(f"UNKNOWN ENGINE {engine.upper()} (have {', '.join(sorted(FACTORIES))})")
    eng = FACTORIES[engine](config, codes)
    fees = float(config.get("fees_bps") or 0.0)
    if fees:  # BT FEES=<bps>: a flat fee on every fill's notional, on top of the market's own cost stack
        base = eng.calc_commission

        def with_fee(size: float, price: float, direction: int, is_open: bool) -> float:
            return base(size, price, direction, is_open) + abs(size * price) * fees / 1e4

        eng.calc_commission = with_fee
    return eng


def backtest(data_map: dict[str, pd.DataFrame], signal_map: dict[str, pd.Series], config: dict, engine: str = "us",
             bars_per_year: int | None = None, bench_ret: pd.Series | None = None,
             benchmark_metadata: dict | None = None) -> BacktestResult:
    eng = make_engine(engine, dict(config), sorted(data_map))
    bpy = bars_per_year if bars_per_year is not None else BARS_PER_YEAR.get(engine, 252)
    metrics = eng.run(data_map, signal_map, bpy, bench_ret=bench_ret, benchmark_metadata=benchmark_metadata)
    return BacktestResult(equity=eng.equity_series, trades=list(eng.trades), fills=list(eng.fill_records),
                          metrics=metrics, benchmark=eng.bench_ret, engine=engine)
