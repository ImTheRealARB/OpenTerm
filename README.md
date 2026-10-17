# OpenTerm

A keyboard-first, open-source market terminal for one power user: a command line on top, tiled panels,
mnemonic function codes, and free data sources. Dense, dark, amber on black. Speed over looks.

> Status: **Phase 1 of 10** (shell, command system, workspace keys, perf instrumentation). No market data yet.
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

`HELP` lists every function and the phase it ships in. Ready now: `HELP`, `PERF`, `SHORTCUTS`.

## Shortcuts

Defined in [`frontend/src/keys/keybindings.json`](frontend/src/keys/keybindings.json) and listed by `SHORTCUTS` or `?`.
Panels: `Alt+1..9` focus · `Tab` cycle · `Ctrl+\` / `Ctrl+-` split · `Alt+W` close · `Ctrl+Shift+Arrows` resize ·
`Ctrl+Shift+F` maximize · `Ctrl+[` / `Ctrl+]` history · `Ctrl+Shift+P` PERF HUD.

## Performance

Budgets are enforced in CI by `node scripts/bench.mjs`. See [docs/PERFORMANCE.md](docs/PERFORMANCE.md).

## Docs

- [Adding a function](docs/ADDING_A_FUNCTION.md)
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
