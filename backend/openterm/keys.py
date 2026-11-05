"""Key store for keyed providers (Phase 11, spec: docs/specs/PHASE_11.md).

Lookup order per field: process env > OS keyring > .env file. New keys go to the keyring, or to .env when there is
no keyring backend. Values never leave the backend: status rows carry presence, source and test state only.
`keyring` is imported on first use, never at startup.
"""

from __future__ import annotations

import asyncio
import base64
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

import httpx

from . import redact

SERVICE = "openterm"
STATES = ("MISSING", "UNTESTED", "OK", "INVALID", "QUOTA", "ERROR")


@dataclass(frozen=True)
class KeySpec:
    name: str
    fields: tuple[str, ...]
    phase: int
    purpose: str
    signup: str
    secret_fields: tuple[str, ...] = ()
    """Fields redacted from logs. Empty = all fields."""
    hidden_fields: tuple[str, ...] = ()
    """Internal fields stored like keys but never shown as inputs (Kite's one-day access token). Not in `fields`, so APIKEYS lists
    only the inputs and `set` / `status` ignore them; read and written through `get_hidden` / `set_hidden`, redacted everywhere."""
    hidden_secret: tuple[str, ...] = ()
    """The hidden fields whose values are redacted (the rest, such as a login date, are plain)."""

    @property
    def secrets(self) -> tuple[str, ...]:
        return self.secret_fields or self.fields

    @property
    def label(self) -> str:
        return self.name.upper()


