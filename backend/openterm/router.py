"""Provider router: first healthy provider wins, fallback on error/429, circuit breaker per provider."""

import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TypeVar

from . import errkinds as K
from .perf import percentile
from .pin import PIN
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
        if err.kind in K.NOT_AN_OUTAGE:
            return  # the provider is fine; it just lacks this symbol, or does not reach back that far
        self.errors += 1
        self.consecutive += 1
        self.last_error = f"{err.kind}: {err}"
        self.last_error_at = time.time()
        if err.kind == K.RATE_LIMITED or self.consecutive >= TRIP_AFTER:
            cooldown = min(MAX_COOLDOWN_S, 5.0 * 2 ** max(0, self.consecutive - 1))
            self.down_until = time.time() + cooldown


class AllFailed(Exception):
    def __init__(self, errors: list[tuple[str, ProviderError]], keys: dict[str, str] | None = None, pinned: str | None = None):
        self.errors = errors
        self.key: str | None = None
        self.pinned = pinned
        kinds = {e.kind for _, e in errors}
        # An expired login (Kite) is a reason shown beside the fallback, not an outage: when the sources that DO answer say
        # "no such symbol" or "too shallow", the user gets that real answer instead of PROVIDER DOWN (audit A-3).
        kinds_ex_login = kinds - {K.LOGIN_EXPIRED}
        if pinned:
            # A pinned source answers alone: say which one and why, never the generic "no data" of a whole chain.
            self.kind, msg = self._pinned(pinned, errors[0][1] if errors else None, keys)
        elif not errors:
            self.kind, msg = K.UNSUPPORTED, "NO PROVIDER SUPPORTS THIS SYMBOL"
        elif K.DEPTH in kinds_ex_login and kinds_ex_login <= {K.NOT_FOUND, K.UNSUPPORTED, K.DEPTH}:
            # Every source that has the symbol is too shallow for this interval + range: a request problem, not missing data.
            self.kind, msg = K.BAD_REQUEST, next(str(e) for _, e in errors if e.kind == K.DEPTH)
        elif kinds_ex_login and kinds_ex_login <= {K.NOT_FOUND, K.UNSUPPORTED}:
            self.kind, msg = K.NOT_FOUND, "NO DATA FOR SYMBOL"
        elif K.KEY_REQUIRED in kinds and kinds <= {K.NOT_FOUND, K.UNSUPPORTED, K.KEY_REQUIRED}:
            # Phase 11: no keyless provider could answer, so the missing key is the reason.
            self.kind, msg = K.KEY_REQUIRED, "KEY REQUIRED"
            self.key = next((keys or {}).get(n) for n, e in errors if e.kind == K.KEY_REQUIRED)
        else:
            self.kind, msg = K.UNAVAILABLE, "PROVIDER DOWN"
        super().__init__(msg)

    def _pinned(self, name: str, err: ProviderError | None, keys: dict[str, str] | None) -> tuple[str, str]:
        head = f"SRC={name.upper()}"
        kind = err.kind if err else K.UNSUPPORTED
        if kind == K.KEY_REQUIRED:
            self.key = (keys or {}).get(name)
            return kind, f"{head}: KEY REQUIRED"
        if kind == K.LOGIN_EXPIRED:
            return kind, f"{head}: {err}"
        if kind in (K.UNSUPPORTED, K.DEPTH, K.BAD_REQUEST):
            return K.BAD_REQUEST, f"{head}: {err}"
        if kind == K.NOT_FOUND:
            return kind, f"{head}: NO DATA FOR SYMBOL"
        return K.UNAVAILABLE, f"{head}: PROVIDER DOWN"


