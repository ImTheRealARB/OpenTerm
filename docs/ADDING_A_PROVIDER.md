# Adding a data provider

Providers are adapters that map an upstream API into the normalized models in
`backend/openterm/models.py` (`Quote`, `Bars`, `SearchHit`). The router, cache, rate limiting,
fallback, health tracking and the SOURCES screen all work from the adapter's declarations.

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

2. Register it in `ADAPTERS` in `providers/__init__.py` (if it needs a key, read it from `Settings`
   and leave it out when the key is empty, so SOURCES shows `KEY REQUIRED`).
3. Add it to the fallback order in `config.yaml`.
4. Record real responses into `backend/tests/fixtures/` and write adapter tests against them
   (see `tests/test_adapters.py`). Tests never hit the network.

Rules:
- Use `self.get_json`: it applies the rate limiter (never waits more than 250 ms, so the router
  falls back instead of stalling the UI) and maps 404/429/5xx/timeouts to `ProviderError` kinds.
- Raise `not_found` for unknown symbols. It does not count against provider health. Everything else does.
- Never fill gaps with estimates. Missing fields stay `None`; the UI shows them as blank.
- Do not work around bot checks, captchas or terms of service.
