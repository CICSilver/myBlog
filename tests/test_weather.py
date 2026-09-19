import json
import unittest
from unittest import mock

from app import create_app
import app.weather as weather_module
from app.weather import (
    CLEAR,
    CLOUDY,
    FOG,
    OVERCAST,
    RAIN,
    SLEET,
    SNOW,
    UNKNOWN,
    classify_condition,
    clear_cache,
    visitor_weather,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return self.payload


def district_response(adcode="320500"):
    return {"status": "1", "districts": [{"name": "苏州市", "adcode": adcode}]}


def weather_response(condition="中雨", temperature="18"):
    return {
        "status": "1",
        "lives": [
            {
                "city": "苏州市",
                "weather": condition,
                "temperature": temperature,
                "reporttime": "2026-09-19 16:00:00",
            }
        ],
    }


class ClassifyConditionTest(unittest.TestCase):
    def test_reads_category_from_the_condition_characters(self):
        cases = {
            "晴": CLEAR,
            "少云": CLOUDY,
            "多云": CLOUDY,
            "阴": OVERCAST,
            "小雨": RAIN,
            "雷阵雨": RAIN,
            "特大暴雨": RAIN,
            "小雪": SNOW,
            "暴雪": SNOW,
            "雨夹雪": SLEET,
            "雨雪天气": SLEET,
            "强浓雾": FOG,
            "中度霾": FOG,
            "扬沙": FOG,
        }

        for condition, category in cases.items():
            with self.subTest(condition=condition):
                self.assertEqual(classify_condition(condition)["category"], category)

    def test_grades_intensity_from_light_to_heavy(self):
        cases = {
            "毛毛雨/细雨": 1,
            "小雨": 1,
            "中雨": 2,
            "大雨": 3,
            "暴雨": 3,
            "特大暴雨": 3,
            "小雪": 1,
            "中雪": 2,
            "大雪": 3,
        }

        for condition, intensity in cases.items():
            with self.subTest(condition=condition):
                self.assertEqual(classify_condition(condition)["intensity"], intensity)

    def test_a_clear_sky_carries_no_intensity(self):
        self.assertEqual(classify_condition("晴"), {"category": CLEAR, "intensity": 0})

    def test_an_empty_condition_is_unknown(self):
        self.assertEqual(classify_condition(""), {"category": UNKNOWN, "intensity": 0})
        self.assertEqual(classify_condition(None), {"category": UNKNOWN, "intensity": 0})


class VisitorWeatherTest(unittest.TestCase):
    def setUp(self):
        clear_cache()
        self.addCleanup(clear_cache)

    def test_resolves_city_then_weather_for_a_chinese_visitor(self):
        responses = [FakeResponse(district_response()), FakeResponse(weather_response())]

        with mock.patch.object(weather_module, "urlopen", side_effect=responses) as urlopen:
            result = visitor_weather("113.118.113.77", "test-amap-key")

        self.assertTrue(result["available"])
        self.assertEqual(result["category"], RAIN)
        self.assertEqual(result["intensity"], 2)
        self.assertEqual(result["condition"], "中雨")
        self.assertEqual(result["temperature_c"], "18")
        self.assertEqual(result["city"], "苏州市")
        self.assertEqual(urlopen.call_count, 2)

    def test_a_second_visitor_from_the_same_city_is_served_from_cache(self):
        responses = [FakeResponse(district_response()), FakeResponse(weather_response())]

        with mock.patch.object(weather_module, "urlopen", side_effect=responses) as urlopen:
            first = visitor_weather("113.118.113.77", "test-amap-key")
            second = visitor_weather("113.118.113.77", "test-amap-key")

        self.assertEqual(first, second)
        self.assertEqual(urlopen.call_count, 2)

    def test_cached_weather_expires(self):
        responses = [
            FakeResponse(district_response()),
            FakeResponse(weather_response("中雨")),
            FakeResponse(weather_response("小雪")),
        ]

        with mock.patch.object(weather_module, "urlopen", side_effect=responses) as urlopen:
            first = visitor_weather("113.118.113.77", "test-amap-key", now=1000)
            later = visitor_weather(
                "113.118.113.77",
                "test-amap-key",
                now=1000 + weather_module.WEATHER_TTL_SECONDS + 1,
            )

        self.assertEqual(first["category"], RAIN)
        self.assertEqual(later["category"], SNOW)
        # The adcode is still cached, so only the weather was fetched again.
        self.assertEqual(urlopen.call_count, 3)

    def test_without_an_api_key_nothing_is_requested(self):
        with mock.patch.object(weather_module, "urlopen") as urlopen:
            result = visitor_weather("113.118.113.77", "")

        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "no-api-key")
        urlopen.assert_not_called()

    def test_visitors_outside_the_amap_coverage_are_skipped(self):
        with mock.patch.object(weather_module, "urlopen") as urlopen:
            for ip in ("127.0.0.1", "8.8.8.8", "", "not-an-ip"):
                with self.subTest(ip=ip):
                    result = visitor_weather(ip, "test-amap-key")
                    self.assertFalse(result["available"])

        urlopen.assert_not_called()

    def test_a_failing_api_degrades_quietly_and_is_not_retried_at_once(self):
        with mock.patch.object(weather_module, "urlopen", side_effect=TimeoutError) as urlopen:
            first = visitor_weather("113.118.113.77", "test-amap-key")
            second = visitor_weather("113.118.113.77", "test-amap-key")

        self.assertFalse(first["available"])
        self.assertEqual(first["reason"], "no-adcode")
        self.assertFalse(second["available"])
        self.assertEqual(urlopen.call_count, 1)

    def test_a_weather_payload_without_a_condition_is_not_used(self):
        responses = [
            FakeResponse(district_response()),
            FakeResponse({"status": "1", "lives": [{"city": "苏州市", "temperature": "18"}]}),
        ]

        with mock.patch.object(weather_module, "urlopen", side_effect=responses):
            result = visitor_weather("113.118.113.77", "test-amap-key")

        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "weather-unavailable")


class WeatherEndpointTest(unittest.TestCase):
    def setUp(self):
        clear_cache()
        self.addCleanup(clear_cache)
        self.app = create_app()
        self.app.config.update(
            TESTING=True,
            BLOG_TIMEZONE="Asia/Shanghai",
            BLOG_AMAP_WEB_SERVICE_KEY="test-amap-key",
        )
        self.client = self.app.test_client()

    def test_returns_the_visitor_weather_as_json(self):
        responses = [
            FakeResponse(district_response()),
            FakeResponse(weather_response("小雪", "-2")),
        ]

        with mock.patch.object(weather_module, "urlopen", side_effect=responses):
            response = self.client.get("/api/weather", environ_overrides={"REMOTE_ADDR": "113.118.113.77"})

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["available"])
        self.assertEqual(payload["category"], SNOW)
        self.assertEqual(payload["intensity"], 1)
        self.assertEqual(response.headers["Cache-Control"], "private, max-age=600")

    def test_answers_even_when_the_weather_is_unknown(self):
        response = self.client.get("/api/weather", environ_overrides={"REMOTE_ADDR": "127.0.0.1"})

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertFalse(payload["available"])
        self.assertEqual(payload["category"], UNKNOWN)

    def test_does_not_leak_the_visitor_address(self):
        response = self.client.get("/api/weather", environ_overrides={"REMOTE_ADDR": "113.118.113.77"})

        self.assertNotIn("113.118.113.77", response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
