import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock, patch

from app import create_app
from app.auth import ADMIN_SESSION_KEY, CSRF_SESSION_KEY
from app.database import Diary
import app.routes as routes_module


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


class DiaryRouteDatabase:
    def __init__(self):
        self.diaries = {}
        self.save_calls = []
        self.save_exception = None

    @staticmethod
    def _copy(diary):
        return Diary(
            entry_date=diary.entry_date,
            content=diary.content,
            image_url=diary.image_url,
            created_at=diary.created_at,
            updated_at=diary.updated_at,
            location=dict(diary.location),
            weather=dict(diary.weather),
        )

    @staticmethod
    def _merge(existing, incoming):
        merged = dict(existing or {})
        for key, value in incoming.items():
            if (
                key not in merged
                or merged[key] is None
                or merged[key] == ""
            ) and value is not None and value != "":
                merged[key] = value
        return merged

    def add(self, diary):
        self.diaries[diary.entry_date] = self._copy(diary)

    def get_diary_by_date(self, entry_date):
        diary = self.diaries.get(entry_date)
        return self._copy(diary) if diary else None

    def get_all_diaries(self):
        return [
            self._copy(self.diaries[entry_date])
            for entry_date in sorted(self.diaries, reverse=True)
        ]

    def get_diaries_by_month(self, year, month):
        prefix = "{0}-{1:02d}-".format(year, int(month))
        return [
            diary for diary in self.get_all_diaries() if diary.entry_date.startswith(prefix)
        ]

    def save_today_diary(self, diary, today):
        self.save_calls.append(self._copy(diary))
        if self.save_exception:
            raise self.save_exception
        if diary.entry_date != today:
            raise ValueError("只能保存当天日记。")
        if not diary.content or not diary.content.strip():
            raise ValueError("日记正文不能为空。")

        existing = self.diaries.get(today)
        if existing:
            saved = Diary(
                entry_date=today,
                content=diary.content,
                image_url=diary.image_url,
                created_at=existing.created_at,
                updated_at=diary.updated_at,
                location=self._merge(existing.location, diary.location),
                weather=self._merge(existing.weather, diary.weather),
            )
            operation = "updated"
            message = "今日日记更新成功。"
        else:
            saved = self._copy(diary)
            operation = "inserted"
            message = "今日日记保存成功。"

        self.diaries[today] = saved
        return {
            "status": "success",
            "operation": operation,
            "message": message,
        }


class DiaryRouteTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app = create_app()
        self.app.config.update(
            TESTING=True,
            BLOG_TIMEZONE="Asia/Shanghai",
            BLOG_DIARY_IMAGE_UPLOAD_DIR=self.temp_dir.name,
            BLOG_DIARY_IMAGE_MAX_BYTES=1024 * 1024,
            BLOG_AMAP_WEB_SERVICE_KEY="test-amap-key",
        )
        self.original_db_helper = routes_module.dbHelper
        self.original_zoneinfo = routes_module.ZoneInfo
        self.db = DiaryRouteDatabase()
        self.zoneinfo = Mock(return_value=timezone.utc)
        routes_module.dbHelper = self.db
        routes_module.ZoneInfo = self.zoneinfo

    def tearDown(self):
        routes_module.dbHelper = self.original_db_helper
        routes_module.ZoneInfo = self.original_zoneinfo
        self.temp_dir.cleanup()

    def today(self):
        return datetime.now(timezone.utc).date()

    def login(self, client, csrf_token="csrf-token"):
        with client.session_transaction() as session:
            session[ADMIN_SESSION_KEY] = True
            session[CSRF_SESSION_KEY] = csrf_token

    def make_diary(
        self,
        entry_date,
        content="日记正文",
        image_url="",
        location=None,
        weather=None,
    ):
        return Diary(
            entry_date=entry_date,
            content=content,
            image_url=image_url,
            created_at="2026-09-02T08:00:00+08:00",
            updated_at="2026-09-02T08:00:00+08:00",
            location=location,
            weather=weather,
        )

    def metadata_result(
        self,
        latitude=31.2,
        longitude=118.7,
        accuracy=9.0,
        city="南京",
        condition="晴",
        temperature="25",
        warnings=None,
    ):
        return {
            "location": {
                "latitude": latitude,
                "longitude": longitude,
                "accuracy_m": accuracy,
                "province": "江苏省",
                "city": city,
                "district": "玄武区",
                "formatted_address": "江苏省南京市玄武区",
                "adcode": "320102",
            },
            "weather": {
                "condition": condition,
                "temperature_c": temperature,
                "report_time": "2026-09-02 08:00:00",
            },
            "warnings": warnings or [],
        }

    def post_diary(self, client, data=None):
        form_data = {"content": "今天的内容"}
        if data:
            form_data.update(data)
        return client.post(
            "/diary",
            headers={"X-CSRF-Token": "csrf-token"},
            data=form_data,
        )

    def test_routes_require_admin_login(self):
        today = self.today()
        diary_rules = {
            rule.endpoint: rule.methods
            for rule in self.app.url_map.iter_rules()
            if rule.rule == "/diary"
        }

        with self.app.test_client() as client:
            diary_response = client.get("/diary")
            detail_response = client.get(
                "/diary/{0}/{1}/{2}".format(today.year, today.month, today.day)
            )
            media_response = client.get("/media/diaries/2026/09/private.png")
            post_response = client.post("/diary", data={"content": "未登录"})

        self.assertEqual(diary_response.status_code, 302)
        self.assertEqual(detail_response.status_code, 302)
        self.assertEqual(media_response.status_code, 302)
        self.assertEqual(post_response.status_code, 401)
        self.assertEqual(post_response.get_json()["status"], "error")
        self.assertIn("main.diary", diary_rules)
        self.assertIn("main.save_diary", diary_rules)
        self.assertIn("GET", diary_rules["main.diary"])
        self.assertNotIn("POST", diary_rules["main.diary"])
        self.assertIn("POST", diary_rules["main.save_diary"])
        self.assertNotIn("GET", diary_rules["main.save_diary"])

    def test_current_month_renders_today_week_and_entry_context(self):
        today = self.today()
        self.db.add(self.make_diary(today.isoformat(), content="今天已经写下的内容"))

        with self.app.test_client() as client:
            self.login(client)
            response = client.get("/diary")

        html = response.get_data(as_text=True)
        detail_url = "/diary/{0}/{1}/{2}".format(today.year, today.month, today.day)
        self.assertEqual(response.status_code, 200)
        self.assertIn(today.isoformat(), html)
        self.assertIn("今天已经写下的内容", html)
        self.assertIn("今天", html)
        self.assertIn("周", html)
        self.assertIn(detail_url, html)
        self.assertIn('data-needs-location="true"', html)
        self.zoneinfo.assert_called_with("Asia/Shanghai")

    def test_past_month_renders_archive_without_today_editor(self):
        past_day = self.today().replace(day=1) - timedelta(days=1)
        self.db.add(self.make_diary(past_day.isoformat(), content="上个月的日记"))
        month_value = past_day.strftime("%Y-%m")

        with self.app.test_client() as client:
            self.login(client)
            response = client.get("/diary?month={0}".format(month_value))

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("上个月的日记", html)
        self.assertIn("这个月的日记仅供回看。", html)
        self.assertIn("{0} 年 {1} 月".format(past_day.year, past_day.month), html)
        self.assertNotIn('id="diary-form"', html)

    def test_invalid_or_future_month_is_rejected(self):
        future_month = (self.today().replace(day=28) + timedelta(days=7)).strftime(
            "%Y-%m"
        )

        with self.app.test_client() as client:
            self.login(client)
            invalid_response = client.get("/diary?month=not-a-month")
            zero_year_response = client.get("/diary?month=0000-01")
            future_response = client.get("/diary?month={0}".format(future_month))

        self.assertEqual(invalid_response.status_code, 400)
        self.assertEqual(zero_year_response.status_code, 400)
        self.assertEqual(future_response.status_code, 400)

    def test_post_requires_csrf_token(self):
        with self.app.test_client() as client:
            self.login(client)
            response = client.post("/diary", data={"content": "缺少令牌"})

        self.assertEqual(response.status_code, 403)

    def test_post_creates_and_updates_the_server_selected_day(self):
        today = self.today()
        metadata = self.metadata_result()

        with patch("app.routes.fetch_diary_metadata", return_value=metadata) as fetch:
            with self.app.test_client() as client:
                self.login(client)
                create_response = self.post_diary(
                    client,
                    {
                        "content": "第一次保存",
                        "entry_date": "1999-01-01",
                        "latitude": "31.2",
                        "longitude": "118.7",
                        "accuracy": "9",
                    },
                )
                update_response = self.post_diary(client, {"content": "第二次保存"})

        create_data = create_response.get_json()
        update_data = update_response.get_json()
        stored = self.db.get_diary_by_date(today.isoformat())
        self.assertEqual(create_response.status_code, 200)
        self.assertEqual(
            set(create_data),
            {"status", "operation", "message", "detail_url", "warnings"},
        )
        self.assertEqual(create_data["status"], "success")
        self.assertEqual(create_data["operation"], "inserted")
        self.assertEqual(create_data["warnings"], [])
        self.assertEqual(update_data["operation"], "updated")
        self.assertEqual(stored.entry_date, today.isoformat())
        self.assertEqual(stored.content, "第二次保存")
        self.assertTrue(stored.created_at.endswith("+00:00"))
        self.assertTrue(stored.updated_at.endswith("+00:00"))
        fetch.assert_called_once_with(31.2, 118.7, 9.0, "test-amap-key")

    def test_post_keeps_replaces_and_removes_images_without_deleting_old_files(self):
        today = self.today()
        full_location = {
            "latitude": 31.2,
            "longitude": 118.7,
            "formatted_address": "江苏省南京市玄武区",
        }
        full_weather = {"condition": "晴", "temperature_c": "25"}
        self.db.add(
            self.make_diary(
                today.isoformat(),
                image_url="old.png",
                location=full_location,
                weather=full_weather,
            )
        )
        old_image = Path(self.temp_dir.name) / "old.png"
        old_image.write_bytes(PNG_BYTES)

        with self.app.test_client() as client:
            self.login(client)
            keep_response = self.post_diary(client, {"content": "保留原图"})
            replace_response = self.post_diary(
                client,
                {
                    "content": "换成新图",
                    "remove-image": "1",
                    "diary-image": (BytesIO(PNG_BYTES), "new.png"),
                },
            )
            new_image_url = self.db.get_diary_by_date(today.isoformat()).image_url
            remove_response = self.post_diary(
                client,
                {"content": "去掉图片", "remove-image": "1"},
            )

        new_image = Path(self.temp_dir.name, *new_image_url.split("/"))
        self.assertEqual(keep_response.status_code, 200)
        self.assertEqual(
            self.db.save_calls[0].image_url,
            "old.png",
        )
        self.assertEqual(replace_response.status_code, 200)
        self.assertNotEqual(new_image_url, "old.png")
        self.assertTrue(new_image.exists())
        self.assertTrue(old_image.exists())
        self.assertEqual(remove_response.status_code, 200)
        self.assertEqual(self.db.get_diary_by_date(today.isoformat()).image_url, "")
        self.assertTrue(old_image.exists())
        self.assertTrue(new_image.exists())

    def test_post_rejects_multiple_images(self):
        today = self.today()
        self.db.add(
            self.make_diary(
                today.isoformat(),
                location={
                    "latitude": 31.2,
                    "longitude": 118.7,
                    "formatted_address": "江苏省南京市玄武区",
                },
                weather={"condition": "晴", "temperature_c": "25"},
            )
        )

        with self.app.test_client() as client:
            self.login(client)
            response = self.post_diary(
                client,
                {
                    "diary-image": [
                        (BytesIO(PNG_BYTES), "first.png"),
                        (BytesIO(PNG_BYTES), "second.png"),
                    ]
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["status"], "error")
        self.assertEqual(self.db.save_calls, [])

    def test_failed_save_removes_the_newly_uploaded_image(self):
        self.db.save_exception = RuntimeError("database unavailable")
        metadata = self.metadata_result()

        with patch("app.routes.fetch_diary_metadata", return_value=metadata):
            with self.app.test_client() as client:
                self.login(client)
                with self.assertRaisesRegex(RuntimeError, "database unavailable"):
                    self.post_diary(
                        client,
                        {
                            "latitude": "31.2",
                            "longitude": "118.7",
                            "accuracy": "9",
                            "diary-image": (BytesIO(PNG_BYTES), "orphan.png"),
                        },
                    )

        self.assertEqual(list(Path(self.temp_dir.name).rglob("*.png")), [])

    def test_empty_content_is_rejected_before_metadata_or_image_write(self):
        with patch("app.routes.fetch_diary_metadata") as fetch:
            with self.app.test_client() as client:
                self.login(client)
                response = self.post_diary(
                    client,
                    {
                        "content": "   ",
                        "latitude": "31.2",
                        "longitude": "118.7",
                        "accuracy": "9",
                        "diary-image": (BytesIO(PNG_BYTES), "empty-content.png"),
                    },
                )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["status"], "error")
        self.assertEqual(list(Path(self.temp_dir.name).rglob("*.png")), [])
        self.assertIsNone(self.db.get_diary_by_date(self.today().isoformat()))
        self.assertEqual(self.db.save_calls, [])
        fetch.assert_not_called()
        self.zoneinfo.assert_not_called()

    def test_metadata_success_is_saved_with_submitted_coordinates(self):
        metadata = self.metadata_result()

        with patch("app.routes.fetch_diary_metadata", return_value=metadata) as fetch:
            with self.app.test_client() as client:
                self.login(client)
                response = self.post_diary(
                    client,
                    {"latitude": "31.2", "longitude": "118.7", "accuracy": "9"},
                )

        stored = self.db.get_diary_by_date(self.today().isoformat())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["warnings"], [])
        self.assertEqual(stored.location["formatted_address"], "江苏省南京市玄武区")
        self.assertEqual(stored.weather["condition"], "晴")
        fetch.assert_called_once_with(31.2, 118.7, 9.0, "test-amap-key")

    def test_zero_coordinates_are_valid(self):
        metadata = self.metadata_result(latitude=0.0, longitude=0.0, accuracy=0.0)

        with patch("app.routes.fetch_diary_metadata", return_value=metadata) as fetch:
            with self.app.test_client() as client:
                self.login(client)
                response = self.post_diary(
                    client,
                    {"latitude": "0", "longitude": "0", "accuracy": "0"},
                )

        self.assertEqual(response.status_code, 200)
        fetch.assert_called_once_with(0.0, 0.0, 0.0, "test-amap-key")

    def test_metadata_warning_does_not_block_content_save(self):
        failed_metadata = {
            "location": {"latitude": 31.2, "longitude": 118.7, "accuracy_m": 9.0},
            "weather": {},
            "warnings": ["高德坐标转换失败，未获取位置和天气信息。"],
        }

        with patch("app.routes.fetch_diary_metadata", return_value=failed_metadata):
            with self.app.test_client() as client:
                self.login(client)
                response = self.post_diary(
                    client,
                    {
                        "content": "高德失败也要保存",
                        "latitude": "31.2",
                        "longitude": "118.7",
                        "accuracy": "9",
                    },
                )

        stored = self.db.get_diary_by_date(self.today().isoformat())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json()["warnings"],
            ["高德坐标转换失败，未获取位置和天气信息。"],
        )
        self.assertEqual(stored.content, "高德失败也要保存")
        self.assertEqual(stored.location["latitude"], 31.2)

    def test_metadata_uses_original_location_coordinates_and_only_fills_empty_fields(self):
        today = self.today()
        self.db.add(
            self.make_diary(
                today.isoformat(),
                location={
                    "latitude": 31.2,
                    "longitude": 118.7,
                    "accuracy_m": 5.0,
                    "city": "南京",
                    "formatted_address": "",
                },
                weather={"condition": "晴", "temperature_c": "20"},
            )
        )
        metadata = self.metadata_result(
            latitude=32.0,
            longitude=120.0,
            accuracy=50.0,
            city="苏州",
        )

        with patch("app.routes.fetch_diary_metadata", return_value=metadata) as fetch:
            with self.app.test_client() as client:
                self.login(client)
                response = self.post_diary(
                    client,
                    {
                        "latitude": "30.0",
                        "longitude": "110.0",
                        "accuracy": "100",
                    },
                )

        stored = self.db.get_diary_by_date(today.isoformat())
        self.assertEqual(response.status_code, 200)
        fetch.assert_called_once_with(31.2, 118.7, 5.0, "test-amap-key")
        self.assertEqual(stored.location["latitude"], 31.2)
        self.assertEqual(stored.location["longitude"], 118.7)
        self.assertEqual(stored.location["city"], "南京")
        self.assertEqual(stored.location["formatted_address"], "江苏省南京市玄武区")
        self.assertEqual(stored.weather["condition"], "晴")
        self.assertEqual(stored.weather["temperature_c"], "20")

    def test_metadata_fills_missing_weather_keys_without_replacing_existing_values(self):
        today = self.today()
        self.db.add(
            self.make_diary(
                today.isoformat(),
                location={
                    "latitude": 31.2,
                    "longitude": 118.7,
                    "formatted_address": "江苏省南京市玄武区",
                },
                weather={"condition": "晴", "temperature_c": ""},
            )
        )
        metadata = self.metadata_result(condition="雨", temperature="26")

        with patch("app.routes.fetch_diary_metadata", return_value=metadata) as fetch:
            with self.app.test_client() as client:
                self.login(client)
                response = self.post_diary(
                    client,
                    {"latitude": "30.0", "longitude": "110.0", "accuracy": "100"},
                )

        stored = self.db.get_diary_by_date(today.isoformat())
        self.assertEqual(response.status_code, 200)
        fetch.assert_called_once_with(31.2, 118.7, None, "test-amap-key")
        self.assertEqual(stored.weather["condition"], "晴")
        self.assertEqual(stored.weather["temperature_c"], "26")

    def test_missing_coordinates_returns_a_warning_but_saves(self):
        with patch("app.routes.fetch_diary_metadata") as fetch:
            with self.app.test_client() as client:
                self.login(client)
                response = self.post_diary(client, {"content": "没有定位也保存"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json()["warnings"],
            ["当前连接未提供定位，天气和位置未记录。"],
        )
        self.assertEqual(self.db.get_diary_by_date(self.today().isoformat()).content, "没有定位也保存")
        fetch.assert_not_called()

    def test_invalid_coordinates_are_rejected(self):
        cases = [
            {"latitude": "nan", "longitude": "118.7", "accuracy": "9"},
            {"latitude": "91", "longitude": "118.7", "accuracy": "9"},
            {"latitude": "31.2", "longitude": "181", "accuracy": "9"},
            {"latitude": "31.2", "longitude": "118.7", "accuracy": "-1"},
            {"latitude": "31.2", "longitude": "", "accuracy": "9"},
        ]

        with self.app.test_client() as client:
            self.login(client)
            for data in cases:
                with self.subTest(data=data):
                    response = self.post_diary(client, data)
                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(response.get_json()["status"], "error")

        self.assertEqual(self.db.save_calls, [])

    def test_private_media_route_serves_authenticated_files(self):
        media_path = Path(self.temp_dir.name) / "2026" / "09" / "private.png"
        media_path.parent.mkdir(parents=True)
        media_path.write_bytes(PNG_BYTES)

        with self.app.test_client() as client:
            unauthenticated_response = client.get("/media/diaries/2026/09/private.png")
            self.login(client)
            authenticated_response = client.get("/media/diaries/2026/09/private.png")

        self.assertEqual(unauthenticated_response.status_code, 302)
        self.assertEqual(authenticated_response.status_code, 200)
        self.assertEqual(authenticated_response.get_data(), PNG_BYTES)
        authenticated_response.close()

    def test_detail_uses_date_order_for_previous_and_next_entries(self):
        today = self.today()
        older_day = today - timedelta(days=3)
        current_day = today - timedelta(days=2)
        newer_day = today - timedelta(days=1)
        for entry_day, content in (
            (older_day, "更早的日记"),
            (current_day, "当前的日记"),
            (newer_day, "更新的日记"),
        ):
            self.db.add(self.make_diary(entry_day.isoformat(), content=content))

        with self.app.test_client() as client:
            self.login(client)
            response = client.get(
                "/diary/{0}/{1}/{2}".format(
                    current_day.year,
                    current_day.month,
                    current_day.day,
                )
            )

        html = response.get_data(as_text=True)
        older_url = "/diary/{0}/{1}/{2}".format(
            older_day.year,
            older_day.month,
            older_day.day,
        )
        newer_url = "/diary/{0}/{1}/{2}".format(
            newer_day.year,
            newer_day.month,
            newer_day.day,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("当前的日记", html)
        self.assertIn('class="diary-detail-previous" href="{0}"'.format(older_url), html)
        self.assertIn('class="diary-detail-next" href="{0}"'.format(newer_url), html)
        self.assertIn(older_day.isoformat(), html)
        self.assertIn(newer_day.isoformat(), html)

    def test_detail_missing_entry_is_404_and_no_delete_route_exists(self):
        today = self.today()

        with self.app.test_client() as client:
            self.login(client)
            missing_response = client.get(
                "/diary/{0}/{1}/{2}".format(today.year, today.month, today.day)
            )
            invalid_date_response = client.get("/diary/2026/2/30")
            delete_response = client.delete(
                "/diary/{0}/{1}/{2}".format(today.year, today.month, today.day)
            )
            delete_path_response = client.post(
                "/diary/{0}/{1}/{2}/delete".format(today.year, today.month, today.day)
            )

        self.assertEqual(missing_response.status_code, 404)
        self.assertEqual(invalid_date_response.status_code, 404)
        self.assertEqual(delete_response.status_code, 405)
        self.assertEqual(delete_path_response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
