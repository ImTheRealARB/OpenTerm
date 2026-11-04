# Correctness audit (cloud, 2026-11-04)

Scope: `backend/openterm/` and `frontend/src/`, read-only. Skipped: items in `docs/review/DECISIONS_FOR_USER.md`, `docs/review/cloud/*.md`, ported Vibe files.
Method: pattern grep plus targeted reads (cache, service, router, hub, ws, userdata, portfolio, alerts, options pricer, AI agent/ground/spend, SEAS, quote rows).
Checked and found sound: `redact()` coverage on API error paths, SQL (all f-string SQL interpolates constant column lists), token bucket, router circuit breaker, `push_history` trimming, `add_lot` accounting, alert tick argument order (`alertMet(price, pct, change)` matches the row layout), socket heartbeat.
Counts: 0 high, 3 medium, 9 low. Ranked.

## Medium

### 1. SEAS buckets bars by the UTC calendar date, not the exchange date
`frontend/src/functions/seasMath.ts:108-135` (`monthKey`, `weekKey`/`isoWeek`, WEEKDAY and DOM branches use `getUTCDay/getUTCDate/getUTCMonth`), fed from `functions/SEAS.tsx:44-51` with no `tz`.
Yahoo daily bars are stamped at the exchange open. For `.AX` and `.NZ` symbols in daylight-saving months the open is 23:00 UTC of the previous calendar day (Sydney 10:00 AEDT). Every Monday bar then lands on Sunday: in WEEKDAY mode `b = 6 >= size 5` so all Monday returns are silently dropped, Tuesday is filed as Monday, and so on. In MONTH mode the first trading day of a month is counted in the previous month, so the period close is wrong. The result is plausible-looking, wrong numbers (never-fake-data). `functions/corrMath.ts:dayKey(t, tz)` already does this correctly, but SEAS ignores `b.tz`.
Test (vitest): bars for a `Australia/Sydney` series with timestamps at 23:00 UTC on Sun/Mon/Tue.. in January; `seasonality(t, c, "WEEKDAY")` must put them in Mon/Tue/Wed and keep `obs` equal to the count of bars minus 1. Fails today (Monday bars missing, `obs` too low). Fix: pass `tz` and bucket with `dayKey`.

### 2. A failed backend "trigger" report loses the alert delivery and is never retried
`frontend/src/command/alerts.ts:100-102` (`fire`), `:57-60` (`refreshAlerts` merge), `:136-140` (`fireNews`).
Alert evaluation is in the browser. When `api8.triggerAlert` rejects (backend restarting, 5xx, network blip) the code prints `FIRED BUT NOT SAVED` once, leaves the id in `firing` for ever, and keeps showing the alert as triggered locally. Nothing retries. Consequences: (a) email/Telegram/webhook delivery is started only by the backend trigger route (`delivery.spawn` on `changed: true`), so the user never receives the push they configured; (b) the backend still says `active`, so after a page reload the alert fires again (duplicate desktop notification); (c) if the user re-arms the alert in another tab, this tab still holds the id in `firing` and will never fire it again until reload. Same for news alerts (`newsFiring`).
Test (vitest with a mocked `api8`): make `triggerAlert` reject once, feed a matching tick, then advance the 60 s refresh timer; expect a second `triggerAlert` call. Currently it is called once only.

### 3. `bars_from_chart` labels the response with the requested interval, never Yahoo's real granularity
`backend/openterm/providers/yahoo.py:112-120` (`interval=interval`; `meta.dataGranularity` is ignored), consumed by SEAS (`SEAS.tsx:37`, `history(symbol, "MAX", "1d")`) and any GP/PERF user of `MAX`.
CLAUDE.md records that Yahoo `range=max` answers monthly bars. The request asks for `1d`, the adapter stamps `interval: "1d"` on the result, and the frontend cannot tell. SEAS WEEKDAY and DOM then compute "daily" returns from month-to-month closes, GP/PERF label monthly bars as daily, and the cache key `h:SYM:max:1d` serves it for the daily TTL. This breaks the "never fake data, state source and basis" rule without any error.
Test (pytest with a recorded chart body where `meta.dataGranularity == "1mo"` but the request was `max`/`1d`): `YahooProvider.history` must either raise `unsupported` / re-request with `20y`, or return `interval == "1mo"`. Today it returns `interval == "1d"`.

## Low

### 4. Watchlist and portfolio edits are read-modify-write across awaits (lost update)
`backend/openterm/userdata.py:157-170` (`edit_watchlist`: `_watchlist` read, then `_store`), `backend/openterm/portfolio.py:178-200` (`Portfolios.edit`: `_get`, then `_store`).
Two PATCHes for the same list in flight (a fast double `WL X ADD A` / `WL X ADD B`, or an import loop) both read the same `current`, and the second `_store` overwrites the first, losing one symbol or lot with a 200 on both. `Alerts.create`'s `COUNT(*)` then `INSERT` has the same shape (can exceed `MAX_ALERTS`).
Test (pytest, `asyncio.gather` of two `edit_watchlist("T", add=["A"])` / `add=["B"]` over the same DB with a patched `_watchlist` that yields before returning): the saved list must contain both. Fix: one `asyncio.Lock` per store, or a single `BEGIN IMMEDIATE` transaction.

