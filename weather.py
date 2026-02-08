import requests
import logging
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

    def get_weather_data(self):
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
            response = requests.get(self.base_url, params=params, timeout=10)
            return response.json()
        except Exception as e:
            logging.error(f"Weather API error: {e}")
            return None

    def format_wx1(self):
        data = self.get_weather_data()
        if not data: return "Error fetching weather."
        
        daily = data['daily']
        lines = []
        for i in range(5):
            date_obj = datetime.strptime(daily['time'][i], "%Y-%m-%d")
            day_name = date_obj.strftime("%a").upper()
            hi = int(daily['temperature_2m_max'][i])
            lo = int(daily['temperature_2m_min'][i])
            cond = self.WMO_CODES.get(daily['weathercode'][i], "Cloudy")
            lines.append(f"{day_name}:{hi}/{lo}{self.unit} {cond}")
        
        return " | ".join(lines)

    def format_wx2(self):
        data = self.get_weather_data()
        if not data: return "Error fetching weather."
        
        hourly = data['hourly']
        current_hour = datetime.now().replace(minute=0, second=0, microsecond=0)
        
        lines = []
        count = 0
        for i, time_str in enumerate(hourly['time']):
            time_obj = datetime.strptime(time_str, "%Y-%m-%dT%H:%M")
            if time_obj >= current_hour and count < 5:
                temp = int(hourly['temperature_2m'][i])
                cond = self.WMO_CODES.get(hourly['weathercode'][i], "Cloudy")
                lines.append(f"{time_obj.strftime('%H:%M')} {temp}{self.unit} {cond}")
                count += 1
        
        return " | ".join(lines)

    def get_cardinal_direction(self, degrees):
        directions = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
        ix = int((degrees + 11.25) / 22.5)
        return directions[ix % 16]

    def format_wx3(self):
        data = self.get_weather_data()
        if not data: return "Error fetching weather."
        
        curr = data.get('current_weather')
        if not curr: return "Current weather data missing."
        
        cond = self.WMO_CODES.get(curr.get('weathercode'), "Cloudy")
        temp = int(curr.get('temperature', 0))
        wind = int(curr.get('windspeed', 0))
        wdir = self.get_cardinal_direction(curr.get('winddirection', 0))
        w_unit = "mph" if self.unit == "F" else "kmh"
        hi = int(data['daily']['temperature_2m_max'][0])
        return f"Currently: {temp}{self.unit}, {cond}. Wind: {wdir} {wind}{w_unit}. Today's High: {hi}{self.unit}."

    def format_wx4(self, target_date_str):
        if not target_date_str: return None
        data = self.get_weather_data()
        if not data: return "Error fetching weather."
        
        daily = data['daily']
        try:
            idx = daily['time'].index(target_date_str)
            hi = int(daily['temperature_2m_max'][idx])
            lo = int(daily['temperature_2m_min'][idx])
            cond = self.WMO_CODES.get(daily['weathercode'][idx], "Cloudy")
            date_obj = datetime.strptime(target_date_str, "%Y-%m-%d")
            day_name = date_obj.strftime("%A, %b %d")
            return f"Forecast for {day_name}: Expect {cond} conditions. The high will be around {hi}{self.unit} with a low of {lo}{self.unit}."
        except ValueError:
            return None

    def format_wx5(self, target_time_str):
        if not target_time_str: return None
        data = self.get_weather_data()
        if not data: return "Error fetching weather."
        
        # We assume today's date for 'HH:MM'
        today_str = datetime.now().strftime("%Y-%m-%d")
        full_time_str = f"{today_str}T{target_time_str}"
        
        hourly = data['hourly']
        try:
            idx = hourly['time'].index(full_time_str)
            temp = int(hourly['temperature_2m'][idx])
            cond = self.WMO_CODES.get(hourly['weathercode'][idx], "Cloudy")
            return f"Hour Forecast for {target_time_str}: Expect {cond} conditions. The temperature will be around {temp}{self.unit}."
        except ValueError:
            return None

    def get_alerts(self):
        # NWS API requires a User-Agent
        headers = {'User-Agent': 'MeshUpGrade (meshtastic-alert-system)'}
        url = f"https://api.weather.gov/alerts/active?point={self.lat},{self.lon}"
        try:
            response = requests.get(url, headers=headers, timeout=10)
            data = response.json()
            alerts = []
            for feature in data.get('features', []):
                props = feature.get('properties', {})
                alerts.append({
                    'id': props.get('id'),
                    'event': props.get('event'),
                    'headline': props.get('headline'),
                    'description': props.get('description'),
                    'severity': props.get('severity')
                })
            return alerts
        except Exception as e:
            logging.error(f"NWS Alert API error: {e}")
            return []
