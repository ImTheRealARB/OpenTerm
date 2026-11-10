"""Third-party extensions: discovery, the enable switch, loading, and undoing a load.

An extension is Python code somebody else wrote. It runs INSIDE the OpenTerm process with the permissions of the user who started
OpenTerm: it can read the files, keys in the environment and network that user can. So:

- nothing is imported until the user types `EXT ENABLE <name>`; discovery only reads a `extension.yaml` (folders) or package
  metadata (entry points), never runs the code;
- a failing extension (bad manifest, import error, `register()` raising, a route or tool crashing) is isolated: logged, shown as ERR in
  `EXT LIST`, and never stops startup or the other extensions;
- what an extension can ADD is narrow and read-only: a data provider (the same `Provider` base as `providers/`, ranked after every
  built-in source), AI tools named `ext.<name>.<tool>` (same 6,000-character cap as every tool, refused if the name or description looks
  like an order, broker or account tool), and GET routes under `/api/ext/<name>/<route>` that return a table or a series.

Where extensions come from: the entry-point group `openterm.extensions` (installed Python packages) and folders
`<data dir>/extensions/<name>/` holding `extension.yaml` and the entry file (default `extension.py`). Both define `register(api)`.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import importlib.util
import inspect
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path
from typing import Any

import yaml

from ..ai import tools as toolbox
from ..providers.base import Provider
from ..providers.hierarchy import DEFAULT_ORDER
from ..redact import redact
from ..router import Health, Router
from .manifest import NAME_RE, SHORT_RE, Manifest, ManifestError, parse_manifest
from .payload import PayloadError, normalize

log = logging.getLogger("openterm.extensions")

GROUP = "openterm.extensions"
ROUTE_TIMEOUT_S = 10.0
MAX_ARGS = 20
MAX_TOOL_DESC = 240
MAX_TOOLS = 10
MAX_ROUTES = 10
PARAM_TYPES = {"string", "integer", "number", "array", "object"}
DEFAULT_ROUTE = "main"

NOTICE = ("EXTENSIONS ARE THIRD-PARTY CODE. AN ENABLED EXTENSION RUNS INSIDE OPENTERM WITH YOUR PERMISSIONS (YOUR FILES, KEYS AND NETWORK). "
          "ENABLE ONLY CODE YOU TRUST FROM AN AUTHOR YOU KNOW.")

# Order-like names are refused. Same words as the checks on the built-in tools (tests/test_phase20_tools.py FORBIDDEN and
# tests/test_phase17_mcp.py FORBIDDEN): this app has no order, broker or account tool and an extension cannot add one.
_SUBSTRING = ("order", "margin", "holding", "broker", "cancel", "execut")
_PREFIX = ("kite", "gtt", "buy", "sell", "kill", "trade")
_DESCRIPTION = re.compile(r"\b(orders?|gtt|margins?|holdings?|kite)\b", re.IGNORECASE)


class ExtError(Exception):
    """kind: bad_request | not_found | forbidden | extension_error (the HTTP layer maps it)."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def order_like(name: str, description: str = "") -> str | None:
    """Why a tool or route name (and description) looks like an order surface, or None when it is fine."""
    low = name.lower()
    tokens = re.split(r"[^a-z0-9]+", low)
    for w in _SUBSTRING:
        if w in low:
            return f"{name}: THE NAME CONTAINS '{w}'"
    for w in _PREFIX:
        if any(t.startswith(w) for t in tokens):
            return f"{name}: THE NAME CONTAINS '{w}'"
    m = _DESCRIPTION.search(description)
    if m:
        return f"{name}: THE DESCRIPTION MENTIONS '{m.group(0)}'"
    return None


@dataclass
class RouteSpec:
    name: str
    handler: Any
    title: str = ""
    args: str = ""


@dataclass
class Loaded:
    providers: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    routes: dict[str, RouteSpec] = field(default_factory=dict)
    modules: list[str] = field(default_factory=list)


@dataclass
class Entry:
    name: str
    source: str  # "folder" | "package:<distribution>"
    manifest: Manifest | None = None
    error: str | None = None  # discovery or load failure
    runtime_error: str | None = None  # last failure of a route or tool call
    folder: Path | None = None
    ep: Any = None
    loaded: Loaded | None = None


