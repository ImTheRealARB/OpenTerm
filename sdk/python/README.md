# openterm-sdk

A small, read-only Python client for an OpenTerm backend running on your own machine. Quotes, bars, fundamentals, news,
search, saved portfolios and stored backtest results come back as pandas DataFrames that keep **where the data came from and
when** in `df.attrs`. Dependencies: `httpx` and `pandas`. No orders, no writes, no API keys (keys stay inside OpenTerm).

Full guide: [docs/SDK.md](../../docs/SDK.md).

## Install

```
pip install ./sdk/python          # from a checkout of this repo
```

Start OpenTerm first (the desktop app, or `openterm`); the default address is `http://127.0.0.1:8000`.

## Examples

```python
from openterm_sdk import OpenTerm, OpenTermError, KeyRequired

ot = OpenTerm()                                   # or OpenTerm("http://127.0.0.1:8123")

bars = ot.history("AAPL", "1Y", "1d")             # DataFrame indexed by UTC time: open high low close volume
bars.attrs["source"], bars.attrs["as_of_iso"], bars.attrs["stale"]

q = ot.quote(["AAPL", "MSFT"])                    # one row per symbol, each with its own source / as_of / stale
q.attrs["errors"]                                 # symbols that failed, with OpenTerm's message

# Pin ONE source. If it cannot answer you get an exception, never another source's data.
try:
    ot.history("AAPL", "5Y", source="nasdaq")
except KeyRequired as e:
    print(e.key)                                  # e.g. the name of the key to set in OpenTerm's APIKEYS
except OpenTermError as e:
    print(e)                                      # "SRC=NASDAQ: PROVIDER DOWN" ...

ot.fundamentals("AAPL", "A", "IS")                # income statement: rows = items, columns = period ends
ot.news("AAPL", limit=20)
ot.search("tesla")
ot.portfolio("main")                              # saved positions, read only
run = ot.backtest(ot.backtests()["id"].iloc[0])   # stored run: run.metrics, run.equity, run.trades
```

`OpenTerm(source="yahoo")` pins every call by default; a per-call `source=` overrides it. `ot.sources()` lists the valid names.

## What is in `df.attrs`

`source`, `as_of` (epoch seconds when OpenTerm fetched the data), `as_of_iso`, `age_s`, `stale`, `fallback_from` (sources that
were tried first and failed; always empty when pinned). `history` adds `symbol range interval currency exchange tz`; `quote`
adds `errors`; `fundamentals` adds `statement period labels units derived`. Portfolios are local data: `name base updated_at`.

## Errors and stale data

Every error is an `OpenTermError` carrying the server's own words: `KeyRequired` (`.key`), `ProviderDown`, `NoData`,
`BadRequest`, `LoginRequired`, `BackendDown`. Nothing is ever made up: a missing value stays `NaN`/`None`.
OpenTerm serves a stale cached answer instantly while it refreshes; the SDK returns it with `attrs["stale"] = True`.
`OpenTerm(raise_on_stale=True)` raises `StaleData` instead.

## Tests

```
cd sdk/python && uv run --with pytest --with pandas --with httpx pytest -q
```

They use `httpx.MockTransport`; no network and no running server. Payloads are labelled TEST DATA, NOT A RECORDING.
