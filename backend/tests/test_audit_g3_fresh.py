"""Audit group 3, "never fake data": a view built from other cached answers must say how old they are.

H-16: the macro boards (macrod), QRY and every other `svc.swr` view dropped the `stale` / `as_of` of the cached answers they read and
      were then cached as fresh.
C-07: every Phase 29 `/api/fund/*` route stamped its answer "fresh, age 0".
H-26 / H-18 tests (backtest and quant honesty) are further down.
"""

import asyncio
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from openterm.fund import service as fund_service

AGE = 100_000  # seconds: far beyond every TTL in the app


def _age_all(client, *, prefix: str = "", keep: tuple[str, ...] = ()) -> None:
    """Make every cached entry (optionally only those starting with `prefix`) look AGE seconds old."""
    mem = client.app.state.service.cache.mem
    for k in list(mem):
        if k.startswith(prefix) and not k.startswith(keep):
            v, s = mem[k]
            mem[k] = (v, s - AGE)


# --- H-16: swr must carry the freshness of what its fetch read ------------------------------------------------------------------

def test_macro_board_carries_the_staleness_of_its_fred_inputs(client):
    first = client.get("/api/macrod/wb").json()
    assert first["stale"] is False
    mem = client.app.state.service.cache.mem
    _age_all(client, prefix="fred:")  # the FRED series are now long past their freshness
    assert any(k.startswith("fred:") for k in mem), "the board read FRED through the cache"
    mem.pop("md:wb", None)  # the board itself has to be rebuilt from those stale series
    old = client.get("/api/macrod/wb").json()
    assert old["stale"] is True, "a board built from stale FRED series must not claim to be fresh"
    assert old["age_s"] >= AGE * 0.9, "age must be the age of the oldest input"


def test_swr_does_not_recache_a_stale_input_as_fresh(client):
    svc = client.app.state.service
    client.get("/api/macrod/wb")
    _age_all(client, prefix="fred:")
    svc.cache.mem.pop("md:wb", None)
    client.get("/api/macrod/wb")
    value, _stored = svc.cache.mem["md:wb"]
    # the cached board remembers that it was built from stale data, so the next read refreshes it instead of calling it fresh
    assert value.get("stale") is True
    assert value.get("as_of") is not None and value["as_of"] < time.time() - AGE * 0.9


def test_query_series_carries_the_staleness_of_its_inputs(client):
    q = "close FOR AAPL DATES -1Y..0 FREQ M"
    fresh = client.get("/api/query", params={"q": q}).json()
    assert fresh["stale"] is False
    _age_all(client)
    old = client.get("/api/query", params={"q": q}).json()
    assert old["stale"] is True
    assert old["age_s"] >= AGE * 0.9


# --- C-07: Phase 29 fund routes ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("path,params", [
    ("/api/fund/gf", {"symbol": "AAPL"}),
    ("/api/fund/score", {"symbol": "AAPL"}),
])
def test_fund_answers_carry_the_staleness_of_their_inputs(client, path, params):
    fresh = client.get(path, params=params)
    if fresh.status_code != 200:
        pytest.skip(f"{path} has no fixture answer here ({fresh.status_code})")
    assert fresh.json()["stale"] is False
    _age_all(client)
    old = client.get(path, params=params).json()
    assert old["stale"] is True, "the filing facts are stale: the answer cannot be 'fresh, age 0'"
    assert old["age_s"] >= AGE * 0.9


# --- H-26: EQS BT must not invent momentum, must use the price series it says it uses, and must count what it drops -----------------

def _days(start: datetime, n: int) -> list[int]:
    """n weekday epochs (UTC midnight) from `start`."""
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(int(d.timestamp()))
        d += timedelta(days=1)
    return out


def _eqsbt(bars: dict[str, dict], rules: str, monkeypatch, start: int, syms: list[str]) -> dict:
    """Run Fund.fn_eqsbt on canned bars with every screen field known (MARGIN = 1), so only the price logic is under test."""
    async def fake_bars(_svc, symbols, _range, tolerate=False):
        return {s: {"data": bars[s], "source": "test"} for s in symbols if s in bars}, {}

    class FakeSec:
        async def cik(self, _s):
            return 1

    svc = SimpleNamespace(router=SimpleNamespace(providers={"sec": FakeSec()}))
    fund = fund_service.Fund(svc)

    async def no_frames(_concept, _year):
        return {}

    monkeypatch.setattr(fund_service, "fetch_bars", fake_bars)
    monkeypatch.setattr(fund, "concept_year", no_frames)
    monkeypatch.setattr(fund_service.Fund, "_known_fields", staticmethod(lambda *_a, **_k: {"MARGIN": 1.0}))
    return asyncio.run(fund.fn_eqsbt(rules=rules, univ=",".join(syms), start=str(start), vs="BENCH"))


def _section(env: dict, sid: str) -> list[dict]:
    return next(s for s in env["data"]["sections"] if s["id"] == sid)["rows"]


def test_eqsbt_mom12_is_empty_before_a_full_year_of_prices(monkeypatch):
    t = _days(datetime(2021, 1, 4, tzinfo=UTC), 400)
    px = {"t": t, "c": [100 + i for i in range(len(t))]}  # always rising: MOM12 > 0 whenever it can be computed
    env = _eqsbt({"AAA": px, "BENCH": px}, "MOM12>0", monkeypatch, 2021, ["AAA"])
    held = {r["month"]: r["held"] for r in _section(env, "monthly")}
    # The first month ends well inside year one (fewer than 252 bars before it): 12-month momentum does not exist yet.
    assert held["2021-03"] == 0, "MOM12 was computed against the first bar in the first year (clamped), not 12 months back"
    assert held["2022-03"] == 1  # a full year of prices exists by then


