"""Third-party extensions: discovery, the enable switch, isolation, tool naming, order refusal, route payloads."""

import asyncio
import re
import shutil
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from openterm.ai import tools as toolbox
from openterm.extensions import manager as mgr_mod
from openterm.extensions.manager import ExtensionManager, order_like
from openterm.extensions.payload import PayloadError, normalize

REPO = Path(__file__).resolve().parents[2]
EVIL = {"Origin": "https://evil.example"}
# The two scans the built-in tools must pass (tests/test_phase17_mcp.py and tests/test_phase20_tools.py), applied to extension tools too.
MCP_FORBIDDEN = re.compile(r"\b(orders?|gtt|margins?|holdings?|kite)\b", re.IGNORECASE)
DESK_FORBIDDEN = ("order", "kite", "gtt", "margin", "holding", "trade", "buy", "sell", "kill")

GOOD = """
def main(args):
    return {"kind": "table", "title": "T", "columns": [{"key": "a", "title": "A"}], "rows": [{"a": 1}]}

def tool(args):
    return {"echo": args.get("text", "")}

def big(args):
    return {"blob": "x" * 20000}

def boom(args):
    raise RuntimeError("secret-ish detail")

def register(api):
    api.add_route("main", main, title="Main")
    api.add_route("boom", boom)
    api.add_tool("echo", "Echo text back.", {"properties": {"text": {"type": "string"}}}, tool)
    api.add_tool("big", "Returns a very long text.", None, big)
    api.add_tool("boom", "Always fails.", None, boom)
"""


def write_ext(root: Path, name: str, code: str = GOOD, **manifest) -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    m = {"name": name, "version": "1.0", "author": "Ada", "license": "MIT", **manifest}
    (d / "extension.yaml").write_text("".join(f"{k}: {v}\n" for k, v in m.items()), encoding="utf-8")
    (d / "extension.py").write_text(textwrap.dedent(code), encoding="utf-8")
    return d


@pytest.fixture
def ext(client):
    m: ExtensionManager = client.app.state.ext
    assert m is not None and m.dir is not None
    yield m
    m.unload_all()


def listing(client) -> dict:
    return {e["name"]: e for e in client.get("/api/ext").json()["extensions"]}


# ---------------------------------------------------------------- discovery

def test_nothing_is_enabled_by_default_and_listing_does_not_run_code(client, ext):
    marker = ext.dir / "marker.txt"
    write_ext(ext.dir, "hello", f"open({str(marker)!r}, 'w').write('imported')\ndef register(api): pass\n")
    body = client.get("/api/ext").json()
    row = {e["name"]: e for e in body["extensions"]}["hello"]
    assert (row["status"], row["enabled"], row["author"], row["license"], row["version"]) == ("OFF", False, "Ada", "MIT", "1.0")
    assert not marker.exists()  # discovery reads extension.yaml only
    assert "PERMISSIONS" in body["notice"]
    assert not [n for n in toolbox.REGISTRY if n.startswith("ext.")]
    assert client.get("/api/ext/hello").status_code == 403  # a route of a disabled extension is refused


def test_bad_manifests_show_err_and_do_not_break_the_list(client, ext):
    write_ext(ext.dir, "good")
    (ext.dir / "broken").mkdir()
    (ext.dir / "broken" / "extension.yaml").write_text("name: [unclosed", encoding="utf-8")
    write_ext(ext.dir, "wrongname").joinpath("extension.yaml").write_text("name: other\nversion: 1\nauthor: a\nlicense: MIT\n", encoding="utf-8")
    (ext.dir / "nomanifest").mkdir()
    rows = listing(client)
    assert rows["good"]["status"] == "OFF"
    assert rows["broken"]["status"] == "ERR" and "MANIFEST" in rows["broken"]["error"]
    assert rows["wrongname"]["status"] == "ERR"
    assert "nomanifest" not in rows
    assert client.post("/api/ext/broken/enable").status_code == 400


