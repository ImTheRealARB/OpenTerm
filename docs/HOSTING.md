# Hosting OpenTerm yourself (remote mode)

OpenTerm is a local app by default: it listens on `127.0.0.1` and trusts "this machine". Remote mode lets **one person** reach **their own** copy from a browser elsewhere, behind HTTPS. It is for one user with one access token, not a multi-user service, and not a way to publish data to others.

Switch it on with `OPENTERM_REMOTE=1` and `OPENTERM_PUBLIC_ORIGIN=https://your.domain`. Without `OPENTERM_REMOTE=1` nothing described here exists and OpenTerm behaves exactly as before.

## Why this needs care

A reverse proxy on the same host (the Caddy in `deploy/`) forwards every request from `127.0.0.1`. OpenTerm's local-only checks ("this route changes keys, so only this machine may call it") would then pass for the whole internet. Remote mode closes that in one place, `http_util.loopback()`: **in remote mode nothing counts as local, for anyone, with or without a login.** Forwarded-for headers are never trusted for this; a client can write them.

## Setup (Docker and Caddy)

You need a server with Docker, a DNS name pointing at it, and ports 80 and 443 open.

```
cd deploy
cp .env.example .env                                   # set OPENTERM_DOMAIN=term.example.com
docker compose -f docker-compose.remote.yml up -d --build
docker compose -f docker-compose.remote.yml logs openterm | grep "ACCESS TOKEN"
```

`deploy/` was written without running Docker. Read `docker-compose.remote.yml` and the `Caddyfile` before you use them. Open `https://term.example.com`, paste the token on the login page.

Without Docker: run `OPENTERM_REMOTE=1 OPENTERM_PUBLIC_ORIGIN=https://term.example.com python -m openterm` (bound to `127.0.0.1`) and put any HTTPS reverse proxy in front that passes WebSockets. `OPENTERM_REMOTE=1` refuses to start unless the public origin is an `https://` address with no path.

## The token and the session

- The token is made on first start (`secrets.token_urlsafe(32)`) and **printed once** on the console (`docker compose logs`). Only a salted scrypt hash is stored, in the data dir as `remote_token`, file mode `0600`. Keep the plain token in a password manager; OpenTerm cannot show it again.
- Login compares in constant time (`hmac.compare_digest`). After 5 wrong tokens in 5 minutes, every login attempt answers 429 until the window passes (the limit is global, since behind the proxy all clients look alike; a right token during the lock-out is also refused).
- A good login sets the cookie `__Host-openterm_session`: random id, `HttpOnly; Secure; SameSite=Strict; Path=/`, 12-hour expiry. Sessions live in memory: restarting OpenTerm logs everyone out. `POST /api/remote/logout` ends one.
- **Cross-site requests.** `SameSite=Strict` keeps the cookie off cross-site requests, and the Origin guard (`origin.py`) refuses any changing request or WebSocket whose `Origin` is not exactly `OPENTERM_PUBLIC_ORIGIN` (a page on `localhost` counts as another site). Both stay on behind the proxy.

### Rotating the token

```
docker compose -f docker-compose.remote.yml exec openterm python -m openterm.remote rotate
```

It prints a new token, replaces the hash and ends every session at once; the running server notices the new file, no restart needed. Rotate when a device is lost, when the token may have been seen (for example in a shared log), and now and then.

## What remote mode changes

| Rule | Detail |
| --- | --- |
| Everything needs a login | Every HTTP route and WebSocket answers 401 (or closes) without a valid session. Open: the login page `/login` (self-contained HTML) and `POST /api/remote/login`. The app itself (static files) is served only after login. |
| Nothing is "this machine" | Routes marked local-only answer 403 to everyone: APIKEYS and key changes, settings that send messages, Telegram and delivery setup, broker sync and the Kite login, the AI spend cap, strategy and thesis changes, AI chat and agents, third-party MCP client servers, extension enable/disable, journal import and clear. They are done at the machine itself. |
| MCP server off | `/mcp` answers 403 even with a session. MCP agents connect locally. |
| AI off remotely | The AI routes are local-only, so they are refused. The daily brief and server-side alerts keep running on the server. |

Why: these routes spend money, start programs, change where data is sent, touch broker sessions or hold your keys. A stolen cookie must not reach them, and a proxy must not make them look local. Read-only market data, charts, panels, layouts and watchlists work normally after login.

Keys you need remotely go in the container environment (for example `FMP_API_KEY` in `deploy/.env` and the compose file), not through APIKEYS.

## Hardening checklist

- Keep OpenTerm's port off the public network (the compose file only `expose`s it to Caddy).
- Use a long, unique domain name you do not share; restrict by firewall or VPN if you can (the login is one shared secret).
- Rotate the token on a schedule; never paste it in chat or issue trackers.
- Back up the data volume (`/data`): your database, watchlists, journal, and `remote_token` hash.
- Extensions are third-party code with your permissions ([EXTENSIONS.md](EXTENSIONS.md)); think twice before enabling one on a server.
