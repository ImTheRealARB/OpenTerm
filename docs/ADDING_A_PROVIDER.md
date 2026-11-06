# Adding a data provider

Providers are adapters that map an upstream API into the normalized models in
`backend/openterm/models.py` (`Quote`, `Bars`, `SearchHit`). The router, cache, rate limiting,
fallback, health tracking and the SOURCES screen all work from the adapter's declarations.

0. Decide where it ranks. The order sources answer in is one table, `providers/hierarchy.py` (best first: depth, freshness, rate limits;
   see [DATA_SOURCES.md](DATA_SOURCES.md)). Add a `Rank` there with the reasons; a test checks the entry is complete. If the source reaches
   back a limited number of days for minute candles, declare `intraday_days = {"5m": 60, ...}` on the adapter and raise
   `ProviderError("depth", ...)` when asked for more (the next source then answers, and no circuit-breaker strike is counted).

1. Create `backend/openterm/providers/foo.py`:

   ```python
   from .base import HISTORY, QUOTES, Provider, ProviderError

   class FooProvider(Provider):
       name = "foo"
       label = "Foo Data"
       capabilities = frozenset({QUOTES, HISTORY})
       markets = "US equities"                         # shown on SOURCES
       terms = "Free tier, 60 req/min, attribution required"
       rate = (1.0, 5)                                  # token bucket: req/s, burst

       def supports(self, capability, symbol=None):     # optional: narrow by symbol
           return capability in self.capabilities

       async def quotes(self, symbols):
           body = await self.get_json("https://api.foo.example/quote", {"s": ",".join(symbols)})
           return [Quote(symbol=..., price=..., source=self.source, as_of=self.now()) for ... in body]

       async def history(self, symbol, range_, interval):
           ...  # return Bars; raise ProviderError("unsupported") for intervals you can't serve

       async def probe(self):
           ...  # cheap liveness call; raise ProviderError on failure
   ```

2. Register it in `ADAPTERS` in `providers/__init__.py`. A provider that needs a key follows "Keyed providers" below.
3. Add it to the fallback order in `config.yaml`.
4. Record real responses into `backend/tests/fixtures/` and write adapter tests against them
   (see `tests/test_adapters.py`). Tests never hit the network.

Rules:
- Use `self.get_json` (or `self.get_bytes` for XML/text such as RSS): it applies the rate limiter
  (waits at most `max_wait`, 250 ms by default, so the router falls back instead of stalling the UI)
  and maps 404/429/5xx/timeouts to `ProviderError` kinds. Slow or one-slot-per-few-seconds sources
  raise the class attributes `timeout` (default 6 s) and `max_wait` (GDELT: 20 s and 6 s).
- Non-quote capabilities (`news_top`, `news_symbol`, `news_keyword`, `movers`, `crypto`) have their own
  fallback order in `DEFAULT_ORDER` in `backend/openterm/providers/hierarchy.py` (the one place every capability's
  order lives; `config.yaml` `providers:` is only for pinning an order by hand). Text fixtures are recorded as
  `{"status", "content_type", "text"}`; unrecorded paths on a new host must answer 404 in `fixtures.py` (add one
  `_route_<name>` checker that returns a response or `None` and list it in `ROUTE_TABLE`, newest first).
- A provider that needs an API key subclasses `KeyedProvider` (`providers/keyed.py`): it owns the key, `set_keys`,
  `supports` and the authenticated request, so the adapter only says where the key goes (header, query or basic auth).
- Raise `not_found` for unknown symbols. It does not count against provider health. Everything else does.
- Never fill gaps with estimates. Missing fields stay `None`; the UI shows them as blank.
- Do not work around bot checks, captchas or terms of service.

## Keyed providers (Phase 11)

Zero keys must still work; a key unlocks more. A keyed provider never fails the request just because its key is missing.

1. **Declare the key** in `KEY_SPECS` (`backend/openterm/keys.py`): `name`, env var `fields`, `phase`, `purpose`, `signup`
   URL, and `secret_fields` if only some fields are secret (SMTP host and port are not). Add the provider's cheapest
   authenticated call to `TESTS` (or `None`); `classify()` maps 401/403 to `INVALID`, 429 or a quota body to `QUOTA`.
   The key then appears in APIKEYS and in SOURCES automatically.
2. **Read the key from the store, at call time**: `app.state.keys.get("<name>")` returns the field dict or `None` (lookup
   order env > OS keyring > `.env`). Never cache it in `Settings` at startup: a key saved in APIKEYS must work without a
   restart (`app.state.on_key_change` is the hook for adapters built at startup; see the FRED case in `main.py`).
3. **No key: raise `ProviderError("key_required", ...)` before any network call** and set the class attribute
   `key_name = "<LABEL>"`. The router does not count it against health (no breaker strike), tries the next provider, and
   only answers HTTP 424 `{"error": "KEY REQUIRED", "key": "<LABEL>"}` when no keyless provider can serve the capability.
   The frontend shows the amber `KEY REQUIRED: set <LABEL> in APIKEYS` line (`KeyRequiredLine.tsx`); `Enter` opens APIKEYS.
4. **Never let the key escape.** Prefer headers to query strings. Every secret the store has seen is registered with
   `redact.py`, which masks it in log records (the `openterm`, `httpx` and `httpcore` loggers), `/api/log`, `/api/perf`,
   `/api/sources` and error details, plus common shapes (`token=`, `apikey=`, `Bearer ...`, `sk-...`). Run any new error
   text you build through `redact.redact()`. No endpoint returns a key value.
5. **Fixtures:** record a real 401 with a made-up key (no account needed) and, when you have a key, one real success.
   Without a key, a success body built from the provider's docs is allowed only if it is marked doc-shaped in the
   fixture and in `fixtures.py` (like `keytest_openrouter_ok` and Phase 7's FRED API files). Tests use
   `OPENTERM_KEYRING=memory` and a temp `OPENTERM_DOTENV_PATH`; the `client` fixture clears every `KEY_SPECS` env var.

A source that is a WebSocket rather than HTTP (AISstream, `providers/aisstream.py`) cannot use a `TESTS` row. Give the module an
async `check_key(values)` returning `(state, detail)`, call it from the `run_test` branch in `keys.py` (imported inside the branch so
the socket library stays off the startup path), and report "not tested" in fixture mode. Test the wire code against a real local
`websockets.serve` server (see `tests/test_aisstream.py`), not against mocks.

LLM providers are not data providers: they go through the gateway in `backend/openterm/llm/` (`Gateway.chat`), which adds
the price lookup and the daily spend cap. A new OpenAI-compatible host is one entry in `openai_compat.BASES` plus a
`KEY_SPECS` row; its prices go in `config.yaml` `llm.prices` (unknown price = refused while a cap is set).
