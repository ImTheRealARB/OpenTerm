"""Phase 19 step 9: NSE archive bhavcopy parser on recorded day files, symbol mapping, holiday gaps, the SQLite day store, the `history` fallback order
(Yahoo first, the archive last and only for `.NS` at `1d`), the AMFI NAV parser and `/api/world/mfnav`. No network."""

import asyncio
import base64
import io
import json
import zipfile
from datetime import date
from pathlib import Path

import aiosqlite
import httpx
import pytest

from openterm.providers.amfi import AmfiProvider
from openterm.providers.base import ProviderError
from openterm.providers.fixtures import fixture_transport
from openterm.providers.nse_archive import FIXTURE_TODAY, NseArchiveProvider
from openterm.world import india
from openterm.world.india_store import DayStore

FIX = Path(__file__).parent / "fixtures"
DAYS = [date(2026, 10, d) for d in (5, 6, 7, 8, 9, 12, 13, 14, 15, 16)]


def zip_bytes(day: str) -> bytes:
    return base64.b64decode(json.loads((FIX / f"nse_bhavcopy_{day}.json").read_text(encoding="utf-8"))["b64"])


def amfi_text() -> str:
    return json.loads((FIX / "amfi_navall.json").read_text(encoding="utf-8"))["text"]


def run(coro):
    return asyncio.run(coro)


# --- bhavcopy parser --------------------------------------------------------------------------------------------------------
def test_recorded_day_file_parses_eq_and_be_only():
    d, rows = india.parse_bhavcopy(india.unzip_bhavcopy(zip_bytes("20261016")))
    assert d == date(2026, 10, 16)
    o, h, lo, c, v = rows["RELIANCE"]
    assert lo <= o <= h and lo <= c <= h and v > 0
    assert "TCS" in rows and "INFY" in rows
    text = india.unzip_bhavcopy(zip_bytes("20261016"))
    other = [ln.split(",") for ln in text.splitlines()[1:]]
    head = text.splitlines()[0].split(",")
    i_ser, i_sym = head.index("SctySrs"), head.index("TckrSymb")
    non_eq = {r[i_sym] for r in other if r[i_ser] not in ("EQ", "BE")} - {r[i_sym] for r in other if r[i_ser] in ("EQ", "BE")}
    assert non_eq and not (non_eq & set(rows))


def test_eq_wins_over_be_and_bad_rows_are_skipped():
    head = ",".join(india.NEEDED)
    lines = [head, "2026-10-16,ABC,BE,1,2,0.5,1.5,10", "2026-10-16,ABC,EQ,3,4,2.5,3.5,20", "2026-10-16,XYZ,EQ,x,1,1,1,1",
                      "2026-10-16,ZERO,EQ,1,1,1,0,1", "2026-10-16,BOND,N1,1,1,1,1,1"]
    text = "\n".join(lines)
    d, rows = india.parse_bhavcopy(text)
    assert rows == {"ABC": [3.0, 4.0, 2.5, 3.5, 20]} and d == date(2026, 10, 16)


def test_bot_check_page_or_changed_format_is_an_error_not_data():
    with pytest.raises(ValueError, match="NOT A ZIP"):
        india.unzip_bhavcopy(b"<html>captcha</html>")
    with pytest.raises(ValueError, match="MISSING"):
        india.parse_bhavcopy("SYMBOL,SERIES,CLOSE\nA,EQ,1\n")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("a.csv", "x")
        z.writestr("b.csv", "y")
    with pytest.raises(ValueError, match="ONE CSV"):
        india.unzip_bhavcopy(buf.getvalue())


@pytest.mark.parametrize("sym,want", [("RELIANCE.NS", "RELIANCE"), ("m&m.ns", "M&M"), ("BAJAJ-AUTO.NS", "BAJAJ-AUTO"), ("RELIANCE.BO", None), ("^NSEI", None), ("AAPL", None)])
def test_symbol_mapping(sym, want):
    assert india.nse_symbol(sym) == want


# --- planning and gaps ------------------------------------------------------------------------------------------------------------
def test_walk_skips_weekends_and_plan_skips_holidays():
    today = date(2026, 10, 17)  # a Saturday
    days = india.walk_days(today, 6)
    assert days[0] == date(2026, 10, 16) and all(d.weekday() < 5 for d in days)
    known = {date(2026, 10, 16): True, date(2026, 10, 15): False, date(2026, 10, 14): True}
    used, missing = india.plan(today, known)
    assert used == [date(2026, 10, 16), date(2026, 10, 14)]
    assert date(2026, 10, 15) not in missing and missing[0] == date(2026, 10, 13)


