"""Strategy sandbox (spec decision E): an allowlist for imports, a denylist for attributes, plus a runtime guard.
Defence in depth, not a kernel sandbox: strategies run in a job worker with a time limit, a memory cap and no network.

Three layers (audit D-1 found that the first one alone can be walked around: `dataclasses.sys.modules["os"]` is just
attribute access on an allowed module):
1. `check(code)` is pure (the server calls it before saving or running): imports must be on an allowlist and attribute
   names that lead to the operating system (`sys`, `os`, `builtins`, `modules`, `compat`, `popen`, ...) are refused.
2. `load(code)` runs in the worker: restricted builtins, a guarded `__import__`, sockets disabled for the worker's life.
3. A Python audit hook (`sys.addaudithook`: the interpreter reports every file open, process start, socket and so on
   to the hook, which may veto it). While strategy code runs (`strict()`), it vetoes anything that touches the machine,
   even if layers 1 and 2 were somehow bypassed. A hook can never be removed once added, so it only acts while
   `strict()` is active: the job's own file reads and the rest of the worker are unaffected.

A separate "no subscript on module objects" rule (the audit's idea) is not needed: indexing a module is only dangerous
after reaching `sys.modules`, and the `sys` / `modules` attribute names are refused in layer 1. A blanket rule would
also break `np.r_[...]` and `typing.Dict[...]`.
"""

from __future__ import annotations

import ast
import contextlib
import os
import threading

ALLOWED_MODULES = {"numpy", "pandas", "math", "statistics", "typing", "dataclasses", "functools", "itertools",
                   "collections", "collections.abc", "datetime"}
BLOCKED_NAMES = {"open", "exec", "eval", "compile", "__import__", "globals", "locals", "vars", "getattr", "setattr",
                 "delattr", "input", "breakpoint", "help", "exit", "quit", "memoryview", "__builtins__", "__loader__",
                 "__spec__", "classmethod", "staticmethod", "property"}
# File, network and code-loading entry points reachable through numpy / pandas attributes.
BLOCKED_ATTRS = {"to_csv", "to_pickle", "to_parquet", "to_json", "to_excel", "to_sql", "to_hdf", "to_feather",
                 "to_html", "to_latex", "to_markdown", "to_clipboard", "to_xml", "to_stata", "to_orc", "load", "save",
                 "savez", "savez_compressed", "savetxt", "loadtxt", "genfromtxt", "fromfile", "tofile", "memmap",
                 "DataSource", "ctypeslib", "eval", "query", "system", "f2py", "testing", "show_config", "io",
                 "HDFStore", "ExcelWriter", "ExcelFile", "lib", "frombuffer", "fromregex", "options", "set_option",
                 "api", "plotting", "plot", "format", "format_map"}
# Audit D-1: the dangerous builtins again as attributes (`builtins.exec`), and every name that reaches the operating
# system through an allowed module (`dataclasses.sys`, `typing.sys`, `pandas.compat.os`, `sys.modules[...]`).
# Left out on purpose because honest strategies use them as ordinary names: `.open` (the OHLC column: `bar.open`),
# `.replace`, `.rename`, `.remove`, `.signal`, `.code`, `.types`, `.input`.
BLOCKED_ATTRS |= {"exec", "eval", "compile", "getattr", "setattr", "delattr", "globals", "locals", "vars",
                  "breakpoint", "memoryview"}
BLOCKED_ATTRS |= {"sys", "os", "builtins", "compat", "subprocess", "modules", "popen", "environ", "listdir", "scandir",
                  "unlink", "rmdir", "mkdir", "makedirs", "startfile", "spawn", "execv", "fork", "socket", "ctypes",
                  "importlib", "inspect", "pickle", "shutil", "pathlib", "tempfile", "threading", "multiprocessing",
                  "marshal", "pty", "winreg", "msvcrt", "webbrowser", "urllib"}
MAX_CODE = 100_000


class SandboxError(ValueError):
    pass


def _blocked_attr(name: str) -> bool:
    return name.startswith(("_", "read_")) or name in BLOCKED_ATTRS


