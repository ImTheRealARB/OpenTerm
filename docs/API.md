# OpenTerm REST API

OpenTerm is a normal web server (FastAPI) on your own machine. Everything the screen shows comes from the same
routes you can call yourself, so you can pull data into Excel, a Python script or an AI app.

Rules that always hold:

- The server listens on `127.0.0.1:8000` (loopback). Only programs on your own computer can reach it. Do not expose it to the internet.
- No key is needed to call the API itself. A route whose data source needs a key answers `KEY REQUIRED: set X in APIKEYS`.
- Every answer carries its source and age. A failure is shown as `STALE`, `ERR` or `PROVIDER DOWN`, never as made-up data.
- There are no order or trading routes. The API reads data and runs historical backtests.
- Keys are never returned by any route.
- A request that changes something (POST, PUT, PATCH, DELETE) with a JSON body must send `Content-Type: application/json`, or it gets a 400.
  If it carries an `Origin` header (browsers add one), the origin must be this machine (`localhost`, `127.0.0.1` or `[::1]`), or it gets a 403.
  Scripts, curl and Excel send no `Origin`, so they only need the content type. This stops other web pages in your browser from driving OpenTerm.

Start OpenTerm first (`openterm`, or `.\scripts\start.ps1`). Then open **http://127.0.0.1:8000/docs** for the interactive
OpenAPI page (a web page that lists every route with its parameters and lets you try it). The raw schema is at `/openapi.json`.

## The routes the MCP server wraps

The [MCP server](MCP.md) (how AI apps call OpenTerm) is a thin layer over these routes. `openterm-mcp` (or
`python -m openterm.mcp`) forwards MCP messages to the running app; `POST /mcp` is the same thing over HTTP.
Add it to Claude Code with `claude mcp add --transport http openterm http://127.0.0.1:8000/mcp`.

| MCP tool | Route | Main parameters |
|---|---|---|
| quote | `GET /api/quote` | `symbols=AAPL,MSFT` (comma separated) |
| history | `GET /api/history` | `symbol`, `range` (1M, 1Y ...), `interval` |
| indicators | `GET /api/history` | `symbol`, `range` (indicators are computed from the bars) |
| profile | `GET /api/profile` | `symbol` |
| fa | `GET /api/fa` | `symbol`, `period=A` (annual) or `Q` |
| filings | `GET /api/filings` | `symbol`, optional `form` (needs `SEC_USER_AGENT`) |
| news | `GET /api/news` | `symbol` or `q` (text query) |
| screener | `GET /api/screener` | whole US universe as one columnar payload |
| research (ee, eeo, anr, ...) | `GET /api/research/{fn}` | `symbol` |
| etf | `GET /api/research/etf` | `symbol` |
| options_chain | `GET /api/deriv/omon` | `symbol`, `exp` |
| option_price | `GET /api/deriv/ov` | `symbol`, `k`, `type`, `exp`, `iv` |
| option_payoff | `GET /api/deriv/osa` | `symbol`, `legs` or `strat`, `exp`, `iv` |
| rates | `GET /api/rates`, `GET /api/rates/curve` | the curve takes `ccy` (USD, EUR, GBP, CAD, JPY) |
| macro | `GET /api/macro` | `q` (text search) |
| holders, insiders | `GET /api/holders`, `GET /api/insiders` | `symbol` |
| calendar | `GET /api/earnings`, `GET /api/eco` | `date` (earnings), economic events use `start` and `days` |
| pred | `GET /api/world/pred` | `q` |
| energy | `GET /api/world/nrg` | none |
| crypto_funding | `GET /api/world/fund` | `sym` |
| crypto_depth | `GET /api/world/cdep` | `pair` |
| portfolio | `GET /api/portfolios` | optional name |
| backtest_run | `POST /api/bt/run` | rule, symbols, range, fees (a historical simulation, not a forecast) |
| backtest_get | `GET /api/bt/runs/{run_id}` | the stored run |

`/api/history` returns bars as columns (`data.t`, `data.o`, `data.h`, `data.l`, `data.c`, `data.v`), not a list of bar objects.

## CSV export

A backtest run exports as CSV (or JSON) from `GET /api/bt/runs/{run_id}/export?fmt=csv&part=trades`.
In the app, every table panel also exports with **Alt+X** (or the `E` key).

## Python (about 20 lines)

```python
import httpx  # pip install httpx

BASE = "http://127.0.0.1:8000"

def get(path: str, **params):
    r = httpx.get(BASE + path, params=params, timeout=30)
    r.raise_for_status()      # a 4xx/5xx means OpenTerm said no (read r.text: it explains why)
    return r.json()

quotes = get("/api/quote", symbols="AAPL,MSFT")["results"]
bars = get("/api/history", symbol="AAPL", range="1Y")
print(quotes)
print(len(bars["data"]["c"]), "daily closes")
```

Check the `source` and age fields in the answer before you rely on a number.

## Excel (Power Query)

Power Query is Excel's built-in data importer. In Excel: **Data > Get Data > From Other Sources > Blank Query**, open the
**Advanced Editor**, and paste:

```
let
    Source = Json.Document(Web.Contents("http://127.0.0.1:8000/api/quote?symbols=AAPL,MSFT")),
    Results = Source[results],
    Table = Table.FromList(Results, Splitter.SplitByNothing(), null, null, ExtraValues.Error)
in
    Table
```

Expand the column to see the fields. **Refresh All** pulls fresh numbers while OpenTerm is running.

## Not covered here

Kite (Indian broker data) has its own read-only routes under `/api/kite/*` and needs a login made today.
The AI desk routes (`/api/ai/*`) stream Server-Sent Events and spend model credits, so they are documented in the OpenAPI page only.
