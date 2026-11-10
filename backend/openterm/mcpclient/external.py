"""Third-party MCP servers: the config file, the built-in presets, and the manager that feeds enabled tools to the AI.

`<data dir>/mcp_servers.yaml` (the data dir is the folder of the database, like `presets/` for SWARM desks):

    servers:
      my-server:
        command: npx            # stdio ...                 or   url: https://host/mcp   (Streamable HTTP)
        args: [-y, some-package]
        env: {SOME_KEY: value}  # secret: never sent to the browser, logs or error text
        headers: {Authorization: Bearer ...}   # HTTP only, same care as env
        enabled: false          # OFF until the user turns it on
        allow: [tool_a, tool_b] # per-tool allow-list: a tool not listed is never offered to the AI

Rules: every server is off until enabled; a tool reaches the AI only if it is on the allow-list AND not order-like; results are wrapped as untrusted
third-party data and labelled with the server name; a server is started on first use and stopped when idle or on shutdown.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import yaml

from ..ai import tools as toolbox
from .client import Client, McpError, ServerSpec, ToolInfo, order_like, wrap_untrusted

log = logging.getLogger("openterm.mcpclient.external")
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$|^[a-z0-9]$")
TOOL_RE = re.compile(r"^[A-Za-z0-9_\-]{1,48}$")  # a tool name that can be part of a provider function name
LIST_TTL_S = 600.0
FILE = "mcp_servers.yaml"


@dataclass(frozen=True)
class Preset:
    name: str
    title: str
    command: str
    args: tuple[str, ...]
    needs: str  # what must be installed
    repo: str
    licence: str
    allow: tuple[str, ...]  # read-only tools allowed when the preset is enabled

    @property
    def notice(self) -> str:
        return (f"THIRD-PARTY CODE, NOT BUNDLED WITH OPENTERM. {self.title} is an unofficial community project ({self.repo}, {self.licence}), "
                f"not affiliated with or endorsed by NSE India. Enabling it means that when the AI or you first use it, `{self.command} {' '.join(self.args)}` "
                f"downloads and runs that code ON THIS COMPUTER WITH YOUR PERMISSIONS. It needs {self.needs} installed. It is started only when used, "
                "stopped when idle, and gets none of OpenTerm's API keys. Its results are labelled THIRD-PARTY and the AI treats them as untrusted data. "
                "The package is not pinned: to pin a version, edit args in mcp_servers.yaml. NSE data may be delayed, rate-limited or stop working without notice.")


PRESETS: dict[str, Preset] = {p.name: p for p in (
    Preset("stock-nse-india", "stock-nse-india", "npx", ("-y", "stock-nse-india", "mcp"), "Node.js (npx)", "github.com/hi-imcodeman/stock-nse-india", "MIT",
           ("get_equity_details", "get_equity_historical_data", "get_equity_option_chain", "get_index_option_chain", "get_market_status",
            "get_gainers_and_losers_by_index")),
    Preset("nse-mcp", "nse-mcp", "uvx", ("nse-mcp",), "uv (uvx)", "github.com/jugaad-py/nse-mcp", "NO LICENCE STATED: no LICENSE file in the repository and none on PyPI, checked 2026-11-10, so all rights are reserved by default; built on jugaad-data",
           ("stock_quote", "stock_history", "index_option_chain", "market_status")),
)}


class ConfigError(Exception):
    """A problem with the config or a request; the text is shown to the user as is (already redacted)."""


def _str_map(v: Any) -> dict[str, str] | None:
    return {str(k): str(x) for k, x in v.items()} if isinstance(v, dict) else None


def parse_entry(name: str, raw: Any) -> ServerSpec:
    if not NAME_RE.match(name):
        raise ConfigError(f"SERVER NAME {name[:30]!r} MUST BE 1-32 CHARACTERS: a-z, 0-9, -")
    if not isinstance(raw, dict):
        raise ConfigError(f"{name}: ENTRY MUST BE A MAPPING")
    command, url = raw.get("command"), raw.get("url")
    if bool(command) == bool(url):
        raise ConfigError(f"{name}: GIVE EXACTLY ONE OF command (stdio) OR url (Streamable HTTP)")
    args = raw.get("args", [])
    if not isinstance(args, list) or not all(isinstance(a, (str, int, float)) for a in args):
        raise ConfigError(f"{name}: args MUST BE A LIST OF STRINGS")
    if url and not (isinstance(url, str) and re.match(r"^https?://", url)):
        raise ConfigError(f"{name}: url MUST START WITH http:// OR https://")
    if command and not isinstance(command, str):
        raise ConfigError(f"{name}: command MUST BE A STRING")
    env, headers = _str_map(raw.get("env", {})), _str_map(raw.get("headers", {}))
    if env is None or headers is None:
        raise ConfigError(f"{name}: env AND headers MUST BE MAPPINGS")
    try:
        timeout = min(max(float(raw.get("timeout_s", 30)), 1.0), 300.0)
    except (TypeError, ValueError):
        raise ConfigError(f"{name}: timeout_s MUST BE A NUMBER") from None
    return ServerSpec(name, command or "", [str(a) for a in args], env, url or "", headers, timeout)


class Manager:
    """Config + live connections. One per app (`manager_of`). The file is re-read on every call, so editing it by hand takes effect at once."""

    def __init__(self, data_dir: Path, transport_for: Any = None):
        self.path = Path(data_dir) / FILE
        self.transport_for = transport_for  # tests: name -> httpx transport for url servers
        self.clients: dict[str, tuple[Client, str]] = {}  # name -> (client, fingerprint of its spec)
        self.listed: dict[str, tuple[float, list[ToolInfo]]] = {}
        self.errors_seen: dict[str, str] = {}
        self._lock = asyncio.Lock()

    # -- config file --
    def read(self) -> tuple[dict[str, dict], list[str]]:
        """(servers, problems): the file's entries plus presets not yet in it (disabled), and what was wrong with the file."""
        problems: list[str] = []
        entries: dict[str, dict] = {}
        try:
            doc = yaml.safe_load(self.path.read_text(encoding="utf-8")) if self.path.exists() else None
        except (OSError, yaml.YAMLError) as e:
            problems.append(f"{FILE}: COULD NOT READ ({type(e).__name__})")
            doc = None
        servers = doc.get("servers") if isinstance(doc, dict) else None
        for name, raw in (servers or {}).items() if isinstance(servers, dict) else []:
            try:
                parse_entry(str(name), raw)
            except ConfigError as e:
                problems.append(str(e))
                continue
            entries[str(name)] = raw
        for p in PRESETS.values():
            if p.name not in entries:
                entries[p.name] = {"preset": p.name, "command": p.command, "args": list(p.args), "enabled": False, "allow": []}
        return entries, problems

    def _write(self, entries: dict[str, dict]) -> None:
        keep = {n: e for n, e in entries.items() if not (n in PRESETS and not e.get("enabled") and not e.get("allow"))}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".mcp_servers.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write("# OpenTerm third-party MCP servers. Every server is off until `enabled: true`. env and headers are secrets: keep this file private.\n")
                yaml.safe_dump({"servers": keep}, f, sort_keys=False)
            with contextlib.suppress(OSError):
                os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    def spec(self, name: str) -> tuple[ServerSpec, dict]:
        entries, _ = self.read()
        if name not in entries:
            raise ConfigError(f"NO SERVER NAMED {name[:32]}: MCP SERVERS LISTS THEM")
        return parse_entry(name, entries[name]), entries[name]

    # -- status for the UI (no secrets) --
    def status(self) -> dict:
        entries, problems = self.read()
        rows = []
        for name, e in entries.items():
            spec = parse_entry(name, e)
            preset = PRESETS.get(e.get("preset") or "")
            known = self.listed.get(name)
            rows.append({
                "name": name, "preset": preset.name if preset else None, "transport": "stdio" if spec.command else "http",
                "target": spec.clean(f"{spec.command} {' '.join(spec.args)}" if spec.command else _host(spec.url)),
                "enabled": bool(e.get("enabled")), "allow": [str(t) for t in e.get("allow") or []], "env_keys": sorted(spec.env), "header_keys": sorted(spec.headers),
                "running": name in self.clients and self.clients[name][0].running, "tools_seen": len(known[1]) if known else None,
                "error": self.errors_seen.get(name), "notice": preset.notice if preset else None})
        return {"servers": rows, "problems": problems, "file": str(self.path)}

    # -- changes --
    def enable(self, name: str) -> dict:
        entries, _ = self.read()
        if name not in entries:
            raise ConfigError(f"NO SERVER NAMED {name[:32]}: MCP SERVERS LISTS THEM")
        e = entries[name]
        preset = PRESETS.get(e.get("preset") or "")
        if preset and not e.get("allow"):
            e["allow"] = list(preset.allow)
        e["enabled"] = True
        self._write(entries)
        self.listed.pop(name, None)
        self.errors_seen.pop(name, None)
        return {"name": name, "enabled": True, "allow": e.get("allow") or [],
                "notice": preset.notice if preset else f"THIRD-PARTY CODE YOU CONFIGURED: {name} runs with your permissions when it is used. Its results are labelled THIRD-PARTY."}

    async def disable(self, name: str) -> dict:
        entries, _ = self.read()
        if name not in entries:
            raise ConfigError(f"NO SERVER NAMED {name[:32]}")
        entries[name]["enabled"] = False
        self._write(entries)
        await self.stop(name)
        return {"name": name, "enabled": False}

    def set_allow(self, name: str, tools: list[str]) -> dict:
        entries, _ = self.read()
        if name not in entries:
            raise ConfigError(f"NO SERVER NAMED {name[:32]}")
        bad = [t for t in tools if not TOOL_RE.match(t)]
        if bad:
            raise ConfigError(f"TOOL NAME(S) NOT VALID: {', '.join(b[:30] for b in bad)}")
        refused = [t for t in tools if order_like(t)]
        if refused:
            raise ConfigError(f"REFUSED: {', '.join(refused)} LOOKS LIKE AN ORDER TOOL. OPENTERM NEVER OFFERS ORDER TOOLS TO THE AI")
        entries[name]["allow"] = sorted(set(tools))
        self._write(entries)
        return {"name": name, "allow": entries[name]["allow"]}

    # -- connections --
    def client(self, name: str) -> tuple[Client, ServerSpec, dict]:
        spec, raw = self.spec(name)
        if not raw.get("enabled"):
            raise ConfigError(f"{name} IS OFF: MCP ENABLE {name} FIRST")
        fp = repr((spec.command, spec.args, sorted(spec.env.items()), spec.url, sorted(spec.headers.items()), spec.timeout_s))
        cur = self.clients.get(name)
        if cur is None or cur[1] != fp:
            if cur is not None:
                asyncio.ensure_future(cur[0].close())
            transport = self.transport_for(name) if self.transport_for and spec.url else None
            self.clients[name] = (Client(spec, transport=transport), fp)
        return self.clients[name][0], spec, raw

    async def stop(self, name: str) -> None:
        cur = self.clients.pop(name, None)
        self.listed.pop(name, None)
        if cur:
            await cur[0].close()

    async def close_all(self) -> None:
        await asyncio.gather(*(self.stop(n) for n in list(self.clients)), return_exceptions=True)
        toolbox.EXTERNAL.clear()

    async def list_tools(self, name: str, *, fresh: bool = False) -> list[ToolInfo]:
        client, _spec, _ = self.client(name)
        hit = self.listed.get(name)
        if hit and not fresh and time.monotonic() - hit[0] < LIST_TTL_S:
            return hit[1]
        try:
            tools = await client.list_tools()
        except McpError as e:
            self.errors_seen[name] = str(e)
            raise
        except (httpx.HTTPError, OSError) as e:
            self.errors_seen[name] = f"CONNECTION FAILED: {type(e).__name__}"
            raise McpError(self.errors_seen[name]) from None
        self.errors_seen.pop(name, None)
        self.listed[name] = (time.monotonic(), tools)
        return tools

    def refusal(self, tool: ToolInfo) -> str | None:
        if not TOOL_RE.match(tool.name):
            return "NAME CANNOT BE USED AS A MODEL FUNCTION NAME"
        if order_like(tool.name, tool.description):
            return "LOOKS LIKE AN ORDER TOOL: NEVER OFFERED TO THE AI"
        return None

    async def call(self, name: str, tool: str, args: dict) -> tuple[bool, str]:
        """Raw call for MCP CALL (the user's own action): the text is the server's, cut to the AI cap, and still wrapped as third-party data."""
        client, spec, _ = self.client(name)
        known = {t.name: t for t in await self.list_tools(name)}
        if tool not in known:
            raise ConfigError(f"{name} HAS NO TOOL {tool[:40]}: MCP TOOLS {name} LISTS THEM")
        if why := self.refusal(known[tool]):
            raise ConfigError(f"REFUSED {name}.{tool}: {why}")
        try:
            ok, text = await client.call(tool, args)
        except McpError as e:
            self.errors_seen[name] = str(e)
            raise
        return ok, wrap_untrusted(name, tool, spec.clean(text))

    # -- the AI's view --
    async def prepare(self) -> list[str]:
        """Before an AI / SWARM run: starts nothing unless a server is enabled with allowed tools; fills `toolbox.EXTERNAL`. Returns notes about servers that failed."""
        entries, _ = self.read()
        notes: list[str] = []
        fresh: dict[str, toolbox.ExternalTool] = {}
        for name, e in entries.items():
            allow = {str(t) for t in e.get("allow") or []}
            if not e.get("enabled") or not allow:
                continue
            try:
                tools = await self.list_tools(name)
            except (McpError, ConfigError) as ex:
                notes.append(f"MCP SERVER {name} UNAVAILABLE: {ex}")
                continue
            for t in tools:
                if t.name not in allow or self.refusal(t):
                    continue
                full, wire = f"{name}.{t.name}", f"{name}__{t.name}"
                if len(wire) > 64:
                    continue
                fresh[full] = toolbox.ExternalTool(full, wire, name, t.description[:600] or t.name, _clean_schema(t.schema), self._runner(name, t.name))
        toolbox.EXTERNAL.clear()
        toolbox.EXTERNAL.update(fresh)
        return notes

    def _runner(self, server: str, tool: str):
        async def run(args: dict) -> toolbox.ToolResult:
            label = f"THIRD-PARTY MCP: {server}"
            try:
                client, spec, raw = self.client(server)
                if tool not in {str(t) for t in raw.get("allow") or []}:
                    return toolbox.ToolResult(ok=False, text=f"{server}.{tool} IS NOT ON THE ALLOW-LIST", error="NOT ALLOWED", source=label)
                ok, text = await client.call(tool, args)
            except (McpError, ConfigError) as e:
                msg = f"MCP ERROR {server}.{tool}: {e}"
                if isinstance(e, McpError):
                    self.errors_seen[server] = str(e)
                return toolbox.ToolResult(ok=False, text=msg, error=msg, source=label)
            wrapped = wrap_untrusted(server, tool, spec.clean(text))
            # untrusted: third-party text is never counted as grounding (same rule as web text), and the panel labels it
            return toolbox.ToolResult(ok=ok, text=wrapped, source=label, age_s=0.0, empty=not text.strip(), error=None if ok else spec.clean(text)[:200],
                                      untrusted=True)
        return run


