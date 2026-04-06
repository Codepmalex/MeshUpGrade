import aiohttp
import logging
import json
from datetime import datetime, timedelta

class WeatherPlugin:
    WMO_CODES = {
        0: "Clear", 1: "M.Clear", 2: "P.Cloudy", 3: "Overcast",
        45: "Fog", 48: "Fog", 51: "Drizzle", 53: "Drizzle", 55: "Drizzle",
        61: "Rain", 63: "Rain", 65: "Rain", 71: "Snow", 73: "Snow", 75: "Snow",
        80: "Showers", 81: "Showers", 82: "Showers", 95: "T-Storm"
    }

    def __init__(self, lat, lon, unit="F"):
        self.lat = lat
        self.lon = lon
        self.unit = unit.upper()
        self.base_url = "https://api.open-meteo.com/v1/forecast"

    async def get_weather_data(self):
        params = {
            "latitude": self.lat,
            "longitude": self.lon,
            "hourly": "temperature_2m,weathercode",
            "daily": "temperature_2m_max,temperature_2m_min,weathercode",
            "current_weather": "true",
            "temperature_unit": "fahrenheit" if self.unit == "F" else "celsius",
            "windspeed_unit": "mph" if self.unit == "F" else "kmh",
            "timezone": "auto"
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.base_url, params=params, timeout=10) as response:
                    return await response.json()
        except Exception as e:
            logging.error(f"Weather API error: {e}")
            return None

    async def format_wx3(self):
        """Standard MeshCore-friendly dashboard."""
        data = await self.get_weather_data()
        if not data: return "Error fetching weather."
        
        curr = data.get('current_weather')
        if not curr: return "Current weather data missing."
        
        cond = self.WMO_CODES.get(curr.get('weathercode'), "Cloudy")
        temp = int(curr.get('temperature', 0))
        wind = int(curr.get('windspeed', 0))
        wdir = self._get_cardinal(curr.get('winddirection', 0))
        w_unit = "mph" if self.unit == "F" else "kmh"
        hi = int(data['daily']['temperature_2m_max'][0])
        return f"{temp}{self.unit}, {cond}. Wind: {wdir} {wind}{w_unit}. High: {hi}{self.unit}."

    async def format_wxa(self):
        """Active alerts via NWS."""
        # NWS API requires a User-Agent
        headers = {'User-Agent': 'MeshUpGrade (meshtastic-alert-system)'}
        url = f"https://api.weather.gov/alerts/active?point={self.lat},{self.lon}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=10) as response:
                    data = await response.json()
                    alerts = []
                    for feature in data.get('features', []):
                        props = feature.get('properties', {})
                        alerts.append(f"⚠️ {props.get('event')} ({props.get('severity')})")
                    
                    if not alerts:
                        return "No active weather alerts for your area."
                    
                    # Truncate to MeshCore friendly size
                    result = "\n".join(alerts)
                    if len(result) > 190:
                        result = result[:187] + "..."
                    return result
        except Exception as e:
            logging.error(f"NWS Alert API error: {e}")
            return "Alert data unavailable."

    def _get_cardinal(self, degrees):
        directions = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
        ix = int((degrees + 11.25) / 22.5)
        return directions[ix % 16]
