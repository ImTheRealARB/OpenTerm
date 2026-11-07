"""Phase 19 step 6: NRG (FRED-CSV energy board) and WETR (Open-Meteo, degree days, NWS alerts) on recorded answers; no network."""

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from openterm.config import get_settings
from openterm.providers.base import ProviderError
from openterm.providers.nws import NwsProvider
from openterm.providers.openmeteo import OpenMeteoProvider
from openterm.world import energy, weather

FIX = Path(__file__).parent / "fixtures"


def rec(name: str):
    r = json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))
    return r["body"] if "body" in r else r["text"]


def series(vals: list[tuple[str, float | None]]) -> dict:
    from calendar import timegm

    t = [timegm((*map(int, d.split("-")), 0, 0, 0)) for d, _ in vals]
    return {"t": t, "v": [v for _, v in vals], "last_date": [d for d, v in vals if v is not None][-1]}


# --- NRG: catalogue and row maths ---------------------------------------------------------------------------------------
def test_catalogue_aliases_and_ids_resolve():
    assert energy.resolve("wti").id == "DCOILWTICO"
    assert energy.resolve("DHHNGSP").alias == "HH"
    assert energy.resolve(" gasret ").freq == energy.WEEKLY
    with pytest.raises(ValueError, match="UNKNOWN ENERGY SERIES"):
        energy.resolve("WCESTUS1")  # EIA weekly stocks are not on the keyless FRED feed


def test_catalogue_is_prices_only_and_complete():
    assert len({s.id for s in energy.SERIES}) == len(energy.SERIES) == 11
    assert {s.group for s in energy.SERIES} == set(energy.GROUPS)
    assert all(s.unit in ("$/BBL", "$/MMBTU", "$/GAL") for s in energy.SERIES)


def test_row_change_range_and_position():
    s = series([("2026-01-02", 60.0), ("2026-06-01", 100.0), ("2026-10-01", 70.0), ("2026-10-02", None), ("2026-10-05", 80.0)])
    row = energy.make_row(energy.resolve("WTI"), s, date(2026, 10, 6))
    assert row["last"] == 80.0 and row["date"] == "2026-10-05"
    assert row["chg"] == pytest.approx(10.0) and row["pct"] == pytest.approx(10 / 70 * 100)  # against the previous VALUE, not the empty day
    assert (row["lo"], row["hi"], row["n"]) == (60.0, 100.0, 4)
    assert row["pos"] == pytest.approx(50.0) and row["stale"] is False and row["error"] is None


def test_row_range_is_one_year_back_from_the_last_observation():
    s = series([("2024-01-02", 10.0), ("2025-10-01", 50.0), ("2026-10-01", 60.0)])
    row = energy.make_row(energy.resolve("BRENT"), s, date(2026, 10, 2))
    assert (row["lo"], row["hi"], row["n"]) == (50.0, 60.0, 2)  # the 2024 value is older than 366 days


def test_row_stale_rule_differs_for_daily_and_weekly():
    old = series([("2026-09-01", 3.0), ("2026-09-08", 3.1)])
    assert energy.make_row(energy.resolve("HH"), old, date(2026, 9, 20))["stale"] is True  # daily: 12 days old
    assert energy.make_row(energy.resolve("GASRET"), old, date(2026, 9, 20))["stale"] is False  # weekly: 12 days is fine
    assert energy.make_row(energy.resolve("GASRET"), old, date(2026, 9, 30))["stale"] is True


def test_row_with_no_data_carries_the_reason_not_zeros():
    row = energy.make_row(energy.resolve("WTI"), None, date(2026, 10, 1), error="NO FRED SERIES DCOILWTICO")
    assert row["last"] is None and row["error"] == "NO FRED SERIES DCOILWTICO"
    assert energy.make_row(energy.resolve("WTI"), {"t": [1], "v": [None]}, date(2026, 10, 1))["error"] == "NO OBSERVATIONS IN RANGE"


