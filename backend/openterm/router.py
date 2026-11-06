"""Provider router: first healthy provider wins, fallback on error/429, circuit breaker per provider."""

import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TypeVar

from .perf import percentile
from .providers.base import Provider, ProviderError
from .providers.hierarchy import rank_of

log = logging.getLogger("openterm.router")
T = TypeVar("T")

TRIP_AFTER = 3
MAX_COOLDOWN_S = 300.0


@dataclass
class Health:
    calls: int = 0
    errors: int = 0
    consecutive: int = 0
    down_until: float = 0.0
    last_ok: float | None = None
    last_error: str | None = None
    last_error_at: float | None = None
    latencies: deque = field(default_factory=lambda: deque(maxlen=100))

    @property
    def down(self) -> bool:
        return time.time() < self.down_until

    def ok(self, ms: float) -> None:
        self.calls += 1
        self.consecutive = 0
        self.down_until = 0.0
        self.last_ok = time.time()
        self.latencies.append(ms)

    def fail(self, err: ProviderError) -> None:
        self.calls += 1
        if err.kind in ("not_found", "unsupported", "depth", "login_expired"):
            return  # the provider is fine; it just lacks this symbol, or does not reach back that far
        self.errors += 1
        self.consecutive += 1
        self.last_error = f"{err.kind}: {err}"
        self.last_error_at = time.time()
        if err.kind == "rate_limited" or self.consecutive >= TRIP_AFTER:
            cooldown = min(MAX_COOLDOWN_S, 5.0 * 2 ** max(0, self.consecutive - 1))
            self.down_until = time.time() + cooldown


class AllFailed(Exception):
    def __init__(self, errors: list[tuple[str, ProviderError]], keys: dict[str, str] | None = None):
        self.errors = errors
        self.key: str | None = None
        kinds = {e.kind for _, e in errors}
        # An expired login (Kite) is a reason shown beside the fallback, not an outage: when the sources that DO answer say
        # "no such symbol" or "too shallow", the user gets that real answer instead of PROVIDER DOWN (audit A-3).
        kinds_ex_login = kinds - {"login_expired"}
        if not errors:
            self.kind, msg = "unsupported", "NO PROVIDER SUPPORTS THIS SYMBOL"
        elif "depth" in kinds_ex_login and kinds_ex_login <= {"not_found", "unsupported", "depth"}:
            # Every source that has the symbol is too shallow for this interval + range: a request problem, not missing data.
            self.kind, msg = "bad_request", next(str(e) for _, e in errors if e.kind == "depth")
        elif kinds_ex_login and kinds_ex_login <= {"not_found", "unsupported"}:
            self.kind, msg = "not_found", "NO DATA FOR SYMBOL"
        elif "key_required" in kinds and kinds <= {"not_found", "unsupported", "key_required"}:
            # Phase 11: no keyless provider could answer, so the missing key is the reason.
            self.kind, msg = "key_required", "KEY REQUIRED"
            self.key = next((keys or {}).get(n) for n, e in errors if e.kind == "key_required")
        else:
            self.kind, msg = "unavailable", "PROVIDER DOWN"
        super().__init__(msg)


