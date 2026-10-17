"""Phase 12 step 6 additions: BT MC / BT WF endpoints and jobs around Vibe's validation functions (no network)."""

import time

import pytest


def _wait(client, job_id, timeout=90.0) -> dict:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["state"] in ("done", "error", "cancelled"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} still {job['state']}")


def _run(client, rule="SMA20>SMA50"):
    r = client.post("/api/bt/run", json={"rule": rule, "symbols": ["AAPL"], "interval": "1D", "range": "10Y",
                                         "options": {"adjusted": False}})
    assert r.status_code == 200, r.text
    job = _wait(client, r.json()["id"])
    assert job["state"] == "done", job
    return job["result"]["run_id"]


def test_mc_result_carries_bootstrap_labels_and_histogram_data(client):
    rid = _run(client)
    job = _wait(client, client.post(f"/api/bt/runs/{rid}/mc", json={"n_simulations": 200, "seed": 7}).json()["id"])
    res = job["result"]
    assert job["state"] == "done" and res["run_id"] == rid and res["n_simulations"] == 200
    assert len(res["sharpe_samples"]) == 200 and res["bootstrap"]["ci_lower"] <= res["bootstrap"]["ci_upper"]
    assert res["labels"]["headline"] == "HISTORICAL SIMULATION, NOT A FORECAST" and "SEED 7" in res["labels"]["validation"]
    assert res["equity_paths"]["actual"] and res["labels"]["engine"] == "us"


def test_same_validation_twice_is_cached_and_new_options_are_not(client):
    rid = _run(client)
    first = client.post(f"/api/bt/runs/{rid}/wf", json={"n_windows": 4}).json()
    _wait(client, first["id"])
    again = client.post(f"/api/bt/runs/{rid}/wf", json={"n_windows": 4}).json()
    other = client.post(f"/api/bt/runs/{rid}/wf", json={"n_windows": 3}).json()
    assert again["state"] == "done" and again.get("cached") is True
    assert other["id"] != first["id"]
    assert _wait(client, other["id"])["result"]["n_windows"] == 3


@pytest.mark.parametrize(("path", "body"), [
    ("mc", {"n_simulations": 50}), ("mc", {"n_simulations": True}), ("mc", {"confidence": 2}), ("mc", {"seed": -1}),
    ("wf", {"n_windows": 1}), ("wf", {"n_windows": "5"}),
])
def test_bad_validation_options_are_400(client, path, body):
    rid = _run(client)
    r = client.post(f"/api/bt/runs/{rid}/{path}", json=body)
    assert r.status_code == 400 and r.json()["kind"] == "bad_request"


def test_validation_of_an_unknown_run_is_404(client):
    assert client.post("/api/bt/runs/nope/mc", json={}).status_code == 404
    assert client.post("/api/bt/runs/nope/wf", json={}).status_code == 404


def test_too_few_trades_fails_with_the_reason_not_a_fake_p_value(client):
    rid = _run(client, "SMA20>SMA50 AND SMA50>SMA200 AND RSI14>99")
    job = _wait(client, client.post(f"/api/bt/runs/{rid}/mc", json={}).json()["id"])
    assert job["state"] == "error" and "AT LEAST 3 TRADES" in job["error"]


def test_validation_jobs_cannot_be_submitted_from_the_generic_jobs_endpoint(client):
    for kind in ("bt.mc", "bt.wf"):
        assert client.post("/api/jobs", json={"kind": kind, "params": {}}).status_code in (400, 403)