class _Checker(ast.NodeVisitor):
    def visit_Import(self, node: ast.Import) -> None:
        for a in node.names:
            if a.name not in ALLOWED_MODULES:
                raise SandboxError(f"LINE {node.lineno}: IMPORT {a.name} IS NOT ALLOWED "
                                   f"(allowed: {', '.join(sorted(ALLOWED_MODULES))})")

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level or node.module not in ALLOWED_MODULES:
            raise SandboxError(f"LINE {node.lineno}: IMPORT FROM {node.module or '.'} IS NOT ALLOWED")
        for a in node.names:
            if a.name == "*":
                raise SandboxError(f"LINE {node.lineno}: 'import *' IS NOT ALLOWED")
            if _blocked_attr(a.name) or a.name in BLOCKED_NAMES:
                raise SandboxError(f"LINE {node.lineno}: {node.module}.{a.name} IS NOT ALLOWED")

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in BLOCKED_NAMES or node.id.startswith("__"):
            raise SandboxError(f"LINE {node.lineno}: {node.id} IS NOT ALLOWED")

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if _blocked_attr(node.attr):
            raise SandboxError(f"LINE {node.lineno}: .{node.attr} IS NOT ALLOWED")
        self.generic_visit(node)

    def _no_decorators(self, node) -> None:
        if node.decorator_list:
            raise SandboxError(f"LINE {node.lineno}: DECORATORS ARE NOT ALLOWED")

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._no_decorators(node)
        if node.name.startswith("__") and node.name not in ("__init__",):
            raise SandboxError(f"LINE {node.lineno}: METHOD {node.name} IS NOT ALLOWED")
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._no_decorators(node)
        if node.bases or node.keywords:
            raise SandboxError(f"LINE {node.lineno}: CLASS {node.name} MUST NOT HAVE BASES OR KEYWORDS")
        self.generic_visit(node)

    def visit_Global(self, node: ast.Global) -> None:
        raise SandboxError(f"LINE {node.lineno}: 'global' IS NOT ALLOWED")

    def visit_Await(self, node: ast.Await) -> None:
        raise SandboxError(f"LINE {node.lineno}: 'await' IS NOT ALLOWED")


def check(code: str) -> ast.Module:
    if not isinstance(code, str) or not code.strip():
        raise SandboxError("EMPTY STRATEGY")
    if len(code) > MAX_CODE:
        raise SandboxError(f"STRATEGY IS TOO LONG ({MAX_CODE // 1000} KB MAX)")
    try:
        tree = ast.parse(code, "<strategy>")
    except SyntaxError as e:
        raise SandboxError(f"LINE {e.lineno}: SYNTAX ERROR: {e.msg}") from None
    _Checker().visit(tree)
    engine = next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "SignalEngine"), None)
    if engine is None or not any(isinstance(n, ast.FunctionDef) and n.name == "generate" for n in engine.body):
        raise SandboxError("A STRATEGY DEFINES class SignalEngine WITH def generate(self, data_map)")
    return tree


# --- worker side ---------------------------------------------------------------------------------------------------

SAFE_BUILTINS = ["abs", "all", "any", "bool", "dict", "divmod", "enumerate", "filter", "float", "frozenset", "int",
                 "isinstance", "issubclass", "iter", "len", "list", "map", "max", "min", "next", "object", "pow",
                 "print", "range", "repr", "reversed", "round", "set", "slice", "sorted", "str", "sum", "tuple",
                 "zip", "hash", "chr", "ord", "callable", "bytes", "bytearray", "super", "type",
                 "Exception", "ValueError", "TypeError", "KeyError", "IndexError", "ZeroDivisionError",
                 "ArithmeticError", "StopIteration", "RuntimeError", "NotImplementedError", "AttributeError",
                 "__build_class__"]


def disable_network() -> None:
    """Sockets are off for the rest of this worker's life (workers never need the network: the server fetches data)."""
    import socket

    def refuse(*_a, **_k):
        raise OSError("NETWORK DISABLED IN STRATEGIES")

    for name in ("socket", "create_connection", "getaddrinfo", "gethostbyname", "socketpair", "fromfd"):
        if hasattr(socket, name):
            setattr(socket, name, refuse)


# --- layer 3: the runtime guard ------------------------------------------------------------------------------------

_state = threading.local()  # .strict = how many strict() blocks this thread is inside; .busy = the hook is working
_hook_installed = False
_read_roots: tuple[str, ...] = ()