KEY_SPECS: dict[str, KeySpec] = {s.name: s for s in [
    KeySpec("openrouter", ("OPENROUTER_API_KEY",), 16, "AI models through one key (AI, SWARM, BRIEF)",
            "https://openrouter.ai/settings/keys"),
    KeySpec("openai", ("OPENAI_API_KEY",), 16, "AI models direct from OpenAI", "https://platform.openai.com/api-keys"),
    KeySpec("anthropic", ("ANTHROPIC_API_KEY",), 16, "AI models direct from Anthropic",
            "https://console.anthropic.com/settings/keys"),
    KeySpec("opencodego", ("OPENCODE_API_KEY",), 16, "AI models through an OpenCode Go subscription (OpenAI-style models)",
            "https://opencode.ai/auth"),
    KeySpec("deepseek", ("DEEPSEEK_API_KEY",), 16, "AI models direct from DeepSeek", "https://platform.deepseek.com/api_keys"),
    KeySpec("groq", ("GROQ_API_KEY",), 16, "Fast open-model AI from Groq", "https://console.groq.com/keys"),
    KeySpec("mistral", ("MISTRAL_API_KEY",), 16, "AI models direct from Mistral", "https://console.mistral.ai/api-keys"),
    KeySpec("xai", ("XAI_API_KEY",), 16, "Grok models direct from xAI", "https://console.x.ai/"),
    KeySpec("together", ("TOGETHER_API_KEY",), 16, "Open-model AI from Together", "https://api.together.ai/settings/api-keys"),
    KeySpec("fireworks", ("FIREWORKS_API_KEY",), 16, "Open-model AI from Fireworks", "https://app.fireworks.ai/settings/users/api-keys"),
    KeySpec("gemini", ("GEMINI_API_KEY",), 16, "Gemini models direct from Google (OpenAI-compatible endpoint)",
            "https://aistudio.google.com/apikey"),
    KeySpec("finnhub", ("FINNHUB_API_KEY",), 13, "Estimates, recommendations, IPOs, company news, real-time US trades",
            "https://finnhub.io/register"),
    KeySpec("alpaca", ("ALPACA_KEY_ID", "ALPACA_SECRET_KEY"), 13, "Real-time IEX quotes, news, paper trading",
            "https://app.alpaca.markets/signup"),
    KeySpec("fmp", ("FMP_API_KEY",), 13, "Estimates, index members (transcripts and segments need a paid plan)",
            "https://site.financialmodelingprep.com/developer/docs"),
    KeySpec("fred", ("FRED_API_KEY",), 7, "FRED API: series titles/units, MACRO search, ECO fallback. "
            "Values work keyless via fred_csv", "https://fred.stlouisfed.org/docs/api/api_key.html"),
    KeySpec("eia", ("EIA_API_KEY",), 19, "Energy inventories and production (NRG)", "https://www.eia.gov/opendata/register.php"),
    KeySpec("openfigi", ("OPENFIGI_API_KEY",), 19, "Identifier mapping (SECF), higher rate limit",
            "https://www.openfigi.com/api"),
    KeySpec("tradier", ("TRADIER_TOKEN",), 14, "Options chain with Greeks (fallback)", "https://developer.tradier.com/"),
    KeySpec("telegram", ("TELEGRAM_BOT_TOKEN",), 17, "Push alerts and briefs", "https://core.telegram.org/bots/tutorial"),
    KeySpec("smtp", ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD"), 17, "Email alerts and briefs (app password)",
            "https://support.google.com/accounts/answer/185833", secret_fields=("SMTP_PASSWORD",)),
    KeySpec("webhook", ("ALERT_WEBHOOK_URL",), 17, "Slack/Discord-style webhook for alerts and briefs (the URL is a secret)",
            "https://api.slack.com/messaging/webhooks"),
    # Free read-only sources: UKCO (Companies House), N headlines with sentiment (Marketaux), ADDR (Etherscan).
    KeySpec("companies_house", ("COMPANIES_HOUSE_KEY",), 20, "UK Companies House (free): company profile, officers, filing history (UKCO). 600 requests per 5 minutes",
            "https://developer.company-information.service.gov.uk/get-started"),
    KeySpec("marketaux", ("MARKETAUX_KEY",), 20, "Marketaux (free): financial news with a sentiment score per company, added to N. About 100 requests a day",
            "https://www.marketaux.com/register"),
    KeySpec("etherscan", ("ETHERSCAN_KEY",), 20, "Etherscan (free): EVM address balance, recent transactions and gas price (ADDR). 3 calls a second",
            "https://etherscan.io/apidashboard"),
    KeySpec("aisstream", ("AISSTREAM_API_KEY",), 20, "AISstream (free, beta): live ship positions in a box (AIS). WebSocket, 3 connections per account",
            "https://aisstream.io/authenticate"),
    # Trade + US macro family (free, read-only). Panels TRADE (Comtrade) and USMAC (BLS, BEA, Census).
    KeySpec("comtrade", ("UN_COMTRADE_KEY",), 19, "UN Comtrade (free): trade flows between two countries by HS product (TRADE)",
            "https://comtradedeveloper.un.org/"),
    KeySpec("bls", ("BLS_API_KEY",), 19, "BLS (free): US CPI, jobs, wages, job openings, 500 queries a day (USMAC BLS)",
            "https://data.bls.gov/registrationEngine/"),
    KeySpec("bea", ("BEA_API_KEY",), 19, "BEA (free): US GDP, trade balance, value added by industry (USMAC BEA)",
            "https://apps.bea.gov/API/signup/"),
    KeySpec("census", ("CENSUS_API_KEY",), 19, "US Census (free): monthly retail sales, US goods trade by country and HS chapter (USMAC CENSUS)",
            "https://api.census.gov/data/key_signup.html"),
    KeySpec("kite",("KITE_API_KEY", "KITE_API_SECRET"), 15,
            "Zerodha Kite Connect (read-only): NSE/BSE/NFO/MCX bars, ticks, option chains with open interest. Paid developer app, daily login",
            "https://developers.kite.trade/", hidden_fields=("KITE_ACCESS_TOKEN", "KITE_LOGIN_AT", "KITE_USER_ID"),
            hidden_secret=("KITE_ACCESS_TOKEN",)),
]}

class KeyStoreError(Exception):
    """kind: unknown_provider | bad_request | env_locked | unavailable"""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


