# Development

This page explains how to run OpenTerm from source, run the checks and add to it. To use OpenTerm, read the
[user guide](GUIDE.md) instead.

## Set up

Install the tools from the [README](../README.md#install), then install the test tools and Chromium. This adds about
1.5 GB.

```powershell
.\scripts\setup.ps1 -Dev       # macOS and Linux: ./scripts/setup --dev
```

## Run the development server

```powershell
.\scripts\dev.ps1              # macOS and Linux: ./scripts/dev
```

The backend runs on port 8000. Vite serves the screen with hot reload on http://localhost:5173.

Two environment variables give repeatable data with no network:

| Variable | Effect |
|---|---|
| `OPENTERM_FIXTURES=1` | Replays recorded responses from `backend/tests/fixtures/`. Each panel shows a label. |
| `OPENTERM_SYNTHETIC=1` | Adds the synthetic tickers `SYN0000` to `SYN9999` with a live price stream, for load tests. |

## Run the checks

| Command | What it checks |
|---|---|
| `node scripts/gates.mjs` | Everything: ruff, tsc, ESLint, pytest, vitest and Playwright. Ports 4173 and 8000 must be free. |
| `.\scripts\check.ps1` (`./scripts/check.sh`) | Only the tests that your changes affect, compared with `main`. Use it while you work. |
| `node scripts/bench.mjs` | The performance budgets. A change that breaks a budget is not done. |

Tests never use the network. They replay recorded responses from `backend/tests/fixtures/`. To test a new data
source, record a real response and add a route in `backend/openterm/providers/fixtures.py`.

## Add to OpenTerm

```powershell
python scripts/new_function.py FOO --title "What FOO shows"
```

This command creates a panel, a registry entry, a test stub and a line in [FUNCTIONS.md](FUNCTIONS.md). Then read:

- [Adding a function](ADDING_A_FUNCTION.md)
- [Adding a provider](ADDING_A_PROVIDER.md)
- [Extensions](EXTENSIONS.md)
- [Design rules](../DESIGN.md)

After you change the function registry or the key bindings, run `python scripts/gen_functions_doc.py`. A test fails
if FUNCTIONS.md is out of date. When you add a function, also add its line to the function list in
[GUIDE.md](GUIDE.md#every-function).

## Screenshots

`node scripts/screenshots.mjs` retakes the pictures in `docs/screenshots/`. The header of the script explains how to
start a separate server for it, so your own layouts stay as they are.

## Repository layout

```text
backend/     Python 3.12 + FastAPI: data providers, cache, streaming, backtests, quant jobs, AI layer
frontend/    React 19 + TypeScript + Vite: command line, panels, canvas grids and charts
scripts/     setup, start, dev server, benchmark, test gates, fixture recorders, screenshots
docs/        user and developer documentation
sdk/python/  openterm-sdk, a read-only Python client
notebooks/   example Jupyter notebooks for the SDK and the query language
examples/    a minimal extension to copy
desktop/     Tauri desktop shell (experimental)
deploy/      Caddy + Docker Compose to host your own copy
```
