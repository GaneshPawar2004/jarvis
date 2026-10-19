"""Web skills: live internet search (DuckDuckGo, free), with a one-hour cache so repeated
questions answer instantly."""
import json
import threading
import time
import urllib.parse
import urllib.request

from ddgs import DDGS

CACHE_SECONDS = 3600
_cache: dict[tuple, tuple[float, list]] = {}
_lock = threading.Lock()


def _cached(key: tuple, fetch):
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]
    value = fetch()
    with _lock:
        _cache[key] = (time.time(), value)
        if len(_cache) > 500:  # keep the cache small
            _cache.pop(next(iter(_cache)))
    return value


def web_search(query: str, fresh: bool = False) -> list[dict] | str:
    """Search the internet for current information (facts, prices, people, how-tos). You may
    call it several times at once for different queries; they run in parallel.

    Args:
        query: What to search for.
        fresh: True for news and anything from the last few days ("latest", "today", scores, launches).
    """
    def fetch():
        if fresh:
            results = DDGS().news(query, max_results=6, timelimit="w")
            return [{"title": r["title"], "url": r["url"], "date": r.get("date", ""), "snippet": r["body"]} for r in results]
        results = DDGS().text(query, max_results=6)
        return [{"title": r["title"], "url": r["href"], "snippet": r["body"]} for r in results]

    try:
        return _cached((query.strip().lower(), fresh), fetch) or "No results found."
    except Exception as e:  # network errors, rate limits
        return f"Search failed: {e}"


WEATHER_CODES = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "fog",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 80: "rain showers", 81: "heavy rain showers",
    82: "violent rain showers", 95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with hail",
}


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.loads(response.read())


def get_weather(place: str) -> dict | str:
    """Get the current weather and today's and tomorrow's forecast for a city or place.
    Faster and more accurate than a web search for weather.

    Args:
        place: City or place name, e.g. "Mumbai" or "Pune".
    """
    def fetch():
        found = _get_json("https://geocoding-api.open-meteo.com/v1/search?count=1&name=" + urllib.parse.quote(place))
        if not found.get("results"):
            return f"I couldn't find a place called {place}."
        spot = found["results"][0]
        data = _get_json(
            "https://api.open-meteo.com/v1/forecast?timezone=auto&forecast_days=2"
            f"&latitude={spot['latitude']}&longitude={spot['longitude']}"
            "&current=temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m"
            "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code"
        )
        now, daily = data["current"], data["daily"]
        days = [
            {"day": label, "condition": WEATHER_CODES.get(daily["weather_code"][i], "mixed"),
             "high_c": daily["temperature_2m_max"][i], "low_c": daily["temperature_2m_min"][i],
             "chance_of_rain_percent": daily["precipitation_probability_max"][i]}
            for i, label in enumerate(("today", "tomorrow"))
        ]
        return {
            "place": f"{spot['name']}, {spot.get('admin1', '')}, {spot.get('country', '')}".replace(", ,", ","),
            "now": {"condition": WEATHER_CODES.get(now["weather_code"], "mixed"), "temperature_c": now["temperature_2m"],
                    "feels_like_c": now["apparent_temperature"], "humidity_percent": now["relative_humidity_2m"],
                    "wind_kmh": now["wind_speed_10m"]},
            "forecast": days,
        }

    try:
        key = ("weather", place.strip().lower(), int(time.time() // 900))  # fresh every 15 minutes
        return _cached(key, fetch)
    except Exception as e:
        return f"Weather service unavailable: {e}"