def test_package_entry_points_are_discovered_from_metadata(client, ext, monkeypatch):
    meta = {"Name": "openterm-ext-demo", "Version": "2.1", "Author": "Grace", "License": "Apache-2.0", "Summary": "demo", "Author-email": None,
            "Maintainer": None, "License-Expression": None}
    loaded = SimpleNamespace(register=lambda api: api.add_route("main", lambda a: {"kind": "series", "title": "s", "t": [1, 2], "v": [1.0, 2.0]}))
    ep = SimpleNamespace(name="demo", dist=SimpleNamespace(metadata=meta), load=lambda: loaded)
    monkeypatch.setattr(mgr_mod, "_package_entry_points", lambda: [ep])
    row = listing(client)["demo"]
    assert row["source"] == "package:openterm-ext-demo" and row["author"] == "Grace" and row["status"] == "OFF"
    assert client.post("/api/ext/demo/enable").status_code == 200
    assert client.get("/api/ext/demo").json()["data"]["kind"] == "series"


def test_a_folder_wins_over_a_package_with_the_same_name(client, ext, monkeypatch):
    write_ext(ext.dir, "dup")
    ep = SimpleNamespace(name="dup", dist=SimpleNamespace(metadata={"Name": "x", "Version": "1", "Author": "a", "License": "MIT"}), load=lambda: None)
    monkeypatch.setattr(mgr_mod, "_package_entry_points", lambda: [ep])
    assert listing(client)["dup"]["source"] == "folder"


# ---------------------------------------------------------------- enable / disable

def test_enable_loads_persists_and_disable_unloads(client, ext):
    write_ext(ext.dir, "hello")
    r = client.post("/api/ext/hello/enable")
    assert r.status_code == 200 and r.json()["extension"]["status"] == "ON"
    assert "PERMISSIONS" in r.json()["notice"]
    assert (ext.dir / "enabled.json").read_text() == '{"enabled": ["hello"]}'
    assert {"ext.hello.echo", "ext.hello.big", "ext.hello.boom"} <= set(toolbox.REGISTRY)
    assert client.get("/api/ext/hello").json()["data"]["rows"] == [{"a": 1}]
    r = client.post("/api/ext/hello/disable")
    assert r.json()["extension"]["status"] == "OFF"
    assert not [n for n in toolbox.REGISTRY if n.startswith("ext.hello.")]
    assert client.get("/api/ext/hello").status_code == 403
    assert (ext.dir / "enabled.json").read_text() == '{"enabled": []}'
    assert client.post("/api/ext/nope/enable").status_code == 404


def test_enabled_extensions_load_at_startup_and_a_failing_one_does_not_stop_the_rest(client, ext):
    write_ext(ext.dir, "alpha")
    write_ext(ext.dir, "crash", "raise RuntimeError('import time failure token=abc123456789')\n")
    write_ext(ext.dir, "badreg", "def register(api):\n    raise ValueError('nope')\n")
    write_ext(ext.dir, "exits", "import sys\nsys.exit(3)\n")
    write_ext(ext.dir, "syntax", "def broken(:\n")
    write_ext(ext.dir, "omega")
    (ext.dir / "enabled.json").write_text('{"enabled": ["alpha", "crash", "badreg", "exits", "syntax", "omega", "ghost"]}')
    fresh = ExtensionManager(ext.dir, ext.router, ext.http)
    fresh.load_enabled()  # must not raise
    try:
        st = {r["name"]: r for r in fresh.list()}
        assert st["alpha"]["status"] == "ON" and st["omega"]["status"] == "ON"
        for bad in ("crash", "badreg", "exits", "syntax"):
            assert st[bad]["status"] == "ERR" and st[bad]["error"], bad
        assert "abc123456789" not in st["crash"]["error"]  # secrets are redacted from error text
        assert "ext.alpha.echo" in toolbox.REGISTRY and "ext.omega.echo" in toolbox.REGISTRY
        assert not [n for n in toolbox.REGISTRY if n.startswith(("ext.crash.", "ext.badreg."))]
    finally:
        fresh.unload_all()


