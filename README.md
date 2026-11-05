<div align="center">

<img src="frontend/public/logo.svg" alt="OpenTerm logo: a terminal window with the letters OT and a command prompt" width="140">

# OpenTerm

**A free, fast market terminal that runs on your own computer.**<br>
Quotes, charts, company filings, macro data and backtests, one command away. No account, no subscription.

[![License: MIT](https://img.shields.io/badge/license-MIT-FFB000?style=flat-square&labelColor=000000)](LICENSE)
[![Benchmarks: 37 of 37 within budget](https://img.shields.io/badge/benchmarks-37%2F37_in_budget-FFB000?style=flat-square&labelColor=000000)](docs/PERFORMANCE.md)
[![Works with zero API keys](https://img.shields.io/badge/API_keys-none_needed-FFB000?style=flat-square&labelColor=000000)](#api-keys-optional)

[Install](#install) ·
[First five minutes](#your-first-five-minutes) ·
[What it can do](#what-it-can-do) ·
[Speed](#built-to-be-fast) ·
[Docs](#docs)

<br>

<img src="docs/screenshots/workspace.png" alt="OpenTerm: a quote monitor, a live chart and top news side by side" width="100%">

</div>

## What is OpenTerm?

Trading desks work on market terminals, which are programs that put live prices, charts, company accounts, news and
economic data behind one command line. They are fast and very complete, but they are also expensive, and they are built
for people who already know the codes.

OpenTerm is an open source terminal of the same kind. It runs on free public data, it lives on your own computer, and
it has two faces, viz. a **GUI mode** with menus and plain-English buttons for someone opening a terminal for the first
time, and a **Terminal mode** with only the command line for someone who wants speed.

> **Explainer:** a *function* is a short code for one screen. `GP` is the price graph, `DES` the company description,
> `FA` the financial statements. You type a company and a function, `AAPL GP`, and the screen opens. Think of it like
> the speed-dial on a phone: you can always scroll through the contacts, but the number is faster once you know it.

You do not have to learn a single code to start, though. Typing `apple stock price past 5 years` works too, and
OpenTerm shows the code it understood (`AAPL GP 5Y`), so you pick the codes up as you go.

**So OpenTerm is a terminal you can use on the first day without a manual, and keep using once you outgrow the manual.**

> **Not investment advice.** The data comes from free public sources, which can be delayed, incomplete or wrong, and
> can change or block access at any time. Backtests are historical simulations, not forecasts. OpenTerm does not place
> orders or connect to a broker, and it is not affiliated with any commercial terminal vendor.

## Install

You need two free tools, **uv** (it installs and runs the Python half, and downloads the right Python by itself) and
**Node.js 20 or newer** (it builds the screen). **Git** is optional. The finished install is about 330 MB.

<details open>
<summary><b>Windows</b> (PowerShell)</summary>

```powershell
winget install --id astral-sh.uv -e
winget install --id OpenJS.NodeJS.LTS -e
winget install --id Git.Git -e
```

Close PowerShell, open it again, then:

```powershell
git clone https://github.com/ImTheRealARB/OpenTerm.git
cd OpenTerm
.\scripts\setup.ps1
.\scripts\start.ps1
```

If Windows says "running scripts is disabled", run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once and try again.

</details>

<details>
<summary><b>macOS</b> (Terminal, with <a href="https://brew.sh">Homebrew</a>)</summary>

```sh
brew install uv node git
git clone https://github.com/ImTheRealARB/OpenTerm.git
cd OpenTerm
./scripts/setup
./scripts/start
```

</details>

<details>
<summary><b>Linux</b></summary>

Install `git`, `curl` and Node.js 20 or newer with your package manager (on Debian and Ubuntu the packaged Node is often
too old, so use [nvm](https://github.com/nvm-sh/nvm): `nvm install --lts`). Then:

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
git clone https://github.com/ImTheRealARB/OpenTerm.git
cd OpenTerm
./scripts/setup
./scripts/start
```

On a computer with no desktop, use `./scripts/start --no-browser` and open the address from another machine.

</details>

Your browser opens at **http://localhost:8000**. Leave the terminal window open while you use OpenTerm, and press
`Ctrl+C` there to stop it. No Git? Click **Code**, then **Download ZIP** on the
[repository page](https://github.com/ImTheRealARB/OpenTerm), unzip it (on Windows, tick **Unblock** in the ZIP's
Properties first) and run the same `setup` and `start` lines inside the folder.

One must keep in mind that OpenTerm is developed and tested on Windows. The macOS and Linux scripts are short and plain,
but they have not been run on those systems yet, so please [open an issue](https://github.com/ImTheRealARB/OpenTerm/issues)
with the error text if anything breaks.

**Updating:** run `git pull`, then start the app as usual. The start script rebuilds the screen and refreshes packages
when the code changed. `.\scripts\install-launcher.ps1` (or `./scripts/install-launcher`) adds an `openterm` command
that starts the app from any terminal.

## Your first five minutes

The first time you open OpenTerm it starts in **GUI mode**, on a ready-made screen with a list of large US stocks, a
chart and the top news.

<img src="docs/screenshots/gui-search.png" alt="GUI mode: the command line understands company names and plain English" width="100%">

- **Type what you want in the command line at the top**, in plain English or as a code, and press `Enter` (or click `GO`).
- **Or browse.** The menu bar and the sidebar list every screen by what it does, with its code next to it.
- **Every panel says what it is** in its title bar, and its toolbar shows what you can do, with the key for each button.
- **Hover a term** such as P/E or EPS for a one-line explanation, and click `?` on any panel for its help.
- **Errors tell you the next step**, e.g. Retry or "Try AAPL", instead of a blank panel.

Some things to type:

| Type | You get |
|---|---|
| `apple stock price past 5 years` | Apple's price chart over five years (`AAPL GP 5Y`) |
| `tesla news` | Tesla headlines (`TSLA N`) |
| `apple vs microsoft since 2021` | Both on one chart |
| `nifty 50`, `reliance share price`, `bitcoin 1 year`, `gold price` | Indian indices and NSE shares, crypto, commodities |
| `amazon balance sheet` | The balance sheet from SEC filings (`AMZN FA BS`) |
| `tech stocks under 50 dollars` | A stock screen (`EQS`) |
| `AAPL DES` | Apple's description, valuation and 52-week range |
| `WEI` | World stock indices, live |
| `BT AAPL SMA20>SMA50 1D 5Y` | A backtest of a moving-average crossover |
| `HELP` | Every function. `HELP GP` explains one |

Plain English is read by a small set of rules on your computer, not by an AI, so it is instant and free. When a name
fits several companies it asks "did you mean", and exact codes such as `AAPL GP` always run as typed.

**Terminal mode** is the same app with only the command line. Switch with `Alt+G` or from the **Settings** menu.
`Shift+Enter` opens a result in a new panel, `Tab` moves between panels, and `LAYOUT SAVE MYDESK` saves your screen.
[docs/COMMANDS.md](docs/COMMANDS.md) has many more commands to try.

## What it can do

| | |
|---|---|
| **Charts and quotes** | Seven chart types, 109 indicators (`IND`) including your own formulas, drawings, event markers, comparisons and price alerts. Live boards for stocks, indices, currencies, commodities and crypto. |
| **Companies** | Profile, financial statements and filings from SEC EDGAR, insider trades, holders, estimates, peers and a DCF valuation. |
| **Screening** | The whole US stock universe, peer comparison, correlation, a sector heat map and seasonality. |
| **Macro** | FRED series, the Treasury yield curve, earnings and economic calendars, central banks and world statistics. |
| **India** | NSE and BSE shares, indices, futures and options, MCX and currency futures. Free Yahoo data by default; with a paid [Zerodha Kite Connect](https://kite.trade/) app, real-time quotes, minute bars back to 2015 and option chains. Read-only. |
| **Derivatives and crypto** | Option chains and pricing, implied volatility, futures, order books, funding rates, DeFi yields. |
| **World and trade** | A world map with ships, ports, chokepoints and earthquakes (`MAP`), shipping and port activity, trade flows, US and UK official data. |
| **Portfolio and backtesting** | Positions with live profit and loss, CSV import. Backtests with fees, slippage, Monte Carlo and walk-forward checks, built as a sentence or written in Python (`BT EDIT`). |
| **Risk, quant and AI** | Value at Risk, portfolio optimisation, factor analysis. Optional AI answers that show which data they used, and an MCP server for Claude and other assistants (read-only, never orders). |

Every function is listed in [docs/FUNCTIONS.md](docs/FUNCTIONS.md).

<img src="docs/screenshots/chart.png" alt="GP: a daily candlestick chart with two moving averages and an RSI pane" width="100%">

<img src="docs/screenshots/fundamentals.png" alt="DES and FA: a company profile next to its income statement" width="100%">

## Built to be fast

Speed is treated like a feature with a budget. Every number below must pass the project's own benchmark
(`node scripts/bench.mjs`) before a change is accepted. Latest run, on a Windows PC on the 5th of November 2026, 37 of 37
within budget ([full record](docs/PERFORMANCE.md)):

| What you do | Result | Budget |
|---|---|---|
| Open the app to a usable command line | about 95 ms | 1,500 ms |
| Press a key, see it on screen | about 15 ms | 16.7 ms |
| Run a cached command, see the panel | about 18 ms | 100 ms |
| A live price arrives, the pixel changes (4,000 ticks a second, 9 panels) | about 37 ms | 50 ms |
| Scroll a 10,000-row table / pan a 50,000-candle chart | 16.7 ms a frame | 20 ms |
| Backtest 10 years of daily bars | about 0.28 s | 0.3 s |
| App download size (compressed) | about 120 KB | 400 KB |

The trick is mostly restraint. There are no animations, shadows or web fonts, tables and charts are drawn on a canvas
instead of thousands of page elements, live prices are batched into one repaint per frame, and heavy maths runs in
separate processes so it never blocks typing.

## Honest about the data

OpenTerm runs on free public sources (Yahoo Finance, Nasdaq, SEC EDGAR, FRED, the US Treasury, Binance and others),
which are meant for personal use and change without notice. So every value carries its **source and age**, and when a
source fails the panel says `STALE`, `ERR` or `PROVIDER DOWN` instead of showing an invented number. When one source
fails the next one in a fixed order answers, and the panel says which one did. Test data is always labelled on screen.
Read [docs/DATA_LIMITS.md](docs/DATA_LIMITS.md) before relying on anything, and please respect each source's terms.

## API keys (optional)

Everything works with **zero keys**, and a key only unlocks more. Paste keys into the `APIKEYS` panel, which also links
to each sign-up page. Keys are stored in your computer's secure store, never typed on the command line and never sent
anywhere except their own provider.

| Key | What it adds |
|---|---|
| Finnhub, FMP, Alpaca | Estimates, recommendations, IPOs, real-time US quotes and news |
| FRED, EIA, BLS, BEA, Census | Series titles and search, energy, US jobs, prices, GDP and trade |
| Kite Connect (paid) | The first source for Indian markets; the login lasts one trading day, then Yahoo takes over |
| UN Comtrade, Companies House, Etherscan, AISstream, Marketaux | Trade flows, UK companies, Ethereum, live ships, news sentiment (all free) |
| An AI provider (OpenRouter, Anthropic, OpenAI and others) | The optional AI panels, billed by that provider |
| Telegram, email or a webhook | Alerts and a daily brief sent to you (off by default) |

For `FA`, `FIL` and `OWN`, the SEC asks every program to say who is calling: set
`SEC_USER_AGENT="Your Name you@example.com"` in the `.env` file that setup created, then restart.

## If something goes wrong

| Problem | Try this |
|---|---|
| `uv` or `node` is "not recognised" | Close and reopen the terminal after installing |
| "Port 8000 is in use" | Close the other OpenTerm window, or start with `OPENTERM_PORT=8001` |
| A panel says `STALE`, `ERR` or `PROVIDER DOWN` | A free source is down or rate limiting you. `SOURCES` shows which one; wait and press `F5` |
| The screen looks old after `git pull` | `.\scripts\start.ps1 -Rebuild` (Windows) or `./scripts/start --rebuild` |
| You want a demo with no internet | Start with `OPENTERM_FIXTURES=1`: recorded data, clearly labelled |

## For developers

```sh
./scripts/setup --dev       # adds test tools and Chromium (about 1.5 GB more); Windows: .\scripts\setup.ps1 -Dev
./scripts/dev               # backend on :8000 and Vite with hot reload on http://localhost:5173
node scripts/gates.mjs      # every check: ruff, tsc, pytest, vitest, Playwright
node scripts/bench.mjs      # the performance budgets
python scripts/new_function.py FOO --title "..."    # scaffold a new function
```

`backend/` is Python 3.12 and FastAPI, `frontend/` is React and TypeScript with canvas grids and charts, `scripts/`
holds setup, start, benchmarks and recorders. Tests never touch the network: they replay recorded responses.

### Docs

- [Every function, key and feature](docs/FUNCTIONS.md) · [Commands to try](docs/COMMANDS.md) · [Data sources](docs/DATA_SOURCES.md) · [Data limits](docs/DATA_LIMITS.md)
- [Performance](docs/PERFORMANCE.md) · [Adding a function](docs/ADDING_A_FUNCTION.md) · [Adding a provider](docs/ADDING_A_PROVIDER.md) · [MCP server](docs/MCP.md)
- [Release notes](docs/RELEASE_NOTES.md) · [Changelog](CHANGELOG.md) · [Third-party code and licences](THIRD_PARTY.md)

## Credits and licence

MIT, see [LICENSE](LICENSE). Charts use [TradingView Lightweight Charts™](https://www.tradingview.com/lightweight-charts/)
(Apache-2.0, copyright © TradingView, Inc.). The backtest engine and quant library include code ported from
[Vibe-Trading](https://github.com/HKUDS/Vibe-Trading) (MIT); every ported file is listed in [THIRD_PARTY.md](THIRD_PARTY.md).
