"""Audit E-1 and E-2: routes skip jsonable_encoder; the BT run list and trim use a covering index."""

from decimal import Decimal

import orjson
import pytest
from pydantic import BaseModel

from openterm import responses
from openterm.responses import Orjson, OrjsonRoute


def test_every_http_route_uses_the_orjson_route_class(client):
    from fastapi.routing import APIRoute

    def walk(routes):  # FastAPI 0.143 keeps included routers nested (`_IncludedRouter.original_router`)
        for r in routes:
            inner = getattr(r, "original_router", None)
            yield from walk(inner.routes) if inner is not None else [r]

    routes = [r for r in walk(client.app.routes) if isinstance(r, APIRoute)]
    assert len(routes) > 100
    assert [r.path for r in routes if not isinstance(r, OrjsonRoute)] == []


def test_dict_routes_never_run_jsonable_encoder(client, monkeypatch):
    """E-1: with no response_model FastAPI walked every returned dict in pure Python on the event loop before orjson."""
    import fastapi.routing

    def boom(*a, **k):
        raise AssertionError("jsonable_encoder ran")

    monkeypatch.setattr(fastapi.routing, "jsonable_encoder", boom)
    for url in ("/api/health", "/api/history?symbol=SYN0001&range=1Y", "/api/screener", "/api/world/geo/quakes", "/api/jobs"):
        r = client.get(url)
        assert r.status_code < 500, (url, r.status_code, r.text[:200])
        assert r.headers["content-type"].startswith("application/json")


class _Model(BaseModel):
    a: int
    b: str = "x"


def test_orjson_renders_what_jsonable_encoder_accepted():
    body = orjson.loads(Orjson({"m": _Model(a=1), "s": {3}, "d": Decimal("1.5"), "t": (1, 2), "n": float("nan")}).body)
    assert body == {"m": {"a": 1, "b": "x"}, "s": [3], "d": 1.5, "t": [1, 2], "n": None}
    with pytest.raises(TypeError):
        Orjson({"o": object()})


def test_sync_endpoints_stay_sync():
    """FastAPI runs a sync endpoint in its thread pool; the wrapper must not turn it into a coroutine function."""
    import inspect

    def f():
        return {"a": 1}

    async def g():
        return [1]

    assert not inspect.iscoroutinefunction(responses._wrap(f)) and inspect.iscoroutinefunction(responses._wrap(g))
    assert isinstance(responses._wrap(f)(), Orjson)


async def test_bt_runs_list_and_trim_use_the_covering_index(tmp_path):
    """E-2: created_at and meta sit after the equity/trade blobs; without the index both queries walked every blob."""
    from openterm.bt.store import BtStore
    from openterm.db import migrate, open_db

    db = await open_db(tmp_path / "bt.db")
    await migrate(db)
    try:
        store = BtStore(db, tmp_path)
        assert await store.runs() == []
        async with db.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='bt_runs_recent'") as cur:
            assert await cur.fetchone() is not None
        for sql in ("SELECT id, metrics, meta, created_at FROM bt_runs ORDER BY created_at DESC LIMIT 200",
                    "SELECT id FROM bt_runs ORDER BY created_at DESC LIMIT 200"):
            async with db.execute("EXPLAIN QUERY PLAN " + sql) as cur:
                plan = " ".join(str(r[-1]) for r in await cur.fetchall())
            assert "COVERING INDEX bt_runs_recent" in plan, plan
    finally:
        await db.close()
