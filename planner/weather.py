"""Game-day weather from Open-Meteo (free, no account). Forecasts are cached so pages stay fast."""
import json
import logging
import re
import urllib.parse
import urllib.request
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

from .schedule_sync import _running_tests, _ssl_context

logger = logging.getLogger(__name__)

HOME = (42.2959, -71.8317)  # Assumption University, Worcester, MA
FORECAST_DAYS = 15

STATES = {
    "ma": "Massachusetts", "mass": "Massachusetts", "ct": "Connecticut", "conn": "Connecticut",
    "ny": "New York", "nh": "New Hampshire", "me": "Maine", "vt": "Vermont", "ri": "Rhode Island",
    "nj": "New Jersey", "pa": "Pennsylvania", "md": "Maryland", "de": "Delaware", "va": "Virginia",
    "dc": "District of Columbia", "oh": "Ohio", "fl": "Florida", "fla": "Florida", "ga": "Georgia",
    "nc": "North Carolina", "sc": "South Carolina", "wv": "West Virginia", "mi": "Michigan", "il": "Illinois",
}

# WMO weather codes -> (short description, icon)
CODES = [
    ((0,), "Clear", "☀️"), ((1,), "Mostly clear", "🌤️"), ((2,), "Partly cloudy", "⛅"), ((3,), "Cloudy", "☁️"),
    ((45, 48), "Fog", "🌫️"), ((51, 53, 55, 56, 57), "Drizzle", "🌦️"), ((61, 63, 80, 81), "Rain", "🌧️"),
    ((65, 66, 67, 82), "Heavy rain", "🌧️"), ((71, 73, 75, 77, 85, 86), "Snow", "🌨️"), ((95, 96, 99), "Thunderstorms", "⛈️"),
]


def _get_json(url, timeout=4):
    request = urllib.request.Request(url, headers={"User-Agent": "SE-Scheduler"})
    with urllib.request.urlopen(request, timeout=timeout, context=_ssl_context()) as response:
        return json.loads(response.read().decode("utf-8"))


def _place(location):
    """'Frostburg, MD / Bobcats Stadium' -> ('Frostburg', 'Maryland'); None if there's no town."""
    town = (location or "").split(" / ")[0]
    if "," not in town:
        return None
    name, _, state = town.partition(",")
    state = re.sub(r"[^a-z]", "", state.lower())
    return name.strip(), STATES.get(state, "")


def coordinates(game):
    if game.is_home:
        return HOME
    place = _place(game.location)
    if not place:
        return HOME if game.is_home is None and "Worcester" in (game.location or "") else None
    key = "geo:" + "|".join(place)
    cached = cache.get(key)
    if cached is not None:
        return cached or None
    try:
        query = urllib.parse.urlencode({"name": place[0], "count": 10, "country": "US"})
        results = _get_json(f"https://geocoding-api.open-meteo.com/v1/search?{query}").get("results") or []
        match = next((r for r in results if place[1] and r.get("admin1") == place[1]), results[0] if results else None)
        coords = (match["latitude"], match["longitude"]) if match else ()
    except Exception:
        logger.warning("Geocoding failed for %s", place, exc_info=True)
        coords = ()
    cache.set(key, coords, 60 * 60 * 24 * 30)
    return coords or None


def describe(code):
    for codes, text, icon in CODES:
        if code in codes:
            return text, icon
    return "Mixed", "🌥️"


def forecast_for(game):
    """{'temp': 48, 'text': 'Light rain', 'icon': '🌧️', 'rain': 60, 'wind': 12} at kickoff, or None."""
    if _running_tests() or game is None or getattr(game, "result", ""):
        return None
    today = timezone.localdate()
    if not (today <= game.date <= today + timedelta(days=FORECAST_DAYS)):
        return None
    key = f"wx:{game.pk}:{game.date}:{game.start_time:%H}:{timezone.now():%Y%m%d%H}"
    cached = cache.get(key)
    if cached is not None:
        return cached or None
    result = {}
    try:
        coords = coordinates(game)
        if coords:
            query = urllib.parse.urlencode({
                "latitude": coords[0], "longitude": coords[1],
                "hourly": "temperature_2m,precipitation_probability,weather_code,wind_speed_10m",
                "temperature_unit": "fahrenheit", "wind_speed_unit": "mph", "timezone": "America/New_York",
                "start_date": game.date.isoformat(), "end_date": game.date.isoformat(),
            })
            hourly = _get_json(f"https://api.open-meteo.com/v1/forecast?{query}")["hourly"]
            hour = 12 if getattr(game, "time_tba", False) else game.start_time.hour
            i = min(hour, len(hourly["time"]) - 1)
            text, icon = describe(hourly["weather_code"][i])
            result = {
                "temp": round(hourly["temperature_2m"][i]),
                "text": text,
                "icon": icon,
                "rain": hourly["precipitation_probability"][i] or 0,
                "wind": round(hourly["wind_speed_10m"][i]),
            }
    except Exception:
        logger.warning("Weather lookup failed for %s", game, exc_info=True)
    cache.set(key, result, 60 * 60 if result else 60 * 20)
    return result or None
