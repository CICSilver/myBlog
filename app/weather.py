"""Live weather for the ambient rain/snow layer.

The diary already records the weather of the moment it was written. This module
answers a different question: what is the weather where the visitor is, right
now. It reuses the ip2region database for the city and the same AMAP web
service key as the diary, and caches aggressively so a busy page never turns
into a burst of API calls.
"""
import json
import time
from threading import RLock
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from app.ip_location import resolve_ip_location


AMAP_DISTRICT_URL = "https://restapi.amap.com/v3/config/district"
AMAP_WEATHER_URL = "https://restapi.amap.com/v3/weather/weatherInfo"

ADCODE_TTL_SECONDS = 7 * 24 * 60 * 60
WEATHER_TTL_SECONDS = 30 * 60
FAILURE_TTL_SECONDS = 5 * 60

CLEAR = "clear"
CLOUDY = "cloudy"
OVERCAST = "overcast"
RAIN = "rain"
SNOW = "snow"
SLEET = "sleet"
FOG = "fog"
UNKNOWN = "unknown"

_NETWORK_ERRORS = (
    HTTPError,
    URLError,
    TimeoutError,
    UnicodeDecodeError,
    json.JSONDecodeError,
    KeyError,
    IndexError,
    TypeError,
    ValueError,
)

_cache = {}
_cache_lock = RLock()


def unavailable(reason=""):
    return {
        "available": False,
        "category": UNKNOWN,
        "intensity": 0,
        "condition": "",
        "temperature_c": "",
        "city": "",
        "reason": reason,
    }


def classify_condition(condition):
    """Map an AMAP condition string onto a category and a 1-3 intensity.

    AMAP publishes some sixty condition strings ("小雨-中雨", "强浓雾", ...), so
    this matches on the characters they are built from instead of enumerating
    every one of them.
    """
    condition = str(condition or "").strip()
    if not condition:
        return {"category": UNKNOWN, "intensity": 0}

    has_rain = "雨" in condition
    has_snow = "雪" in condition

    if has_rain and has_snow:
        category = SLEET
    elif has_snow:
        category = SNOW
    elif has_rain:
        category = RAIN
    elif any(mark in condition for mark in ("雾", "霾", "尘", "沙")):
        category = FOG
    elif "阴" in condition:
        category = OVERCAST
    elif "云" in condition:
        category = CLOUDY
    elif "晴" in condition:
        category = CLEAR
    else:
        category = CLEAR

    if category in (CLEAR, CLOUDY, OVERCAST):
        intensity = 0
    else:
        intensity = _condition_intensity(condition)

    return {"category": category, "intensity": intensity}


def visitor_weather(ip, api_key, timeout=4, now=None):
    """Resolve the weather where this visitor is, or an unavailable payload."""
    api_key = api_key.strip() if isinstance(api_key, str) else ""
    if not api_key:
        return unavailable("no-api-key")

    location = resolve_ip_location(ip)
    if location.get("ip_country") != "中国":
        # The AMAP live weather feed only covers mainland China.
        return unavailable("outside-coverage")

    city = location.get("ip_city") or location.get("ip_region") or ""
    if not city:
        return unavailable("no-city")

    now = time.time() if now is None else now

    adcode = _resolve_adcode(city, api_key, timeout, now)
    if not adcode:
        return unavailable("no-adcode")

    weather = _fetch_city_weather(adcode, api_key, timeout, now)
    if not weather:
        return unavailable("weather-unavailable")

    classified = classify_condition(weather["condition"])
    return {
        "available": True,
        "category": classified["category"],
        "intensity": classified["intensity"],
        "condition": weather["condition"],
        "temperature_c": weather["temperature_c"],
        "city": weather["city"] or city,
        "reason": "",
    }


def clear_cache():
    with _cache_lock:
        _cache.clear()


def _condition_intensity(condition):
    if any(mark in condition for mark in ("特大", "极端", "狂", "暴")):
        return 3
    if "大" in condition:
        return 3
    if "中" in condition:
        return 2
    if any(mark in condition for mark in ("小", "毛毛", "细", "轻")):
        return 1
    return 2


def _resolve_adcode(city, api_key, timeout, now):
    key = ("adcode", city)
    cached = _cache_read(key, now)
    if cached is not None:
        return cached or ""

    try:
        response = _json_get(
            AMAP_DISTRICT_URL,
            {
                "key": api_key,
                "keywords": city,
                "subdistrict": 0,
                "extensions": "base",
            },
            timeout,
        )
        if not isinstance(response, dict) or str(response.get("status")) != "1":
            raise ValueError("district query failed")

        districts = response["districts"]
        if not isinstance(districts, list) or not districts:
            raise ValueError("district response is empty")

        adcode = str(districts[0].get("adcode") or "").strip()
        if not adcode:
            raise ValueError("district response has no adcode")
    except _NETWORK_ERRORS:
        _cache_write(key, "", now, FAILURE_TTL_SECONDS)
        return ""

    _cache_write(key, adcode, now, ADCODE_TTL_SECONDS)
    return adcode


def _fetch_city_weather(adcode, api_key, timeout, now):
    key = ("weather", adcode)
    cached = _cache_read(key, now)
    if cached is not None:
        return cached or None

    try:
        response = _json_get(
            AMAP_WEATHER_URL,
            {
                "key": api_key,
                "city": adcode,
                "extensions": "base",
            },
            timeout,
        )
        if not isinstance(response, dict) or str(response.get("status")) != "1":
            raise ValueError("weather query failed")

        lives = response["lives"]
        if not isinstance(lives, list) or not lives or not isinstance(lives[0], dict):
            raise ValueError("weather response is invalid")

        live = lives[0]
        weather = {
            "condition": str(live.get("weather") or "").strip(),
            "temperature_c": str(live.get("temperature") or "").strip(),
            "city": str(live.get("city") or "").strip(),
            "report_time": str(live.get("reporttime") or "").strip(),
        }
        if not weather["condition"]:
            raise ValueError("weather response has no condition")
    except _NETWORK_ERRORS:
        _cache_write(key, {}, now, FAILURE_TTL_SECONDS)
        return None

    _cache_write(key, weather, now, WEATHER_TTL_SECONDS)
    return weather


def _cache_read(key, now):
    with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return None

        expires_at, value = entry
        if now >= expires_at:
            _cache.pop(key, None)
            return None

        return value


def _cache_write(key, value, now, ttl):
    with _cache_lock:
        _cache[key] = (now + ttl, value)


def _json_get(url, params, timeout):
    request_url = "{0}?{1}".format(url, urlencode(params))
    with urlopen(request_url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))
