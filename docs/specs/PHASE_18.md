# Phase 18: orders and broker sync

Step 1 (orders) and step 2 (read-only broker sync) are both built. This file describes them as built, not as planned.
Every broker payload in the tests is a doc-shaped fixture labelled NOT A RECORDING; no test or fixture contacts a broker.

## Step 1: orders (`ORD`)

### Hard rules
- **The AI never places orders.** No AI tool, MCP tool or swarm role has a route under `/api/orders`; `ToolRunner` refuses any tool
  path containing `/api/orders`; tests scan the tool registry, the MCP tool list and the `ai` and `mcp` sources for the order package.
- **Paper or live is structural.** `Order.from_body` refuses the words `mode`, `live`, `paper`, `host`, `base_url`, `environment`,
  `sandbox`, `force` in a request. The mode of an order is the mode of the broker slot it names, derived from the host that adapter
  talks to and checked against the broker's own answer:
  - `alpaca-paper` uses key slot `alpaca_paper` and host `paper-api.alpaca.markets` (mode paper).
  - `alpaca-live` uses key slot `alpaca_live` and host `api.alpaca.markets` (mode live). A live host that answers with a paper-style
    account number (`PA...`) is refused (`mode_mismatch`).
  - `kite` is always live (Kite has no paper mode; the panel says so). It reuses the read-only Kite login and rate limits.
  - The service re-checks `account.mode == expected mode of that broker id` before every order.
- **Live needs all of:** the key for that slot, the user switching live on (`ORD` key `L`, typed phrase
  `I UNDERSTAND LIVE ORDERS USE REAL MONEY`), a mandate that allows the order, and a fresh one-time confirm token. Without keys the answer
  is `KEY REQUIRED: set ALPACA_LIVE_KEY_ID and ALPACA_LIVE_SECRET_KEY in APIKEYS`; nothing is sent.
- **Loopback only.** Every `/api/orders/*` route answers 403 to a non-loopback client.
- **No secret leaves the backend.** Keys travel in broker headers only; broker and network error text goes through `redact()`; the
  ledger stores neither keys nor confirm tokens.

### Order of checks (`orders/service.py`)
`submit` runs: kill switch off, keys present, account read (mode verified), live switched on (live only), mandate passes, confirm
token valid. Each refusal is written to the ledger. `submitted` is written before the broker is called and `accepted` or `failed`
after, so a crash mid-call still leaves a record. A lock serialises preview-to-send so two orders cannot both pass the daily cap, and the
kill switch is read again inside it.

### Mandate (`orders/mandate.py`)
Allowed symbols (default: none), max shares, max notional per order, max gross exposure after the order, max trades per day. Zero means
zero. A check that cannot be computed (no fresh quote for a market order, positions unreadable) fails; the mandate never passes on missing
data. The daily count is the `orders_log` table (an order the broker rejected, or whose outcome is unknown, still counts). Changing the
mandate voids every open token.

### Confirm token (`orders/confirm.py`)
Issued only by `preview`, and only when the mandate check passes. Bound to a fingerprint of the whole order plus mode and account, valid
60 s, single use, burned by any failed attempt, held in memory (a restart voids all). Reuse, expiry and a different order are refused.

### Kill switch
`POST /api/orders/kill` persists `on` first (it survives a restart), voids every token, then cancels all open orders at every connected
broker, reporting each broker's result (a broker that fails is named, the switch stays on). `unkill` releases it.

### Ledger (`orders/ledger.py`)
Every event is a `kind = "order"` entry of the same hash-chained audit ledger the AI uses (`ai_ledger`): confirm_issued, refused,
submitted, accepted, failed, cancel, replace, kill_on, kill_off, kill_cancel_all, live_on, live_off, mandate_changed, import_fills.
`GET /api/orders/ledger` returns them newest first with the result of walking the whole chain; changing or removing an entry breaks it.

### Routes (`orders/routes.py`)
`GET /status`, `GET /blotter?broker=`, `GET /ledger`, `POST /preview`, `POST /submit`, `POST /cancel`, `POST /kill`, `POST /unkill`,
`PUT /mandate`, `PUT /live`, `POST /import`. Migration 18 adds `orders_log` (daily cap) and `orders_imported` (fills already added to a
portfolio, keyed by broker and fill id).

### Fills into PORT
`POST /api/orders/import {broker, portfolio}` adds today's broker fills as lots, once each. Lots carry `source`: `paper` (Alpaca paper,
so paper fills go to a portfolio of their own, for example `PAPER`), `alpaca` (Alpaca live) or `kite-orders` (Kite). The step 2 sync only
replaces lots tagged `kite` or `ibkr`, so a re-sync never deletes an order fill. Where a fill merges into an existing position, the lot
average-cost rule of `PORT` applies and the merged position becomes a manual lot, which sync never touches either.

### Frontend (`functions/ORD.tsx`, `ordModel.ts`, `net/ordersApi.ts`)
A banner shows PAPER PLAY MONEY (green) or LIVE REAL MONEY (red, heavy) for the selected broker; after a review it shows the mode the server
reported. The ticket has broker, side, symbol, quantity, type, price and time in force. Confirm is two steps: Enter reviews (mandate check
lines plus the token and its remaining seconds); a paper order is sent with `Y`, a live order needs the symbol typed again. Any change to the
ticket voids the review. Below: the blotter (account, open orders, fills, positions; a part that fails shows its error, the rest still
shows), the order ledger with its chain verification, and the kill switch (`X`), release (`U`), live toggle (`L`), mandate editor (`M`).

### Not verified without accounts
Alpaca and Kite response shapes come from their documentation (fixtures say so). Not exercised against a real account: Alpaca partial
fills and `PATCH` replace, Kite AMO and trigger-pending states, Kite product choice for derivatives. Nothing was ever sent to a broker.

## Step 2: read-only broker sync (`SYNC`)
Already merged; see `backend/openterm/brokers/` and `docs/COMMANDS.md`.
- Reads Zerodha Kite holdings (and optionally net day positions) and Interactive Brokers positions through the Client Portal Gateway,
  and writes them as lots of a `PORT` portfolio. It never sends an order; Alpaca belongs to step 1.
- The IBKR gateway is local: only `localhost`, `127.0.0.1` and `::1` are accepted as its URL (its certificate is self-signed), and the
  routes answer loopback clients only.
- A synced lot carries `source` (`kite` or `ibkr`) and `synced_at`. A re-sync replaces only the lots of that source, never duplicates, and
  never touches manual lots or lots of any other source (including `paper`, `alpaca`, `kite-orders` from step 1). A synced symbol that is
  already held by another lot is reported as a CONFLICT instead of merged.
- `SYNC` panel: last sync with age, counts, difference against the previous sync, last error; keys `K`, `I`, `S`, `R`.
