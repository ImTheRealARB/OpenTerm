"""The mandate: what the user allows orders to do. Pure checks (`check`) plus validation of the stored document.

Zero means zero: a cap of 0 refuses every order, and an empty symbol list allows no symbol. The default mandate therefore allows
nothing until the user sets it (ORD, key M). A check that cannot be computed (no price for a market order, positions unreadable)
fails: the mandate never passes on missing data.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

from .errors import OrderError
from .model import SYMBOL_RE, Order, number, qty_text

MAX_SYMBOLS = 200
MAX_VALUE = 1e12


@dataclass
class Mandate:
    symbols: list[str] = field(default_factory=list)
    max_shares: float = 100.0
    max_notional: float = 5000.0
    max_gross: float = 25000.0
    max_trades_per_day: int = 10

    def public(self) -> dict:
        return asdict(self)


def parse(raw) -> Mandate:
    """A validated mandate from a JSON object. Unknown fields are refused."""
    if not isinstance(raw, dict):
        raise OrderError("bad_request", "MANDATE MUST BE AN OBJECT")
    extra = sorted(set(raw) - set(Mandate.__dataclass_fields__))
    if extra:
        raise OrderError("bad_request", f"UNKNOWN MANDATE FIELD {', '.join(extra)[:60].upper()}")
    base = Mandate()
    syms = raw.get("symbols", base.symbols)
    if not isinstance(syms, list) or len(syms) > MAX_SYMBOLS or not all(isinstance(s, str) for s in syms):
        raise OrderError("bad_request", f"symbols MUST BE A LIST OF AT MOST {MAX_SYMBOLS} SYMBOLS")
    clean: list[str] = []
    for s in syms:
        u = s.strip().upper()
        if not SYMBOL_RE.match(u):
            raise OrderError("bad_request", f"BAD SYMBOL IN MANDATE: {u[:24]}")
        if u not in clean:
            clean.append(u)
    out = Mandate(symbols=clean)
    for name in ("max_shares", "max_notional", "max_gross"):
        v = number(raw.get(name, getattr(base, name)), name)
        if not 0 <= v <= MAX_VALUE:
            raise OrderError("bad_request", f"{name} MUST BE 0 TO {MAX_VALUE:g}")
        setattr(out, name, v)
    n = number(raw.get("max_trades_per_day", base.max_trades_per_day), "max_trades_per_day", integer=True)
    if not 0 <= n <= 1000:
        raise OrderError("bad_request", "max_trades_per_day MUST BE 0 TO 1000")
    out.max_trades_per_day = int(n)
    return out


def check(order: Order, m: Mandate, price: float | None, gross: float | None, position_qty: float | None, trades_today: int) -> dict:
    """{ok, checks: [{name, ok, detail}]}. `price` is the reference price (limit, stop or a quote), `gross` the account's current gross
    exposure, `position_qty` the signed quantity held in this symbol; any of them None fails the check that needs it."""
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    allowed = order.symbol in m.symbols
    add("SYMBOL ALLOWED", allowed,
        f"{order.symbol} IS ON THE ALLOWLIST" if allowed else f"{order.symbol} IS NOT ON THE ALLOWLIST ({len(m.symbols)} SYMBOLS)")
    add("MAX SHARES", order.qty <= m.max_shares, f"{qty_text(order.qty)} OF MAX {m.max_shares:g}")
    if price is None or not math.isfinite(price) or price <= 0:
        add("MAX NOTIONAL", False, "NO PRICE TO VALUE THE ORDER (A MARKET ORDER NEEDS A LIVE QUOTE): REFUSED")
        add("MAX GROSS EXPOSURE", False, "NO PRICE TO VALUE THE ORDER: REFUSED")
    else:
        notional = order.qty * price
        add("MAX NOTIONAL", notional <= m.max_notional, f"{notional:,.2f} OF MAX {m.max_notional:,.2f} (PRICE {price:g})")
        if gross is None or position_qty is None:
            add("MAX GROSS EXPOSURE", False, "ACCOUNT POSITIONS COULD NOT BE READ: REFUSED")
        else:
            signed = order.qty if order.side == "buy" else -order.qty
            after = gross - abs(position_qty * price) + abs((position_qty + signed) * price)
            add("MAX GROSS EXPOSURE", after <= m.max_gross, f"{after:,.2f} AFTER THIS ORDER OF MAX {m.max_gross:,.2f} (NOW {gross:,.2f})")
    add("DAILY TRADES", trades_today < m.max_trades_per_day, f"{trades_today} SENT TODAY OF MAX {m.max_trades_per_day}")
    return {"ok": all(c["ok"] for c in checks), "checks": checks}