class MemoryKeyring:
    """In-process stand-in with the keyring API (tests, OPENTERM_KEYRING=memory)."""

    def __init__(self) -> None:
        self.data: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, user: str) -> str | None:
        return self.data.get((service, user))

    def set_password(self, service: str, user: str, value: str) -> None:
        self.data[(service, user)] = value

    def delete_password(self, service: str, user: str) -> None:
        self.data.pop((service, user), None)


class LazyKeyring:
    """The OS keyring, imported on first use. `usable` is False when keyring has no real backend."""

    def __init__(self) -> None:
        self._kr = None
        self._usable: bool | None = None

    @property
    def usable(self) -> bool:
        if self._usable is None:
            try:
                import keyring
                from keyring.backends import fail

                self._kr = keyring
                self._usable = not isinstance(keyring.get_keyring(), fail.Keyring)
            except Exception:  # noqa: BLE001 - not installed or broken backend: fall back to .env
                self._usable = False
        return self._usable

    def get_password(self, service: str, user: str) -> str | None:
        return self._kr.get_password(service, user) if self.usable else None

    def set_password(self, service: str, user: str, value: str) -> None:
        self._kr.set_password(service, user, value)

    def delete_password(self, service: str, user: str) -> None:
        try:
            self._kr.delete_password(service, user)
        except Exception:  # noqa: BLE001, S110 - deleting a missing entry raises PasswordDeleteError
            pass


# --- .env file ---------------------------------------------------------------------------------------------------

def read_dotenv(path: Path) -> dict[str, str]:
    try:
        text = path.read_bytes().decode("utf-8")
    except FileNotFoundError:
        return {}
    out = {}
    for line in text.splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                v = v[1:-1]
            out[k.strip()] = v
    return out


def write_dotenv(path: Path, updates: Mapping[str, str | None]) -> None:
    """Replaces keys in place, appends new ones, removes keys mapped to None. Other lines keep their order; LF."""
    try:
        lines = path.read_bytes().decode("utf-8").splitlines()
    except FileNotFoundError:
        lines = []
    left = dict(updates)
    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        if key in left:
            value = left.pop(key)
            if value is not None:
                out.append(f"{key}={value}")
        else:
            out.append(line)
    out += [f"{k}={v}" for k, v in left.items() if v is not None]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(("\n".join(out) + "\n").encode("utf-8") if out else b"")


# --- store -------------------------------------------------------------------------------------------------------

