"""Phase 19 step 2: GP event markers (earnings, dividends, splits) from /api/world/events, and the drawings store."""

import json
from pathlib import Path

import pytest

from openterm.providers.base import ProviderError
from openterm.research import corp_parse as cp

FIX = Path(__file__).parent / "fixtures"


def fixture_body(name: str) -> dict:
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))["body"]


def test_nasdaq_earnings_history_parses_the_recorded_answer():
    out = cp.nasdaq_earnings_history(fixture_body("nasdaq_earnings_surprise_aapl"), "nasdaq_research")
    assert len(out["rows"]) == 4
    first = out["rows"][0]
    assert first == {"date": "2026-07-30", "fiscal": "Jun 2026", "eps": 1.91, "estimate": 1.88, "surprise_pct": 1.6}
    assert out["source"] == "nasdaq_research"


def test_nasdaq_earnings_history_drops_rows_without_a_date_and_says_not_found_when_empty():
    body = {"data": {"earningsSurpriseTable": {"rows": [
        {"fiscalQtrEnd": "Jun 2026", "dateReported": "N/A", "eps": 1, "consensusForecast": "1", "percentageSurprise": "0"},
        {"fiscalQtrEnd": "Mar 2026", "dateReported": "4/30/2026", "eps": 2.01, "consensusForecast": "N/A", "percentageSurprise": "N/A"}]}}}
    out = cp.nasdaq_earnings_history(body, "x")
    assert [r["date"] for r in out["rows"]] == ["2026-04-30"]
    assert out["rows"][0]["estimate"] is None and out["rows"][0]["surprise_pct"] is None
    for empty in ({"data": None}, {"data": {"earningsSurpriseTable": {"rows": []}}}, {}):
        with pytest.raises(ProviderError) as e:
            cp.nasdaq_earnings_history(empty, "x")
        assert e.value.kind == "not_found"


def test_chart_events_merge_sort_ascending_and_say_what_is_missing():
    dvd = {"rows": [{"ex_date": "2026-08-10", "amount": 0.27, "type": "Cash", "declared": None, "record": None, "pay": None},
                    {"ex_date": "2026-05-11", "amount": None, "type": "Cash", "declared": None, "record": None, "pay": None}], "source": "nasdaq_research"}
    splt = {"rows": [{"date": "2020-08-31", "ratio": "4:1"}], "source": "yahoo"}
    earn = {"rows": [{"date": "2026-07-30", "fiscal": "Jun 2026", "eps": 1.91, "estimate": 1.88, "surprise_pct": 1.6}], "source": "nasdaq_research"}
    out = cp.chart_events("AAPL", dvd, splt, earn, [])
    assert [(e["date"], e["kind"]) for e in out["events"]] == [
        ("2020-08-31", "S"), ("2026-05-11", "D"), ("2026-07-30", "E"), ("2026-08-10", "D")]
    by = {(e["date"], e["kind"]): e["detail"] for e in out["events"]}
    assert by[("2026-08-10", "D")] == "DIV $0.27"
    assert by[("2026-05-11", "D")] == "DIV"
    assert by[("2020-08-31", "S")] == "SPLIT 4:1"
    assert "EPS 1.91 VS 1.88" in by[("2026-07-30", "E")] and "+1.6%" in by[("2026-07-30", "E")]
    assert out["missing"] == []
    assert out["source"] == "nasdaq_research + yahoo"

    partial = cp.chart_events("AAPL", dvd, None, None, ["SPLITS", "EARNINGS"])
    assert {e["kind"] for e in partial["events"]} == {"D"}
    assert partial["missing"] == ["SPLITS", "EARNINGS"]
    assert any("EARNINGS" in n and "last four" not in n.lower() for n in partial["notes"])
    assert any("LAST FOUR REPORTED" in n for n in cp.chart_events("AAPL", None, None, earn, [])["notes"])


def test_events_route_in_fixture_mode(client):
    r = client.get("/api/world/events", params={"symbol": "AAPL"})
    assert r.status_code == 200, r.text
    env = r.json()
    assert env["stale"] is False and env["source"]
    data = env["data"]
    assert data["symbol"] == "AAPL"
    kinds = {e["kind"] for e in data["events"]}
    assert {"D", "E"} <= kinds
    dates = [e["date"] for e in data["events"]]
    assert dates == sorted(dates) and all(len(d) == 10 for d in dates)
    assert any("LAST FOUR REPORTED" in n for n in data["notes"])


def test_events_route_needs_a_symbol_and_never_invents_events(client):
    assert client.get("/api/world/events").status_code in (400, 422)
    r = client.get("/api/world/events", params={"symbol": "ZZZZ9"})
    assert r.status_code in (404, 502, 503), r.text
    assert "events" not in r.json().get("data", {})
