# Extensions

An extension is Python code somebody wrote that adds something small and read-only to OpenTerm: a data source, a table or chart, or a tool the AI may read. This page is for people who write one and for people who think about turning one on.

## Read this first: what enabling means

**An enabled extension is third-party code running inside OpenTerm, with the permissions of the user who started it.** It can read that user's files, environment variables (including API keys in the environment) and network. OpenTerm limits what an extension can *register*, not what its Python can *do*. There is no sandbox. Enable only code you have read or trust from an author you know.

What OpenTerm does guarantee:

- **Off until enabled.** Finding an extension only reads its manifest (`extension.yaml` or package metadata). Its code is not imported until you type `EXT ENABLE <name>`. The choice is remembered in `<data dir>/extensions/enabled.json` and applied at the next start.
- **Enabling and disabling are for this machine only.** They are refused for any other machine and any other browser origin. In remote mode (see [HOSTING.md](HOSTING.md)) no request counts as local, so an extension can only be enabled from the machine itself.
- **Read-only by construction.** An extension can add: a data provider (ranked after every built-in source), AI tools named `ext.<name>.<tool>`, and `GET` routes under `/api/ext/<name>/`. It cannot add a route that changes anything, a broker, an order, or an account tool.
- **The order-word guard.** A tool or route whose name contains `order`, `margin`, `holding`, `broker`, `cancel` or `execut`, or whose description mentions orders, GTT, margins, holdings or kite, is refused and the whole extension fails to enable. This is the same rule the built-in tools pass (`tests/test_phase17_mcp.py`). The AI never places orders, and an extension cannot give it a way to.
- **Isolation.** A bad manifest, an import error, `register()` raising, a route or tool raising, or a route taking more than 10 seconds is caught, logged, shown as `ERR` in `EXT LIST`, and does not stop OpenTerm or any other extension. A failed enable is not remembered. Registration is all-or-nothing: an extension that fails halfway leaves nothing behind.
- **Prefixes you cannot escape.** Routes live under `/api/ext/<name>/`, tools are `ext.<name>.<tool>`; the manifest name equals the folder name and may only use lowercase letters, digits, `_` and `-`.
- **Results are capped and labelled.** A tool result is cut at 6,000 characters like every tool, and an extension's data is always labelled `ext:<name>` as its source. It is never presented as a built-in source.
- **AI and MCP.** An extension tool is offered to an outside MCP client under its full name; it is not offered in the plain AI chat. In remote mode MCP is off.

## Where extensions come from

1. **A folder:** `<data dir>/extensions/<name>/` containing `extension.yaml` and the entry file (`extension.py` unless the manifest says otherwise). The data dir is the folder that holds `openterm.db` (`data/` when you run from source, `/data` in Docker).
2. **An installed Python package** that declares an entry point in the group `openterm.extensions` and ships the same manifest. If a folder and a package share a name, the folder wins.

## The manifest

```yaml
name: hello          # equals the folder name; lowercase letters, digits, _ and -; at most 32
version: 0.1.0
author: Ada Lovelace
license: MIT
description: One sentence.
adds: [route, tools]   # any of: provider, tools, route
entry: extension.py    # optional
```

`name`, `version`, `author` and `license` are required. They are shown in `EXT LIST` so you can see who wrote what you are about to enable.

## Writing one

The entry file defines `register(api)`:

```python
def table(args: list[str]) -> dict:            # a route handler: strings in, a payload out (sync or async)
    return {"kind": "table", "title": "MY TABLE",
            "columns": [{"key": "a", "title": "A"}, {"key": "n", "title": "N", "kind": "num"}],
            "rows": [{"a": "x", "n": 1.5}, {"a": "y", "n": None}]}   # None prints as a dash, never a made-up number

def lookup(args: dict) -> dict:                 # a tool handler: plain (not async), fast, returns a dict
    return {"echo": args.get("text", "")}

def register(api):
    api.add_route("main", table, title="My table", args="[TEXT]")       # `EXT <name>` shows `main`
    api.add_tool("lookup", "Echoes text back.", {"properties": {"text": {"type": "string"}}}, lookup)
```

- `api.add_route(name, handler, title="", args="")`: `GET /api/ext/<name>/<route>?q=a b c`; the words arrive as a list of strings. Return a **table** (`columns` + `rows`) or a **series** (`t` epoch seconds ascending, `v` numbers). Anything else is refused with a clear error. At most 10 routes.
- `api.add_tool(name, description, parameters, handler)`: description 1 to 240 characters; up to 8 flat, typed arguments (`string`, `integer`, `number`, `array`, `object`); at most 10 tools.
- `api.add_provider(cls)`: `cls` subclasses `openterm.providers.base.Provider` (see [ADDING_A_PROVIDER.md](ADDING_A_PROVIDER.md)). It joins the end of every capability's order and cannot replace a built-in source or invent a capability.

### Rules for honest data

Follow the project's rules: never invent numbers (return `None` and say why), label sample or computed data as such (`notes`), keep secrets out of results and error text (errors are redacted before they reach the screen, but do not rely on it), and make no network call at import time.

## The example

`examples/extensions/hello/` is a complete extension: a table route, a series route and one tool. All its numbers are computed and labelled as demo data.

```
cp -r examples/extensions/hello  <data dir>/extensions/hello
EXT LIST            # hello is OFF
EXT ENABLE hello    # read the notice first
EXT hello           # the table
EXT hello wave 90   # a 90-day series (chart)
EXT DISABLE hello
```

## Commands

See `EXT` in [COMMANDS.md](COMMANDS.md). The panel is generic, so an extension needs no frontend code.

## Testing your extension

`backend/tests/test_extensions.py` shows how: write the extension into a temporary extensions folder, enable it through the API, call its route and tool, and check that failures stay contained. Tests must not touch the network.
