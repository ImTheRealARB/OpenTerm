"""Open-Meteo forecast and geocoding (keyless, global; free for non-commercial use, attribution to open-meteo.com)."""

from __future__ import annotations

from typing import Any, ClassVar

from ..world import weather
from .base import Provider

GEOCODE = "weather_geocode"
FORECAST = "weather_forecast"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"


class OpenMeteoProvider(Provider):
    name = "openmeteo"
    label = "Open-Meteo forecast and geocoding"
    capabilities = frozenset({GEOCODE, FORECAST})
    markets = "Global 7-day forecasts (any lat/lon) and place-name geocoding"
    terms = "Free for non-commercial use, no key; attribution: Open-Meteo.com (CC BY 4.0 data)."
    rate = (2.0, 6)
    timeout = 10.0
    headers: ClassVar[dict[str, str]] = {"User-Agent": "OpenTerm", "Accept": "application/json"}

    async def weather_geocode(self, name: str) -> list[dict[str, Any]]:
        body = await self.get_json(GEOCODE_URL, {"name": name, "count": 5, "language": "en", "format": "json"})
        return weather.parse_geocode(body)

    async def weather_forecast(self, points: list[tuple[float, float]]) -> list[dict[str, Any]]:
        params = {"latitude": ",".join(str(p[0]) for p in points), "longitude": ",".join(str(p[1]) for p in points),
                  "daily": weather.DAILY_FIELDS, "timezone": "auto", "forecast_days": 7}
        return weather.parse_forecast_many(await self.get_json(FORECAST_URL, params), len(points))

    async def probe(self) -> None:
        await self.weather_forecast([(40.71, -74.01)])