def test_eqsbt_uses_adjusted_closes_when_the_source_sends_them(monkeypatch):
    t = _days(datetime(2023, 1, 2, tzinfo=UTC), 120)
    adj = [100 * 1.001 ** i for i in range(len(t))]  # a steady climb with a 2-for-1 split inside it
    raw = [a * 2 if i < 40 else a for i, a in enumerate(adj)]  # raw close halves on the split day
    bars = {"AAA": {"t": t, "c": raw, "adj": adj}, "BENCH": {"t": t, "c": adj}}
    env = _eqsbt(bars, "MARGIN>0", monkeypatch, 2023, ["AAA"])
    rets = [r["ret"] for r in _section(env, "monthly") if r["held"]]
    assert rets and min(rets) > 0, "the split month must not read as a -50% loss: adjusted closes were available"


# --- H-12 (2): an extension route must be able to say how old its data is ---------------------------------------------------------------

AGED = """
def main(args):
    import time
    return {"kind": "table", "title": "T", "columns": [{"key": "a", "title": "A"}], "rows": [{"a": 1}],
            "as_of": time.time() - 5000, "stale": True}

def register(api):
    api.add_route("main", main)
"""


def test_extension_route_passes_on_the_age_and_staleness_it_declares(client):
    from test_extensions import write_ext

    mgr = client.app.state.ext
    write_ext(mgr.dir, "aged", AGED)
    assert client.post("/api/ext/aged/enable").status_code == 200
    body = client.get("/api/ext/aged/main").json()
    assert body["stale"] is True, "the extension said its data is stale: the envelope must not say False"
    assert body["age_s"] >= 4900 and body["as_of"] < time.time() - 4900


def test_extension_payload_rejects_a_nonsense_age():
    from openterm.extensions.payload import PayloadError, normalize

    table = {"kind": "table", "title": "T", "columns": [{"key": "a"}], "rows": []}
    with pytest.raises(PayloadError):
        normalize({**table, "as_of": "yesterday"})
    with pytest.raises(PayloadError):
        normalize({**table, "stale": "yes"})


# --- H-18: RISK and PGRK must say what they left out or swapped ----------------------------------------------------------------------

def test_risk_says_when_the_evt_expected_shortfall_is_the_historical_one(monkeypatch):
    import json

    from openterm.quantjobs import common as cm
    from openterm.quantjobs import risk

    day = 86400
    t0 = 1_700_000_000 // day * day
    bars = {"t": [t0 + i * day for i in range(300)], "c": [100.0 + (i % 7) * 0.5 + (i % 13) * 0.3 for i in range(300)]}
    monkeypatch.setattr(cm, "load", lambda params: {"bars": {"AAA": bars}, "fx": {}})
    # An EVT fit whose shape is too heavy (xi >= 1) has no expected shortfall: the job substitutes the historical one.
    monkeypatch.setattr(risk, "_gpd_var", lambda port, conf, hor, fit: (0.05, None))
    params = {"positions": [{"symbol": "AAA", "qty": 1, "ccy": ""}], "name": "T", "range": "1y"}
    out = json.dumps(risk.run(params, lambda *a: None))
    assert "EVT EXPECTED SHORTFALL NEEDS A TAIL SHAPE BELOW 1" in out, "the substitution has to be named in the notes"


def test_pgrk_flags_legs_it_could_not_put_in_the_totals(client):
    # Two OCC legs; the second expiry has no option chain, so its IV (and Greeks) are missing: the totals are INCOMPLETE.
    pf = {"positions": [{"symbol": "AAPL260116C00200000", "qty": 1, "cost": 1.0}, {"symbol": "AAPL990101C00200000", "qty": 1, "cost": 1.0}]}
    assert client.put("/api/portfolios/G3OPT", json=pf).status_code == 200
    r = client.get("/api/deriv/pgrk", params={"name": "G3OPT"})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    rows = next(s for s in data["sections"] if s["id"] == "legs")["rows"]
    missing = [x["symbol"] for x in rows if x.get("delta") is None]
    assert missing, "fixture setup: one leg must have no Greeks"
    text = " ".join(data["notes"]) + " " + str(data.get("status")) + " " + " ".join(h["label"] + h["value"] for h in data["headline"])
    assert "INCOMPLETE" in text and missing[0] in text, "a leg left out of the net Greeks must be named, not silently dropped"


def test_pgrk_beta_joins_days_not_exact_timestamps():
    from openterm.derivs.phase28 import _beta

    day = 86400
    t = [1_700_000_000 // day * day + i * day for i in range(120)]
    import math
    idx = [100 * math.exp(0.01 * math.sin(i)) for i in range(120)]
    stock = [50 * math.exp(0.02 * math.sin(i)) for i in range(120)]  # twice the index's moves
    # the stock's bars are stamped a few hours later than the index's (different source / session open)
    beta = _beta([x + 4 * 3600 for x in t], stock, t, idx)
    assert beta is not None and 1.5 < beta < 2.5


def test_eqsbt_says_how_many_picks_had_no_exit_price(monkeypatch):
    t = _days(datetime(2023, 1, 2, tzinfo=UTC), 200)
    full = {"t": t, "c": [100 + i for i in range(len(t))]}
    cut = {"t": t[:100], "c": [100 + i for i in range(100)]}  # this name stops trading (delisted) half way
    env = _eqsbt({"AAA": full, "GONE": cut, "BENCH": full}, "MARGIN>0", monkeypatch, 2023, ["AAA", "GONE"])
    assert any("NO EXIT PRICE" in n for n in env["data"]["notes"]), "a pick that vanished must be counted in a note, never dropped silently"
