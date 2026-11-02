"""BT editor backend: starter templates and the dry-run sandbox check route. No network."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from openterm.bt import sandbox
from openterm.bt.templates import TEMPLATES

IDS = ["sma_cross", "rsi_mean_reversion", "breakout"]


def synthetic_ohlcv(n: int = 300) -> pd.DataFrame:
    """A random walk with a seeded generator so the test is repeatable. Waves are added so every template
    gets trends (SMA, breakout) and dips (RSI) to react to."""
    rng = np.random.default_rng(7)
    close = 100 + np.cumsum(rng.normal(0, 1, n)) + 10 * np.sin(np.arange(n) / 15)
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) + rng.uniform(0, 1, n)
    low = np.minimum(open_, close) - rng.uniform(0, 1, n)
    idx = pd.date_range("2023-01-02", periods=n, freq="B")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close,
                         "volume": rng.integers(1_000, 5_000, n)}, index=idx)


def test_template_order_and_keys():
    assert [t["id"] for t in TEMPLATES] == IDS
    for t in TEMPLATES:
        assert set(t) == {"id", "title", "summary", "code"}
        assert all(isinstance(v, str) and v for v in t.values())


@pytest.mark.parametrize("tpl", TEMPLATES, ids=IDS)
def test_template_passes_sandbox_check(tpl):
    sandbox.check(tpl["code"])


@pytest.mark.parametrize("tpl", TEMPLATES, ids=IDS)
def test_template_generates_valid_weights(tpl, monkeypatch):
    # `load` normally switches sockets off for the whole process (right for a job worker, wrong for a test run).
    monkeypatch.setattr(sandbox, "disable_network", lambda: None)
    df = synthetic_ohlcv()
    out = sandbox.load(tpl["code"]).generate({"AAA": df})
    s = out["AAA"]
    assert isinstance(s, pd.Series)
    assert s.index.equals(df.index)
    assert s.between(-1, 1).all()  # also false for NaN, so no NaN may leak out of the template
    assert (s != 0).any()


def test_templates_route_returns_all_three(client):
    r = client.get("/api/bt/templates")
    assert r.status_code == 200
    items = r.json()["templates"]
    assert [t["id"] for t in items] == IDS
    assert all(set(t) == {"id", "title", "summary", "code"} for t in items)


def test_check_route_accepts_a_template(client):
    r = client.post("/api/bt/check", json={"code": TEMPLATES[0]["code"]})
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_check_route_reports_a_rejected_strategy_as_200(client):
    r = client.post("/api/bt/check", json={"code": "import os\n" + TEMPLATES[0]["code"]})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "LINE" in body["error"]


def test_check_route_saves_nothing(client):
    client.post("/api/bt/check", json={"code": TEMPLATES[0]["code"]})
    assert client.get("/api/bt/strategies").json()["strategies"] == []


@pytest.mark.parametrize("body", [{}, {"code": 5}, {"code": None}])
def test_check_route_needs_string_code(client, body):
    r = client.post("/api/bt/check", json=body)
    assert r.status_code == 400
    assert r.json()["kind"] == "bad_request"
