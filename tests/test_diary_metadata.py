import json
import os
import tempfile
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlparse

from app import create_app, project_root
from app.diary_metadata import fetch_diary_metadata


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return self.payload


class DiaryMetadataTest(unittest.TestCase):
    def _response(self, payload):
        return FakeResponse(payload)

    def _reverse_geocode_response(self, adcode="310101"):
        return {
            "status": "1",
            "regeocode": {
                "formatted_address": "上海市黄浦区中山东一路1号",
                "addressComponent": {
                    "province": "上海市",
                    "city": "上海市",
                    "district": "黄浦区",
                    "township": "外滩街道",
                    "streetNumber": {"street": "中山东一路", "number": "1号"},
                    "adcode": adcode,
                },
                "pois": [{"name": "外滩"}],
            },
        }

    def _successful_responses(self, adcode="310101"):
        return [
            self._response({"status": "1", "locations": "121.48001,31.23512"}),
            self._response(self._reverse_geocode_response(adcode)),
            self._response(
                {
                    "status": "1",
                    "lives": [
                        {
                            "weather": "晴",
                            "temperature": "28",
                            "reporttime": "2026-09-02 10:00:00",
                        }
                    ],
                }
            ),
        ]

    def test_fetches_location_and_weather_in_amap_order(self):
        with mock.patch(
            "app.diary_metadata.urlopen",
            side_effect=self._successful_responses(),
        ) as mocked_urlopen:
            result = fetch_diary_metadata(
                31.2304,
                121.4737,
                12,
                " test-api-key ",
            )

        self.assertEqual(
            result,
            {
                "location": {
                    "latitude": 31.2304,
                    "longitude": 121.4737,
                    "accuracy_m": 12,
                    "amap_latitude": 31.23512,
                    "amap_longitude": 121.48001,
                    "province": "上海市",
                    "city": "上海市",
                    "district": "黄浦区",
                    "township": "外滩街道",
                    "street": "中山东一路",
                    "number": "1号",
                    "formatted_address": "上海市黄浦区中山东一路1号",
                    "poi_name": "外滩",
                    "adcode": "310101",
                },
                "weather": {
                    "condition": "晴",
                    "temperature_c": "28",
                    "report_time": "2026-09-02 10:00:00",
                },
                "warnings": [],
            },
        )
        self.assertEqual(mocked_urlopen.call_count, 3)

        urls = [call.args[0] for call in mocked_urlopen.call_args_list]
        self.assertEqual(
            [call.kwargs["timeout"] for call in mocked_urlopen.call_args_list],
            [5, 5, 5],
        )
        self.assertEqual([urlparse(url).scheme for url in urls], ["https", "https", "https"])
        coordinate_query = parse_qs(urlparse(urls[0]).query)
        reverse_query = parse_qs(urlparse(urls[1]).query)
        weather_query = parse_qs(urlparse(urls[2]).query)
        self.assertEqual(urlparse(urls[0]).path, "/v3/assistant/coordinate/convert")
        self.assertEqual(coordinate_query["locations"], ["121.4737,31.2304"])
        self.assertEqual(coordinate_query["coordsys"], ["gps"])
        self.assertEqual(coordinate_query["key"], ["test-api-key"])
        self.assertEqual(urlparse(urls[1]).path, "/v3/geocode/regeo")
        self.assertEqual(reverse_query["location"], ["121.48001,31.23512"])
        self.assertEqual(reverse_query["radius"], ["1000"])
        self.assertEqual(reverse_query["extensions"], ["all"])
        self.assertEqual(urlparse(urls[2]).path, "/v3/weather/weatherInfo")
        self.assertEqual(weather_query["city"], ["310101"])
        self.assertEqual(weather_query["extensions"], ["base"])

    def test_empty_key_skips_all_requests(self):
        with mock.patch("app.diary_metadata.urlopen") as mocked_urlopen:
            result = fetch_diary_metadata(31.2304, 121.4737, 12, "   ")

        self.assertEqual(result["location"], {})
        self.assertEqual(result["weather"], {})
        self.assertEqual(len(result["warnings"]), 1)
        self.assertIn("未配置高德 Web 服务 API Key", result["warnings"][0])
        mocked_urlopen.assert_not_called()

    def test_coordinate_conversion_failure_skips_following_requests(self):
        with mock.patch(
            "app.diary_metadata.urlopen",
            return_value=self._response({"status": "0"}),
        ) as mocked_urlopen:
            result = fetch_diary_metadata(31.2304, 121.4737, 12, "test-api-key")

        self.assertEqual(
            result["location"],
            {"latitude": 31.2304, "longitude": 121.4737, "accuracy_m": 12},
        )
        self.assertEqual(result["weather"], {})
        self.assertIn("坐标转换失败", result["warnings"][0])
        self.assertEqual(mocked_urlopen.call_count, 1)

    def test_reverse_geocode_failure_keeps_known_coordinates(self):
        with mock.patch(
            "app.diary_metadata.urlopen",
            side_effect=[
                self._response({"status": "1", "locations": "121.48001,31.23512"}),
                self._response({"status": "0"}),
            ],
        ) as mocked_urlopen:
            result = fetch_diary_metadata(31.2304, 121.4737, 12, "test-api-key")

        self.assertEqual(result["location"]["amap_latitude"], 31.23512)
        self.assertEqual(result["location"]["amap_longitude"], 121.48001)
        self.assertEqual(result["weather"], {})
        self.assertIn("逆地理编码失败", result["warnings"][0])
        self.assertEqual(mocked_urlopen.call_count, 2)

    def test_missing_adcode_skips_weather_request(self):
        with mock.patch(
            "app.diary_metadata.urlopen",
            side_effect=self._successful_responses(adcode=""),
        ) as mocked_urlopen:
            result = fetch_diary_metadata(31.2304, 121.4737, 12, "test-api-key")

        self.assertEqual(result["location"]["adcode"], "")
        self.assertEqual(result["weather"], {})
        self.assertIn("行政区划编码", result["warnings"][0])
        self.assertEqual(mocked_urlopen.call_count, 2)

    def test_weather_failure_keeps_location(self):
        responses = self._successful_responses()
        responses[-1] = self._response({"status": "0"})
        with mock.patch(
            "app.diary_metadata.urlopen",
            side_effect=responses,
        ) as mocked_urlopen:
            result = fetch_diary_metadata(31.2304, 121.4737, 12, "test-api-key")

        self.assertEqual(result["location"]["formatted_address"], "上海市黄浦区中山东一路1号")
        self.assertEqual(result["weather"], {})
        self.assertIn("天气查询失败", result["warnings"][0])
        self.assertEqual(mocked_urlopen.call_count, 3)


