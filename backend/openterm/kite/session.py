"""Kite login state (spec "Login" and "Status"). The login is daily and never automated: the user opens KITE LOGIN, the callback stores
the one-day access token as a hidden field of the `kite` key (keys.py), and every call reads it from here.

States: NO KEY, LOGGED OUT, OK, KITE LOGIN EXPIRED. A login expires at the next 06:00 IST strictly after it was made, or when any
Kite call answers a 403 TokenException (`mark_expired`). The token, the secret, the public token and the enctoken never leave this module
except in the Authorization header of a Kite request.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..errors import DataError

IST = timezone(timedelta(hours=5, minutes=30))
EXPIRY_HOUR_IST = 6
KEY_REQUIRED_MESSAGE = "KEY REQUIRED: set KITE_API_KEY in APIKEYS"
LOGGED_OUT_MESSAGE = "KITE LOGGED OUT: run KITE LOGIN"
EXPIRED_MESSAGE = "KITE LOGIN EXPIRED: run KITE LOGIN"

TOKEN, LOGIN_AT, USER_ID = "KITE_ACCESS_TOKEN", "KITE_LOGIN_AT", "KITE_USER_ID"


def expiry_of(login_dt: datetime) -> datetime:
    """The next 06:00 IST strictly after the login."""
    local = login_dt.astimezone(IST)
    cut = local.replace(hour=EXPIRY_HOUR_IST, minute=0, second=0, microsecond=0)
    return cut if cut > local else cut + timedelta(days=1)


def expired(login_dt: datetime, now_dt: datetime) -> bool:
    return now_dt >= expiry_of(login_dt)


class KiteSession:
    def __init__(self, store, clock=None):
        self.store = store  # keys.KeyStore
        self.clock = clock or (lambda: datetime.now(IST))
        self._loaded = False
        self._creds: dict[str, str] | None = None
        self._token: str | None = None
        self._login_at: datetime | None = None
        self._user: str | None = None
        self._flagged = False  # a 403 TokenException was seen

    # --- cache over the key store (reload on any key change) ---
    def reload(self) -> None:
        self._loaded = False
        self._flagged = False

    def _load(self) -> None:
        if self._loaded:
            return
        self._creds = self.store.get("kite")
        self._token = self.store.get_hidden("kite", TOKEN) if self._creds else None
        raw = self.store.get_hidden("kite", LOGIN_AT) if self._token else None
        try:
            self._login_at = datetime.fromisoformat(raw) if raw else None
        except ValueError:
            self._login_at = None
        self._user = self.store.get_hidden("kite", USER_ID) if self._token else None
        self._loaded = True

    # --- state ---
    @property
    def has_key(self) -> bool:
        self._load()
        return self._creds is not None

    def credentials(self) -> tuple[str, str] | None:
        self._load()
        return (self._creds["KITE_API_KEY"], self._creds["KITE_API_SECRET"]) if self._creds else None

    @property
    def state(self) -> str:
        self._load()
        if self._creds is None:
            return "NO KEY"
        if not self._token:
            return "LOGGED OUT"
        if self._flagged or self._login_at is None or expired(self._login_at, self.clock()):
            return "KITE LOGIN EXPIRED"
        return "OK"

    @property
    def logged_in(self) -> bool:
        return self.state == "OK"

    def message(self) -> str | None:
        return {"NO KEY": KEY_REQUIRED_MESSAGE, "LOGGED OUT": LOGGED_OUT_MESSAGE, "KITE LOGIN EXPIRED": EXPIRED_MESSAGE}.get(self.state)

    def status(self) -> dict:
        st = self.state
        out = {"state": st, "message": self.message(), "user": None, "logged_in_at": None, "expires_note": None}
        if st in ("OK", "KITE LOGIN EXPIRED") and self._login_at is not None:
            out["user"] = self._user
            out["logged_in_at"] = self._login_at.isoformat()
            out["expires_note"] = f"LOGIN ENDS {expiry_of(self._login_at).strftime('%Y-%m-%d %H:%M')} IST (KITE LOGINS LAST ONE TRADING DAY)"
        return out

    def auth(self) -> tuple[str, str]:
        """(api key, access token) for a request, or the DataError that names what is missing."""
        st = self.state
        if st == "NO KEY":
            raise DataError("key_required", KEY_REQUIRED_MESSAGE, key="KITE_API_KEY")
        if st == "LOGGED OUT":
            raise DataError("login_required", LOGGED_OUT_MESSAGE)
        if st == "KITE LOGIN EXPIRED":
            raise DataError("login_expired", EXPIRED_MESSAGE)
        return self._creds["KITE_API_KEY"], self._token  # type: ignore[index, return-value]

    # --- transitions ---
    def login(self, access_token: str, user_id: str | None) -> None:
        now = self.clock()
        self.store.set_hidden("kite", {TOKEN: access_token, LOGIN_AT: now.isoformat(), USER_ID: user_id or None})
        self.store.record_check("kite", "OK", None)
        self._loaded = False
        self._flagged = False

    def logout(self) -> None:
        if self.has_key:
            self.store.set_hidden("kite", {TOKEN: None, LOGIN_AT: None, USER_ID: None})
        self.store.record_check("kite", "UNTESTED", "LOG IN WITH KITE LOGIN TO PROVE THE KEY")
        self._loaded = False
        self._flagged = False

    def mark_expired(self) -> None:
        """A 403 TokenException from any call: the token is dead whatever the clock says."""
        self._flagged = True
        self.store.record_check("kite", "UNTESTED", EXPIRED_MESSAGE)
