"""Service functions behind NRG (`/api/world/nrg`) and WETR (`/api/world/wetr`)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from ..config import get_settings
from ..errors import DataError
from ..redact import redact
from ..router import AllFailed
from . import energy, weather

NRG_TTL_S = 900.0
WX_TTL_S = 1800.0
ALERT_TTL_S = 300.0
NRG_SOURCE = "FRED CSV (SERIES REPUBLISHED FROM EIA / US ENERGY INFORMATION ADMINISTRATION)"
NO_UA_NOTE = "NWS ALERTS SKIPPED: SET SEC_USER_AGENT IN .ENV (NAME AND CONTACT), WEATHER.GOV REQUIRES A USER-AGENT THAT NAMES A CONTACT"


async def nrg(svc: Any) -> dict[str, Any]:
    async def fetch() -> dict:
        got = await asyncio.gather(*(svc.fred_series(s.id, "1Y") for s in energy.SERIES), return_exceptions=True)
        today = datetime.now(UTC).date()
        rows, datas, errors = [], {}, []
        for s, g in zip(energy.SERIES, got, strict=True):
            if isinstance(g, DataError):
                rows.append(energy.make_row(s, None, today, error=redact(str(g))))
                errors.append(s.alias)
            elif isinstance(g, BaseException):
                raise g
            else:
                datas[s.alias] = g["data"]
                rows.append(energy.make_row(s, g["data"], today))
        if len(errors) == len(rows):
            raise next(g for g in got if isinstance(g, DataError))  # every series failed: surface the first reason
        data = {"rows": rows, "spread": energy.spread(datas.get("WTI"), datas.get("BRENT")), "failed": errors, "groups": list(energy.GROUPS),
                "note": "PRICES ONLY: EIA WEEKLY STOCKS AND PRODUCTION ARE NOT ON THE KEYLESS FRED FEED. SPOT PRICES LAG ONE TO THREE BUSINESS DAYS."}
        return {"data": data, "source": NRG_SOURCE, "fallback_from": []}

    return await svc.swr("w:nrg", NRG_TTL_S, fetch)


async def _forecast(svc: Any, key: str, points: list[tuple[float, float]]) -> dict:
    async def fetch() -> dict:
        out, failed = await svc.router.call("weather_forecast", lambda p: p.weather_forecast(points))
        return {"data": out, "fallback_from": failed, "source": "open-meteo"}

    return await svc.swr(key, WX_TTL_S, fetch)


async def _geocode(svc: Any, name: str) -> dict:
    async def fetch() -> dict:
        out, failed = await svc.router.call("weather_geocode", lambda p: p.weather_geocode(name))
        return {"data": out, "fallback_from": failed, "source": "open-meteo"}

    try:
        return await svc.swr(f"w:geo:{name.lower()}", 86400.0, fetch)
    except DataError as e:
        if e.kind != "not_found":
            raise
        raise DataError("not_found", f"NO PLACE FOUND FOR {name.upper()[:40]}", e.detail) from e


async def _alerts(svc: Any, lat: float, lon: float) -> dict[str, Any]:
    """Status is OK | NONE | SKIPPED | UNAVAILABLE | OUTSIDE: alerts never fail the forecast."""
    if not weather.in_nws_coverage(lat, lon):
        return {"status": "OUTSIDE", "items": [], "note": "NWS ALERTS COVER THE US ONLY"}
    if not (get_settings().sec_user_agent or "").strip():
        return {"status": "SKIPPED", "items": [], "note": NO_UA_NOTE}

    async def fetch() -> dict:
        out, failed = await svc.router.call("nws_alerts", lambda p: p.nws_alerts(lat, lon))
        return {"data": out, "fallback_from": failed, "source": "nws"}

    try:
        env = await svc.swr(f"w:nws:{lat:.4f},{lon:.4f}", ALERT_TTL_S, fetch)
    except (AllFailed, DataError) as e:
        return {"status": "UNAVAILABLE", "items": [], "note": f"NWS ALERTS UNAVAILABLE: {redact(str(e))[:80].upper()}"}
    items = env["data"]
    return {"status": "OK" if items else "NONE", "items": items, "note": None if items else "NO ACTIVE NWS ALERTS FOR THIS POINT",
            "age_s": env["age_s"], "stale": env["stale"]}


async def wetr(svc: Any, place_text: str) -> dict[str, Any]:
    try:
        arg = weather.parse_place_arg(place_text)
    except ValueError as e:
        raise DataError("bad_request", str(e)) from e
    basket_env = await _forecast(svc, "w:wx:basket", [(c[1], c[2]) for c in weather.BASKET])
    data: dict[str, Any] = {"basket": weather.basket_rows(basket_env["data"]), "place": None, "forecast": None, "alerts": None, "base_f": weather.BASE_F,
                            "note": "DEGREE DAYS: F-DAYS, BASE 65 F, DAILY MEAN = (MAX + MIN) / 2. TEMPERATURES IN C."}
    meta = basket_env
    if arg:
        place = arg
        if "lat" not in arg:
            hits = (await _geocode(svc, arg["name"]))["data"]
            top = hits[0]
            label = ", ".join(x for x in (top["name"], top["admin1"], top["cc"]) if x)
            place = {"name": label, "lat": top["lat"], "lon": top["lon"], "cc": top["cc"], "tz": top["tz"],
                     "others": [f"{h['name']}, {h['cc']}" for h in hits[1:4]]}
        f_env = await _forecast(svc, f"w:wx:{place['lat']:.3f},{place['lon']:.3f}", [(place["lat"], place["lon"])])
        data["place"] = place
        data["forecast"] = f_env["data"][0]
        data["alerts"] = await _alerts(svc, place["lat"], place["lon"])
        meta = f_env
    return {"data": data, "source": "open-meteo (forecast) + nws (alerts)", "as_of": meta["as_of"], "age_s": meta["age_s"],
            "stale": meta["stale"], "fallback_from": meta["fallback_from"]}