class Router:
    def __init__(self, providers: dict[str, Provider], order: dict[str, list[str]]):
        self.providers = providers
        self.order = order
        self.health = {name: Health() for name in providers}
        self.prefs: dict[str, str] = {}  # SETTINGS SOURCE <capability> <provider>: tried first, the default order still backs it up

    def candidates(self, capability: str, symbol: str | None = None) -> list[Provider]:
        pin = PIN.get()
        if pin:  # a pinned source is the only candidate (`pin_block` says why it may still be unable to answer)
            p = self.providers.get(pin)
            return [p] if p is not None and p.supports(capability, symbol) else []
        names = self.order.get(capability, [])
        if self.prefs.get(capability) in names:
            names = [self.prefs[capability], *(n for n in names if n != self.prefs[capability])]
        ps = [
            self.providers[n]
            for n in names
            if n in self.providers and self.providers[n].supports(capability, symbol)
        ]
        up = [p for p in ps if not self.health[p.name].down]
        # Everything tripped: try anyway (half-open) rather than refusing outright.
        return up or sorted(ps, key=lambda p: self.health[p.name].down_until)

    async def attempt(self, p: Provider, fn: Callable[[Provider], Awaitable[T]]) -> T:
        """Calls `fn(p)` on ONE named provider, recording its health and latency (the circuit breaker sees it). Public: the scheduler's
        probes and the per-provider news fan-out use it to talk to a specific source instead of walking the fallback order."""
        t0 = time.perf_counter()
        try:
            result = await fn(p)
        except ProviderError as e:
            if e.kind in K.NEEDS_USER_ACTION:  # not an outage: no circuit-breaker strike
                log.debug("provider %s needs a key", p.name)
                raise
            self.health[p.name].fail(e)
            log.warning("provider %s failed: %s %s", p.name, e.kind, e)
            raise
        except Exception as e:  # adapter bug or unexpected payload: treat as provider failure
            err = ProviderError(K.UNAVAILABLE, f"{type(e).__name__}: {e}")
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
        pin = PIN.get()
        if pin:
            return await self._call_pinned(pin, capability, fn, symbol), []
        for p in self.candidates(capability, symbol):
            try:
                return await self.attempt(p, fn), [n for n, _ in errors]
            except ProviderError as e:
                errors.append((p.name, e))
                if e.kind == K.KEY_REQUIRED:
                    keys[p.name] = getattr(p, "key_name", "") or p.name.upper()
        raise AllFailed(errors, keys)

    def pin_block(self, p: Provider, capability: str, symbol: str | None) -> ProviderError | None:
        """Why the pinned source cannot even be asked (None = ask it)."""
        if capability not in p.capabilities:
            return ProviderError(K.UNSUPPORTED, f"DOES NOT SERVE {capability.upper()}")
        if p.supports(capability, symbol):
            return None
        why = p.why_down()
        if why:
            return ProviderError(K.LOGIN_EXPIRED, why)
        if getattr(p, "key_name", "") and not getattr(p, "has_key", True):
            return ProviderError(K.KEY_REQUIRED, "KEY REQUIRED")
        return ProviderError(K.UNSUPPORTED, f"DOES NOT COVER {symbol}" if symbol else "NOT SWITCHED ON")

    async def _call_pinned(self, pin: str, capability: str, fn: Callable[[Provider], Awaitable[T]], symbol: str | None) -> T:
        p = self.providers.get(pin)
        err = ProviderError(K.BAD_REQUEST, "UNKNOWN SOURCE") if p is None else self.pin_block(p, capability, symbol)
        keys = {pin: getattr(p, "key_name", "") or pin.upper()}
        if err is None:
            try:
                return await self.attempt(p, fn)
            except ProviderError as e:
                err = e
        raise AllFailed([(pin, err)], keys, pinned=pin)

    async def quotes(self, symbols: list[str]) -> tuple[dict, dict[str, AllFailed]]:
        """Batch quotes across providers: each provider gets the symbols still missing that it supports."""
        found: dict = {}
        errors: dict[str, list[tuple[str, ProviderError]]] = {s: [] for s in symbols}
        pin = PIN.get()
        pinned_p = self.providers.get(pin) if pin else None
        if pin:  # each symbol gets its own reason when the pinned source is off for it
            for s in symbols:
                why = ProviderError(K.BAD_REQUEST, "UNKNOWN SOURCE") if pinned_p is None else self.pin_block(pinned_p, "quotes", s)
                if why is not None:
                    errors[s].append((pin, why))
        for p in ([pinned_p] if pinned_p is not None else []) if pin else self.candidates("quotes"):
            name = p.name
            batch = [s for s in symbols if s not in found and not (pin and errors[s]) and p.supports("quotes", s)]
            if not batch:
                continue
            try:
                for q in await self.attempt(p, lambda prov, b=batch: prov.quotes(b)):
                    if q.symbol in errors:
                        found[q.symbol] = (q, [n for n, _ in errors[q.symbol]])
                for s in batch:
                    if s not in found:
                        errors[s].append((name, ProviderError(K.NOT_FOUND)))
            except ProviderError as e:
                for s in batch:
                    errors[s].append((name, e))
        keys = {pin: getattr(pinned_p, "key_name", "") or pin.upper()} if pin else None
        return found, {s: AllFailed(errors[s], keys, pinned=pin) for s in symbols if s not in found}

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
