"""Self-hosted remote mode (`OPENTERM_REMOTE=1`, docs/HOSTING.md): one user, one access token, one session cookie.

THE TRAP this module exists to close: behind a reverse proxy on the same host (the Caddy compose in `deploy/`) every remote
request reaches the app from 127.0.0.1, so every "this machine only" check (`http_util.loopback`, the WebSocket client check, the
MCP endpoint) would pass for the whole internet. The rules in remote mode are therefore:

1. Every route, HTTP and WebSocket, needs a valid session cookie. Only the login page and the login call are open.
2. Nothing is "local" any more: `http_util.loopback()` answers False for everyone, a valid session included. The routes that change
   keys, settings, brokers, delivery, the AI and MCP clients are refused remotely; they are set up from the machine itself.
   Forwarded-for headers are never read, because a client can write them.
3. `/mcp` is refused outright, even with a session.

The token is made on first start (`secrets.token_urlsafe(32)`), shown once on the console and stored only as a salted hash in the
data directory (mode 0600). `python -m openterm.remote rotate` makes a new one and ends every session.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sys
import time
from pathlib import Path

import orjson

COOKIE = "__Host-openterm_session"  # the __Host- prefix: the browser only accepts it Secure, Path=/ and with no Domain
SESSION_TTL_S = 12 * 3600
MAX_SESSIONS = 20
FAIL_LIMIT = 5  # wrong tokens allowed ...
FAIL_WINDOW_S = 300  # ... in this window; after that every attempt (right or wrong) gets 429 until the window has passed
TOKEN_FILE = "remote_token"

# What a visitor without a session may reach: the login page (inline HTML, no other assets) and the login call. Nothing else.
OPEN = {("GET", "/login"), ("HEAD", "/login"), ("POST", "/api/remote/login")}


def enabled() -> bool:
    """Read on every call (not cached) so a test or a restart with a changed environment is honoured at once."""
    return os.environ.get("OPENTERM_REMOTE", "").strip().lower() in ("1", "true", "yes", "on")


def public_origin() -> str:
    return os.environ.get("OPENTERM_PUBLIC_ORIGIN", "").strip().rstrip("/")


def check_config() -> None:
    """Refuse to start remote mode half-configured: without the public origin the Origin guard could not tell the real site from another."""
    o = public_origin()
    if not o.startswith("https://") or len(o) <= len("https://") or "/" in o[len("https://"):]:
        raise RuntimeError("OPENTERM_REMOTE=1 needs OPENTERM_PUBLIC_ORIGIN set to the https address people use, e.g. https://term.example.com")


def _hash(token: str, salt: bytes) -> str:
    return hashlib.scrypt(token.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32).hex()


class RemoteAuth:
    """The token file and the sessions. Sessions live in memory (a restart logs everyone out); the token hash is re-read when the file changes."""

    def __init__(self, data_dir: Path | None):
        self.path = data_dir / TOKEN_FILE if data_dir is not None else None
        self._mem: tuple[bytes, str] | None = None  # no data dir (in-memory database): the hash lives in memory only
        self._seen: tuple[int, tuple[bytes, str]] | None = None
        self.sessions: dict[str, tuple[float, str]] = {}  # sha256(session id) -> (expires, token hash it was made under)
        self.fails: list[float] = []

    # --- the token ---
    def ensure_token(self) -> str | None:
        """Makes the token on first start and returns it (to print once); None when one already exists."""
        if self._load() is not None:
            return None
        return self.rotate()

    def rotate(self) -> str:
        token = secrets.token_urlsafe(32)
        salt = secrets.token_bytes(16)
        record = (salt, _hash(token, salt))
        if self.path is None:
            self._mem = record
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(f"{salt.hex()}${record[1]}\n")
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
        self._seen = None
        self.sessions.clear()
        return token

    def _load(self) -> tuple[bytes, str] | None:
        if self.path is None:
            return self._mem
        try:
            mtime = self.path.stat().st_mtime_ns
        except OSError:
            return None
        if self._seen and self._seen[0] == mtime:
            return self._seen[1]
        try:
            salt_hex, digest = self.path.read_text().strip().split("$")
            record = (bytes.fromhex(salt_hex), digest)
        except ValueError:
            return None
        self._seen = (mtime, record)
        return record

    # --- login ---
    def locked(self, now: float | None = None) -> int:
        """Seconds until a login attempt is looked at again (0 = now). Global, not per address: behind the proxy every client looks the same."""
        now = time.time() if now is None else now
        self.fails = [t for t in self.fails if now - t < FAIL_WINDOW_S]
        return int(FAIL_WINDOW_S - (now - self.fails[0])) + 1 if len(self.fails) >= FAIL_LIMIT else 0

    def login(self, token: object) -> str | None:
        """A new session id for a right token, else None (and the failure is counted)."""
        record = self._load()
        now = time.time()
        if record is None or not isinstance(token, str) or len(token) > 200:
            self.fails.append(now)
            return None
        if not hmac.compare_digest(_hash(token, record[0]), record[1]):
            self.fails.append(now)
            return None
        self.fails.clear()
        self.sessions = {k: v for k, v in self.sessions.items() if v[0] > now}
        while len(self.sessions) >= MAX_SESSIONS:
            self.sessions.pop(min(self.sessions, key=lambda k: self.sessions[k][0]))
        sid = secrets.token_urlsafe(32)
        self.sessions[hashlib.sha256(sid.encode()).hexdigest()] = (now + SESSION_TTL_S, record[1])
        return sid

    def valid(self, sid: str | None) -> bool:
        if not sid:
            return False
        key = hashlib.sha256(sid.encode()).hexdigest()
        rec = self.sessions.get(key)
        record = self._load()
        if rec is None or record is None:
            return False
        if rec[0] <= time.time() or rec[1] != record[1]:  # expired, or the token was rotated since
            self.sessions.pop(key, None)
            return False
        return True

    def logout(self, sid: str | None) -> None:
        if sid:
            self.sessions.pop(hashlib.sha256(sid.encode()).hexdigest(), None)


def cookie_from(scope) -> str | None:
    for k, v in scope.get("headers", ()):
        if k == b"cookie":
            for part in v.decode("latin-1").split(";"):
                name, _, val = part.strip().partition("=")
                if name == COOKIE:
                    return val
    return None


def set_cookie(sid: str, max_age: int = SESSION_TTL_S) -> str:
    return f"{COOKIE}={sid}; Max-Age={max_age}; Path=/; HttpOnly; Secure; SameSite=Strict"


LOGIN_PAGE = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>OpenTerm login</title>
<style>body{background:#000;color:#ffb000;font:14px/1.5 monospace;display:grid;place-items:center;min-height:100vh;margin:0}
form{display:grid;gap:10px;width:min(90vw,420px)}input,button{font:inherit;background:#111;color:#ffb000;border:1px solid #ffb000;padding:8px}
#e{color:#ff5555;min-height:1.5em}</style>
<form id="f"><div>OPENTERM ACCESS TOKEN</div><input id="t" type="password" autocomplete="current-password" autofocus required>
<button>LOGIN</button><div id="e"></div></form>
<script>
document.getElementById("f").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const e = document.getElementById("e"); e.textContent = "";
  try {
    const r = await fetch("/api/remote/login", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({token: document.getElementById("t").value})});
    if (r.ok) { location.replace("/"); return; }
    const b = await r.json().catch(() => ({}));
    e.textContent = b.error || "LOGIN FAILED";
  } catch { e.textContent = "NETWORK ERROR"; }
});
</script>
"""