def test_plan_caps_at_250_sessions():
    today = date(2026, 10, 16)
    known = {d: True for d in india.walk_days(today, 300)}
    used, missing = india.plan(today, known)
    assert len(used) == india.MAX_SESSIONS and missing == []


def test_build_columns_cuts_the_range_and_marks_the_open():
    days = {date(2026, 10, 1 + i): {"ABC": [1.0, 2.0, 0.5, 1.0 + i, 10]} for i in range(10)}
    cols = india.build_columns(days, "ABC", "5d")
    assert cols["c"] == [6.0, 7.0, 8.0, 9.0, 10.0]
    assert cols["t"][0] == india.session_ts(date(2026, 10, 6))
    assert india.build_columns(days, "NOPE", "1mo") is None
    assert len(india.build_columns(days, "ABC", "max")["t"]) == 10


def test_label_names_the_source_and_the_file_count():
    assert india.label(1) == "NSE ARCHIVE, EOD, built from 1 daily file"
    assert india.label(10, True) == "NSE ARCHIVE, EOD, built from 10 daily files (INCOMPLETE)"
    assert india.is_partial(india.label(10, True)) and not india.is_partial(india.label(10))


# --- store and provider on the recordings ------------------------------------------------------------------------------------------
async def _db(tmp_path):
    db = await aiosqlite.connect(tmp_path / "t.db")
    await db.execute("CREATE TABLE kv (key TEXT PRIMARY KEY, value BLOB NOT NULL)")
    return db


def test_day_store_round_trip_gaps_and_prune(tmp_path):
    async def go():
        db = await _db(tmp_path)
        s = DayStore(db)
        await s.put_day(date(2026, 10, 16), {"ABC": [1, 2, 0.5, 1.5, 9]})
        await s.put_gap(date(2026, 10, 2))
        await s.put_day(date(2025, 1, 2), {"OLD": [1, 1, 1, 1, 1]})
        known = await s.known(date(2026, 1, 1))
        assert known == {date(2026, 10, 16): True, date(2026, 10, 2): False}
        rows, at = await s.rows([date(2026, 10, 16)])
        assert rows[date(2026, 10, 16)]["ABC"] == [1, 2, 0.5, 1.5, 9] and at
        await s.prune(date(2026, 1, 1))
        assert date(2025, 1, 2) not in await s.known(date(2000, 1, 1))
        await db.close()

    run(go())


def _provider(handler=None) -> NseArchiveProvider:
    transport = fixture_transport() if handler is None else httpx.MockTransport(handler)
    return NseArchiveProvider(httpx.AsyncClient(transport=transport), source="nse_archive:fixture")


def test_archive_history_builds_from_recorded_days_and_labels_itself(tmp_path):
    async def go():
        db = await _db(tmp_path)
        p = _provider()
        p.attach(db)
        assert p.clock() == FIXTURE_TODAY and p.background is False
        bars = await p.history("RELIANCE.NS", "1mo", "1d")
        assert len(bars.t) == len(DAYS) and bars.currency == "INR" and bars.tz == "Asia/Kolkata"
        assert bars.source.startswith("NSE ARCHIVE, EOD, built from 10 daily files") and bars.source.endswith("(INCOMPLETE)")
        assert "NOT ADJUSTED" in bars.exchange
        known = await p.store.known(date(2026, 1, 1))
        assert known[date(2026, 10, 2)] is False  # the recorded 404 is a gap (holiday), never a made-up day
        assert sum(known.values()) == 10
        await db.close()

    run(go())


def test_archive_refuses_other_symbols_and_intervals(tmp_path):
    async def go():
        db = await _db(tmp_path)
        p = _provider()
        assert p.supports("history", "RELIANCE.NS") is False  # not attached yet
        p.attach(db)
        assert p.supports("history", "RELIANCE.NS") and not p.supports("history", "AAPL") and not p.supports("history", "RELIANCE.BO")
        for sym, iv in (("AAPL", "1d"), ("RELIANCE.NS", "1h")):
            with pytest.raises(ProviderError) as e:
                await p.history(sym, "1mo", iv)
            assert e.value.kind == "unsupported"
        with pytest.raises(ProviderError) as e:
            await p.history("NOSUCHNAME.NS", "1mo", "1d")
        assert e.value.kind == "not_found"
        await db.close()

    run(go())


