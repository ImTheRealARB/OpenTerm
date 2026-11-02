# Phase 17: MCP server, alert delivery, daily brief

Written 2026-11-03 by the Opus orchestrator from `NEXT_SESSION.md` Part 2 (roadmap defaults are pre-approved; the user
approved building without a check-in). Build order: A (MCP), B (delivery), C (brief), D (frontend).

## A. MCP server (read-only)
MCP (Model Context Protocol) lets an outside AI client (Claude Desktop, Claude Code, Cursor) call OpenTerm's data tools.
- **One implementation, two transports.** `openterm/mcp/server.py` = a pure JSON-RPC 2.0 dispatcher (`initialize`,
  `notifications/initialized`, `ping`, `tools/list`, `tools/call`; protocol version `2025-06-18`, older client versions
  accepted by echoing ours). Hand-written, no `mcp` SDK dependency (about 200 lines vs ~10 extra packages).
  - **HTTP:** `POST /mcp` (Streamable HTTP, JSON response mode; `GET /mcp` = 405). Loopback clients only (`api.loopback`);
    a request whose `Origin` header is not `http://localhost*` / `http://127.0.0.1*` is refused 403 (DNS-rebinding guard the
    MCP spec requires).
  - **stdio:** `uv run python -m openterm.mcp` reads JSON-RPC lines on stdin, forwards each to
    `http://127.0.0.1:8000/mcp` (`OPENTERM_URL` overrides), writes answers to stdout. If OpenTerm is not running every call
    answers a JSON-RPC error `OPENTERM IS NOT RUNNING AT <url>: start it with openterm`.
- **Tools = the AI agent's registry** (`ai/tools.REGISTRY`, minus `doc_only`), run through `ToolRunner` (in-process ASGI,
  as the local user). Same validation, shaping, size caps. Each result carries `source`, `age_s`, `stale`, `empty` in the
  text (`structuredContent` too) so the client can see where data came from. Tool errors are `isError: true` results,
  never protocol errors. `backtest_run` and `quant` are compute jobs: listed with `readOnlyHint: false`,
  `destructiveHint: false`; all others `readOnlyHint: true`.
- **No order tools, ever.** A test scans `tools/list` names, descriptions and the `mcp` package source for
  `order`, `gtt`, `margin`, `holdings`, `position` (word) and `kite` routes.
- Error text through `redact()`. Docs: `docs/MCP.md` (Claude Desktop / Claude Code config snippets, PowerShell syntax).

## B. Alert delivery
- **How alerts reach the backend:** unchanged evaluation in the browser; the existing `POST /api/alerts/{id}/trigger`
  and `POST /api/newsalerts/{id}/trigger` already return `changed: true` exactly once per firing. On `changed` the route
  schedules `delivery.dispatch(...)` as a background task (never blocks the answer). Known limit (DATA_LIMITS.md): alerts fire
  only while an OpenTerm tab is open, as today.
- **Channels** (`openterm/delivery/`, one module per channel, pure message formatting in `delivery/format.py`):
  - `desktop`: browser Notification API in the frontend (no backend part). Off until the user enables it and grants permission.
  - `email`: SMTP from keys `SMTP_HOST/PORT/USER/PASSWORD` + recipient `email_to` in delivery settings.
    **TLS (closes the DECISIONS_FOR_USER item):** port 465 = `SMTP_SSL` with `ssl.create_default_context()`; any other port =
    `starttls(context=ssl.create_default_context())`, and a server without STARTTLS is refused (`SMTP SERVER OFFERS NO TLS`)
    unless the host is loopback (a local relay such as MailHog). Certificates are always verified; a failure says
    `SMTP TLS CERTIFICATE NOT TRUSTED`. `keys._smtp_check` uses the same helper.
  - `telegram`: key `TELEGRAM_BOT_TOKEN` + `telegram_chat_id` in delivery settings; `sendMessage`, plain text.
  - `webhook` (optional extra): new key `ALERT_WEBHOOK_URL` (a Slack/Discord webhook URL is a secret, so it is a key, not a
    setting); POST JSON `{text, kind, ...}`; https only (http only for loopback).
- **Off by default.** Delivery settings live in kv key `delivery` (`{channels: {email, telegram, webhook, desktop}: bool,
  email_to, telegram_chat_id, brief: {...}}`), routes `GET/PUT /api/delivery` (PUT loopback only). A channel that is on but
  has no key says `KEY REQUIRED: set X in APIKEYS` in its status and log, never fails silently.
- **Log:** migration 15 table `deliveries(id, at, kind, ref, channel, status, detail)`; kind alert|news|brief|test, status
  sent|failed|skipped; `detail` redacted, 300 chars; kept to the last 500 rows. `GET /api/delivery/log`.
  `POST /api/delivery/test {channel}` sends a test message (loopback only).
- Network calls go through the app's httpx client; fixture mode never sends (status `skipped`, detail `FIXTURE MODE`);
  tests use a fake transport / fake SMTP class. Per-channel timeout 10 s; one retry after 2 s on a network error.

## C. Daily brief
- `openterm/brief.py`: `build_brief(app)` makes a data brief through in-process ASGI calls to the app's own routes (no new
  data paths): watchlist quotes with the biggest movers (default list, else the first list), alerts triggered in the last
  24 h, today's earnings and economic events for those names (existing calendar routes), top 5 headlines. Every section
  names its source and age; a failed section says `ERR <source>` and the brief still goes out. No AI in v1 (keeps it free;
  an AI summary is a later option).
- Schedule: `brief: {enabled: false, time: "08:30", days: "mon-fri", tz: <local>}` in delivery settings; apscheduler cron
  job, rescheduled on PUT. Delivered to every enabled push channel (email, telegram, webhook). Stored: kv `brief:last`.
  Routes: `GET /api/brief` (last), `POST /api/brief/run` (build now; `send=true` also delivers; loopback only).

## D. Frontend
- `DLVR` function: channel table (on/off, key status, test with `T`), recipient fields, brief schedule, delivery log.
  Keyboard: arrows, `Space` toggles, `Enter` edits a field, `T` test, `L` log view.
- `BRIEF` function: shows the last brief (sections with source/age), `R` builds now, `S` builds and sends.
- Desktop notifications: on a trigger the frontend already reports, show `new Notification(...)` when the desktop
  channel is on and permission is granted (`DLVR` asks for permission on enable).
- Register in `categories.ts`, regenerate `docs/FUNCTIONS.md`.

## Tests (tests-first, strict xfail per step group: `MCP`, `DLV`, `BRF`)
`tests/test_phase17_mcp.py`, `test_phase17_delivery.py`, `test_phase17_brief.py`, vitest for pure parsers, Playwright for
DLVR/BRIEF with mocked routes. Migration 15 tables in `TABLES_BY_VERSION`.

## Bench
No new budget. Backend trigger route must not slow (dispatch is a background task). Bundle: the two panels lazy-load.
