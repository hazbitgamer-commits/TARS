"""Weather via Open-Meteo — free, no API key. Home city from .env (HOME_CITY)."""
import os

import requests

DESCRIPTION = "Current weather or forecast. E.g. 'what's the weather', 'will it rain tomorrow'."
ARGS = {"when": "'now', 'today', or 'tomorrow'", "place": "city name, only if Jacob names one"}

WMO = {0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast",
       45: "foggy", 48: "foggy", 51: "drizzly", 53: "drizzly", 55: "drizzly",
       61: "light rain", 63: "rainy", 65: "heavy rain", 66: "freezing rain",
       67: "freezing rain", 71: "light snow", 73: "snowy", 75: "heavy snow",
       77: "snowy", 80: "showery", 81: "showery", 82: "heavy showers",
       85: "snow showers", 86: "snow showers", 95: "stormy", 96: "stormy",
       99: "stormy"}


def run(args: dict) -> str:
    place = (args.get("place") or os.getenv("HOME_CITY", "Perth")).strip()
    when = (args.get("when") or "now").strip().lower()

    try:
        geo = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": place, "count": 1}, timeout=15,
        ).json()
        spot = geo["results"][0]
        fc = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": spot["latitude"], "longitude": spot["longitude"],
                "current": "temperature_2m,weather_code",
                "daily": "temperature_2m_max,temperature_2m_min,"
                         "precipitation_probability_max,weather_code",
                "timezone": "auto", "forecast_days": 2,
            }, timeout=15,
        ).json()
    except Exception:
        return f"I couldn't reach the weather service for {place}."

    daily = fc["daily"]
    if when == "tomorrow":
        code = WMO.get(daily["weather_code"][1], "changeable")
        return (f"Tomorrow in {spot['name']}: {code}, "
                f"{round(daily['temperature_2m_min'][1])} to "
                f"{round(daily['temperature_2m_max'][1])} degrees, "
                f"{daily['precipitation_probability_max'][1]} percent chance of rain.")
    cur = fc["current"]
    code = WMO.get(cur["weather_code"], "changeable")
    return (f"{spot['name']} right now: {round(cur['temperature_2m'])} degrees and {code}. "
            f"Today's range {round(daily['temperature_2m_min'][0])} to "
            f"{round(daily['temperature_2m_max'][0])}, "
            f"{daily['precipitation_probability_max'][0]} percent chance of rain.")
