# OpenTerm MCP server

MCP (Model Context Protocol) is an open standard that lets an AI app such as Claude Desktop or Claude Code call tools
that another program offers. OpenTerm offers its read-only market data tools, so you can ask Claude "what is AAPL
trading at, and what do its latest filings say?" and it answers from OpenTerm's data, with the source and age shown.

## Start it

1. Start OpenTerm: `openterm` (or `.\scripts\start.ps1`). The backend listens on `http://127.0.0.1:8000`.
2. Point a client at it, using one of the two transports below.

Only programs on your own machine can connect (loopback only), and a request from a web page on another site is refused
(Origin check). No key is needed for the MCP server itself; tools that need a data key say `KEY REQUIRED`.

## Claude Code (HTTP)

```
claude mcp add --transport http openterm http://127.0.0.1:8000/mcp
```

## Claude Desktop (stdio)

Claude Desktop starts a program and talks to it over stdin/stdout. `openterm-mcp` is a small bridge (a console command
installed with the backend; `python -m openterm.mcp` is the same program) that forwards to the running OpenTerm.
With `openterm-mcp`, add this to `claude_desktop_config.json` (replace `<repo>` with your OpenTerm folder;
in JSON a backslash is written twice):

```json
{
  "mcpServers": {
    "openterm": {
      "command": "uv",
      "args": ["--directory", "<repo>\\backend", "run", "openterm-mcp"]
    }
  }
}
```

The older form still works: `"args": ["--directory", "<repo>\\backend", "run", "python", "-m", "openterm.mcp"]`.

If OpenTerm is not running, every call answers `OPENTERM IS NOT RUNNING AT <url>: start it with openterm`.
Set `OPENTERM_URL` (default `http://127.0.0.1:8000`) if you run the backend elsewhere.

## Tools

The same tools the built-in AI agent uses (`backend/openterm/ai/tools.py`):

`skill`, `skills`, `strategy_check`, `quote`, `history`, `profile`, `fa`, `filings`, `news`, `screener`, `research`,
`options_chain`, `rates`, `macro`, `portfolio`, `backtest_run`, `backtest_get`, `quant`, and (Phase 20) twelve more
read-only desk tools: `indicators`, `option_price`, `option_payoff`, `etf`, `holders`, `insiders`, `calendar`, `pred`,
`energy`, `crypto_funding`, `crypto_depth`, `rigor`. That is 30 tools in all. The route behind each one is listed in
[API.md](API.md). `skills` searches the playbook library; `skill` reads one playbook, or one part of it with `section`.

- Every result starts with `[source=... age_s=... stale=... empty=...]` and also comes back as `structuredContent`, so
  you can see where the data came from and how old it is.
- `backtest_run` and `quant` start compute jobs: they are listed with `readOnlyHint: false` (they use CPU and save a run),
  but never change market or account data.
- A failed call returns `isError: true` with the reason, not a protocol error.

## No orders, ever

There are no order, broker or account-balance tools in this server, and none will be added. A test
(`backend/tests/test_phase17_mcp.py`) scans the tool list and the `openterm/mcp` source for order, GTT, margin, holdings
and Kite words and fails if any appear.