class KeyStore:
    def __init__(self, env: Mapping[str, str], dotenv: Path, keyring=None):
        self.env = env
        self.dotenv = Path(dotenv)
        self.keyring = keyring
        self._ring_cache: dict[str, str | None] = {}
        self._checks: dict[str, tuple[str, float, str | None]] = {}
        dot = read_dotenv(self.dotenv)
        for spec in KEY_SPECS.values():  # env and .env are cheap: register their secrets now, the keyring lazily
            redact.register([v for f in spec.secrets if (v := self.env.get(f) or dot.get(f))])

    def _spec(self, name: str) -> KeySpec:
        if name not in KEY_SPECS:
            raise KeyStoreError("unknown_provider", f"UNKNOWN PROVIDER {name.upper()}")
        return KEY_SPECS[name]

    def _ring_usable(self) -> bool:
        return self.keyring is not None and getattr(self.keyring, "usable", True)

    def _ring_get(self, field: str) -> str | None:
        if field not in self._ring_cache:
            self._ring_cache[field] = self.keyring.get_password(SERVICE, field) if self._ring_usable() else None
        return self._ring_cache[field]

    def _lookup(self, spec: KeySpec) -> tuple[dict[str, str], str | None]:
        dot = None
        values, source = {}, None
        for f in spec.fields:
            if v := self.env.get(f):
                src = "env"
            elif v := self._ring_get(f):
                src = "keyring"
            else:
                dot = read_dotenv(self.dotenv) if dot is None else dot
                v, src = dot.get(f), "dotenv"
            if v:
                values[f] = v
                source = source or src
        if values:
            redact.register([values[f] for f in spec.secrets if f in values])
        return values, source

    def get(self, name: str) -> dict[str, str] | None:
        spec = self._spec(name)
        values, _ = self._lookup(spec)
        return values if len(values) == len(spec.fields) else None

    def status(self, name: str) -> dict:
        spec = self._spec(name)
        values, source = self._lookup(spec)
        present = len(values) == len(spec.fields)
        state, checked_at, detail = self._checks.get(name, ("UNTESTED", None, None)) if present else ("MISSING", None, None)
        return {"name": name, "present": present, "source": source if present else None, "state": state,
                "checked_at": checked_at, "detail": detail}

    def statuses(self) -> list[dict]:
        return [self.status(n) for n in KEY_SPECS]

    def env_locked(self, spec: KeySpec) -> bool:
        return any(self.env.get(f) for f in spec.fields)

    def set(self, name: str, fields: Mapping[str, str]) -> None:
        spec = self._spec(name)
        if not isinstance(fields, Mapping) or set(fields) != set(spec.fields):
            raise KeyStoreError("bad_request", f"{spec.label} NEEDS {', '.join(spec.fields)}")
        for f, v in fields.items():
            if not isinstance(v, str) or not v.strip() or "\n" in v or "\r" in v:
                raise KeyStoreError("bad_request", f"{f} MUST BE ONE NON-EMPTY LINE")
        if self.env_locked(spec):
            raise KeyStoreError("env_locked", f"SET IN ENV: CHANGE {spec.label} IN .env OR THE ENVIRONMENT")
        values = {f: v.strip() for f, v in fields.items()}
        redact.register([values[f] for f in spec.secrets])
        if self._ring_usable():
            for f, v in values.items():
                self.keyring.set_password(SERVICE, f, v)
                self._ring_cache[f] = v
            if self._in_dotenv(spec):  # an older .env copy would come back after a delete
                write_dotenv(self.dotenv, dict.fromkeys(spec.fields))
        else:
            write_dotenv(self.dotenv, values)
        self._clear_hidden(spec)  # a new key or secret makes yesterday's access token meaningless
        self._checks.pop(name, None)

    # --- hidden fields (Kite's access token): same stores as the keys, never an input, never in a status row ---
    def get_hidden(self, name: str, field: str) -> str | None:
        spec = self._spec(name)
        if field not in spec.hidden_fields:
            raise KeyStoreError("bad_request", f"{field} IS NOT A HIDDEN FIELD OF {spec.label}")
        v = self._ring_get(field) if self._ring_usable() else None
        v = v or read_dotenv(self.dotenv).get(field)
        if v and field in spec.hidden_secret:
            redact.register([v])
        return v or None

    def set_hidden(self, name: str, values: Mapping[str, str | None]) -> None:
        """Stores (or, for None, removes) hidden fields. A value is one line."""
        spec = self._spec(name)
        for f, v in values.items():
            if f not in spec.hidden_fields:
                raise KeyStoreError("bad_request", f"{f} IS NOT A HIDDEN FIELD OF {spec.label}")
            if v is not None and (not isinstance(v, str) or not v.strip() or "\n" in v or "\r" in v):
                raise KeyStoreError("bad_request", f"{f} MUST BE ONE NON-EMPTY LINE")
            if v and f in spec.hidden_secret:
                redact.register([v])
        if self._ring_usable():
            for f, v in values.items():
                if v is None:
                    self.keyring.delete_password(SERVICE, f)
                    self._ring_cache[f] = None
                else:
                    self.keyring.set_password(SERVICE, f, v)
                    self._ring_cache[f] = v
            if any(f in read_dotenv(self.dotenv) for f in values):
                write_dotenv(self.dotenv, dict.fromkeys(values))
        else:
            write_dotenv(self.dotenv, values)

    def _clear_hidden(self, spec: KeySpec) -> None:
        if spec.hidden_fields:
            self.set_hidden(spec.name, dict.fromkeys(spec.hidden_fields))

    def _in_dotenv(self, spec: KeySpec) -> bool:
        dot = read_dotenv(self.dotenv)
        return any(f in dot for f in spec.fields)

    def delete(self, name: str) -> None:
        spec = self._spec(name)
        if self.env_locked(spec):
            raise KeyStoreError("env_locked", f"SET IN ENV: CHANGE {spec.label} IN .env OR THE ENVIRONMENT")
        if self._ring_usable():
            for f in spec.fields:
                self.keyring.delete_password(SERVICE, f)
                self._ring_cache[f] = None
        if self._in_dotenv(spec):
            write_dotenv(self.dotenv, dict.fromkeys(spec.fields))
        self._clear_hidden(spec)
        self._checks.pop(name, None)

    def record_check(self, name: str, state: str, detail: str | None) -> None:
        self._checks[name] = (state, time.time(), detail)

    def secrets(self) -> set[str]:
        out: set[str] = set()
        for spec in KEY_SPECS.values():
            values, _ = self._lookup(spec)
            out.update(values[f] for f in spec.secrets if f in values)
            out.update(v for f in spec.hidden_secret if (v := self.get_hidden(spec.name, f)))
        return out


