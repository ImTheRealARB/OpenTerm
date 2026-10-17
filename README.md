# OpenTerm

A keyboard-first, open-source market terminal for one power user: a command line on top, tiled panels,
mnemonic function codes, and free data sources. Dense, dark, amber on black. Speed over looks.

> Status: **Phase 2 of 10**. Shell, command system, workspace keys and perf instrumentation (phase 1);
> data core with Yahoo + Nasdaq adapters, cache, rate limits, fallback and symbol search (phase 2).
> Charts, quotes and descriptions arrive in phase 3.
> Data may be delayed. Not investment advice.

## Quick start (zero API keys)

Requirements: [uv](https://docs.astral.sh/uv/) and Node 20+.

Windows (PowerShell):

```powershell
.\scripts\setup.ps1
.\scripts\dev.ps1
```

macOS/Linux:

```sh
./scripts/setup
./scripts/dev
```

Open http://localhost:5173. The backend runs on :8000.

## Command line

Focus it with `/`, `` ` ``, `Ctrl+K`, or just start typing.

```
[N:] <SECURITY> [MARKET] <FUNCTION> [ARGS]     AAPL GP 1Y D · RELIANCE IN DES · 2: MSFT DES
[N:] <FUNCTION> [ARGS]                         HELP GP · N · FRED GDP
```

- `Enter` runs in the focused panel. `Shift+Enter` runs in a new panel. `2:` targets panel 2.
- The security is sticky per panel: `GP` on a panel showing AAPL charts AAPL.
- `Tab` accepts a suggestion. `↑/↓` move through suggestions or history.
- Markets: `US`, `IN`/`NS` (.NS), `BO` (.BO), `LN`, `JP`, `HK`, `GR`, `CN`, `AU`. Explicit suffixes (`RELIANCE.NS`, `BTC-USD`) pass through.

## Functions

`HELP` lists every function and the phase it ships in. Ready now: `HELP`, `PERF`, `SHORTCUTS`,
`SOURCES` (provider health, latency, quota, key status), `LOG` (backend log).

Typing a ticker in the command line searches symbols live (`relian` → `RELIANCE.NS`). Highlighting a
result prefetches its quote and 1Y bars. Aliases: `SPX`, `NDX`, `NIFTY`, `SENSEX`, `EURUSD`, `BTCUSD` ...

## Data

Works with **zero API keys** (Yahoo Finance + Nasdaq.com public endpoints). Every value carries its
`source` and `as_of`; when a provider fails you see `STALE` or `PROVIDER DOWN`, never invented numbers.
Read [docs/DATA_LIMITS.md](docs/DATA_LIMITS.md) before relying on any of it: these are unofficial
endpoints for personal use, and they change.

API: `/api/quote?symbols=`, `/api/history?symbol=&range=&interval=`, `/api/search?q=`, `/api/sources`, `/api/log`.

## Shortcuts

Defined in [`frontend/src/keys/keybindings.json`](frontend/src/keys/keybindings.json) and listed by `SHORTCUTS` or `?`.
Panels: `Alt+1..9` focus · `Tab` cycle · `Ctrl+\` / `Ctrl+-` split · `Alt+W` close · `Ctrl+Shift+Arrows` resize ·
`Ctrl+Shift+F` maximize · `Ctrl+[` / `Ctrl+]` history · `Ctrl+Shift+P` PERF HUD.

## Performance

Budgets are enforced in CI by `node scripts/bench.mjs`. See [docs/PERFORMANCE.md](docs/PERFORMANCE.md).

## Docs

- [Adding a function](docs/ADDING_A_FUNCTION.md)
- [Adding a provider](docs/ADDING_A_PROVIDER.md)
- [Data limits](docs/DATA_LIMITS.md)

## Layout

```
backend/   FastAPI, orjson, async; /api/*, one multiplexed /ws
frontend/  React + TS + Vite; canvas for live grids/charts; plain CSS
scripts/   setup, dev, bench
docs/
```

## License

MIT. OpenTerm is not affiliated with any commercial terminal vendor.
