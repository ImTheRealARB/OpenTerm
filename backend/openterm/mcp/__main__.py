"""stdio transport for MCP: `uv run python -m openterm.mcp`.

Some MCP clients (Claude Desktop) start a program and talk to it over stdin/stdout, one JSON message per line.
This bridge forwards each line to the running OpenTerm backend (POST http://127.0.0.1:8000/mcp) and prints the answer.
It holds no logic of its own; if OpenTerm is not running it answers a JSON-RPC error instead of hanging.
"""

from __future__ import annotations

import json
import os
import sys
from typing import IO

import httpx

DEFAULT_URL = "http://127.0.0.1:8000"


def _err(id_, message: str) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": id_, "error": {"code": -32603, "message": message}})


def bridge(lines: IO[str] | list[str], out: IO[str], client: httpx.Client, url: str) -> None:
    """Reads JSON-RPC lines, posts each to `url`/mcp, writes the answers to `out`. Streams and client are passed in so tests can fake them."""
    endpoint = url.rstrip("/") + "/mcp"
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            id_ = json.loads(line).get("id")
        except (ValueError, AttributeError):
            id_ = None
        try:
            r = client.post(endpoint, content=line.encode(), headers={"Content-Type": "application/json"})
        except httpx.HTTPError:
            if id_ is not None:
                out.write(_err(id_, f"OPENTERM IS NOT RUNNING AT {url}: start it with openterm") + "\n")
                out.flush()
            continue
        if r.status_code == 202 or not r.content:  # a notification: no answer
            continue
        out.write(r.text.strip().replace("\n", " ") + "\n")
        out.flush()


def main() -> None:
    url = os.environ.get("OPENTERM_URL", DEFAULT_URL)
    with httpx.Client(timeout=130.0) as client:
        bridge(sys.stdin, sys.stdout, client, url)


if __name__ == "__main__":
    main()