def test_spread_uses_the_latest_date_both_have():
    wti = series([("2026-10-01", 70.0), ("2026-10-02", 71.0), ("2026-10-05", 72.0)])
    brent = series([("2026-10-01", 74.0), ("2026-10-02", 75.5)])  # Brent has no 10-05 value
    sp = energy.spread(wti, brent)
    assert sp["date"] == "2026-10-02" and sp["value"] == pytest.approx(4.5) and sp["label"] == "BRENT - WTI"
    assert energy.spread(wti, None) is None
    assert energy.spread(series([("2026-10-01", 1.0)]), series([("2026-10-02", 2.0)])) is None


def test_recorded_energy_csv_flows_through_the_board_route(client):
    r = client.get("/api/world/nrg").json()
    rows = {x["alias"]: x for x in r["data"]["rows"]}
    assert list(rows) == [s.alias for s in energy.SERIES]
    assert rows["WTI"]["last"] and rows["BRENT"]["last"] and rows["HH"]["last"]
    assert r["data"]["spread"]["label"] == "BRENT - WTI" and "FRED" in r["source"] and "EIA" in r["source"]
    assert "PRICES ONLY" in r["data"]["note"]
    assert all(x["error"] is None for x in rows.values()), [x["error"] for x in rows.values()]


def test_one_series_failing_leaves_the_others_and_names_it(client):
    svc = client.app.state.service
    real = svc.fred_series

    async def pick(sid, rng=None):
        if sid == "DHOILNYH":
            from openterm.errors import DataError

            raise DataError("unavailable", "FRED DOWN")
        return await real(sid, rng)

    svc.fred_series = pick
    try:
        svc.cache.mem.clear()
        d = client.get("/api/world/nrg").json()["data"]
    finally:
        svc.fred_series = real
        svc.cache.mem.clear()
    assert d["failed"] == ["HEAT"]
    heat = next(x for x in d["rows"] if x["alias"] == "HEAT")
    assert heat["last"] is None and "FRED DOWN" in heat["error"]
    assert next(x for x in d["rows"] if x["alias"] == "WTI")["last"]


# --- WETR: degree days -----------------------------------------------------------------------------------------------------
def test_degree_days_hand_values():
    assert weather.degree_days(10.0, 0.0) == pytest.approx((65 - 41.0, 0.0))  # mean 5 C = 41 F
    hdd, cdd = weather.degree_days(35.0, 25.0)  # mean 30 C = 86 F
    assert hdd == 0.0 and cdd == pytest.approx(21.0)
    assert weather.degree_days(18.3333333, 18.3333333) == pytest.approx((0.0, 0.0), abs=1e-3)  # 65 F is neither
    assert weather.degree_days(None, 5.0) is None


def test_forecast_parse_and_totals_on_the_recorded_basket():
    forecasts = weather.parse_forecast_many(rec("openmeteo_forecast_basket"), len(weather.BASKET))
    ny = forecasts[0]
    assert len(ny["days"]) == 7 and ny["days_counted"] == 7 and ny["tz"] == "America/New_York"
    d0 = ny["days"][0]
    hdd, cdd = weather.degree_days(d0["tmax"], d0["tmin"])
    assert d0["hdd"] == pytest.approx(hdd) and d0["cdd"] == pytest.approx(cdd)
    assert ny["hdd"] == pytest.approx(round(sum(d["hdd"] for d in ny["days"]), 1))
    assert d0["sky"] == weather.WMO[d0["code"]]


def test_forecast_with_a_missing_day_skips_it_instead_of_zero_filling():
    body = {"latitude": 1.0, "longitude": 2.0, "timezone": "UTC", "daily": {
        "time": ["2026-10-18", "2026-10-19"], "temperature_2m_max": [10.0, None], "temperature_2m_min": [0.0, 1.0],
        "temperature_2m_mean": [5.0, None], "precipitation_sum": [0.0, None], "wind_speed_10m_max": [3.0, None], "weather_code": [0, None]}}
    f = weather.parse_forecast(body)
    assert f["days_counted"] == 1 and f["days"][1]["hdd"] is None and f["days"][1]["tmax"] is None and f["days"][1]["sky"] is None
    assert f["hdd"] == pytest.approx(24.0)


def test_forecast_shape_errors_are_provider_errors():
    for bad in ({}, {"daily": {}}, {"daily": {"time": []}}, [], None):
        with pytest.raises(ProviderError):
            weather.parse_forecast(bad)
    with pytest.raises(ProviderError, match="ANSWERED 1 LOCATIONS FOR 10"):
        weather.parse_forecast_many(rec("openmeteo_forecast_houston"), 10)