class ExtensionApi:
    """What `register(api)` receives. Everything is checked when it is added; nothing is live until `register` returns."""

    def __init__(self, name: str):
        self.name = name
        self.providers: list[type] = []
        self.tools: list[tuple[str, str, dict, Any]] = []
        self.routes: dict[str, RouteSpec] = {}

    def add_provider(self, cls: type) -> None:
        if not (isinstance(cls, type) and issubclass(cls, Provider)):
            raise ExtError("bad_request", "add_provider NEEDS A SUBCLASS OF openterm.providers.base.Provider")
        self.providers.append(cls)

    def add_tool(self, name: str, description: str, parameters: dict | None, handler) -> None:
        """A read-only AI tool. `handler(args: dict) -> dict` is synchronous and fast; the result is cut to 6,000 characters."""
        if not SHORT_RE.match(str(name)):
            raise ExtError("bad_request", f"TOOL NAME {name!r} MUST BE LOWERCASE LETTERS, DIGITS AND _")
        if not callable(handler) or inspect.iscoroutinefunction(handler):
            raise ExtError("bad_request", "A TOOL HANDLER MUST BE A PLAIN (NOT async) FUNCTION")
        if not isinstance(description, str) or not description.strip() or len(description) > MAX_TOOL_DESC:
            raise ExtError("bad_request", f"A TOOL DESCRIPTION IS 1 TO {MAX_TOOL_DESC} CHARACTERS")
        if len(self.tools) >= MAX_TOOLS or any(t[0] == name for t in self.tools):
            raise ExtError("bad_request", f"AT MOST {MAX_TOOLS} UNIQUE TOOLS PER EXTENSION")
        if why := order_like(name, description):
            raise ExtError("forbidden", f"REFUSED, ORDER-LIKE TOOL: {why}")
        self.tools.append((name, description, _schema(parameters), handler))

    def add_route(self, name: str, handler, title: str = "", args: str = "") -> None:
        """A GET route: `handler(args: list[str]) -> table or series payload` (sync or async). `main` answers `EXT <name>`."""
        if not SHORT_RE.match(str(name)):
            raise ExtError("bad_request", f"ROUTE NAME {name!r} MUST BE LOWERCASE LETTERS, DIGITS AND _")
        if not callable(handler):
            raise ExtError("bad_request", "A ROUTE HANDLER MUST BE CALLABLE")
        if len(self.routes) >= MAX_ROUTES or name in self.routes:
            raise ExtError("bad_request", f"AT MOST {MAX_ROUTES} UNIQUE ROUTES PER EXTENSION")
        if why := order_like(name):
            raise ExtError("forbidden", f"REFUSED, ORDER-LIKE ROUTE: {why}")
        self.routes[name] = RouteSpec(name, handler, str(title)[:80], str(args)[:80])


def _schema(parameters: dict | None) -> dict:
    """The tool's argument schema in the form `ai.tools.validate` understands (flat, typed properties, no extras)."""
    parameters = parameters or {}
    props_in = parameters.get("properties") or {}
    if not isinstance(props_in, dict) or len(props_in) > 8:
        raise ExtError("bad_request", "TOOL parameters.properties MUST BE AN OBJECT OF AT MOST 8 ARGUMENTS")
    props: dict[str, dict] = {}
    for k, spec in props_in.items():
        if not SHORT_RE.match(str(k)) or not isinstance(spec, dict) or spec.get("type") not in PARAM_TYPES:
            raise ExtError("bad_request", f"ARGUMENT {k!r} NEEDS A LOWERCASE NAME AND A type OF {', '.join(sorted(PARAM_TYPES))}")
        props[k] = {kk: spec[kk] for kk in ("type", "description", "enum") if kk in spec}
    required = [r for r in (parameters.get("required") or []) if r in props]
    return toolbox.obj(props, required)


def _package_entry_points() -> list:
    return list(metadata.entry_points(group=GROUP))


