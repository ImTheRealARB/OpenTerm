"""Phase 12 step 8 additions: IMPORT parsing rules, local history (resampling, ranges), list / delete (no network)."""

import importlib

import pytest


def _csv():
    return importlib.import_module("openterm.bt.csvimport")


def _days(n: int, start: str = "2024-01-01") -> str:
    import datetime as dt

    d0 = dt.date.fromisoformat(start)
    lines = ["Date,Open,High,Low,Close,Volume"]
    for i in range(n):
        d = d0 + dt.timedelta(days=i)
        lines.append(f"{d.isoformat()},{10 + i},{11 + i},{9 + i},{10.5 + i},{100 + i}")
    return "\n".join(lines) + "\n"


def test_parse_sorts_by_date_and_reads_any_case_and_order():
    got = _csv().parse_bars("Close,DATE,low,High,open\n3,2024-01-03,1,4,2\n2,2024-01-02 09:30:00,0.5,3,1\n")
    assert got["d"] == ["2024-01-02", "2024-01-03"] and got["c"] == [2.0, 3.0] and got["o"] == [1.0, 2.0]
    assert got["v"] is None and got["t"][1] - got["t"][0] == 86_400


@pytest.mark.parametrize(("text", "msg"), [
    ("", "EMPTY"),
    ("date,open,high,low,close\n2024-01-02,1,1,1,1\n", "AT LEAST 2 ROWS"),
    ("date,open,high,low,close\n2024-01-02,1,1,1,1\n2024-01-02,1,1,1,1\n", "ROW 2: DUPLICATE DATE"),
    ("date,open,high,low,close\n2024-01-02,1,1,1,1\n2024-01-03,0,1,1,1\n", "ROW 2: PRICES MUST BE POSITIVE"),
    ("date,open,high,low,close\n2024-01-02,1,1,1,1\n2024-01-03,1,1,2,1\n", "ROW 2: HIGH BELOW LOW"),
    ("date,open,high,low,close\n2024-01-02,1,1,1,1\n2024-01-03,1,1,1,nan\n", "ROW 2: BAD NUMBER IN close"),
    ("date,open,high,low,close\n2024-01-02,1,1,1\n", "ROW 1: HAS 4 COLUMNS"),
    ("date,open,high,low,close,volume\n2024-01-02,1,1,1,1,-5\n2024-01-03,1,1,1,1,1\n", "ROW 1: NEGATIVE VOLUME"),
    ("date,open,high,low,close\n2024-02-30,1,1,1,1\n2024-02-31,1,1,1,1\n", "ROW 1: BAD DATE"),
])
def test_parse_rejects_the_whole_file_with_the_row(text, msg):
    with pytest.raises(_csv().CsvError, match=msg):
        _csv().parse_bars(text)


@pytest.mark.parametrize("bad", ["", "a b", "x" * 17, "-A", "A/B"])
def test_bad_symbols(client, bad):
    r = client.post("/api/bt/import", params={"symbol": bad}, content=_days(3).encode())
    assert r.status_code == 400


def test_reimport_replaces_and_history_reads_the_new_bars(client):
    client.post("/api/bt/import", params={"symbol": "mine"}, content=_days(3).encode())
    r = client.post("/api/bt/import", params={"symbol": "MINE"}, content=_days(5, "2024-03-01").encode())
    assert r.json()["rows"] == 5 and r.json()["first_date"] == "2024-03-01"
    h = client.get("/api/history", params={"symbol": "mine", "range": "MAX", "interval": "1d"}).json()
    assert h["source"] == "local" and h["stale"] is False and len(h["data"]["t"]) == 5
    assert h["data"]["exchange"] == "LOCAL DATA" and h["data"]["v"][0] == 100


def test_weekly_and_monthly_bars_aggregate_the_daily_ones(client):
    client.post("/api/bt/import", params={"symbol": "AGG"}, content=_days(60).encode())  # 2024-01-01 (Mon) .. 2024-02-29
    wk = client.get("/api/history", params={"symbol": "AGG", "range": "MAX", "interval": "1wk"}).json()["data"]
    assert wk["o"][0] == 10 and wk["c"][0] == 16.5 and wk["h"][0] == 17 and wk["l"][0] == 9  # Mon 1 .. Sun 7
    assert wk["v"][0] == sum(100 + i for i in range(7))
    mo = client.get("/api/history", params={"symbol": "AGG", "range": "MAX", "interval": "1mo"}).json()["data"]
    assert len(mo["t"]) == 2 and mo["c"][1] == 10.5 + 59 and mo["o"][1] == 10 + 31


def test_ranges_count_back_from_the_last_imported_bar(client):
    client.post("/api/bt/import", params={"symbol": "OLD"}, content=_days(400, "2015-01-01").encode())
    one_month = client.get("/api/history", params={"symbol": "OLD", "range": "1M", "interval": "1d"}).json()["data"]
    assert 28 <= len(one_month["t"]) <= 33  # not empty although the data ended years ago
    assert len(client.get("/api/history", params={"symbol": "OLD", "range": "MAX", "interval": "1d"}).json()["data"]["t"]) == 400


def test_local_data_has_no_intraday_bars(client):
    client.post("/api/bt/import", params={"symbol": "DAILY"}, content=_days(5).encode())
    r = client.get("/api/history", params={"symbol": "DAILY", "range": "1D", "interval": "5m"})
    assert r.status_code == 400 and "DAILY" in r.json()["error"]


def test_no_volume_column_gives_no_volume(client):
    client.post("/api/bt/import", params={"symbol": "NOVOL"}, content=b"date,open,high,low,close\n2024-01-02,1,2,1,2\n2024-01-03,2,3,2,3\n")
    h = client.get("/api/history", params={"symbol": "NOVOL", "range": "MAX", "interval": "1d"}).json()["data"]
    assert h["v"] == [None, None]


def test_list_and_delete(client):
    client.post("/api/bt/import", params={"symbol": "LST"}, content=_days(4).encode())
    rows = client.get("/api/bt/import").json()["symbols"]
    assert [r["symbol"] for r in rows] == ["LST"] and rows[0]["rows"] == 4 and rows[0]["label"] == "LOCAL DATA"
    assert client.delete("/api/bt/import/lst").json() == {"deleted": "LST"}
    assert client.delete("/api/bt/import/LST").status_code == 404
    assert client.get("/api/bt/import").json()["symbols"] == []
    assert client.get("/api/history", params={"symbol": "LST", "range": "MAX", "interval": "1d"}).status_code in (404, 503)


def test_utf8_bom_and_non_utf8(client):
    ok = client.post("/api/bt/import", params={"symbol": "BOM"}, content=b"\xef\xbb\xbf" + _days(3).encode())
    assert ok.status_code == 200
    bad = client.post("/api/bt/import", params={"symbol": "BAD"}, content=b"date,open\n\xff\xfe")
    assert bad.status_code == 400 and "UTF-8" in bad.json()["detail"]