def _host(url: str) -> str:
    """scheme://host[:port]/path with no user info, query or fragment (they may hold a key)."""
    u = urlsplit(url)
    return f"{u.scheme}://{u.hostname or ''}{':' + str(u.port) if u.port else ''}{u.path}"


def _clean_schema(schema: dict) -> dict:
    """A tool's input schema as the model sees it: an object with properties (a server may send less), nothing else trusted."""
    props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    props = {str(k): v for k, v in list(props.items())[:40] if isinstance(v, dict)}
    for v in props.values():
        if isinstance(v.get("description"), str):
            v["description"] = v["description"][:300]
    required = [r for r in schema.get("required") or [] if isinstance(r, str) and r in props]
    return {"type": "object", "properties": props, "required": required}


def data_dir_of(app) -> Path:
    return Path(app.state.settings.openterm_db_path).parent


def manager_of(app) -> Manager:
    """The app's manager; a new data dir (tests reuse the app object) gets a new one."""
    cur = getattr(app.state, "mcp_manager", None)
    want = data_dir_of(app)
    if cur is None or cur.path.parent != want:
        app.state.mcp_manager = Manager(want)
    return app.state.mcp_manager



async def prepare_for_run(app) -> list[str]:
    """Called by the AI and SWARM routes before a run. Never raises: a broken config or server becomes a notice for the run."""
    try:
        return await manager_of(app).prepare()
    except Exception as e:  # noqa: BLE001
        log.warning("mcp prepare failed: %s", type(e).__name__)
        toolbox.EXTERNAL.clear()
        return [f"MCP CLIENT UNAVAILABLE: {type(e).__name__}"]


async def with_notes(notes: list[str], events):
    """The run's events, preceded by one `notice` event per note (a server that failed to start is said, not silently missing)."""
    for n in notes:
        yield {"type": "notice", "text": n}
    try:
        async for ev in events:
            yield ev
    finally:
        await events.aclose()
