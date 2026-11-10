# Python SDK (`openterm-sdk`)

A small, read-only Python client for OpenTerm running on your own machine. It returns pandas DataFrames that remember where
the data came from and when. Source: `sdk/python/`. Dependencies: `httpx` and `pandas`.

It has **no order, trading or write capability** (it only issues HTTP GET), holds **no API keys** (keys stay in OpenTerm's
APIKEYS) and **never invents data**.

## Install

From a checkout of this repo (not published to PyPI):

```
pip install ./sdk/python
```

Start OpenTerm first (the desktop app or `openterm`); the default address is `http://127.0.0.1:8000`.

## Examples

```python
from openterm_sdk import OpenTerm, KeyRequired, OpenTermError

ot = OpenTerm()                                     # OpenTerm("http://127.0.0.1:8123") for another port

bars = ot.history("AAPL", "1Y", "1d")               # index: UTC time; open high low close volume (adj when known)
quotes = ot.quote(["AAPL", "MSFT"])                 # index: symbol; per-row source, as_of, age_s, stale
quotes.attrs["errors"]                              # {symbol: OpenTerm's message} for the ones that failed
ot.profile("AAPL")                                  # dict; provenance under ["_meta"]
ot.search("tesla"); ot.news("AAPL", limit=20)
ot.fundamentals("AAPL", period="Q", statement="BS") # US filers (SEC); rows = items, columns = period ends
ot.portfolios(); ot.portfolio("main")               # saved positions, as stored
runs = ot.backtests(); run = ot.backtest(runs["id"].iloc[0])   # run.metrics, run.equity, run.trades
ot.sources()                                        # valid source names, health, which keys are set
```

### Pinning a source

`source=` is the SDK's form of the `SRC=` command (see COMMANDS.md). Per call, or for the whole client with
`OpenTerm(source="nasdaq")`:

```python
try:
    df = ot.history("AAPL", "5Y", source="nasdaq")
except KeyRequired as e:      # the pinned source needs a key: e.key names it
    ...
except OpenTermError as e:    # "SRC=NASDAQ: PROVIDER DOWN", "... DOES NOT SERVE HISTORY", "... UNKNOWN SOURCE"
    print(e)
```

A pinned source answers alone. If it cannot, you get an exception, never another source's data. Without a pin OpenTerm uses
its normal source order (and your `SETTINGS SOURCE` preferences) and says in `fallback_from` which sources failed first.
`source=` applies to market data (quote, history, profile, search, news). `fundamentals` is SEC-only and portfolios and
backtests are your own local data, so the pin is not sent for them.

## What is in `df.attrs`

| field | meaning |
|---|---|
| `source` | the source that answered (`"mixed"` for a multi-symbol quote with several) |
| `as_of`, `as_of_iso` | when OpenTerm fetched it (epoch seconds, UTC ISO text); the oldest, for several rows |
| `age_s` | seconds since then |
| `stale` | true if OpenTerm served its stale cache while refreshing in the background |
| `fallback_from` | sources tried first and skipped (always empty when pinned) |
| `errors` | quote only: symbols that failed and why |

`history` adds `symbol range interval currency exchange tz`; `fundamentals` adds `statement period labels units derived`
(`derived` marks quarters computed from year-to-date values); `news` adds `kind failed_feeds`. Portfolios carry
`name base updated_at` (local data, no source).

## Errors and stale data

All errors subclass `OpenTermError` and carry the server's own text and `.kind` / `.status`: `KeyRequired` (`.key`),
`ProviderDown`, `NoData`, `BadRequest` (bad symbol, unknown source, a source that does not serve this), `LoginRequired`,
`BackendDown` (OpenTerm is not running). `.source` is set when the message names a pinned source.

A stale answer is returned with `attrs["stale"] = True`; check it before trusting a number. `OpenTerm(raise_on_stale=True)`
raises `StaleData` instead. A missing value stays `NaN` / `None`: nothing is filled or interpolated.

## Limits

- Needs a running local OpenTerm; it talks only to it (loopback), never to a data provider directly.
- Read only. Backtests are made in OpenTerm (`BT`); the SDK reads stored results. Orders do not exist in the SDK.
- Wraps the routes in API.md that exist today: quote, history, profile, search, news, fa, sources, portfolios, bt runs.
  Research, world and options routes are not wrapped yet.
- Data is only as good as OpenTerm's sources (see DATA_LIMITS.md); the SDK adds no data of its own.

## Tests

```
cd sdk/python && uv run --with pytest --with pandas --with httpx pytest -q
```

They use `httpx.MockTransport`: no network, no server. Payloads are TEST DATA, NOT A RECORDING.