def from_settings(settings) -> KeyStore:
    from .config import ROOT

    mode = (settings.openterm_keyring or "auto").lower()
    ring = MemoryKeyring() if mode == "memory" else None if mode == "none" else LazyKeyring()
    path = Path(settings.openterm_dotenv_path) if settings.openterm_dotenv_path else ROOT / ".env"
    return KeyStore(env=os.environ, dotenv=path if path.is_absolute() else ROOT / path, keyring=ring)


# --- test calls --------------------------------------------------------------------------------------------------

QUOTA_WORDS = ("limit reach", "quota", "upgrade your plan", "rate limit exceeded", "too many requests")


def _body_rejects_key(low: str) -> bool:
    """BLS and BEA answer HTTP 200 with the complaint in the body (doc-shaped, unverified against a live bad key)."""
    # Etherscan: HTTP 200 with {"status":"0","message":"NOTOK","result":"Invalid API Key"} (text from docs.etherscan.io "Common Error Messages").
    return (("request_not_processed" in low and "key" in low) or ('"apierrorcode"' in low and ("userid" in low or "user id" in low))
            or "invalid api key" in low)


def classify(status: int, body: str) -> str:
    low = (body or "").lower()
    if status in (429, 402) or (200 <= status < 300 and any(w in low for w in QUOTA_WORDS)):  # 402: Marketaux "usage_limit_reached"
        return "QUOTA"
    if 200 <= status < 300 and _body_rejects_key(low):
        return "INVALID"
    if 200 <= status < 300:
        return "OK"
    if status in (401, 403) or (status == 400 and ("api_key" in low or "api key" in low)):
        return "INVALID"
    return "ERROR"


def _bearer(v: str) -> dict:
    return {"Authorization": f"Bearer {v}"}


