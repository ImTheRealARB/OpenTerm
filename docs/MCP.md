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

(This section is about OpenTerm as an MCP *server*. The client side below has its own refusal rule.)

There are no order, broker or account-balance tools in this server, and none will be added. A test
(`backend/tests/test_phase17_mcp.py`) scans the tool list and the `openterm/mcp` source for order, GTT, margin, holdings
and Kite words and fails if any appear.

# OpenTerm as an MCP client (third-party servers)

OpenTerm can also call tools offered by other MCP servers, for example NSE India data. This is optional, off by default, and
nothing is installed or started until you enable a server. Manage it in the `MCP` panel (or the commands below).

## Config file

`<data dir>/mcp_servers.yaml` (the folder that holds `openterm.db`; the panel shows the exact path). The file may hold secrets
(`env`, `headers`): keep it private (OpenTerm writes it owner-only on systems that support that). Editing it by hand takes effect at once.

```yaml
servers:
  my-tools:                       # 1-32 characters: a-z, 0-9, -
    command: npx                  # stdio: a program to start ...
    args: [-y, some-package, mcp]
    env: {SOME_KEY: value}        # given to that program only; OpenTerm's own environment and API keys are NOT passed on
    enabled: false                # OFF until you set true (or press E in MCP)
    allow: [tool_a, tool_b]       # per-tool allow-list; a tool not listed is never offered to the AI
    timeout_s: 30                 # per call, 1-300
  remote-tools:
    url: https://host.example/mcp # Streamable HTTP (give exactly one of command or url)
    headers: {Authorization: Bearer ...}
```

The command that is started comes only from this file. It is never taken from a request, from the AI, or from a tool result.

## Presets (shipped disabled, not bundled)

| Name | Runs | Source | Notes |
|---|---|---|---|
| `stock-nse-india` | `npx -y stock-nse-india mcp` (needs Node.js) | github.com/hi-imcodeman/stock-nse-india, MIT, about 30 tools | NSE India equities, indices, option chains |
| `nse-mcp` | `uvx nse-mcp` (needs uv) | github.com/jugaad-py/nse-mcp, built on jugaad-data, about 24 tools | NSE India market data |

Both are unofficial community projects, not affiliated with or endorsed by NSE. OpenTerm does not ship their code: `npx` or `uvx`
fetches it from npm or PyPI on this machine the first time the server is used, runs it with your permissions, and the package is
not pinned (pin a version in `args` if you want one). Their data terms are the source's, and NSE data may be delayed, rate-limited
or stop working without notice. Enabling a preset in `MCP` shows this notice and needs a second press (`MCP ENABLE <name> YES`);
the preset then allows a short read-only list of tools; change it in the tool list. See `THIRD_PARTY.md`.

## Safety model

- Every server is off until enabled. Nothing is started for a server that is off, and a server that is on is started only when used and stopped when idle or on exit.
- Per-tool allow-list: only listed tools reach the AI and SWARM, named `<server>.<tool>` (SWARM roles opt in with the `external` tool entry).
- Any tool whose name or description looks like order placement is refused: it cannot be allowed, listed for the AI, or called from `MCP`. The AI never places orders.
- Results are third-party data: wrapped and labelled `THIRD-PARTY MCP: <server>`, truncated, and the AI is told to treat them as untrusted data, never as instructions. They never count as grounding (the same rule as web text in docs/AI_WEB.md): an answer that rests only on a third-party tool is not labelled GROUNDED. Keys named in `env` or `headers` are removed from results and errors.
- Every AI call of a third-party tool is in the `AUDIT` ledger (`<server>.<tool>`, argument hashes), and so are manual calls.
- A server that hangs or crashes ends the call with an error after its timeout, and is restarted on the next call.
- The management routes (`/api/mcpc/...`) answer only to programs on this machine.

## Commands

`MCP` lists servers; `MCP ENABLE <server> [YES]`, `MCP DISABLE <server>`, `MCP TEST <server>` (starts it and lists its tools),
`MCP ALLOW <server> <tool>`, `MCP DENY <server> <tool>`. Keys: Up/Down select, `E` enable (twice), `D` disable, `Enter`/`T` test and list tools,
then `Space` toggles a tool, `Esc` goes back.
