"""MCP (Model Context Protocol) server for OpenTerm.

MCP is an open standard that lets an outside AI app (Claude Desktop, Claude Code, Cursor) call tools that
another program offers. Here the "tools" are OpenTerm's read-only data tools (quotes, history, filings...).
The app speaks JSON-RPC 2.0 (a tiny request/response format: {"jsonrpc","id","method","params"}).

Layout:
- server.py   pure dispatcher: JSON-RPC message in, JSON-RPC answer out. No web framework.
- routes.py   HTTP transport: POST /mcp on the running backend (loopback only).
- __main__.py stdio transport: a small bridge for clients that start a program and talk over stdin/stdout.

This server only reads data. A test keeps it that way.
"""
