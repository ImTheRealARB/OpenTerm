"""Phase 26 (strategy lab), minimal test bar: the pure maths and parsers, plus one optimiser run and one forward test
through the API in fixture mode."""

import math
import time

import numpy as np
import pytest

from openterm.bt import fwd, optspace, overfit, stops

# --- optspace: templates, grid, random, GA -----------------------------------------------------------------------------


def test_parse_render_and_count():
    parts, params = optspace.parse("SMA{10..50:5}>SMA{50..200:25}")
    assert [p.values for p in params] == [tuple(str(v) for v in range(10, 55, 5)), tuple(str(v) for v in range(50, 225, 25))]
    assert optspace.count(params) == 9 * 7
    assert optspace.render(parts, params, (1, 2)) == "SMA15>SMA100"
    assert optspace.shown(parts, params) == "SMA{P1}>SMA{P2}"
    _, dec = optspace.parse("RSI14<{0.5..1.5:0.5}")
    assert dec[0].values == ("0.5", "1", "1.5")


@pytest.mark.parametrize("bad", ["SMA20>SMA50", "SMA{10..}>SMA50", "SMA{50..10}>SMA5", "SMA{1..2:0}>SMA5"])
def test_parse_refuses(bad):
    with pytest.raises(optspace.SpaceError):
        optspace.parse(bad)


def test_grid_cap_and_code_template():
    _, params = optspace.parse("SMA{1..100}>SMA{1..100}")
    with pytest.raises(optspace.SpaceError, match="AT MOST 2,000"):
        optspace.grid(params)
    code = "FAST = 20\nSLOW: int = 100  # slow average\n"
    out = optspace.code_template(code, {"FAST": "{10..30:10}", "SLOW": "{50..150:50}"})
    assert out == "FAST = {10..30:10}\nSLOW: int = {50..150:50}  # slow average\n"
    with pytest.raises(optspace.SpaceError, match="EXACTLY ONE"):
        optspace.code_template(code, {"MISSING": "{1..2}"})


def test_random_and_ga_are_reproducible_and_ga_finds_the_peak():
    _, params = optspace.parse("A{0..29}B{0..29}")
    assert optspace.random_sample(params, 50, 7) == optspace.random_sample(params, 50, 7)
    assert len(set(optspace.random_sample(params, 50, 7))) == 50

    def score(idx):  # one smooth peak at (20, 9)
        return -((idx[0] - 20) ** 2 + (idx[1] - 9) ** 2)

    a = optspace.genetic(params, score, 20, 15, 3)
    b = optspace.genetic(params, score, 20, 15, 3)
    assert list(a) == list(b)
    assert max(a, key=a.get) == (20, 9)
    assert len(a) <= 20 * 15


def test_edges_and_neighbours():
    _, params = optspace.parse("X{1..5}Y{1..2}")
    assert optspace.on_edge((0, 0), params) == ["P1"]  # P2 has only 2 values: an end says nothing
    assert optspace.on_edge((2, 1), params) == []
    assert sorted(optspace.neighbours((0, 1), params)) == [(0, 0), (1, 1)]


# --- overfit: PBO, efficient front, walk-forward ------------------------------------------------------------------------


def test_pbo_noise_high_dominant_low():
    rng = np.random.default_rng(0)
    noise = rng.normal(0, 0.01, (1000, 40))
    assert overfit.pbo_cscv(noise)["pbo"] > 0.3
    strong = noise.copy()
    strong[:, 7] += 0.004  # one column with a real, steady edge wins in sample AND out of sample
    res = overfit.pbo_cscv(strong)
    assert res["pbo"] < 0.05 and res["splits"] == 252
    assert overfit.pbo_cscv(noise[:, :1]) is None


def test_efficient_front():
    pts = [(0.10, -0.20), (0.15, -0.30), (0.08, -0.25), (0.20, -0.30), (None, -0.1)]
    assert overfit.efficient(pts) == {0, 3}


def test_walk_forward_stitches_out_of_sample():
    r = np.zeros((120, 2))
    r[:, 1] = 0.001  # column 1 always better: every window picks it
    times = list(range(120))
    wf = overfit.walk_forward(r, times, 5, False, "RETURN", 252, 100.0)
    assert [w["best"] for w in wf["windows"]] == [1] * 5
    assert wf["equity"][0][0] == 20 and len(wf["equity"]) == 100
    assert wf["equity"][-1][1] == pytest.approx(100 * 1.001**100, rel=1e-6)
    assert overfit.walk_forward(r[:10], times[:10], 5, False, "RETURN", 252, 100.0) is None


# --- stops: which level came first --------------------------------------------------------------------------------------


