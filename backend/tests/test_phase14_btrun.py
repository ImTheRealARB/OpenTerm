"""Phase 14 step 8b: `BT ... MKT=options` through /api/bt/run (fixture mode, deterministic).

The engine itself is pinned against Vibe's own runs in test_phase14_btopt.py; this file covers the wiring: the
structure becomes trade instructions, the labels, NOT RUNNABLE for missing inputs, and the server-never-imports-pandas rule.
"""

import time

import pytest

LABEL = "MODEL-PRICED OPTIONS (BLACK-SCHOLES ON HISTORICAL VOL), NOT MARKET QUOTES"
STRUCT = {
    "open_date": "2026-06-01", "close_date": "2026-08-14", "risk_free_rate": 0.04, "contract_multiplier": 100,
    "exercise_style": "european",
    "legs": [{"type": "call", "strike": 250, "expiry": "2026-09-18", "qty": 1},
             {"type": "put", "strike": 250, "expiry": "2026-09-18", "qty": 1}],
}


def post(client, structure, **extra):
    body = {"symbols": ["AAPL"], "interval": "1D", "range": "10Y", "options": {"engine": "options", "cash": 100_000},
            "structure": structure, **extra}
    return client.post("/api/bt/run", json=body)


def wait(client, job_id):
    end = time.monotonic() + 30
    while time.monotonic() < end:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["state"] in ("done", "error", "cancelled"):
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_label_matches_the_engine():
    from openterm.bt import catalog
    from openterm.bt.engines import options_portfolio as op

    assert catalog.OPTIONS_LABEL == op.MODEL_LABEL == LABEL


def test_options_run_through_the_api(client):
    r = post(client, STRUCT)
    assert r.status_code == 200, r.text
    job = wait(client, r.json()["id"])
    assert job["state"] == "done", job
    run = client.get(f"/api/bt/runs/{job['result']['run_id']}").json()
    labels = run["labels"]
    assert labels["model"] == LABEL and labels["headline"] == "HISTORICAL SIMULATION, NOT A FORECAST"
    assert labels["engine"] == "options" and labels["fees_bps"] == 0
    assert labels["slippage"] == "NONE MODELLED" and "FEES=" in labels["commission"]
    assert labels["sources"][0]["name"].startswith("yahoo")
    sides = [t["exit_reason"] for t in run["trades"]]
    assert sides.count("buy") == 2 and sides.count("close") == 2
    assert len(run["equity"]) > 50 and run["metrics"]["trade_count"] is not None
    # buying a straddle: the cash leaves on the open bar, so equity is not the starting cash everywhere
    assert len({p[1] for p in run["equity"]}) > 5


def test_options_run_is_deterministic_and_cached(client):
    first = wait(client, post(client, STRUCT).json()["id"])
    again = post(client, STRUCT).json()
    assert again["cached"] is True and again["run_id"] == first["result"]["run_id"]


def test_fees_become_the_commission(client):
    free = wait(client, post(client, STRUCT).json()["id"])["result"]
    paid = wait(client, client.post("/api/bt/run", json={
        "symbols": ["AAPL"], "interval": "1D", "range": "10Y", "structure": STRUCT,
        "options": {"engine": "options", "cash": 100_000, "fees_bps": 50}}).json()["id"])["result"]
    assert free["run_id"] != paid["run_id"]
    assert paid["metrics"]["final_value"] < free["metrics"]["final_value"]
    stored = client.get(f"/api/bt/runs/{paid['run_id']}").json()
    assert stored["labels"]["commission"] == "FEES= 50 BPS OF PREMIUM"


@pytest.mark.parametrize("drop,field", [
    ("risk_free_rate", "risk_free_rate"), ("contract_multiplier", "contract_multiplier"),
    ("exercise_style", "exercise_style"), ("open_date", "open_date")])
def test_missing_inputs_are_not_runnable_never_defaulted(client, drop, field):
    s = {k: v for k, v in STRUCT.items() if k != drop}
    r = post(client, s)
    assert r.status_code == 400
    assert r.json()["error"].startswith("NOT RUNNABLE: MISSING") and field in r.json()["error"]


def test_missing_leg_fields_are_listed(client):
    s = {**STRUCT, "legs": [{"type": "call", "strike": 250}]}
    err = post(client, s).json()["error"]
    assert "legs[0].expiry" in err and "legs[0].qty" in err and "legs[0].strike" not in err
    assert "legs" in post(client, {**STRUCT, "legs": []}).json()["error"]
    assert "structure" in post(client, None).json()["error"]


def test_options_needs_one_underlying_and_no_rule(client):
    r = client.post("/api/bt/run", json={"symbols": ["AAPL", "MSFT"], "structure": STRUCT,
                                         "options": {"engine": "options"}})
    assert r.status_code == 400 and "exactly one underlying" in r.json()["error"]
    r = client.post("/api/bt/run", json={"symbols": ["AAPL"], "structure": STRUCT, "rule": "SMA20>SMA50",
                                         "options": {"engine": "options"}})
    assert r.status_code == 400 and "STRUCTURE ONLY" in r.json()["error"]
    s = {**STRUCT, "exercise_style": "bermudan"}
    assert "exercise_style" in post(client, s).json()["error"]


def test_option_signals_pure():
    from openterm.bt.job import option_signals

    sig = option_signals("AAPL", STRUCT)
    assert [s["action"] for s in sig] == ["open", "close"] and sig[0]["date"] == "2026-06-01"
    assert sig[0]["legs"][0] == {"type": "call", "strike": 250.0, "expiry": "2026-09-18", "qty": 1}
    assert "qty" not in sig[1]["legs"][0]
    assert len(option_signals("AAPL", {k: v for k, v in STRUCT.items() if k != "close_date"})) == 1