class RemoteAuthMiddleware:
    """Pure ASGI. Inert unless `OPENTERM_REMOTE=1`. With it, nothing but `OPEN` gets through without a valid session cookie."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        kind = scope["type"]
        if kind not in ("http", "websocket") or not enabled():
            return await self.app(scope, receive, send)
        path = scope["path"]
        auth: RemoteAuth | None = getattr(scope["app"].state, "remote", None)
        if auth is None:  # remote mode on but not set up: fail closed
            return await self._deny(scope, receive, send, 503, "REMOTE MODE IS NOT READY")
        if kind == "http" and (scope["method"], path) in OPEN:
            return await self.app(scope, receive, send)
        if path == "/mcp" or path.startswith("/mcp/"):  # even with a session: the MCP server is for local agents only
            return await self._deny(scope, receive, send, 403, "FORBIDDEN: MCP IS NOT AVAILABLE IN REMOTE MODE")
        if not auth.valid(cookie_from(scope)):
            return await self._deny(scope, receive, send, 401, "LOGIN REQUIRED")
        await self.app(scope, receive, send)

    @staticmethod
    async def _deny(scope, receive, send, status: int, message: str) -> None:
        if scope["type"] == "websocket":
            await receive()
            return await send({"type": "websocket.close", "code": 1008})
        headers = dict(scope.get("headers", ()))
        wants_page = scope["method"] == "GET" and b"text/html" in headers.get(b"accept", b"") and not scope["path"].startswith("/api/")
        if status == 401 and wants_page:
            await send({"type": "http.response.start", "status": 302, "headers": [(b"location", b"/login"), (b"content-length", b"0")]})
            return await send({"type": "http.response.body", "body": b""})
        body = orjson.dumps({"error": message, "kind": "login_required" if status == 401 else "forbidden"})
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()), (b"cache-control", b"no-store")]})
        await send({"type": "http.response.body", "body": body})


def announce(token: str, path: Path | None) -> None:
    """The one place the token is shown. It goes to stderr (the console / `docker compose logs`), never to a logger or a file."""
    where = f" Only its hash is stored in {path}." if path else ""
    print(f"\n  OPENTERM REMOTE ACCESS TOKEN (shown once): {token}\n  Rotate: python -m openterm.remote rotate.{where}\n", file=sys.stderr, flush=True)


def _data_dir() -> Path:
    from .config import ROOT, get_settings

    p = Path(get_settings().openterm_db_path)
    return (p if p.is_absolute() else ROOT / p).parent


def main(argv: list[str]) -> int:
    if argv[:1] != ["rotate"]:
        print("usage: python -m openterm.remote rotate   (a new token; every session ends; the running server needs no restart)", file=sys.stderr)
        return 2
    auth = RemoteAuth(_data_dir())
    announce(auth.rotate(), auth.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