def test_basket_is_equal_weighted_and_says_so():
    b = weather.basket_rows(weather.parse_forecast_many(rec("openmeteo_forecast_basket"), 10))
    assert [r["city"] for r in b["rows"]] == [c[0] for c in weather.BASKET]
    assert b["average"]["hdd"] == pytest.approx(round(sum(r["hdd"] for r in b["rows"]) / 10, 1), abs=0.06)
    assert "EQUAL-WEIGHTED" in b["weighting"] and "NOT WEIGHTED" in b["weighting"]


# --- geocoding and place arguments -------------------------------------------------------------------------------------------
def test_geocode_parse_and_no_match():
    hits = weather.parse_geocode(rec("openmeteo_geocode_houston"))
    assert hits[0]["name"] == "Houston" and hits[0]["cc"] == "US" and hits[0]["tz"] == "America/Chicago"
    with pytest.raises(ProviderError) as e:
        weather.parse_geocode(rec("openmeteo_geocode_nowhere"))  # no `results` key at all
    assert e.value.kind == "not_found"


@pytest.mark.parametrize("text,expect", [("", None), ("  ", None), ("Houston", {"name": "Houston"}), ("new   york", {"name": "new york"}),
                                         ("29.76,-95.37", {"lat": 29.76, "lon": -95.37}), ("-33.9 151.2", {"lat": -33.9, "lon": 151.2})])
def test_place_args(text, expect):
    got = weather.parse_place_arg(text)
    if expect is None:
        assert got is None
    else:
        assert all(got[k] == v for k, v in expect.items())


@pytest.mark.parametrize("text", ["91,0", "10,200", "123", "x" * 61])
def test_bad_place_args(text):
    with pytest.raises(ValueError):
        weather.parse_place_arg(text)


# --- NWS alerts ------------------------------------------------------------------------------------------------------------------
def test_alert_parse_orders_by_severity_and_caps():
    alerts = weather.parse_alerts(rec("nws_alerts_tx"))
    assert alerts and {"event", "severity", "area", "headline", "ends"} <= set(alerts[0])
    mk = lambda sev, end: {"properties": {"event": sev, "severity": sev, "ends": end}}
    body = {"features": [mk("Minor", "2026-10-02"), mk("Extreme", "2026-10-09"), mk("Severe", "2026-10-03"), mk("Severe", "2026-10-01"), mk("Weird", None)] + [mk("Minor", "2026-11-01")] * 30}
    got = weather.parse_alerts(body)
    assert [a["event"] for a in got[:4]] == ["Extreme", "Severe", "Severe", "Minor"] and got[1]["ends"] == "2026-10-01" and len(got) == weather.MAX_ALERTS
    assert weather.parse_alerts(rec("nws_alerts_houston")) == []  # a quiet point is an empty list, not an error
    with pytest.raises(ProviderError):
        weather.parse_alerts({"title": "x"})


def test_nws_coverage_box():
    assert weather.in_nws_coverage(29.76, -95.37) and weather.in_nws_coverage(61.2, -149.9) and weather.in_nws_coverage(21.3, -157.9)
    assert not weather.in_nws_coverage(51.51, -0.13) and not weather.in_nws_coverage(35.7, 139.7)