def test_stop_target_decisions():
    stop, target = stops.levels(100.0, 1, 5, 10)
    assert (stop, target) == pytest.approx((95.0, 110.0))
    assert stops.decide(1, 100, 104, 96, stop, target, None) is None
    assert stops.decide(1, 100, 104, 94, stop, target, None) == ("stop", stop, "single")
    assert stops.decide(1, 93, 104, 90, stop, target, None) == ("stop", 93, "gap")
    assert stops.decide(1, 100, 112, 94, stop, target, None) == ("stop", stop, "stop_first")
    assert stops.decide(1, 100, 112, 94, stop, target, [(103, 99), (111, 101), (101, 94)]) == ("target", target, "intrabar")
    assert stops.decide(1, 100, 112, 94, stop, target, [(112, 94)]) == ("stop", stop, "stop_first")
    s_stop, s_target = stops.levels(100.0, -1, 5, 10)  # a short's stop is above its entry
    assert stops.decide(-1, 100, 106, 99, s_stop, s_target, None) == ("stop", s_stop, "single")


# --- fwd: the forward-test book -----------------------------------------------------------------------------------------


def test_forward_book_fills_next_open_and_marks_catch_up():
    day = 86_400
    t = [i * day for i in range(6)]
    o = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0]
    c = [10.5, 11.5, 12.5, 13.5, 14.5, 15.5]
    st = fwd.new_state("x", "AAPL", "s", "1D", 1000.0, now=t[1] + 10)  # bar 1 was forming at the start
    fwd.step(st, t[:4], o[:4], [0, 1, 1], now=0)  # bars 0-2 complete; bar 0 ended before the start
    assert [d[:2] for d in st["decisions"]] == [[t[1], 1], [t[2], 1]]
    assert [d[2] for d in st["decisions"]] == [True, False]  # two bars decided at once: the older one is CATCH-UP
    assert st["fills"] == [[t[2], "BUY", pytest.approx(1000 / 12), 12.0]]  # decided on bar 1, filled at bar 2's open
    fwd.step(st, t, o, [0, 1, 1, 0, 0], now=0)
    assert st["fills"][-1][1] == "SELL" and st["fills"][-1][3] == 14.0 and st["pos"] == 0
    cmp = fwd.compare(st, t, o, c, [0, 1, 0, 0, 0])  # today's data says flat on bar 2
    assert cmp["n_diverged"] == 1 and cmp["diverged"][0] == [t[2], 1, 0]
    assert math.isclose(cmp["live_return"], 1000 / 12 * 14 / 1000 - 1)


# --- API: one optimiser run and one forward test (fixture mode) ---------------------------------------------------------


def _wait(client, job_id, timeout=120.0) -> dict:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["state"] in ("done", "error", "cancelled"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} still {job['state']}")


def test_api_opt_grid_with_walk_forward(client):
    r = client.post("/api/bt/opt", json={"rule": "SMA{10..30:10}>SMA{50..100:50}", "symbols": ["AAPL"], "interval": "1D",
                                         "range": "10Y", "wf": 3, "options": {"stop_pct": 8}})
    assert r.status_code == 200, r.text
    assert r.json()["budget"] == 6
    job = _wait(client, r.json()["id"])
    assert job["state"] == "done", job
    res = job["result"]
    assert len(res["runs"]) == 6 and res["guards"]["trials"] == 6 and res["best"] is not None
    assert res["guards"]["pbo"] is not None and len(res["wf"]["windows"]) == 3
    assert any(run.get("front") for run in res["runs"])
    assert res["labels"]["headline"] == "HISTORICAL SIMULATION, NOT A FORECAST" and "STOP 8" in res["labels"]["stops"]
    bad = client.post("/api/bt/opt", json={"rule": "SMA{1..100}>SMA{1..100}", "symbols": ["AAPL"], "interval": "1D", "range": "10Y"})
    assert bad.status_code == 400 and "2,000" in bad.json()["error"]


def test_api_forward_test_runs_and_compares(client):
    put = client.put("/api/bt/strategies/fwdrule", json={"rule": "SMA20>SMA50"})
    assert put.status_code == 200, put.text
    r = client.post("/api/bt/fwd", json={"symbol": "AAPL", "strategy": "fwdrule", "interval": "1D"})
    assert r.status_code == 200, r.text
    fwd_id = r.json()["test"]["id"]
    assert _wait(client, r.json()["job"]["id"])["state"] == "done"
    got = client.get(f"/api/bt/fwd/{fwd_id}").json()
    assert got["checked"] is not None and got["backtest"] is not None
    assert client.post(f"/api/bt/fwd/{fwd_id}/stop").json()["status"] == "stopped"
    assert any(t["id"] == fwd_id for t in client.get("/api/bt/fwd").json()["tests"])
