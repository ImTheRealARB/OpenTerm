"""Interactive Brokers READ-ONLY sync through the Client Portal Web API gateway (the local `clientportal.gw`, default
`https://localhost:5000/v1/api`). Accounts, positions and the cash ledger. Nothing else: the client below has one request method,
GET, and a fixed list of paths; there is no order, modify, cancel or what-if endpoint anywhere in OpenTerm.

The gateway presents a self-signed certificate, so TLS verification is switched off for it, and ONLY for it: `validate_gateway_url`
refuses every host except the loopback ones (`localhost`, `127.0.0.1`, `::1` and the rest of 127/8), so the unverified connection can
never leave this machine. The client ignores proxy environment variables and does not follow redirects, for the same reason.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

import httpx

from ..errors import DataError
from ..portfolio import check_position
from ..redact import redact
from ..userdata import UserDataError

DEFAULT_GATEWAY_URL = "https://localhost:5000/v1/api"
API_PATH = "/v1/api"
PAGE_SIZE = 100  # the gateway returns at most 100 positions per page
MAX_PAGES = 30
TIMEOUT_S = 10.0

NOT_RUNNING = ("IBKR GATEWAY NOT RUNNING: start the Client Portal Gateway (bin/run.sh root/conf.yaml in the clientportal.gw folder), "
               "open https://localhost:5000 in a browser, log in, then run SYNC IBKR again")
NOT_LOGGED_IN = ("IBKR GATEWAY NOT LOGGED IN: open https://localhost:5000 in a browser, log in with your IBKR user "
                 "(approve the second factor), then run SYNC IBKR again")


class GatewayUrlError(ValueError):
    pass


def validate_gateway_url(raw) -> str:
    """The normalised gateway URL, or GatewayUrlError. Loopback hosts only, no credentials, no query, path `/v1/api`."""
    if not isinstance(raw, str) or not raw.strip() or len(raw) > 200:
        raise GatewayUrlError("IBKR GATEWAY URL MUST BE TEXT, E.G. https://localhost:5000/v1/api")
    text = raw.strip()
    try:
        u = urlsplit(text)
        port = u.port
        host = (u.hostname or "").lower()
    except ValueError:
        raise GatewayUrlError("IBKR GATEWAY URL IS NOT A VALID URL") from None
    if u.scheme not in ("http", "https"):
        raise GatewayUrlError("IBKR GATEWAY URL MUST START WITH https:// (OR http://)")
    if u.username is not None or u.password is not None or "@" in u.netloc:
        raise GatewayUrlError("IBKR GATEWAY URL MUST NOT CARRY A USER OR PASSWORD")
    if u.query or u.fragment:
        raise GatewayUrlError("IBKR GATEWAY URL MUST NOT HAVE A QUERY OR FRAGMENT")
    if not _loopback(host):
        raise GatewayUrlError("IBKR GATEWAY MUST BE ON THIS MACHINE: ONLY localhost, 127.0.0.1 AND ::1 ARE ALLOWED "
                              "(THE GATEWAY'S SELF-SIGNED CERTIFICATE IS ACCEPTED FOR LOOPBACK ONLY)")
    if u.path.rstrip("/") not in ("", API_PATH):
        raise GatewayUrlError(f"IBKR GATEWAY URL PATH MUST BE {API_PATH}")
    shown = f"[{host}]" if ":" in host else host
    return f"{u.scheme}://{shown}:{port or 5000}{API_PATH}"


def _loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class IbkrGateway:
    """GET-only client for the gateway. `http` is injectable for tests (an httpx.AsyncClient on a mock transport)."""

    def __init__(self, url: str, http: httpx.AsyncClient | None = None):
        self.url = validate_gateway_url(url)
        self._own = http is None
        self.http = http or httpx.AsyncClient(verify=False, trust_env=False, follow_redirects=False, timeout=TIMEOUT_S)  # loopback only: see the module doc

    async def aclose(self) -> None:
        if self._own:
            await self.http.aclose()

    async def _get(self, path: str):
        try:
            r = await self.http.get(f"{self.url}{path}", headers={"Accept": "application/json", "User-Agent": "OpenTerm/0.1"})
        except httpx.TimeoutException as e:
            raise DataError("unavailable", "IBKR GATEWAY TIMEOUT: it is running but did not answer. Log in again at https://localhost:5000") from e
        except httpx.HTTPError as e:
            raise DataError("unavailable", NOT_RUNNING) from e
        if r.status_code in (401, 403):
            raise DataError("login_required", NOT_LOGGED_IN)
        if 300 <= r.status_code < 400:
            raise DataError("unavailable", f"IBKR GATEWAY ANSWERED WITH A REDIRECT (HTTP {r.status_code}): NOT FOLLOWED. {NOT_LOGGED_IN}")
        if r.status_code >= 400:
            raise DataError("unavailable", redact(f"IBKR GATEWAY: HTTP {r.status_code} FOR {path.split('?')[0]}"))
        try:
            return r.json()
        except ValueError:
            raise DataError("unavailable", f"IBKR GATEWAY ANSWERED HTTP {r.status_code} WITHOUT JSON FOR {path.split('?')[0]}") from None

    async def check(self) -> dict:
        """The session state. Raises the NOT RUNNING / NOT LOGGED IN DataError when it cannot be used."""
        body = await self._get("/iserver/auth/status")
        if not isinstance(body, dict) or not body.get("authenticated"):
            raise DataError("login_required", NOT_LOGGED_IN)
        return {"authenticated": True, "connected": bool(body.get("connected", True))}

    async def accounts(self) -> list[str]:
        body = await self._get("/portfolio/accounts")  # also what the gateway needs before it serves the other portfolio calls
        ids = [str(a.get("accountId") or a.get("id")) for a in body if isinstance(a, dict) and (a.get("accountId") or a.get("id"))] \
            if isinstance(body, list) else []
        if not ids:
            raise DataError("not_found", "IBKR: THE GATEWAY LISTED NO ACCOUNTS FOR THIS LOGIN")
        return ids

    async def positions(self, account: str) -> list[dict]:
        out: list[dict] = []
        for page in range(MAX_PAGES):
            body = await self._get(f"/portfolio/{_acct(account)}/positions/{page}")
            rows = [r for r in body if isinstance(r, dict)] if isinstance(body, list) else []
            out.extend(rows)
            if len(rows) < PAGE_SIZE:
                break
        return out

    async def ledger(self, account: str) -> dict:
        body = await self._get(f"/portfolio/{_acct(account)}/ledger")
        return body if isinstance(body, dict) else {}


def _acct(account: str) -> str:
    if not account.replace("-", "").isalnum() or len(account) > 24:
        raise DataError("bad_request", "IBKR ACCOUNT ID: LETTERS AND DIGITS ONLY")
    return account


# --- mapping (pure) ---------------------------------------------------------------------------------------------------------------------

US_EXCHANGES = {"NYSE", "NASDAQ", "AMEX", "ARCA", "BATS", "ISLAND", "IEX", "NMS", "PINK", "OTCBB", "SMART", "BEX", "NYSEARCA"}
#: IBKR listing exchange -> Yahoo-style symbol suffix
EXCHANGE_SUFFIX = {
    "LSE": ".L", "TSE": ".TO", "VENTURE": ".V", "SBF": ".PA", "IBIS": ".DE", "FWB": ".F", "AEB": ".AS", "SEHK": ".HK", "ASX": ".AX",
    "NSE": ".NS", "SGX": ".SI", "EBS": ".SW", "SWX": ".SW", "BVME": ".MI", "BM": ".MC", "TSEJ": ".T", "KSE": ".KS", "OMXNO": ".OL",
    "SFB": ".ST", "CPH": ".CO", "HEX": ".HE", "WSE": ".WA", "BVL": ".LS",
}
LSE_NOTE = "LSE PRICES TAKEN AS PENCE (GBp), THE UNIT IBKR QUOTES THEM IN. CHECK ONE LSE LOT AGAINST TWS"


def map_position(row: dict) -> tuple[dict | None, str | None, str | None]:
    """(lot, skip reason, warning) for one gateway position row. Only stocks and ETFs (assetClass STK) become lots."""
    qty = row.get("position")
    desc = str(row.get("contractDesc") or row.get("ticker") or row.get("conid") or "?")
    asset = str(row.get("assetClass") or "").upper()
    if isinstance(qty, bool) or not isinstance(qty, int | float) or qty == 0:
        return None, None, None
    if asset != "STK":
        return None, f"{desc}: ASSET CLASS {asset or 'UNKNOWN'} IS NOT IMPORTED (STOCKS AND ETFS ONLY)", None
    ticker = str(row.get("ticker") or desc.split(" ")[0]).strip().upper().replace(" ", "-")
    exch = str(row.get("listingExchange") or "").upper()
    ccy = str(row.get("currency") or "").upper()
    if exch in EXCHANGE_SUFFIX:
        symbol = ticker.replace(".", "-") + EXCHANGE_SUFFIX[exch]
    elif exch in US_EXCHANGES or (not exch and ccy == "USD"):
        symbol = ticker.replace(".", "-")
    else:
        return None, f"{desc}: LISTING EXCHANGE {exch or 'UNKNOWN'} IS NOT MAPPED", None
    warning = None
    if exch == "LSE" and ccy == "GBP":
        ccy, warning = "GBp", LSE_NOTE
    cost = row.get("avgPrice") if isinstance(row.get("avgPrice"), int | float) else row.get("avgCost")
    cost = float(cost) if isinstance(cost, int | float) and not isinstance(cost, bool) and cost >= 0 else None
    try:
        lot = check_position({"symbol": symbol, "qty": float(qty), "cost": cost, "currency": ccy or None})
    except UserDataError as e:
        return None, f"{desc}: {e}", None
    return lot, None, warning


def _num(d: dict, k: str):
    x = d.get(k)
    return x if isinstance(x, int | float) and not isinstance(x, bool) else None


def map_cash(ledger: dict) -> list[dict]:
    """Per-currency cash from the ledger (`BASE` is the account total in base currency, kept under `base`)."""
    out = []
    for key, v in ledger.items():
        if not isinstance(v, dict):
            continue
        out.append({"currency": str(v.get("currency") or key).upper(), "base": key == "BASE", "cash": _num(v, "cashbalance"),
                    "settled": _num(v, "settledcash"), "net_liq": _num(v, "netliquidationvalue"), "unrealized": _num(v, "unrealizedpnl")})
    return sorted(out, key=lambda c: (c["base"], c["currency"]))