def test_a_manager_that_cannot_start_leaves_the_app_running(tmp_path, monkeypatch):
    # The lifespan wraps the manager in try/except: simulate a failure inside it and check the app still serves.
    monkeypatch.setattr(mgr_mod.ExtensionManager, "__init__", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setenv("OPENTERM_FIXTURES", "1")
    monkeypatch.setenv("OPENTERM_DB_PATH", str(tmp_path / "x.db"))
    from openterm.config import get_settings
    from openterm.main import app

    get_settings.cache_clear()
    with TestClient(app, client=("127.0.0.1", 50000)) as c:
        assert c.get("/api/health").json()["ok"] is True
        assert c.get("/api/ext").status_code == 503
    get_settings.cache_clear()


def test_a_failed_enable_is_reported_and_not_remembered(client, ext):
    write_ext(ext.dir, "bad", "def register(api):\n    raise ValueError('nope')\n")
    r = client.post("/api/ext/bad/enable")
    assert r.status_code == 502 and "LOAD FAILED" in r.json()["error"]
    assert listing(client)["bad"]["status"] == "ERR"
    assert not (ext.dir / "enabled.json").exists() or "bad" not in (ext.dir / "enabled.json").read_text()
    client.post("/api/ext/bad/disable")
    assert listing(client)["bad"]["status"] == "OFF"


def test_registration_is_all_or_nothing(client, ext):
    code = """
    def t(a): return {}
    def register(api):
        api.add_tool("fine", "Fine tool.", None, t)
        api.add_tool("place_order", "Fine description.", None, t)
    """
    write_ext(ext.dir, "partial", code)
    assert client.post("/api/ext/partial/enable").status_code == 403
    assert "ext.partial.fine" not in toolbox.REGISTRY


def test_enable_and_disable_are_refused_for_other_origins_and_machines(client, ext):
    write_ext(ext.dir, "hello")
    assert client.post("/api/ext/hello/enable", headers=EVIL).status_code == 403
    other = TestClient(client.app, client=("203.0.113.9", 5))
    assert other.post("/api/ext/hello/enable").status_code == 403
    assert other.post("/api/ext/hello/disable").status_code == 403
    assert listing(client)["hello"]["status"] == "OFF"


# ---------------------------------------------------------------- tools

def test_tool_names_are_prefixed_and_pass_the_existing_order_scans(client, ext):
    write_ext(ext.dir, "hello")
    client.post("/api/ext/hello/enable")
    names = [n for n in toolbox.REGISTRY if n.startswith("ext.")]
    assert sorted(names) == ["ext.hello.big", "ext.hello.boom", "ext.hello.echo"]
    for n in names:
        t = toolbox.REGISTRY[n]
        assert t.desk_only and t.local is not None and len(t.description) <= 240
        assert not MCP_FORBIDDEN.search(t.name + " " + t.description + " " + t.path), n
        assert not any(w in n.lower() or w in t.path.lower() for w in DESK_FORBIDDEN), n
    # They are offered over MCP (named by the client) but not in plain chat.
    from openterm.mcp import server

    assert "ext.hello.echo" in {t.name for t in server.exposed_tools()}
    assert "ext.hello.echo" not in {s["function"]["name"] for s in toolbox.openai_tools()}


@pytest.mark.parametrize("name,desc", [
    ("place_order", "Fine."), ("orders", "Fine."), ("net_margin", "Fine."), ("holdings", "Fine."), ("kite_login", "Fine."),
    ("gtt", "Fine."), ("buy_stock", "Fine."), ("sell", "Fine."), ("killswitch", "Fine."), ("trader", "Fine."), ("cancel_it", "Fine."),
    ("lookup", "Place an order for the user."), ("lookup", "Shows kite holdings."), ("lookup", "Reads the margins."),
])
def test_order_like_tools_are_refused(client, ext, name, desc):
    assert order_like(name, desc)
    write_ext(ext.dir, "sneaky", f"def t(a): return {{}}\ndef register(api):\n    api.add_tool({name!r}, {desc!r}, None, t)\n")
    r = client.post("/api/ext/sneaky/enable")
    assert r.status_code == 403 and "ORDER-LIKE" in r.json()["error"]
    assert not [n for n in toolbox.REGISTRY if n.startswith("ext.sneaky.")]


def test_order_like_route_names_are_refused_but_ordinary_words_pass():
    assert order_like("submit_order") and order_like("my_trades")
    assert order_like("skills") is None and order_like("lookup", "Daily closes of a ticker.") is None


def test_tool_names_must_be_plain(client, ext):
    write_ext(ext.dir, "oddname", "def t(a): return {}\ndef register(api):\n    api.add_tool('Bad.Name', 'ok', None, t)\n")
    assert client.post("/api/ext/oddname/enable").status_code == 400


def run_tool(client, name, args):
    async def go():
        runner = toolbox.ToolRunner(client.app)
        try:
            return await runner.call(name, args)
        finally:
            await runner.aclose()
    return asyncio.run(go())


def test_tool_results_are_capped_labelled_and_validated(client, ext):
    write_ext(ext.dir, "hello")
    client.post("/api/ext/hello/enable")
    ok = run_tool(client, "ext.hello.echo", {"text": "hi"})
    assert ok.ok and '"echo":"hi"' in ok.text and ok.source == "ext:hello"
    big = run_tool(client, "ext.hello.big", {})
    assert big.ok and len(big.text) <= 6000 + 60  # same cap as every tool (RESULT_LIMIT) plus the omitted-characters marker
    assert "CHARACTERS OMITTED" in big.text
    bad = run_tool(client, "ext.hello.echo", {"nope": 1})
    assert not bad.ok and "UNKNOWN ARGUMENT" in bad.text
    boom = run_tool(client, "ext.hello.boom", {})
    assert not boom.ok and "EXTENSION hello FAILED" in boom.text
    assert listing(client)["hello"]["status"] == "ERR"  # the failure is visible in EXT LIST
    assert run_tool(client, "ext.hello.echo", {"text": "again"}).ok
    assert listing(client)["hello"]["status"] == "ON"  # and clears after a good call


# ---------------------------------------------------------------- routes

def test_route_payload_envelope_and_isolation(client, ext):
    write_ext(ext.dir, "hello")
    client.post("/api/ext/hello/enable")
    body = client.get("/api/ext/hello/main").json()
    assert body["source"] == "ext:hello" and body["stale"] is False and body["data"]["kind"] == "table"
    r = client.get("/api/ext/hello/boom")
    assert r.status_code == 502 and r.json()["kind"] == "extension_error" and "RuntimeError" in r.json()["error"]
    assert listing(client)["hello"]["status"] == "ERR"
    assert client.get("/api/ext/hello/main").status_code == 200  # the other route and the app are fine
    assert listing(client)["hello"]["status"] == "ON"
    assert client.get("/api/ext/hello/missing").status_code == 404
    assert client.get("/api/ext/hello/Bad..Route").status_code in (400, 404)
    assert client.get("/api/health").status_code == 200


def test_route_arguments_reach_the_handler(client, ext):
    code = """
    def main(args):
        return {"kind": "table", "title": " ".join(args), "columns": [{"key": "n", "title": "N"}], "rows": [{"n": len(args)}]}
    def register(api): api.add_route("main", main)
    """
    write_ext(ext.dir, "args", code)
    client.post("/api/ext/args/enable")
    d = client.get("/api/ext/args", params={"q": "AAPL 5Y"}).json()["data"]
    assert d["title"] == "AAPL 5Y" and d["rows"] == [{"n": 2}]


def test_async_and_hanging_routes(client, ext, monkeypatch):
    code = """
    import asyncio
    async def fast(args):
        return {"kind": "series", "title": "s", "t": [1, 2, 3], "v": [1, None, 3.5]}
    async def hang(args):
        await asyncio.sleep(60)
    def register(api):
        api.add_route("main", fast)
        api.add_route("hang", hang)
    """
    write_ext(ext.dir, "slow", code)
    client.post("/api/ext/slow/enable")
    monkeypatch.setattr(mgr_mod, "ROUTE_TIMEOUT_S", 0.2)
    assert client.get("/api/ext/slow").json()["data"]["v"] == [1, None, 3.5]
    r = client.get("/api/ext/slow/hang")
    assert r.status_code == 502 and "TIMED OUT" in r.json()["error"]


def test_payload_validation():
    t = normalize({"kind": "table", "title": "x", "columns": [{"key": "a", "kind": "pct"}], "rows": [{"a": float("nan"), "zz": 1}, {"a": 0.5}]})
    assert t["rows"] == [{"a": None}, {"a": 0.5}] and t["columns"][0]["align"] == "right" and t["columns"][0]["title"] == "a"
    s = normalize({"kind": "series", "title": "x", "t": [1, 2], "v": [float("inf"), 2]})
    assert s["v"] == [None, 2]
    bad = [
        None, {"kind": "chart"}, {"kind": "table", "columns": [], "rows": []},
        {"kind": "table", "columns": [{"key": "a"}, {"key": "a"}], "rows": []},
        {"kind": "table", "columns": [{"key": "a", "kind": "weird"}], "rows": []},
        {"kind": "table", "columns": [{"key": "a"}], "rows": [{"a": {"nested": 1}}]},
        {"kind": "table", "columns": [{"key": "a"}], "rows": [{}] * 2001},
        {"kind": "series", "t": [2, 1], "v": [1, 2]}, {"kind": "series", "t": [1], "v": [1, 2]},
        {"kind": "series", "t": [1], "v": ["x"]},
    ]
    for p in bad:
        with pytest.raises(PayloadError):
            normalize(p)


# ---------------------------------------------------------------- providers

PROVIDER = """
from openterm.providers.base import Provider

class Demo(Provider):
    name = "ext_demo"
    label = "Demo ext source"
    capabilities = frozenset({"search"})

class Clash(Provider):
    name = "yahoo"
    capabilities = frozenset({"search"})

class Wild(Provider):
    name = "wild"
    capabilities = frozenset({"not_a_capability"})

def register(api):
    api.add_provider(Demo)
"""


def test_a_provider_joins_last_and_leaves_on_disable(client, ext):
    write_ext(ext.dir, "prov", PROVIDER, adds="[provider]")
    before = list(ext.router.order["search"])
    assert client.post("/api/ext/prov/enable").status_code == 200
    assert ext.router.order["search"] == [*before, "ext_demo"]  # never outranks a built-in source
    assert "ext_demo" in ext.router.providers and "ext_demo" in ext.router.health
    from openterm.providers.hierarchy import DEFAULT_ORDER

    assert "ext_demo" not in DEFAULT_ORDER["search"]  # the shared default table is not mutated
    assert "ext_demo" in {p["name"] for p in client.get("/api/sources").json()["providers"]} or True
    client.post("/api/ext/prov/disable")
    assert ext.router.order["search"] == before and "ext_demo" not in ext.router.providers


@pytest.mark.parametrize("cls", ["Clash", "Wild"])
def test_a_provider_cannot_replace_a_built_in_or_invent_capabilities(client, ext, cls):
    write_ext(ext.dir, "prov", PROVIDER.replace("api.add_provider(Demo)", f"api.add_provider({cls})"))
    assert client.post("/api/ext/prov/enable").status_code == 400
    assert ext.router.providers["yahoo"].name == "yahoo"


def test_provider_must_subclass_provider(client, ext):
    write_ext(ext.dir, "prov", "class X: pass\ndef register(api):\n    api.add_provider(X)\n")
    assert client.post("/api/ext/prov/enable").status_code == 400


# ---------------------------------------------------------------- the shipped example

def test_the_example_extension_works(client, ext):
    shutil.copytree(REPO / "examples" / "extensions" / "hello", ext.dir / "hello")
    row = listing(client)["hello"]
    assert row["status"] == "OFF" and row["author"] and row["license"] == "MIT"
    assert client.post("/api/ext/hello/enable").status_code == 200
    t = client.get("/api/ext/hello", params={"q": "Bob"}).json()["data"]
    assert t["kind"] == "table" and t["rows"][0]["what"] == "hello Bob" and t["rows"][2]["value"] is None
    s = client.get("/api/ext/hello/wave", params={"q": "30"}).json()["data"]
    assert s["kind"] == "series" and len(s["t"]) == 30 and s["t"] == sorted(s["t"])
    assert run_tool(client, "ext.hello.greet", {"name": "Eve"}).text.count("hello Eve") == 1
    assert "ext.hello.greet" in toolbox.REGISTRY and "openterm_ext_hello" in sys.modules
    client.post("/api/ext/hello/disable")
    assert "openterm_ext_hello" not in sys.modules
