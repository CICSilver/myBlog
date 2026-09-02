import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen


AMAP_COORDINATE_CONVERT_URL = "https://restapi.amap.com/v3/assistant/coordinate/convert"
AMAP_REVERSE_GEOCODE_URL = "https://restapi.amap.com/v3/geocode/regeo"
AMAP_WEATHER_URL = "https://restapi.amap.com/v3/weather/weatherInfo"


def _json_get(url, params, timeout):
    request_url = "{0}?{1}".format(url, urlencode(params))
    with urlopen(request_url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_diary_metadata(latitude, longitude, accuracy_m, api_key, timeout=5):
    """Fetch the location and weather metadata for a diary entry."""
    api_key = api_key.strip() if isinstance(api_key, str) else ""
    if not api_key:
        return {
            "location": {},
            "weather": {},
            "warnings": ["未配置高德 Web 服务 API Key，无法获取位置和天气信息。"],
        }

    result = {
        "location": {
            "latitude": latitude,
            "longitude": longitude,
            "accuracy_m": accuracy_m,
        },
        "weather": {},
        "warnings": [],
    }

    try:
        converted = _json_get(
            AMAP_COORDINATE_CONVERT_URL,
            {
                "key": api_key,
                "locations": "{0},{1}".format(longitude, latitude),
                "coordsys": "gps",
            },
            timeout,
        )
        if not isinstance(converted, dict) or str(converted.get("status")) != "1":
            raise ValueError("coordinate conversion failed")

        converted_coordinates = converted["locations"]
        if not isinstance(converted_coordinates, str):
            raise ValueError("coordinate conversion response is invalid")
        amap_longitude, amap_latitude = converted_coordinates.split(",", 1)
        result["location"]["amap_latitude"] = float(amap_latitude)
        result["location"]["amap_longitude"] = float(amap_longitude)
    except (
        HTTPError,
        URLError,
        TimeoutError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ):
        result["warnings"].append("高德坐标转换失败，未获取位置和天气信息。")
        return result

    try:
        reverse_geocode = _json_get(
            AMAP_REVERSE_GEOCODE_URL,
            {
                "key": api_key,
                "location": "{0},{1}".format(amap_longitude, amap_latitude),
                "radius": 1000,
                "extensions": "all",
            },
            timeout,
        )
        if not isinstance(reverse_geocode, dict) or str(reverse_geocode.get("status")) != "1":
            raise ValueError("reverse geocode failed")

        regeocode = reverse_geocode["regeocode"]
        if not isinstance(regeocode, dict):
            raise ValueError("reverse geocode response is invalid")
        address = regeocode["addressComponent"]
        if not isinstance(address, dict):
            raise ValueError("address component is invalid")

        city = address.get("city") or ""
        if isinstance(city, list):
            city = city[0] if city else ""
        street_number = address.get("streetNumber") or {}
        if not isinstance(street_number, dict):
            street_number = {}
        pois = regeocode.get("pois") or []
        poi_name = ""
        if pois and isinstance(pois[0], dict):
            poi_name = pois[0].get("name") or ""

        result["location"].update(
            {
                "province": address.get("province") or "",
                "city": city,
                "district": address.get("district") or "",
                "township": address.get("township") or "",
                "street": street_number.get("street") or "",
                "number": street_number.get("number") or "",
                "formatted_address": regeocode.get("formatted_address") or "",
                "poi_name": poi_name,
                "adcode": address.get("adcode") or "",
            }
        )
    except (
        HTTPError,
        URLError,
        TimeoutError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ):
        result["warnings"].append("高德逆地理编码失败，未获取详细位置和天气信息。")
        return result

    adcode = result["location"]["adcode"]
    if not adcode:
        result["warnings"].append("未获取到行政区划编码，未获取天气信息。")
        return result

    try:
        weather_response = _json_get(
            AMAP_WEATHER_URL,
            {
                "key": api_key,
                "city": adcode,
                "extensions": "base",
            },
            timeout,
        )
        if not isinstance(weather_response, dict) or str(weather_response.get("status")) != "1":
            raise ValueError("weather query failed")

        lives = weather_response["lives"]
        if not isinstance(lives, list) or not lives or not isinstance(lives[0], dict):
            raise ValueError("weather response is invalid")

        weather = lives[0]
        result["weather"] = {
            "condition": weather.get("weather") or "",
            "temperature_c": weather.get("temperature") or "",
            "report_time": weather.get("reporttime") or "",
        }
    except (
        HTTPError,
        URLError,
        TimeoutError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ):
        result["warnings"].append("高德天气查询失败。")

    return result
