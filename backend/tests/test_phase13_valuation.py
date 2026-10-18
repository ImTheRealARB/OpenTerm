"""Phase 13 step 4: how DCF, WACC and RV are fed (parameters, filed figures, honest refusals)."""

import pytest

from openterm.research import valuation as vp


def test_percent_arguments_become_ratios_and_choices_map_to_engine_names():
    p = vp.parse_params({"symbol": "AAPL", "erp": "5.5", "g": "2.5", "exitx": "14", "basis": "CURRENT", "conv": "mid", "tv": "exit",
                         "years": "7", "other": "0", "peers": "msft, goog"})
    assert p["erp"] == pytest.approx(0.055) and p["g"] == pytest.approx(0.025) and p["exitx"] == 14.0
    assert (p["basis"], p["conv"], p["tv"]) == ("current", "mid_year", "exit_multiple")
    assert p["years"] == 7 and p["other"] == 0.0 and p["peers"] == ["MSFT", "GOOG"]


@pytest.mark.parametrize("q", [{"erp": "abc"}, {"basis": "sideways"}, {"years": "0"}, {"years": "99"}, {"other": "1"},
                               {"policy": "calendar"}, {"nope": "1"}, {"erp": "nan"}])
def test_bad_arguments_are_refused_with_a_usage_message(q):
    with pytest.raises(vp.ParamError):
        vp.parse_params(q)


def test_ltm_from_the_filings_equals_the_sum_of_the_last_four_quarters(client):
    """FY + year-to-date - prior year-to-date is the same number as the newest four quarters added up."""
    research = client.app.state.service.research

    async def go():
        fa, _ = await research._fin("AAPL", "A")
        fq, _ = await research._fin("AAPL", "Q")
        return fa, fq

    fa, fq = client.portal.call(go)
    for key in ("revenue", "operating_income"):
        fy, ytd, pytd = vp._flow_parts(fa, fq, lambda f, i, k=key: f.v(k, i))
        last4 = sum(fq.v(key, i) for i in range(4))
        assert fy + ytd - pytd == pytest.approx(last4, rel=1e-9), key


def test_dcf_refuses_a_terminal_growth_at_or_above_wacc(client):
    q = {"symbol": "AAPL", "erp": 5.5, "g": 30, "exitx": 14, "growth": 5, "basis": "current", "conv": "mid", "tv": "perp",
         "kd": 3.5, "other": 0}
    p = client.get("/api/valuation/dcf", params=q).json()["data"]
    assert p["runnable"] is False and p["status"].startswith("NOT RUNNABLE") and "growth" in p["status"].lower()
    assert p["result"] is None


def test_dcf_without_a_cost_of_debt_says_apple_stopped_tagging_interest(client):
    q = {"symbol": "AAPL", "erp": 5.5, "g": 2.5, "exitx": 14, "growth": 5, "basis": "current", "conv": "mid", "tv": "perp", "other": 0}
    p = client.get("/api/valuation/dcf", params=q).json()["data"]
    assert p["runnable"] is False and p["missing"] == ["pretax_cost_of_debt"]
    why = next(r for r in p["sections"][0]["rows"] if r["input"] == "PRETAX COST OF DEBT")
    assert why["value"] == "MISSING" and "KD=" in why["source"]
    assert any("TO RUN: DCF AAPL" in n for n in p["notes"])


def test_target_basis_needs_its_weight_and_uses_it(client):
    q = {"symbol": "AAPL", "erp": 5.5, "basis": "target", "kd": 3.5}
    assert "target_equity_weight" in client.get("/api/valuation/wacc", params=q).json()["data"]["missing"]
    r = client.get("/api/valuation/wacc", params={**q, "ew": 80}).json()["data"]["result"]
    assert r["equity_weight"] == pytest.approx(0.8) and r["debt_weight"] == pytest.approx(0.2)


def test_rv_with_default_peers_lists_who_was_left_out_and_why(client):
    d = client.get("/api/valuation/rv", params={"symbol": "AAPL"}).json()["data"]
    assert d["runnable"] is True and d["result"]["peers"] == ["META"]  # AMZN/TSLA/GOOG/MSFT have no usable recorded data
    notes = " ".join(d["notes"])
    assert "EXCLUDED AMZN" in notes and "EXCLUDED MSFT" in notes
    assert any("fewer than 3" in w for w in d["warnings"])  # the engine's own small-sample warning is shown
    assert any("EV BRIDGE OMITS" in n for n in d["notes"])
    peers = next(s for s in d["sections"] if s["id"] == "peers")["rows"]
    assert peers[0]["peer"] == "META" and peers[0]["ev_ebitda"] > 0


def test_rv_with_no_usable_peer_is_not_runnable(client):
    d = client.get("/api/valuation/rv", params={"symbol": "AAPL", "peers": "ZZZZ"}).json()["data"]
    assert d["runnable"] is False and d["missing"] == ["peers"]
    assert any(r["input"] == "ZZZZ" and r["value"] == "EXCLUDED" for r in d["sections"][0]["rows"])


def test_valuation_bad_requests(client):
    assert client.get("/api/valuation/dcf").status_code == 400
    assert client.get("/api/valuation/dcf", params={"symbol": "AAPL", "erp": "x"}).status_code == 400
    r = client.get("/api/valuation/nope", params={"symbol": "AAPL"})
    assert r.status_code == 404 and r.json()["kind"] == "not_found"
