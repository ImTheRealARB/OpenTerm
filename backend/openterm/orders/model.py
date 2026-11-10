"""The order a user typed, validated. Pure: no network, no database.

`Order.from_body` accepts exactly the fields below. A request can name a broker (`alpaca-paper`, `alpaca-live`, `kite`) but can never
say "paper" or "live": those words are refused as fields, because the mode comes from the broker account (brokers/*.detect_mode).
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass

import orjson

from .errors import OrderError

BROKERS = ("alpaca-paper", "alpaca-live", "kite")
SIDES = ("buy", "sell")
TYPES = ("market", "limit", "stop")
TIFS = ("day", "gtc", "ioc")
KITE_PRODUCTS = ("CNC", "MIS", "NRML")
KITE_SUFFIXES = ("NS", "BO", "NFO", "MCX")
FIELDS = {"broker", "symbol", "side", "qty", "type", "tif", "limit_price", "stop_price", "product"}
SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-&]{0,19}\Z")
MAX_QTY = 1e9
MAX_PRICE = 1e9
#: words that would mean "a request sets the mode"; refused with a pointed message instead of the generic unknown-field one
MODE_WORDS = {"mode", "live", "paper", "account_type", "host", "base_url", "environment", "env", "sandbox", "simulate", "dry_run", "force"}


def number(x, what: str, integer: bool = False) -> float:
    if isinstance(x, bool) or not isinstance(x, int | float) or not math.isfinite(x):
        raise OrderError("bad_request", f"{what} MUST BE A FINITE NUMBER")
    if integer and float(x) != int(x):
        raise OrderError("bad_request", f"{what} MUST BE A WHOLE NUMBER")
    return float(x)


def qty_text(q: float) -> str:
    """Canonical text of a quantity (no float noise): 10, 0.5, 1.25."""
    return f"{q:.6f}".rstrip("0").rstrip(".")


@dataclass(frozen=True)
class Order:
    broker: str
    symbol: str
    side: str
    qty: float
    type: str
    tif: str
    limit_price: float | None = None
    stop_price: float | None = None
    product: str | None = None

    @classmethod
    def from_body(cls, body) -> Order:
        if not isinstance(body, dict):
            raise OrderError("bad_request", "ORDER MUST BE AN OBJECT")
        bad = [k for k in body if k in MODE_WORDS]
        if bad:
            raise OrderError("bad_request", "PAPER OR LIVE IS NEVER SET BY A REQUEST: IT COMES FROM THE BROKER ACCOUNT. PICK THE BROKER "
                                            f"({', '.join(BROKERS)}) AND REMOVE {', '.join(sorted(bad)).upper()}")
        extra = sorted(set(body) - FIELDS)
        if extra:
            raise OrderError("bad_request", f"UNKNOWN ORDER FIELD {', '.join(extra)[:60].upper()}")
        broker = body.get("broker")
        if broker not in BROKERS:
            raise OrderError("bad_request", f"broker MUST BE ONE OF {', '.join(BROKERS)}")
        sym = body.get("symbol")
        if not isinstance(sym, str) or not SYMBOL_RE.match(sym.strip().upper()):
            raise OrderError("bad_request", "symbol MUST BE LETTERS/DIGITS, E.G. AAPL OR RELIANCE.NS")
        sym = sym.strip().upper()
        side = body.get("side")
        if side not in SIDES:
            raise OrderError("bad_request", "side MUST BE buy OR sell")
        typ = body.get("type", "market")
        if typ not in TYPES:
            raise OrderError("bad_request", "type MUST BE market, limit OR stop")
        tif = body.get("tif", "day")
        if tif not in TIFS:
            raise OrderError("bad_request", "tif MUST BE day, gtc OR ioc")
        qty = number(body.get("qty"), "qty", integer=broker == "kite")
        if not 0 < qty <= MAX_QTY:
            raise OrderError("bad_request", "qty MUST BE ABOVE 0")
        if round(qty, 6) != qty:
            raise OrderError("bad_request", "qty HAS AT MOST 6 DECIMALS")
        limit = stop = None
        if typ == "limit":
            limit = number(body.get("limit_price"), "limit_price")
        elif body.get("limit_price") is not None:
            raise OrderError("bad_request", "limit_price IS ONLY FOR type limit")
        if typ == "stop":
            stop = number(body.get("stop_price"), "stop_price")
        elif body.get("stop_price") is not None:
            raise OrderError("bad_request", "stop_price IS ONLY FOR type stop")
        for name, v in (("limit_price", limit), ("stop_price", stop)):
            if v is not None and not 0 < v <= MAX_PRICE:
                raise OrderError("bad_request", f"{name} MUST BE ABOVE 0")
        product = body.get("product")
        if broker == "kite":
            if tif == "gtc":
                raise OrderError("bad_request", "KITE HAS NO GTC: USE day OR ioc")
            if "." not in sym or sym.rsplit(".", 1)[-1] not in KITE_SUFFIXES:
                raise OrderError("bad_request", "KITE SYMBOL NEEDS A SUFFIX: RELIANCE.NS, TCS.BO, <X>.NFO OR <X>.MCX")
            if product is not None and product not in KITE_PRODUCTS:
                raise OrderError("bad_request", f"product MUST BE ONE OF {', '.join(KITE_PRODUCTS)}")
        elif product is not None:
            raise OrderError("bad_request", "product IS ONLY FOR kite")
        return cls(broker, sym, side, qty, typ, tif, limit, stop, product)

    def ref_price(self) -> float | None:
        """The price the order itself names (limit, else stop); None for a market order, whose price must come from a quote."""
        return self.limit_price if self.limit_price is not None else self.stop_price

    def public(self) -> dict:
        return {"broker": self.broker, "symbol": self.symbol, "side": self.side, "qty": self.qty, "type": self.type, "tif": self.tif,
                "limit_price": self.limit_price, "stop_price": self.stop_price, "product": self.product}

    def line(self) -> str:
        px = f" @ {self.limit_price:g}" if self.limit_price is not None else f" STOP {self.stop_price:g}" if self.stop_price is not None else ""
        return f"{self.side.upper()} {qty_text(self.qty)} {self.symbol} {self.type.upper()}{px} {self.tif.upper()}"


def fingerprint(order: Order, mode: str, account: str) -> str:
    """What a confirm token is bound to: the whole order plus the mode and account the broker reported."""
    d = {**order.public(), "qty": qty_text(order.qty), "mode": mode, "account": account}
    return hashlib.sha256(orjson.dumps(d, option=orjson.OPT_SORT_KEYS)).hexdigest()