# Audit events strategy code never needs. Matched by prefix ("os.exec" covers os.execv, os.execve, ...).
REFUSED_EVENTS = ("subprocess.", "os.system", "os.exec", "os.spawn", "os.posix_spawn", "os.fork", "os.forkpty",
                  "os.startfile", "os.kill", "os.killpg", "os.remove", "os.rename", "os.mkdir", "os.rmdir", "os.chmod",
                  "os.chown", "os.truncate", "os.link", "os.symlink", "os.utime", "os.chdir", "os.putenv",
                  "os.unsetenv", "os.mkfifo", "os.mknod", "shutil.", "socket.", "ctypes.", "winreg.", "msvcrt.",
                  "webbrowser.", "urllib.", "http.client.", "ftplib.", "smtplib.", "pty.", "sys.addaudithook")


def _norm(path: str) -> str:
    return os.path.normcase(os.path.realpath(path))


def _compute_read_roots() -> tuple[str, ...]:
    """Where pandas / numpy may legitimately read inside strategy code (lazy imports, time-zone data): the Python
    install and its packages. Never the project folder or the user's folders (`.env`, the database)."""
    import site
    import sys

    roots = {sys.prefix, sys.base_prefix, sys.exec_prefix, sys.base_exec_prefix}
    with contextlib.suppress(Exception):
        roots.update(site.getsitepackages())
    return tuple(sorted({_norm(r) for r in roots if r}))


def _under_read_roots(path) -> bool:
    if isinstance(path, bytes):
        path = os.fsdecode(path)
    if not isinstance(path, str):  # an open file descriptor or None: nothing in a strategy needs one
        return False
    full = _norm(path)
    return any(full == r or full.startswith(r + os.sep) for r in _read_roots)


def _write_intent(mode, flags) -> bool:
    if isinstance(mode, str):
        return any(c in mode for c in "wax+")
    if isinstance(flags, int):
        return bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC))
    return False


def _audit(event: str, args: tuple) -> None:
    if not getattr(_state, "strict", 0) or getattr(_state, "busy", False):
        return
    if event == "open" or event in ("os.listdir", "os.scandir"):
        _state.busy = True  # the path checks below must not trigger this hook again
        try:
            if event == "open" and _write_intent(args[1] if len(args) > 1 else None, args[2] if len(args) > 2 else None):
                raise PermissionError("WRITING FILES IS NOT ALLOWED IN STRATEGIES")
            if not _under_read_roots(args[0] if args else None):
                raise PermissionError(f"{event.upper()} IS NOT ALLOWED IN STRATEGIES")
        finally:
            _state.busy = False
        return
    if event.startswith(REFUSED_EVENTS):
        raise PermissionError(f"{event.upper()} IS NOT ALLOWED IN STRATEGIES")


@contextlib.contextmanager
def strict():
    """While active, the audit hook vetoes file, process and network access (layer 3). Re-entrant, per thread."""
    import sys

    global _hook_installed, _read_roots
    if not _hook_installed:
        _read_roots = _compute_read_roots()
        sys.addaudithook(_audit)
        _hook_installed = True
    _state.strict = getattr(_state, "strict", 0) + 1
    try:
        yield
    finally:
        _state.strict -= 1


class Guarded:
    """What `load` returns: the strategy's SignalEngine, whose `generate` always runs under `strict()`."""

    def __init__(self, engine) -> None:
        self._engine = engine

    def generate(self, data_map):
        with strict():
            return self._engine.generate(data_map)


def load(code: str):
    """-> a Guarded SignalEngine. Call `check` first; this repeats it so the worker never trusts the caller."""
    import builtins

    check(code)
    disable_network()
    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if level or name not in ALLOWED_MODULES:
            raise ImportError(f"IMPORT {name} IS NOT ALLOWED")
        return real_import(name, globals, locals, fromlist, level)

    safe = {k: getattr(builtins, k) for k in SAFE_BUILTINS if hasattr(builtins, k)}
    safe["__import__"] = guarded_import
    env = {"__builtins__": safe, "__name__": "strategy"}
    with strict():  # module-level code and __init__ are strategy code too
        exec(compile(code, "<strategy>", "exec"), env)  # noqa: S102 - checked above, restricted builtins
        return Guarded(env["SignalEngine"]())