class ExtensionManager:
    def __init__(self, ext_dir: Path | None, router: Router, http: Any):
        self.dir = ext_dir
        self.router = router
        self.http = http
        self.entries: dict[str, Entry] = {}
        self.enabled: set[str] = set()
        self._read_state()
        self.refresh()

    # --- state file -------------------------------------------------------------------------------------------------------------
    @property
    def _state_file(self) -> Path | None:
        return self.dir / "enabled.json" if self.dir is not None else None

    def _read_state(self) -> None:
        f = self._state_file
        if f is None or not f.is_file():
            return
        try:
            names = json.loads(f.read_text(encoding="utf-8")).get("enabled", [])
            self.enabled = {n for n in names if isinstance(n, str) and NAME_RE.match(n)}
        except (OSError, ValueError, AttributeError):
            log.warning("extensions: %s is unreadable; every extension stays off", f)

    def _save(self) -> None:
        f = self._state_file
        if f is None:
            return
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            tmp = f.with_suffix(".tmp")
            tmp.write_text(json.dumps({"enabled": sorted(self.enabled)}), encoding="utf-8")
            tmp.replace(f)
        except OSError as e:
            log.warning("extensions: could not save the enabled list: %s", redact(str(e)))

    # --- discovery (never runs extension code) ----------------------------------------------------------------------------------
    def refresh(self) -> None:
        found: dict[str, Entry] = {}
        for entry in [*self._scan_folders(), *self._scan_packages()]:
            if entry.name in found:  # the first one (a folder) wins; a package with the same name is reported, not loaded
                log.warning("extensions: duplicate name %s ignored (%s)", entry.name, entry.source)
                continue
            old = self.entries.get(entry.name)
            if old is not None:  # the state of a load or a call survives a rescan; a bad manifest is judged afresh
                entry.loaded, entry.runtime_error = old.loaded, old.runtime_error
                entry.error = entry.error or old.error
            found[entry.name] = entry
        for name, old in self.entries.items():  # something loaded that vanished from disk stays listed until it is disabled
            if name not in found and old.loaded is not None:
                found[name] = old
        self.entries = dict(sorted(found.items()))

    def _scan_folders(self) -> list[Entry]:
        out: list[Entry] = []
        if self.dir is None or not self.dir.is_dir():
            return out
        for d in sorted(self.dir.iterdir()):
            if d.name.startswith(".") or not d.is_dir():
                continue
            e = Entry(name=d.name, source="folder", folder=d)
            try:
                raw = yaml.safe_load((d / "extension.yaml").read_text(encoding="utf-8"))
                e.manifest = parse_manifest(raw, expect_name=d.name)
            except FileNotFoundError:
                continue  # not an extension folder
            except (OSError, yaml.YAMLError, ManifestError) as err:
                e.error = f"BAD MANIFEST: {redact(str(err))[:160]}"
                log.warning("extensions: %s: %s", d.name, e.error)
            out.append(e)
        return out

    def _scan_packages(self) -> list[Entry]:
        out: list[Entry] = []
        try:
            eps = _package_entry_points()
        except Exception as err:  # noqa: BLE001 - a broken installed distribution must not break the listing
            log.warning("extensions: entry points unreadable: %s", err)
            return out
        for ep in eps:
            dist = getattr(ep, "dist", None)
            source = f"package:{dist.metadata['Name']}" if dist is not None else "package"
            e = Entry(name=ep.name, source=source, ep=ep)
            try:
                if dist is None or not NAME_RE.match(ep.name):
                    raise ManifestError("ENTRY POINT NAME MUST BE LOWERCASE LETTERS, DIGITS, _ AND -")
                md = dist.metadata
                e.manifest = parse_manifest({
                    "name": ep.name, "version": md["Version"], "author": md["Author"] or md["Author-email"] or md["Maintainer"],
                    "license": md["License-Expression"] or md["License"] or "see package", "description": md["Summary"],
                })
            except (ManifestError, KeyError, TypeError) as err:
                e.error = f"BAD METADATA: {redact(str(err))[:160]}"
            out.append(e)
        return out

    # --- listing ----------------------------------------------------------------------------------------------------------------
    def status_of(self, e: Entry) -> str:
        if e.error or (e.runtime_error and e.loaded is not None):
            return "ERR"
        return "ON" if e.loaded is not None else "OFF"

    def list(self) -> list[dict]:
        rows = []
        for e in self.entries.values():
            m = e.manifest
            adds = list(m.adds) if m else []
            if e.loaded is not None:
                adds = [k for k, v in (("provider", e.loaded.providers), ("tools", e.loaded.tools), ("route", e.loaded.routes)) if v]
            rows.append({
                "name": e.name, "version": m.version if m else None, "author": m.author if m else None,
                "license": m.license if m else None, "description": m.description if m else "", "source": e.source,
                "adds": adds, "enabled": e.name in self.enabled, "status": self.status_of(e),
                "error": redact(e.error or e.runtime_error or "") or None,
                "routes": [{"name": r.name, "title": r.title, "args": r.args} for r in (e.loaded.routes.values() if e.loaded else [])],
                "tools": list(e.loaded.tools) if e.loaded else [],
            })
        return rows

    def summary(self) -> dict:
        return {"extensions": self.list(), "dir": str(self.dir) if self.dir else None, "notice": NOTICE}

    # --- enable / disable -------------------------------------------------------------------------------------------------------
    def _get(self, name: str) -> Entry:
        e = self.entries.get(name)
        if e is None:
            raise ExtError("not_found", f"NO EXTENSION NAMED {name}: run EXT LIST")
        return e

    def enable(self, name: str) -> dict:
        self.refresh()
        e = self._get(name)
        if e.manifest is None:
            raise ExtError("bad_request", e.error or "BAD MANIFEST")
        if e.loaded is None:
            self._load(e)  # raises ExtError, after recording e.error
        self.enabled.add(name)
        self._save()
        return self.list_one(name)

    def disable(self, name: str) -> dict:
        e = self._get(name)
        self._unload(e)
        e.error = e.runtime_error = None
        self.enabled.discard(name)
        self._save()
        return self.list_one(name)

    def list_one(self, name: str) -> dict:
        return next(r for r in self.list() if r["name"] == name)

    def load_enabled(self) -> None:
        """Startup: load every extension the user enabled. A failure is logged and shown as ERR; it never propagates."""
        for name in sorted(self.enabled):
            e = self.entries.get(name)
            if e is None:
                log.warning("extensions: %s is enabled but not found on disk", name)
                continue
            with contextlib.suppress(ExtError):
                self._load(e)

    def unload_all(self) -> None:
        for e in list(self.entries.values()):
            self._unload(e)

    # --- loading ----------------------------------------------------------------------------------------------------------------
    def _import(self, e: Entry):
        if e.ep is not None:
            return e.ep.load()
        assert e.folder is not None and e.manifest is not None
        path = (e.folder / e.manifest.entry).resolve()
        if not path.is_file() or e.folder.resolve() not in path.parents:
            raise ExtError("bad_request", f"ENTRY FILE {e.manifest.entry} NOT FOUND INSIDE THE EXTENSION FOLDER")
        modname = "openterm_ext_" + e.name.replace("-", "_")
        spec = importlib.util.spec_from_file_location(modname, path, submodule_search_locations=[str(e.folder.resolve())])
        if spec is None or spec.loader is None:
            raise ExtError("bad_request", "ENTRY FILE CANNOT BE IMPORTED")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[modname] = mod
        try:
            spec.loader.exec_module(mod)
        except BaseException:
            self._drop_modules(modname)
            raise
        return mod

    @staticmethod
    def _drop_modules(prefix: str) -> None:
        for n in [n for n in sys.modules if n == prefix or n.startswith(prefix + ".")]:
            del sys.modules[n]

    def _load(self, e: Entry) -> None:
        try:
            obj = self._import(e)
            register = getattr(obj, "register", None) or (obj if callable(obj) and not inspect.ismodule(obj) else None)
            if register is None:
                raise ExtError("bad_request", "THE EXTENSION DEFINES NO register(api) FUNCTION")
            api = ExtensionApi(e.name)
            register(api)
            e.loaded = self._commit(e, api)
            e.error = e.runtime_error = None
            log.info("extensions: %s %s loaded (%s)", e.name, e.manifest.version if e.manifest else "?", e.source)
        except (Exception, SystemExit) as err:  # noqa: BLE001 - isolation: whatever the extension does, the app goes on
            self._drop_modules("openterm_ext_" + e.name.replace("-", "_"))
            msg = f"LOAD FAILED: {type(err).__name__}: {redact(str(err))[:160]}" if not isinstance(err, ExtError) else redact(str(err))
            e.error, e.loaded = msg, None
            log.warning("extensions: %s: %s", e.name, msg)
            raise (err if isinstance(err, ExtError) else ExtError("extension_error", msg)) from None

    def _commit(self, e: Entry, api: ExtensionApi) -> Loaded:
        """Validate everything, then make it live. Nothing changes when any part is refused."""
        r = self.router
        built: list[Provider] = []
        for cls in api.providers:
            p = cls(self.http)
            if not p.name or p.name in r.providers or p.name in {b.name for b in built}:
                raise ExtError("bad_request", f"PROVIDER NAME {p.name!r} IS EMPTY OR ALREADY TAKEN")
            unknown = sorted(c for c in p.capabilities if c not in DEFAULT_ORDER)
            if unknown:
                raise ExtError("bad_request", f"PROVIDER {p.name} DECLARES UNKNOWN CAPABILITIES: {', '.join(unknown)}")
            built.append(p)
        tools = []
        for short, desc, params, handler in api.tools:
            full = f"ext.{e.name}.{short}"
            if full in toolbox.REGISTRY:
                raise ExtError("bad_request", f"TOOL {full} ALREADY EXISTS")
            tools.append(toolbox.Tool(full, desc, params, f"local:{full}", local=self._tool_runner(e, handler), desk_only=True))
        loaded = Loaded(modules=["openterm_ext_" + e.name.replace("-", "_")])
        for p in built:
            r.providers[p.name] = p
            r.health[p.name] = Health()
            for cap in p.capabilities:  # last in line: an extension never outranks a built-in source
                r.order[cap] = [*r.order.get(cap, []), p.name]
            loaded.providers.append(p.name)
        for t in tools:
            toolbox.REGISTRY[t.name] = t
            loaded.tools.append(t.name)
        loaded.routes = dict(api.routes)
        return loaded

    def _tool_runner(self, e: Entry, handler):
        name = e.name

        def run(args: dict, ctx: dict) -> dict:
            e = self.entries.get(name) or Entry(name, "gone")  # a refresh replaces Entry objects: look the current one up
            try:
                out = handler(dict(args))
                data = out if isinstance(out, dict) else {"result": out}
                json.dumps(data, default=str)
            except Exception as err:  # noqa: BLE001 - reported to the model as a tool error, never raised into the agent
                e.runtime_error = f"{type(err).__name__}: {redact(str(err))[:120]}"
                log.warning("extensions: %s tool failed: %s", e.name, e.runtime_error)
                raise ValueError(f"EXTENSION {e.name} FAILED: {e.runtime_error}") from None
            e.runtime_error = None
            return {**data, "source": f"ext:{e.name}"}
        return run

    def _unload(self, e: Entry) -> None:
        if e.loaded is None:
            return
        r = self.router
        for name in e.loaded.providers:
            r.providers.pop(name, None)
            r.health.pop(name, None)
            for cap in list(r.order):
                if name in r.order[cap]:
                    r.order[cap] = [n for n in r.order[cap] if n != name]
        for name in e.loaded.tools:
            toolbox.REGISTRY.pop(name, None)
        for m in e.loaded.modules:
            self._drop_modules(m)
        e.loaded = None

    # --- routes -----------------------------------------------------------------------------------------------------------------
    async def call_route(self, name: str, route: str, args: list[str]) -> dict:
        e = self._get(name)
        if e.loaded is None:
            raise ExtError("forbidden", f"EXTENSION {name} IS NOT ENABLED: run EXT ENABLE {name}")
        spec = e.loaded.routes.get(route)
        if spec is None:
            known = ", ".join(e.loaded.routes) or "none"
            raise ExtError("not_found", f"EXTENSION {name} HAS NO ROUTE {route} (routes: {known})")
        try:
            if inspect.iscoroutinefunction(spec.handler):
                raw = await asyncio.wait_for(spec.handler(list(args)), ROUTE_TIMEOUT_S)
            else:
                raw = await asyncio.wait_for(asyncio.to_thread(spec.handler, list(args)), ROUTE_TIMEOUT_S)
            payload = normalize(raw)
        except PayloadError as err:
            e.runtime_error = f"BAD PAYLOAD: {redact(str(err))[:160]}"
            raise ExtError("extension_error", f"EXTENSION {name} ERR {e.runtime_error}") from None
        except TimeoutError:
            e.runtime_error = f"TIMED OUT AFTER {ROUTE_TIMEOUT_S:.0f}S"
            raise ExtError("extension_error", f"EXTENSION {name} ERR {e.runtime_error}") from None
        except Exception as err:  # noqa: BLE001 - isolation
            e.runtime_error = f"{type(err).__name__}: {redact(str(err))[:160]}"
            log.warning("extensions: %s route %s failed: %s", name, route, e.runtime_error)
            raise ExtError("extension_error", f"EXTENSION {name} ERR {e.runtime_error}") from None
        e.runtime_error = None
        return payload


def split_args(q: str | None) -> list[str]:
    return [a[:100] for a in (q or "").split()[:MAX_ARGS]]