async def test_nws_provider_without_a_user_agent_refuses_to_call(monkeypatch):
    monkeypatch.setattr(get_settings(), "sec_user_agent", "")

    def handler(request):  # must never be reached
        raise AssertionError("an anonymous request was sent")

    p = NwsProvider(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(ProviderError) as e:
        await p.nws_alerts(29.76, -95.37)
    assert e.value.kind == "key_required" and "SEC_USER_AGENT" in str(e.value)


async def test_nws_provider_sends_the_configured_user_agent_and_point(monkeypatch):
    monkeypatch.setattr(get_settings(), "sec_user_agent", "Test Agent test@example.invalid")
    seen = {}

    def handler(request):
        seen["ua"], seen["point"] = request.headers["user-agent"], request.url.params["point"]
        return httpx.Response(200, json=rec("nws_alerts_point"))

    items = await NwsProvider(httpx.AsyncClient(transport=httpx.MockTransport(handler))).nws_alerts(34.1471, -98.5971)
    assert seen == {"ua": "Test Agent test@example.invalid", "point": "34.1471,-98.5971"} and items[0]["event"] == "Flood Advisory"


async def test_open_meteo_provider_batches_points_in_request_order():
    seen = {}

    def handler(request):
        seen.update(request.url.params)
        return httpx.Response(200, json=rec("openmeteo_forecast_basket"))

    p = OpenMeteoProvider(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    out = await p.weather_forecast([(c[1], c[2]) for c in weather.BASKET])
    assert len(out) == 10 and seen["latitude"].startswith("40.71,41.88") and seen["forecast_days"] == "7" and "temperature_2m_mean" in seen["daily"]


# --- WETR route --------------------------------------------------------------------------------------------------------------------
def test_wetr_basket_only(client):
    r = client.get("/api/world/wetr").json()
    d = r["data"]
    assert d["place"] is None and d["forecast"] is None and d["alerts"] is None
    assert len(d["basket"]["rows"]) == 10 and "EQUAL-WEIGHTED" in d["basket"]["weighting"] and "BASE 65 F" in d["note"]
    assert "open-meteo" in r["source"]


def test_wetr_place_name_alerts_skipped_without_a_user_agent(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "sec_user_agent", "")
    d = client.get("/api/world/wetr", params={"place": "Houston"}).json()["data"]
    assert d["place"]["name"] == "Houston, Texas, US" or d["place"]["name"].startswith("Houston")
    assert len(d["forecast"]["days"]) == 7
    assert d["alerts"]["status"] == "SKIPPED" and "SEC_USER_AGENT" in d["alerts"]["note"] and d["alerts"]["items"] == []


def test_wetr_place_with_a_user_agent_and_no_alerts(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "sec_user_agent", "Test Agent test@example.invalid")
    d = client.get("/api/world/wetr", params={"place": "Houston"}).json()["data"]
    assert d["alerts"]["status"] == "NONE" and d["alerts"]["note"] == "NO ACTIVE NWS ALERTS FOR THIS POINT"


def _any_point_forecast(client):
    """The recording holds the basket and Houston only: serve the Houston forecast for any single point (a test stub, not a claim about that place)."""
    async def any_point(points):
        return weather.parse_forecast_many(rec("openmeteo_forecast_basket" if len(points) == 10 else "openmeteo_forecast_houston"), len(points))

    client.app.state.service.router.providers["openmeteo"].weather_forecast = any_point


def test_wetr_coordinates_with_active_alerts(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "sec_user_agent", "Test Agent test@example.invalid")
    _any_point_forecast(client)
    d = client.get("/api/world/wetr", params={"place": "34.1471,-98.5971"}).json()["data"]
    assert d["place"]["name"] == "34.15,-98.60" and d["alerts"]["status"] == "OK"
    assert d["alerts"]["items"][0]["event"] == "Flood Advisory" and d["alerts"]["items"][0]["severity"] == "Minor"


def test_wetr_outside_the_us_says_so(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "sec_user_agent", "Test Agent test@example.invalid")
    _any_point_forecast(client)
    d = client.get("/api/world/wetr", params={"place": "51.51,-0.13"}).json()["data"]
    assert d["alerts"]["status"] == "OUTSIDE" and "US ONLY" in d["alerts"]["note"] and d["forecast"]["days"]


def test_wetr_unknown_place_and_bad_input(client):
    nf = client.get("/api/world/wetr", params={"place": "Zzqqxxvv"})
    assert nf.status_code == 404 and "NO PLACE FOUND FOR ZZQQXXVV" in nf.json()["error"]
    bad = client.get("/api/world/wetr", params={"place": "95,0"})
    assert bad.status_code == 400 and "OUT OF RANGE" in bad.json()["error"]


def test_wetr_alert_failure_does_not_fail_the_forecast(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "sec_user_agent", "Test Agent test@example.invalid")

    async def boom(lat, lon):
        raise ProviderError("unavailable", "down")

    client.app.state.service.router.providers["nws"].nws_alerts = boom
    d = client.get("/api/world/wetr", params={"place": "Houston"}).json()["data"]
    assert d["alerts"]["status"] == "UNAVAILABLE" and d["forecast"]["days"]