### 5. `OSA` silently turns a typed `MULT=0` into 100
`backend/openterm/derivs/service.py:~317` `mult = pr.num(params, "mult") or 100.0`.
`or` treats the typed value `0.0` as missing, so the validation `mult <= 0` right after never sees it, and the INPUTS table then says `default: US equity contract size 100`. The user typed 0 and gets a result that looks like their input was accepted and defaulted. Same pattern for `comm` is harmless (0 is the default).
Test (pytest): `fn_osa("SPY", legs="+1C270@5", t="0.5", iv="20", r="4", mult="0")` must answer `bad_request`; today it answers OK with MULT 100.

### 6. OV barrier level and OSA strategy strikes are not range-checked
`backend/openterm/derivs/service.py` (`fn_ov`: `h = pr.num(params, "h")` accepted at 0 or negative), `backend/openterm/options/pricer.py:90-110` (`parse_strategy`: strikes only checked for order; `parse_legs` rejects `strike <= 0` but strategies do not; `float("nan")` and `inf` pass `float()`).
`OV ... H=0 BARR=UO` or `STRAT=STRADDLE,-5` reaches the pricer and either raises a non-`ParamError` (HTTP 500 with a stack-derived message) or prints a nonsense payoff table. Test (pytest): `parse_strategy("STRADDLE,-5")`, `parse_strategy("STRADDLE,nan")` and `fn_ov(..., h="0", barr="UO")` must raise `ParamError`/`bad_request`.

### 7. Nasdaq history adapter truncates MAX/20Y to 10 years and uses the machine's local date
`backend/openterm/providers/nasdaq.py:165-175` (`min(range_days(range_), 3653)`, `date.today()`).
As a fallback after Yahoo fails, a `MAX` or `20Y` request returns about 10 years of bars still tagged `range: "max"`. The caller cannot see the truncation. `todate` uses the local calendar date, so in time zones ahead of New York the last session can be requested a day early or late. Test (pytest with the fixture rows): `history("AAPL", "20y", "1d")` must raise `unsupported` or set a note/`range` that says 10Y.

### 8. LLM spend cap ignores prompt cost and parallel callers
`backend/openterm/llm/spend.py:24-28` (`check`: `spent + max_tokens * output_price` only), `:51-60`.
A call with a very large prompt on an expensive-input model can cost more than `max_tokens * output_price`, so a call is allowed that pushes the day over the cap. Two calls that overlap each pass `check` against the same `spent` and both run (the increment is atomic, the check is not). Impact is a cap overshoot, not a leak. Test (pytest): `check(spent=0.99, cap=1.0, max_tokens=1, price={"input": 100, "output": 1}, local=False)` with a 100k-token prompt should refuse; it returns `None` because the prompt size is not an argument.

### 9. `apply_tick` refreshes the price but can leave `change` / `change_pct` from the old snapshot
`backend/openterm/service.py:227-244`.
Each field is applied only when the tick carries it (`if v is not None`), but `price` is always written and the entry is re-stamped fresh. For ticks without change fields (poller or IEX ticks whose `prev` was missing, `streaming/iex.py:90-93`) a REST `/api/quote` now returns a new price with an old `%CHG`, labelled fresh and `as_of` now. Test (pytest): seed `q:AAPL` with `price 100, change 1, change_pct 1.0`, `apply_tick(Tick(price=110, change=None, change_pct=None))`, expect `change`/`change_pct` recomputed from `prev_close` or set to None.

### 10. `Cache.flush` drops the batch from its retry queue when the write fails
`backend/openterm/cache.py:108-120`. `rows, self._dirty = self._dirty, {}` happens before the `executemany`; on an exception the rows are gone from `_dirty` (the log line says "kept in memory only", but the LRU can evict them and nothing re-queues them). A transient `database is locked` loses cached envelopes silently, so the next start serves older data than the app showed. Test (pytest): make `db.executemany` raise once, call `flush()`, then call it again with a working DB and assert the rows reach SQLite. Fix: on failure merge `rows` back into `_dirty` (without overwriting newer keys).

### 11. OVDV smile builder is not guarded against a zero or missing strike / forward
`backend/openterm/derivs/service.py:~355-365` (`math.log(x["strike"] / F)` in `_equity_smiles`; same in `_crypto_smiles` with `e["forward"]`).
One chain row with `strike == 0` (seen in bad Yahoo rows) or a crypto expiry with a missing or zero forward makes the whole surface call raise `ZeroDivisionError` / `ValueError`, which becomes a 500 for every expiry instead of skipping the bad row. Test (pytest): a chain fixture with one strike of 0 must still produce points for the others.

### 12. Number formatting rounds across unit boundaries
`frontend/src/format.ts:30-37` (`fmtBig`), `:61-65` (`fmtAge`).
`fmtBig(999_950)` prints `1000.0K` (should be `1.00M`), `fmtBig(999_999_999)` prints `1000.00M`; `fmtAge(3599.6)` prints `60M`, `fmtAge(86399)` prints `24H`. Cosmetic but visible in volume and age columns. Test (vitest): those four inputs must produce `1.00M`, `1.00B`, `1H`, `1D`.

## Not confirmed (looked, left out)
- Hub `_sync_upstream` interleaving between two clients: ordering is preserved because `Yahoo.set_symbols` updates its state before its first await, so no stale set was found.
- `brief.py` prints trigger times in the server's local zone without a zone label and uses local `date.today()` for the eco start; harmless on a single-machine app, noted only.