def test_a_bot_check_answer_is_an_error_and_backs_off(tmp_path):
    async def go():
        db = await _db(tmp_path)
        calls = []

        def handler(request):
            calls.append(request.url.path)
            return httpx.Response(200, text="<html>please verify you are human</html>")

        p = _provider(handler)
        p.attach(db)
        with pytest.raises(ProviderError) as e:
            await p.history("RELIANCE.NS", "1mo", "1d")
        assert e.value.kind == "unavailable" and "NOT A ZIP" in str(e.value)
        n = len(calls)
        with pytest.raises(ProviderError):
            await p.history("RELIANCE.NS", "1mo", "1d")
        assert len(calls) == n  # resting: no second burst at the host
        assert await p.store.known(date(2000, 1, 1)) == {}
        await db.close()

    run(go())


def test_recent_404_is_not_cached_as_a_holiday(tmp_path):
    async def go():
        db = await _db(tmp_path)
        p = _provider(lambda r: httpx.Response(404, text="nope"))
        p.attach(db)
        p.clock = lambda: date(2026, 10, 16)
        await p.extend(3)
        known = await p.store.known(date(2026, 1, 1))
        assert date(2026, 10, 16) not in known and date(2026, 10, 15) not in known  # too recent: maybe not published yet
        assert known.get(date(2026, 10, 14)) is False
        await db.close()

    run(go())


def test_history_order_puts_the_archive_last():
    from openterm.main import DEFAULT_ORDER

    assert DEFAULT_ORDER["history"][-1] == "nse_archive" and DEFAULT_ORDER["history"].index("yahoo") < DEFAULT_ORDER["history"].index("nse_archive")
    assert DEFAULT_ORDER["mfnav"] == ["amfi"]


def test_history_route_falls_back_to_the_archive_when_yahoo_has_nothing(client):
    r = client.get("/api/history", params={"symbol": "TCS.NS", "range": "1M", "interval": "1d"}).json()
    assert r["source"].startswith("NSE ARCHIVE") and "yahoo" in r["fallback_from"]
    assert len(r["data"]["c"]) == 10 and r["data"]["currency"] == "INR"


# --- AMFI ---------------------------------------------------------------------------------------------------------------------------------------
def test_amfi_recorded_file_parses_categories_amcs_and_rows():
    t = india.parse_amfi(amfi_text())
    assert t["nav_date"] == "2026-10-16" and t["skipped"] == 0 and len(t["rows"]) == 186
    r = t["rows"][0]
    assert r[0] == "135762" and r[1] == "INF846K01WO1" and r[2] is None and r[4] == "Direct Plan" and r[6] == pytest.approx(29.396)
    assert t["amcs"][r[9]] == "Axis Mutual Fund" and t["cats"][r[8]].startswith("Open Ended Schemes")


def test_amfi_skips_na_navs_and_reads_the_old_layout():
    lines = ["Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date", "Open Ended Schemes(Equity)", "X Mutual Fund",
                      "1001;INF000000001;-;X Fund Growth;12.5;01-Oct-2026", "1002;-;-;X Fund Old;N.A.;01-Oct-2026", "1003;-;-;X Bad Date;1.0;2026-10-01"]
    text = "\n".join(lines)
    t = india.parse_amfi(text)
    assert [r[0] for r in t["rows"]] == ["1001"] and t["skipped"] == 2 and t["rows"][0][4] is None
    assert india.amfi_date("16-Oct-2026") == "2026-10-16" and india.amfi_date("31-Feb-2026") is None


def test_amfi_search_by_name_isin_and_code():
    t = india.parse_amfi(amfi_text())
    items, total = india.search_amfi(t, "axis children")
    assert total == len(items) >= 4 and items[0]["plan"] == "Direct Plan" and "Growth" in items[0]["option"]
    assert india.search_amfi(t, "INF846K01WO1")[0][0]["code"] == "135762"
    assert india.search_amfi(t, "135762")[0][0]["isin"] == "INF846K01WO1"
    assert india.search_amfi(t, "zzqqxx") == ([], 0)


def test_amfi_follows_one_redirect_inside_amfiindia_only():
    p = AmfiProvider(httpx.AsyncClient(transport=fixture_transport()), source="amfi:fixture")
    t = run(p.navall())
    assert len(t["rows"]) == 186 and t["source"] == "amfi:fixture"
    evil = AmfiProvider(httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(302, headers={"location": "https://example.com/x"}))))
    with pytest.raises(ProviderError, match="NOT FOLLOWED"):
        run(evil.navall())


def test_mfnav_route(client):
    r = client.get("/api/world/mfnav", params={"q": "axis children"}).json()
    d = r["data"]
    assert d["items"] and d["nav_date"] == "2026-10-16" and d["schemes"] == 186 and "NOT A MARKET PRICE" in d["note"]
    assert r["source"].startswith("amfi")
    assert client.get("/api/world/mfnav", params={"q": "ab"}).status_code == 400