# name -> fn(values) -> (method, url, params, headers, json body)
TESTS: dict[str, Callable[[dict], tuple]] = {
    "openrouter": lambda k: ("GET", "https://openrouter.ai/api/v1/key", None, _bearer(k["OPENROUTER_API_KEY"]), None),
    "openai": lambda k: ("GET", "https://api.openai.com/v1/models", None, _bearer(k["OPENAI_API_KEY"]), None),
    "anthropic": lambda k: ("GET", "https://api.anthropic.com/v1/models", None,
                            {"x-api-key": k["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"}, None),
    "opencodego": lambda k: ("GET", "https://opencode.ai/inference/go/v1/models", None, _bearer(k["OPENCODE_API_KEY"]), None),
    "deepseek": lambda k: ("GET", "https://api.deepseek.com/models", None, _bearer(k["DEEPSEEK_API_KEY"]), None),
    "groq": lambda k: ("GET", "https://api.groq.com/openai/v1/models", None, _bearer(k["GROQ_API_KEY"]), None),
    "mistral": lambda k: ("GET", "https://api.mistral.ai/v1/models", None, _bearer(k["MISTRAL_API_KEY"]), None),
    "xai": lambda k: ("GET", "https://api.x.ai/v1/models", None, _bearer(k["XAI_API_KEY"]), None),
    "together": lambda k: ("GET", "https://api.together.xyz/v1/models", None, _bearer(k["TOGETHER_API_KEY"]), None),
    "fireworks": lambda k: ("GET", "https://api.fireworks.ai/inference/v1/models", None, _bearer(k["FIREWORKS_API_KEY"]), None),
    "gemini": lambda k: ("GET", "https://generativelanguage.googleapis.com/v1beta/openai/models", None,
                         _bearer(k["GEMINI_API_KEY"]), None),
    "finnhub": lambda k: ("GET", "https://finnhub.io/api/v1/quote", {"symbol": "AAPL", "token": k["FINNHUB_API_KEY"]},
                          None, None),
    "alpaca": lambda k: ("GET", "https://paper-api.alpaca.markets/v2/account", None,
                         {"APCA-API-KEY-ID": k["ALPACA_KEY_ID"], "APCA-API-SECRET-KEY": k["ALPACA_SECRET_KEY"]}, None),
    "fmp": lambda k: ("GET", "https://financialmodelingprep.com/stable/quote",
                      {"symbol": "AAPL", "apikey": k["FMP_API_KEY"]}, None, None),
    "fred": lambda k: ("GET", "https://api.stlouisfed.org/fred/series",
                       {"series_id": "DGS10", "api_key": k["FRED_API_KEY"], "file_type": "json"}, None, None),
    "eia": lambda k: ("GET", "https://api.eia.gov/v2/", {"api_key": k["EIA_API_KEY"]}, None, None),
    "openfigi": lambda k: ("POST", "https://api.openfigi.com/v3/mapping", None,
                           {"X-OPENFIGI-APIKEY": k["OPENFIGI_API_KEY"]}, [{"idType": "ID_ISIN", "idValue": "US0378331005"}]),
    "tradier": lambda k: ("GET", "https://sandbox.tradier.com/v1/markets/clock", None,
                          {**_bearer(k["TRADIER_TOKEN"]), "Accept": "application/json"}, None),
    "telegram": lambda k: ("GET", f"https://api.telegram.org/bot{k['TELEGRAM_BOT_TOKEN']}/getMe", None, None, None),
    # Companies House: HTTP basic auth, the key is the user name and the password is empty. A search for one company is the cheapest call.
    "companies_house": lambda k: ("GET", "https://api.company-information.service.gov.uk/search/companies", {"q": "tesco", "items_per_page": "1"},
                                 {"Authorization": "Basic " + base64.b64encode(f"{k['COMPANIES_HOUSE_KEY']}:".encode()).decode("ascii")}, None),
    # Marketaux has no free "who am I" call: one article is the cheapest, and it does spend one of the ~100 daily requests.
    "marketaux": lambda k: ("GET", "https://api.marketaux.com/v1/news/all", {"api_token": k["MARKETAUX_KEY"], "limit": "1", "language": "en"}, None, None),
    # Etherscan answers HTTP 200 with status "0" for a bad key; classify() reads "Invalid API Key" out of the body.
    "etherscan": lambda k: ("GET", "https://api.etherscan.io/v2/api", {"chainid": "1", "module": "gastracker", "action": "gasoracle",
                                                                       "apikey": k["ETHERSCAN_KEY"]}, None, None),
    # Trade + US macro family: each uses the source's cheapest documented call (doc-shaped, never run against a live key).
    "comtrade": lambda k: ("GET", "https://comtradeapi.un.org/data/v1/get/C/A/HS",
                           {"reporterCode": "842", "partnerCode": "0", "period": "2022", "cmdCode": "TOTAL", "flowCode": "X", "maxrecords": "1"},
                           {"Ocp-Apim-Subscription-Key": k["UN_COMTRADE_KEY"]}, None),
    "bls": lambda k: ("POST", "https://api.bls.gov/publicAPI/v2/timeseries/data/", None, None,
                      {"seriesid": ["LNS14000000"], "startyear": "2025", "endyear": "2025", "registrationkey": k["BLS_API_KEY"]}),
    "bea": lambda k: ("GET", "https://apps.bea.gov/api/data", {"UserID": k["BEA_API_KEY"], "method": "GETDATASETLIST", "ResultFormat": "JSON"},
                      None, None),
    "census": lambda k: ("GET", "https://api.census.gov/data/timeseries/eits/marts",
                         {"get": "cell_value", "time": "2024-01", "category_code": "44X72", "data_type_code": "SM", "key": k["CENSUS_API_KEY"]},
                         None, None),
}


def _smtp_check(k: dict) -> tuple[str, str | None]:
    import smtplib

    from .delivery import DeliveryError
    from .delivery.email import (
        smtp_connect,  # the same TLS rules as a real send (verified certificate, no plaintext)
    )

    try:
        smtp_connect(k["SMTP_HOST"], int(k["SMTP_PORT"]), k["SMTP_USER"], k["SMTP_PASSWORD"], 10).close()
        return "OK", None
    except smtplib.SMTPAuthenticationError as e:
        return "INVALID", f"SMTP {e.smtp_code}"
    except DeliveryError as e:
        return "ERROR", str(e)
    except (OSError, ValueError, smtplib.SMTPException) as e:
        return "ERROR", type(e).__name__


async def run_test(store: KeyStore, name: str, http: httpx.AsyncClient, fixtures: bool = False) -> dict:
    """Calls the provider's cheapest authenticated endpoint and records OK / INVALID / QUOTA / ERROR."""
    values = await asyncio.to_thread(store.get, name)
    if values is None:
        return await asyncio.to_thread(store.status, name)
    if name == "kite":  # no network: a Kite key is only proven by a login (GET /api/kite/login), so UNTESTED until then
        token = await asyncio.to_thread(store.get_hidden, "kite", "KITE_ACCESS_TOKEN")
        state, detail = ("OK", None) if token else ("UNTESTED", "LOG IN WITH KITE LOGIN TO PROVE THE KEY")
    elif name == "webhook":  # a test would post a real message into someone's channel: only the URL shape is checked
        from .delivery import DeliveryError
        from .delivery.webhook import check_url

        try:
            check_url(values["ALERT_WEBHOOK_URL"])
            state, detail = "UNTESTED", "SHAPE OK: USE DELIVERY TEST TO SEND A MESSAGE"
        except DeliveryError as e:
            state, detail = "INVALID", str(e)
    elif name == "smtp":
        state, detail = ("ERROR", "SMTP IS NOT TESTED IN FIXTURE MODE") if fixtures else \
            await asyncio.to_thread(_smtp_check, values)
    elif name == "aisstream":  # a WebSocket, not an HTTP call: subscribe to a tiny box and wait for the confirmation (see aisstream.check_key)
        if fixtures:
            state, detail = "ERROR", "AISSTREAM IS NOT TESTED IN FIXTURE MODE (NO NETWORK)"
        else:
            # imported here so `websockets` stays off the startup path
            from .providers.aisstream import check_key

            state, detail = await check_key(values)
    else:
        method, url, params, headers, body = TESTS[name](values)
        try:
            r = await http.request(method, url, params=params, headers=headers, json=body, timeout=10.0)
            state = classify(r.status_code, r.text)
            detail = None if state == "OK" else f"HTTP {r.status_code}: {r.text[:160]}"
        except httpx.HTTPError as e:
            state, detail = "ERROR", type(e).__name__
    store.record_check(name, state, redact.redact(detail) if detail else None)
    return await asyncio.to_thread(store.status, name)
