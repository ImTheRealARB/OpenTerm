"""MCP *client* mode: OpenTerm calling third-party MCP servers the user configured and enabled.

Kept apart from `openterm.mcp` (OpenTerm's own MCP server) on purpose: this package holds the refusal list of order-like words,
while the server package must contain none (tests/test_phase17_mcp.py scans it with no exemptions).
"""
