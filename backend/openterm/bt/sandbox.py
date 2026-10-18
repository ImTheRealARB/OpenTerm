"""Strategy sandbox (spec decision E): an allowlist, not a denylist. Defence in depth, not a kernel sandbox: strategies
only ever come from this machine (loopback), and run in a job worker with a time limit, a memory cap and no network.

`check(code)` is pure (the server calls it before saving or running). `load(code)` runs in the worker: restricted
builtins, a guarded `__import__`, and sockets disabled for the life of the worker.
"""

from __future__ import annotations

import ast

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


def load(code: str):
    """-> a SignalEngine instance. Call `check` first; this repeats it so the worker never trusts the caller."""
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
    exec(compile(code, "<strategy>", "exec"), env)  # noqa: S102 - checked above, restricted builtins
    return env["SignalEngine"]()