class Router:
    def __init__(self, providers: dict[str, Provider], order: dict[str, list[str]]):
        self.providers = providers
        self.order = order
        self.health = {name: Health() for name in providers}

    def candidates(self, capability: str, symbol: str | None = None) -> list[Provider]:
        ps = [
            self.providers[n]
            for n in self.order.get(capability, [])
            if n in self.providers and self.providers[n].supports(capability, symbol)
        ]
        up = [p for p in ps if not self.health[p.name].down]
        # Everything tripped: try anyway (half-open) rather than refusing outright.
        return up or sorted(ps, key=lambda p: self.health[p.name].down_until)

    async def _attempt(self, p: Provider, fn: Callable[[Provider], Awaitable[T]]) -> T:
        t0 = time.perf_counter()
        try:
            result = await fn(p)
        except ProviderError as e:
            if e.kind in ("key_required", "login_expired"):  # not an outage: no circuit-breaker strike
                log.debug("provider %s needs a key", p.name)
                raise
            self.health[p.name].fail(e)
            log.warning("provider %s failed: %s %s", p.name, e.kind, e)
            raise
        except Exception as e:  # adapter bug or unexpected payload: treat as provider failure
            err = ProviderError("unavailable", f"{type(e).__name__}: {e}")
            self.health[p.name].fail(err)
            log.exception("provider %s crashed", p.name)
            raise err from e
        self.health[p.name].ok((time.perf_counter() - t0) * 1000)
        return result

    async def call(
        self, capability: str, fn: Callable[[Provider], Awaitable[T]], symbol: str | None = None
    ) -> tuple[T, list[str]]:
        """Returns (result, names of providers that failed first)."""
        errors: list[tuple[str, ProviderError]] = []
        keys: dict[str, str] = {}
        for p in self.candidates(capability, symbol):
            try:
                return await self._attempt(p, fn), [n for n, _ in errors]
            except ProviderError as e:
                errors.append((p.name, e))
                if e.kind == "key_required":
                    keys[p.name] = getattr(p, "key_name", "") or p.name.upper()
        raise AllFailed(errors, keys)

    async def quotes(self, symbols: list[str]) -> tuple[dict, dict[str, AllFailed]]:
        """Batch quotes across providers: each provider gets the symbols still missing that it supports."""
        found: dict = {}
        errors: dict[str, list[tuple[str, ProviderError]]] = {s: [] for s in symbols}
        for p in self.candidates("quotes"):
            name = p.name
            batch = [s for s in symbols if s not in found and p.supports("quotes", s)]
            if not batch:
                continue
            try:
                for q in await self._attempt(p, lambda prov, b=batch: prov.quotes(b)):
                    if q.symbol in errors:
                        found[q.symbol] = (q, [n for n, _ in errors[q.symbol]])
                for s in batch:
                    if s not in found:
                        errors[s].append((name, ProviderError("not_found")))
            except ProviderError as e:
                for s in batch:
                    errors[s].append((name, e))
        return found, {s: AllFailed(errors[s]) for s in symbols if s not in found}

    def history_limits(self, symbol: str) -> dict:
        """How far back each intraday candle length reaches for this symbol, from the best source that can serve it.

        {"intraday_days": {"5m": 1400, ...}, "source": "kite"}. Each length takes the deepest limit among the sources that are
        switched on for the symbol and have declared one (Provider.intraday_days); a length no source declares is absent.
        Daily and longer candles are not limited here. Used by the chart so it only offers what will work.
        """
        best: dict[str, tuple[int, str]] = {}
        for p in self.candidates("history", symbol):
            if p.why_down() is not None:  # e.g. an expired Kite login: its depth is not on offer right now (audit A-3)
                continue
            for interval, days in (p.intraday_days or {}).items():
                if interval not in best or days > best[interval][0]:
                    best[interval] = (days, p.name)
        sources = {name for _, name in best.values()}
        return {"symbol": symbol, "intraday_days": {i: d for i, (d, _) in best.items()}, "source": sorted(sources)}

    def summary(self) -> list[dict]:
        now = time.time()
        out = []
        for name, p in self.providers.items():
            h = self.health[name]
            lat = list(h.latencies)
            out.append({
                "name": name,
                "label": p.label,
                "source": p.source,
                "capabilities": sorted(p.capabilities),
                "hierarchy": rank_of(name),  # where it sits per capability and why (providers/hierarchy.py)
                "markets": p.markets,
                "terms": p.terms,
                "status": "DOWN" if h.down else ("DEGRADED" if h.consecutive else ("OK" if h.last_ok else "IDLE")),
                "down_for_s": max(0.0, h.down_until - now) if h.down else 0.0,
                "latency_p50_ms": percentile(lat, 50) if lat else None,
                "latency_p95_ms": percentile(lat, 95) if lat else None,
                "calls": h.calls,
                "errors": h.errors,
                "last_error": h.last_error,
                "last_error_age_s": now - h.last_error_at if h.last_error_at else None,
                "last_ok_age_s": now - h.last_ok if h.last_ok else None,
                "tokens_remaining": round(p.bucket.remaining, 1),
                "rate_per_s": p.bucket.rate,
            })
        return out
