"""WeatherTool — get current weather and forecasts via wttr.in (free, no API key)."""
from __future__ import annotations
from typing import Any

import aiohttp

from weebot.tools.base import BaseTool, ToolResult

from weebot.config.api_endpoints import WEATHER_WTTR_URL

_WTTR_URL = WEATHER_WTTR_URL


class WeatherTool(BaseTool):
    name: str = "weather"
    description: str = (
        "Get current weather or forecast for any location using wttr.in. "
        "No API key required. Returns temperature, conditions, humidity, wind, etc. "
        "Use this instead of browser scraping for weather data — it's fast and reliable."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "location": {
                "type": "string",
                "description": "City name, airport code, or coordinates (e.g. 'Thessaloniki', 'SKG', '40.6,22.9')",
            },
            "forecast": {
                "type": "string",
                "enum": ["now", "today", "tomorrow", "week"],
                "description": "Forecast type. 'now' = current conditions, 'today' = today's forecast, 'tomorrow' = tomorrow's forecast, 'week' = 3-day outlook (default: 'now')",
                "default": "now",
            },
        },
        "required": ["location"],
    }

    _FORMAT_MAP = {
        "now": "j1",     # JSON current + today
        "today": "j1",   # JSON (we filter to today)
        "tomorrow": "j2", # JSON 2-day (we filter to day 2)
        "week": "j2",    # JSON 2-day (gives today + tomorrow)
    }

    async def health_check(self) -> bool:
        """Check if aiohttp is available."""
        try:
            import aiohttp  # noqa: F401
            return True
        except ImportError:
            return False

    async def execute(
        self, location: str, forecast: str = "now", **kwargs: Any
    ) -> ToolResult:
        fmt = self._FORMAT_MAP.get(forecast, "j1")
        url = f"{_WTTR_URL}/{location}?format={fmt}"

        try:
            import json as _json
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers={"User-Agent": "weebot/1.0"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        return ToolResult.error_result(
                            error=f"wttr.in returned HTTP {resp.status} for '{location}'"
                        )
                    # wttr.in returns text/plain even for JSON format
                    text = await resp.text()
                    data = _json.loads(text)
        except aiohttp.ClientError as e:
            return ToolResult.error_result(
                error=f"Failed to reach wttr.in: {e}"
            )
        except Exception as e:
            return ToolResult.error_result(
                error=f"Failed to parse weather for '{location}': {e}"
            )

        return ToolResult.success_result(
            output=self._format_weather(data, location, forecast),
            data=data,
        )

    def _format_weather(self, data: dict, location: str, forecast: str) -> str:
        """Format wttr.in JSON into readable text."""
        try:
            current = data.get("current_condition", [{}])[0]
            weather = data.get("weather", [])
            nearest = data.get("nearest_area", [{}])[0]

            area_name = (
                nearest.get("areaName", [{}])[0].get("value", "")
                or nearest.get("region", [{}])[0].get("value", "")
                or location
            )
            country = nearest.get("country", [{}])[0].get("value", "")

            lines = [f"🌍 Weather for {area_name}, {country}".rstrip(", ")]

            # Current conditions
            if current:
                temp_c = current.get("temp_C", "?")
                feels = current.get("FeelsLikeC", "?")
                desc = current.get("weatherDesc", [{}])[0].get("value", "?")
                humidity = current.get("humidity", "?")
                wind = current.get("windspeedKmph", "?")
                wind_dir = current.get("winddir16Point", "?")
                visibility = current.get("visibility", "?")
                pressure = current.get("pressure", "?")

                lines.append(f"  🌡️  {temp_c}°C (feels like {feels}°C) — {desc}")
                lines.append(f"  💧 Humidity: {humidity}%  |  🌬️  Wind: {wind} km/h {wind_dir}")
                lines.append(f"  👁️  Visibility: {visibility} km  |  📊 Pressure: {pressure} mb")

            # Forecast
            if forecast in ("today", "tomorrow", "week") and weather:
                lines.append("")
                for day in weather:
                    date = day.get("date", "?")
                    max_c = day.get("maxtempC", "?")
                    min_c = day.get("mintempC", "?")
                    hourly = day.get("hourly", [])
                    # Pick midday (index 4 = ~10-12h depending on timezone)
                    midday = hourly[4] if len(hourly) > 4 else (hourly[0] if hourly else {})
                    day_desc = (
                        midday.get("weatherDesc", [{}])[0].get("value", "")
                        or day.get("weatherDesc", "")
                    )

                    if forecast == "tomorrow" and weather.index(day) == 0:
                        continue  # Skip today when asking for tomorrow
                    if forecast == "today" and weather.index(day) > 0:
                        break  # Only today

                    lines.append(f"  📅 {date}: {min_c}°C – {max_c}°C — {day_desc}")

            return "\n".join(lines)

        except Exception:
            # Fallback: return raw text summary
            return f"Weather data for {location} (raw): {str(data)[:500]}"