class DiaryConfigTest(unittest.TestCase):
    config_keys = (
        "BLOG_AMAP_WEB_SERVICE_KEY",
        "BLOG_DIARY_IMAGE_UPLOAD_DIR",
        "BLOG_DIARY_IMAGE_MAX_BYTES",
        "BLOG_TIMEZONE",
    )

    def setUp(self):
        self._saved_env = {key: os.environ.get(key) for key in self.config_keys}
        for key in self.config_keys:
            os.environ.pop(key, None)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path_patch = mock.patch(
            "app._local_config_path",
            return_value=os.path.join(self.temp_dir.name, "config.py"),
        )
        self.config_path_patch.start()

    def tearDown(self):
        self.config_path_patch.stop()
        self.temp_dir.cleanup()
        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_diary_config_defaults(self):
        app = create_app()

        self.assertEqual(app.config["BLOG_AMAP_WEB_SERVICE_KEY"], "")
        self.assertEqual(
            app.config["BLOG_DIARY_IMAGE_UPLOAD_DIR"],
            os.path.join(project_root, "instance", "uploads", "diaries"),
        )
        self.assertEqual(app.config["BLOG_DIARY_IMAGE_MAX_BYTES"], 10 * 1024 * 1024)
        self.assertEqual(app.config["BLOG_TIMEZONE"], "Asia/Shanghai")

    def test_diary_config_uses_environment_and_strips_api_key(self):
        os.environ["BLOG_AMAP_WEB_SERVICE_KEY"] = " test-api-key "
        os.environ["BLOG_DIARY_IMAGE_UPLOAD_DIR"] = self.temp_dir.name
        os.environ["BLOG_DIARY_IMAGE_MAX_BYTES"] = "4096"
        os.environ["BLOG_TIMEZONE"] = "Asia/Tokyo"

        app = create_app()

        self.assertEqual(app.config["BLOG_AMAP_WEB_SERVICE_KEY"], "test-api-key")
        self.assertEqual(app.config["BLOG_DIARY_IMAGE_UPLOAD_DIR"], self.temp_dir.name)
        self.assertEqual(app.config["BLOG_DIARY_IMAGE_MAX_BYTES"], 4096)
        self.assertEqual(app.config["BLOG_TIMEZONE"], "Asia/Tokyo")


if __name__ == "__main__":
    unittest.main()
