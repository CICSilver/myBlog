import os
import tempfile
import unittest
from unittest.mock import patch

from tinydb import TinyDB
from tinydb.table import Document

from app import create_app
from app.auth import ADMIN_SESSION_KEY, CSRF_SESSION_KEY
from app.database import Blog, DatabaseHelper
import app.database as database_module
import app.routes as routes_module


class ArticleViewDatabaseTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = TinyDB(os.path.join(self.temp_dir.name, "blog_db.json"))
        self.helper = DatabaseHelper()
        self.helper.date_table = self.db.table("date")
        self.helper.category_table = self.db.table("categories")
        self.helper.blog_table = self.db.table("blogs")
        self.helper.article_view_table = self.db.table("article_views")
        self.helper.excluded_article_view_ip_table = self.db.table(
            "article_view_excluded_ips"
        )
        self.helper.settings_table = self.db.table("settings")

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def make_blog(self, html_title="hello", title="Hello"):
        blog = Blog()
        blog.html_title = html_title
        blog.title = title
        blog.category = "Notes"
        blog.year = "2026"
        blog.month = "5"
        blog.date = "2026-05-18"
        blog.time = "10:00:00"
        return blog

    def test_records_each_view_and_summarizes_by_article(self):
        blog = self.make_blog()

        self.helper.record_article_view(blog, "203.0.113.1", "/2026/5/hello", "2026-05-18 10:00:00")
        self.helper.record_article_view(blog, "203.0.113.1", "/2026/5/hello", "2026-05-18 10:01:00")
        self.helper.record_article_view(blog, "203.0.113.2", "/2026/5/hello", "2026-05-18 10:02:00")

        dashboard = self.helper.get_article_view_dashboard()

        self.assertEqual(dashboard["total_views"], 3)
        self.assertEqual(dashboard["unique_ip_count"], 2)
        self.assertEqual(dashboard["article_summaries"][0]["views"], 3)
        self.assertEqual(dashboard["article_summaries"][0]["blog_title"], "Hello")
        self.assertEqual(dashboard["recent_views"][0]["ip"], "203.0.113.2")
        self.assertEqual(dashboard["recent_views"][2]["ip"], "203.0.113.1")

    def test_recent_views_respects_limit(self):
        blog = self.make_blog()

        for index in range(3):
            self.helper.record_article_view(
                blog,
                "203.0.113.{0}".format(index),
                "/2026/5/hello",
                "2026-05-18 10:0{0}:00".format(index),
            )

        dashboard = self.helper.get_article_view_dashboard(recent_limit=2)

        self.assertEqual(len(dashboard["recent_views"]), 2)
        self.assertEqual(dashboard["recent_views"][0]["ip"], "203.0.113.2")
        self.assertEqual(dashboard["recent_views"][1]["ip"], "203.0.113.1")

    def test_record_article_view_stores_public_ipv4_location(self):
        blog = self.make_blog()

        view_record = self.helper.record_article_view(
            blog,
            "113.118.113.77",
            "/2026/5/hello",
            "2026-05-18 10:00:00",
        )

        self.assertEqual(view_record["ip_country"], "中国")
        self.assertEqual(view_record["ip_region"], "广东省")
        self.assertEqual(view_record["ip_city"], "深圳市")
        self.assertEqual(view_record["ip_isp"], "电信")
        self.assertEqual(view_record["ip_location"], "中国 / 广东省 / 深圳市 / 电信")

    def test_dashboard_excludes_loopback_article_views(self):
        blog = self.make_blog()

        self.helper.record_article_view(
            blog,
            "127.0.0.1",
            "/2026/5/hello",
            "2026-05-18 10:00:00",
        )
        self.helper.record_article_view(
            blog,
            "203.0.113.9",
            "/2026/5/hello",
            "2026-05-18 10:01:00",
        )

        dashboard = self.helper.get_article_view_dashboard()

        self.assertEqual(len(self.helper.article_view_table.all()), 2)
        self.assertEqual(dashboard["total_views"], 1)
        self.assertEqual(dashboard["unique_ip_count"], 1)
        self.assertEqual(dashboard["recent_views"][0]["ip"], "203.0.113.9")

    def test_dashboard_excludes_configured_article_view_ip(self):
        blog = self.make_blog()

        self.helper.record_article_view(
            blog,
            "114.221.164.47",
            "/2026/5/hello",
            "2026-05-18 10:00:00",
        )
        self.helper.record_article_view(
            blog,
            "203.0.113.9",
            "/2026/5/hello",
            "2026-05-18 10:01:00",
        )

        dashboard = self.helper.get_article_view_dashboard()

        self.assertEqual(dashboard["total_views"], 1)
        self.assertEqual(dashboard["unique_ip_count"], 1)
        self.assertEqual(dashboard["recent_views"][0]["ip"], "203.0.113.9")
        self.assertIn(
            {"ip": "114.221.164.47", "label": "测试机"},
            dashboard["excluded_ips"],
        )

    def test_excluded_article_view_ip_defaults_are_seeded_once(self):
        excluded_ips = self.helper.get_excluded_article_view_ips()

        self.assertIn(
            {"ip": "114.221.164.47", "label": "测试机"},
            [
                {"ip": excluded_ip["ip"], "label": excluded_ip["label"]}
                for excluded_ip in excluded_ips
            ],
        )

        self.helper.delete_excluded_article_view_ip("114.221.164.47")

        self.assertFalse(self.helper.is_excluded_article_view_ip("114.221.164.47"))
        self.assertNotIn(
            "114.221.164.47",
            [excluded_ip["ip"] for excluded_ip in self.helper.get_excluded_article_view_ips()],
        )

    def test_add_update_and_delete_excluded_article_view_ip(self):
        self.helper.add_excluded_article_view_ip("203.0.113.9", "办公室")

        self.assertTrue(self.helper.is_excluded_article_view_ip("203.0.113.9"))
        self.assertIn(
            {"ip": "203.0.113.9", "label": "办公室"},
            [
                {"ip": excluded_ip["ip"], "label": excluded_ip["label"]}
                for excluded_ip in self.helper.get_excluded_article_view_ips()
            ],
        )

        self.helper.update_excluded_article_view_ip(
            "203.0.113.9",
            "203.0.113.10",
            "新办公室",
        )

        self.assertFalse(self.helper.is_excluded_article_view_ip("203.0.113.9"))
        self.assertTrue(self.helper.is_excluded_article_view_ip("203.0.113.10"))
        self.assertIn(
            {"ip": "203.0.113.10", "label": "新办公室"},
            [
                {"ip": excluded_ip["ip"], "label": excluded_ip["label"]}
                for excluded_ip in self.helper.get_excluded_article_view_ips()
            ],
        )

        self.helper.delete_excluded_article_view_ip("203.0.113.10")

        self.assertFalse(self.helper.is_excluded_article_view_ip("203.0.113.10"))

    def test_dashboard_excludes_verified_crawler_ip_article_views(self):
        blog = self.make_blog()

        self.helper.record_article_view(
            blog,
            "40.77.167.4",
            "/2026/5/hello",
            "2026-05-18 10:00:00",
        )
        self.helper.record_article_view(
            blog,
            "203.0.113.9",
            "/2026/5/hello",
            "2026-05-18 10:01:00",
        )

        with patch("app.database.is_verified_crawler_ip") as is_crawler_ip:
            is_crawler_ip.side_effect = lambda ip: ip == "40.77.167.4"
            dashboard = self.helper.get_article_view_dashboard()

        self.assertEqual(dashboard["total_views"], 1)
        self.assertEqual(dashboard["unique_ip_count"], 1)
        self.assertEqual(dashboard["recent_views"][0]["ip"], "203.0.113.9")

    def test_article_view_insert_retries_when_doc_id_collides(self):
        blog = self.make_blog()
        self.helper.article_view_table.insert(
            Document({"existing": True}, doc_id=4242)
        )
        generated_ids = iter([4242, 4243])
        original_new_doc_id = database_module._new_article_view_doc_id
        database_module._new_article_view_doc_id = lambda: next(generated_ids)

        try:
            self.helper.record_article_view(
                blog,
                "203.0.113.9",
                "/2026/5/hello",
                "2026-05-18 10:00:00",
            )
        finally:
            database_module._new_article_view_doc_id = original_new_doc_id

        inserted = self.helper.article_view_table.get(doc_id=4243)
        self.assertIsNotNone(inserted)
        self.assertEqual(inserted["ip"], "203.0.113.9")
        self.assertEqual(len(self.helper.article_view_table.all()), 2)

    def test_article_view_session_updates_reading_time_without_duplicate_view(self):
        blog = self.make_blog()

        first_record = self.helper.record_or_update_article_view_session(
            blog,
            "113.118.113.77",
            "/2026/5/hello",
            "session-1",
            15,
            "2026-05-18 10:00:15",
        )
        second_record = self.helper.record_or_update_article_view_session(
            blog,
            "113.118.113.77",
            "/2026/5/hello",
            "session-1",
            45,
            "2026-05-18 10:00:45",
        )
        dashboard = self.helper.get_article_view_dashboard()

        self.assertEqual(dashboard["total_views"], 1)
        self.assertEqual(first_record["reading_seconds"], 15)
        self.assertEqual(second_record["reading_seconds"], 45)
        self.assertEqual(second_record["reading_time_label"], "45秒")
        self.assertEqual(second_record["last_seen_at"], "2026-05-18 10:00:45")
        self.assertEqual(dashboard["article_summaries"][0]["total_reading_seconds"], 45)
        self.assertEqual(dashboard["article_summaries"][0]["reading_time_label"], "45秒")

    def test_article_view_session_merges_same_ip_path_within_thirty_seconds(self):
        blog = self.make_blog()

        self.helper.record_or_update_article_view_session(
            blog,
            "203.0.113.9",
            "/2026/5/hello",
            "session-1",
            15,
            "2026-05-18 10:00:15",
        )
        merged_record = self.helper.record_or_update_article_view_session(
            blog,
            "203.0.113.9",
            "/2026/5/hello",
            "session-2",
            25,
            "2026-05-18 10:00:40",
        )
        dashboard = self.helper.get_article_view_dashboard()

        self.assertEqual(len(self.helper.article_view_table.all()), 1)
        self.assertEqual(dashboard["total_views"], 1)
        self.assertEqual(dashboard["article_summaries"][0]["views"], 1)
        self.assertEqual(merged_record["reading_seconds"], 25)
        self.assertEqual(merged_record["last_seen_at"], "2026-05-18 10:00:40")

    def test_article_view_session_counts_same_ip_path_after_thirty_seconds(self):
        blog = self.make_blog()

        self.helper.record_or_update_article_view_session(
            blog,
            "203.0.113.9",
            "/2026/5/hello",
            "session-1",
            15,
            "2026-05-18 10:00:15",
        )
        self.helper.record_or_update_article_view_session(
            blog,
            "203.0.113.9",
            "/2026/5/hello",
            "session-2",
            20,
            "2026-05-18 10:00:46",
        )
        dashboard = self.helper.get_article_view_dashboard()

        self.assertEqual(len(self.helper.article_view_table.all()), 2)
        self.assertEqual(dashboard["total_views"], 2)
        self.assertEqual(dashboard["article_summaries"][0]["views"], 2)

    def test_article_view_compaction_preview_does_not_rewrite_table(self):
        self.helper.article_view_table.insert({"ip": "127.0.0.1"})
        self.helper.article_view_table.insert(
            {
                "year": "2026",
                "month": "5",
                "html_title": "hello",
                "blog_title": "Hello",
                "ip": "203.0.113.9",
                "path": "/2026/5/hello",
                "viewed_at": "2026-05-18 10:00:00",
            }
        )
        self.helper.article_view_table.insert(
            {
                "year": "2026",
                "month": "5",
                "html_title": "hello",
                "blog_title": "Hello",
                "ip": "203.0.113.9",
                "path": "/2026/5/hello",
                "viewed_at": "2026-05-18 10:00:25",
            }
        )

        stats = self.helper.compact_article_views()

        self.assertFalse(stats["applied"])
        self.assertEqual(stats["total_records"], 3)
        self.assertEqual(stats["excluded_ip_records"], 0)
        self.assertEqual(stats["loopback_records"], 1)
        self.assertEqual(stats["crawler_ip_records"], 0)
        self.assertEqual(stats["merged_duplicate_records"], 1)
        self.assertEqual(stats["compacted_records"], 1)
        self.assertEqual(len(self.helper.article_view_table.all()), 3)

    def test_article_view_compaction_apply_removes_loopback_and_merges_duplicates(self):
        self.helper.article_view_table.insert({"ip": "127.0.0.1"})
        for viewed_at in (
            "2026-05-18 10:00:00",
            "2026-05-18 10:00:25",
            "2026-05-18 10:01:00",
        ):
            self.helper.article_view_table.insert(
                {
                    "year": "2026",
                    "month": "5",
                    "html_title": "hello",
                    "blog_title": "Hello",
                    "ip": "203.0.113.9",
                    "path": "/2026/5/hello",
                    "viewed_at": viewed_at,
                    "reading_seconds": 15,
                }
            )

        stats = self.helper.compact_article_views(apply_changes=True)
        dashboard = self.helper.get_article_view_dashboard()

        self.assertTrue(stats["applied"])
        self.assertEqual(stats["total_records"], 4)
        self.assertEqual(stats["excluded_ip_records"], 0)
        self.assertEqual(stats["loopback_records"], 1)
        self.assertEqual(stats["crawler_ip_records"], 0)
        self.assertEqual(stats["merged_duplicate_records"], 1)
        self.assertEqual(stats["compacted_records"], 2)
        self.assertEqual(stats["removed_records"], 2)
        self.assertEqual(len(self.helper.article_view_table.all()), 2)
        self.assertEqual(dashboard["total_views"], 2)

    def test_article_view_compaction_apply_removes_verified_crawler_ip(self):
        self.helper.article_view_table.insert(
            {
                "year": "2026",
                "month": "5",
                "html_title": "hello",
                "blog_title": "Hello",
                "ip": "40.77.167.4",
                "path": "/2026/5/hello",
                "viewed_at": "2026-05-18 10:00:00",
            }
        )
        self.helper.article_view_table.insert(
            {
                "year": "2026",
                "month": "5",
                "html_title": "hello",
                "blog_title": "Hello",
                "ip": "203.0.113.9",
                "path": "/2026/5/hello",
                "viewed_at": "2026-05-18 10:01:00",
            }
        )

        with patch("app.database.is_verified_crawler_ip") as is_crawler_ip:
            is_crawler_ip.side_effect = lambda ip: ip == "40.77.167.4"
            stats = self.helper.compact_article_views(apply_changes=True)

        self.assertEqual(stats["crawler_ip_records"], 1)
        self.assertEqual(stats["compacted_records"], 1)
        self.assertEqual(len(self.helper.article_view_table.all()), 1)
        self.assertEqual(self.helper.article_view_table.all()[0]["ip"], "203.0.113.9")

    def test_article_view_compaction_apply_removes_configured_excluded_ip(self):
        self.helper.article_view_table.insert(
            {
                "year": "2026",
                "month": "5",
                "html_title": "hello",
                "blog_title": "Hello",
                "ip": "114.221.164.47",
                "path": "/2026/5/hello",
                "viewed_at": "2026-05-18 10:00:00",
            }
        )
        self.helper.article_view_table.insert(
            {
                "year": "2026",
                "month": "5",
                "html_title": "hello",
                "blog_title": "Hello",
                "ip": "203.0.113.9",
                "path": "/2026/5/hello",
                "viewed_at": "2026-05-18 10:01:00",
            }
        )

        stats = self.helper.compact_article_views(apply_changes=True)

        self.assertEqual(stats["excluded_ip_records"], 1)
        self.assertEqual(stats["compacted_records"], 1)
        self.assertEqual(len(self.helper.article_view_table.all()), 1)
        self.assertEqual(self.helper.article_view_table.all()[0]["ip"], "203.0.113.9")

    def test_recent_views_adds_unknown_location_for_legacy_records(self):
        self.helper.article_view_table.insert(
            {
                "year": "2026",
                "month": "5",
                "html_title": "legacy",
                "blog_title": "Legacy",
                "ip": "203.0.113.1",
                "viewed_at": "2026-05-18 10:00:00",
                "path": "/2026/5/legacy",
            }
        )

        dashboard = self.helper.get_article_view_dashboard()

        self.assertEqual(dashboard["recent_views"][0]["ip_location"], "未知")


class StubArticleViewHelper:
    def __init__(self):
        self.recorded_views = []
        self.blog = self.make_blog()
        self.dashboard = {
            "total_views": 3,
            "unique_ip_count": 2,
            "article_summaries": [
                {
                    "year": "2026",
                    "month": "5",
                    "html_title": "hello",
                    "blog_title": "Hello",
                    "path": "/2026/5/hello",
                    "views": 3,
                    "last_viewed_at": "2026-05-18 10:02:00",
                }
            ],
            "recent_views": [
                {
                    "year": "2026",
                    "month": "5",
                    "html_title": "hello",
                    "blog_title": "Hello",
                    "ip": "203.0.113.8",
                    "viewed_at": "2026-05-18 10:02:00",
                    "path": "/2026/5/hello",
                }
            ],
            "excluded_ips": [
                {
                    "ip": "114.221.164.47",
                    "label": "测试机",
                }
            ],
        }

    def make_blog(self):
        blog = Blog()
        blog.html_title = "hello"
        blog.title = "Hello"
        blog.content = "body"
        blog.category = "Notes"
        blog.year = "2026"
        blog.month = "5"
        blog.date = "2026-05-18"
        blog.time = "10:00:00"
        return blog

    def get_specify_blog(self, year, month, html_title):
        if (year, month, html_title) == ("2026", "5", "hello"):
            return self.blog
        return None

    def record_article_view(self, blog, ip, path):
        self.recorded_views.append({"blog": blog, "ip": ip, "path": path})

    def record_or_update_article_view_session(self, blog, ip, path, view_session_id, reading_seconds):
        self.recorded_views.append(
            {
                "blog": blog,
                "ip": ip,
                "path": path,
                "view_session_id": view_session_id,
                "reading_seconds": reading_seconds,
                "reading_time_label": "{0}秒".format(reading_seconds),
            }
        )
        return self.recorded_views[-1]

    def get_article_view_dashboard(self, recent_limit=100):
        return self.dashboard

    def is_excluded_article_view_ip(self, ip):
        return any(excluded_ip["ip"] == ip for excluded_ip in self.dashboard["excluded_ips"])

    def add_excluded_article_view_ip(self, ip, label):
        excluded_ip = {"ip": ip, "label": label or "手动排除"}
        self.dashboard["excluded_ips"].append(excluded_ip)
        return excluded_ip

    def update_excluded_article_view_ip(self, original_ip, ip, label):
        for excluded_ip in self.dashboard["excluded_ips"]:
            if excluded_ip["ip"] == original_ip:
                excluded_ip["ip"] = ip
                excluded_ip["label"] = label or "手动排除"
                return excluded_ip
        raise ValueError("要修改的排除 IP 不存在。")

    def delete_excluded_article_view_ip(self, original_ip):
        self.dashboard["excluded_ips"] = [
            excluded_ip
            for excluded_ip in self.dashboard["excluded_ips"]
            if excluded_ip["ip"] != original_ip
        ]


class ArticleViewRouteTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.original_db_helper = routes_module.dbHelper
        self.stub_db_helper = StubArticleViewHelper()
        routes_module.dbHelper = self.stub_db_helper

    def tearDown(self):
        routes_module.dbHelper = self.original_db_helper

    def post_article_view_ping(
        self,
        client,
        csrf_token="csrf-token",
        payload=None,
        headers=None,
        remote_addr="198.51.100.10",
    ):
        with client.session_transaction() as flask_session:
            flask_session[CSRF_SESSION_KEY] = csrf_token

        request_payload = {
            "year": "2026",
            "month": "5",
            "html_title": "hello",
            "view_session_id": "session-1",
            "reading_seconds": 15,
        }
        if payload:
            request_payload.update(payload)

        request_headers = {"X-CSRF-Token": csrf_token}
        if headers:
            request_headers.update(headers)

        return client.post(
            "/track/article-view",
            json=request_payload,
            headers=request_headers,
            environ_overrides={"REMOTE_ADDR": remote_addr},
        )

    def test_article_detail_waits_for_client_tracking_before_recording(self):
        with self.app.test_client() as client:
            response = client.get(
                "/2026/5/hello",
                environ_overrides={"REMOTE_ADDR": "198.51.100.10"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.stub_db_helper.recorded_views, [])
        self.assertIn("BLOG_ARTICLE_VIEW_TRACKING", response.get_data(as_text=True))

    def test_article_detail_skips_loopback_tracking_config(self):
        with self.app.test_client() as client:
            response = client.get(
                "/2026/5/hello",
                environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.stub_db_helper.recorded_views, [])
        self.assertNotIn("BLOG_ARTICLE_VIEW_TRACKING", response.get_data(as_text=True))

    def test_article_detail_skips_excluded_ip_tracking_config(self):
        with self.app.test_client() as client:
            response = client.get(
                "/2026/5/hello",
                environ_overrides={"REMOTE_ADDR": "114.221.164.47"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.stub_db_helper.recorded_views, [])
        self.assertNotIn("BLOG_ARTICLE_VIEW_TRACKING", response.get_data(as_text=True))

    def test_tracking_records_effective_view_with_remote_addr(self):
        with self.app.test_client() as client:
            response = self.post_article_view_ping(client)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.stub_db_helper.recorded_views), 1)
        self.assertEqual(self.stub_db_helper.recorded_views[0]["ip"], "198.51.100.10")
        self.assertEqual(self.stub_db_helper.recorded_views[0]["path"], "/2026/5/hello")
        self.assertEqual(self.stub_db_helper.recorded_views[0]["reading_seconds"], 15)

    def test_article_detail_skips_admin_view(self):
        with self.app.test_client() as client:
            with client.session_transaction() as flask_session:
                flask_session[ADMIN_SESSION_KEY] = True

            response = client.get(
                "/2026/5/hello",
                environ_overrides={"REMOTE_ADDR": "198.51.100.10"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.stub_db_helper.recorded_views, [])

    def test_tracking_skips_admin_view(self):
        with self.app.test_client() as client:
            with client.session_transaction() as flask_session:
                flask_session[ADMIN_SESSION_KEY] = True
                flask_session[CSRF_SESSION_KEY] = "csrf-token"

            response = client.post(
                "/track/article-view",
                json={
                    "year": "2026",
                    "month": "5",
                    "html_title": "hello",
                    "view_session_id": "session-1",
                    "reading_seconds": 15,
                },
                headers={"X-CSRF-Token": "csrf-token"},
                environ_overrides={"REMOTE_ADDR": "198.51.100.10"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["reason"], "admin")
        self.assertEqual(self.stub_db_helper.recorded_views, [])

    def test_tracking_skips_bingbot_user_agent(self):
        with self.app.test_client() as client:
            response = self.post_article_view_ping(
                client,
                headers={"User-Agent": "Mozilla/5.0 (compatible; bingbot/2.0)"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["reason"], "crawler")
        self.assertEqual(self.stub_db_helper.recorded_views, [])

    def test_tracking_skips_verified_crawler_ip(self):
        with patch("app.routes.is_verified_crawler_ip") as is_crawler_ip:
            is_crawler_ip.side_effect = lambda ip: ip == "40.77.167.4"
            with self.app.test_client() as client:
                response = self.post_article_view_ping(
                    client,
                    remote_addr="40.77.167.4",
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["reason"], "crawler")
        self.assertEqual(self.stub_db_helper.recorded_views, [])

    def test_tracking_skips_excluded_remote_addr(self):
        with self.app.test_client() as client:
            response = self.post_article_view_ping(
                client,
                remote_addr="114.221.164.47",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["reason"], "excluded_ip")
        self.assertEqual(self.stub_db_helper.recorded_views, [])

    def test_tracking_skips_loopback_remote_addr(self):
        with self.app.test_client() as client:
            response = self.post_article_view_ping(
                client,
                remote_addr="127.0.0.1",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["reason"], "local_test")
        self.assertEqual(self.stub_db_helper.recorded_views, [])

    def test_tracking_skips_short_view(self):
        with self.app.test_client() as client:
            response = self.post_article_view_ping(
                client,
                payload={"reading_seconds": 14},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["reason"], "short_view")
        self.assertEqual(self.stub_db_helper.recorded_views, [])

    def test_tracking_uses_forwarded_ip_when_trusted(self):
        self.app.config["BLOG_TRUST_PROXY_HEADERS"] = True

        with self.app.test_client() as client:
            response = self.post_article_view_ping(
                client,
                headers={"X-Forwarded-For": "203.0.113.9, 198.51.100.10"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.stub_db_helper.recorded_views[0]["ip"], "203.0.113.9")

    def test_missing_article_does_not_record_view(self):
        with self.app.test_client() as client:
            response = client.get("/2026/5/missing")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.stub_db_helper.recorded_views, [])

    def test_view_stats_requires_login(self):
        with self.app.test_client() as client:
            response = client.get("/manage/views", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertIn(self.app.config["ADMIN_LOGIN_PATH"], response.headers["Location"])

    def test_view_stats_page_renders_dashboard(self):
        with self.app.test_client() as client:
            with client.session_transaction() as flask_session:
                flask_session[ADMIN_SESSION_KEY] = True

            response = client.get("/manage/views")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("浏览量统计", html)
        self.assertIn("排除 IP 列表", html)
        self.assertIn("114.221.164.47", html)
        self.assertIn("测试机", html)
        self.assertIn('action="/manage/views/excluded-ips"', html)
        self.assertIn('name="original_ip"', html)
        self.assertIn("保存", html)
        self.assertIn("删除", html)
        self.assertIn("<th>地域</th>", html)
        self.assertIn("Hello", html)
        self.assertIn("203.0.113.8", html)
        self.assertIn("未知", html)
        self.assertIn("/2026/5/hello", html)

    def test_add_excluded_ip_from_view_stats_page(self):
        with self.app.test_client() as client:
            with client.session_transaction() as flask_session:
                flask_session[ADMIN_SESSION_KEY] = True
                flask_session[CSRF_SESSION_KEY] = "csrf-token"

            response = client.post(
                "/manage/views/excluded-ips",
                data={
                    "csrf_token": "csrf-token",
                    "ip": "203.0.113.9",
                    "label": "办公室",
                },
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        self.assertIn(
            {"ip": "203.0.113.9", "label": "办公室"},
            self.stub_db_helper.dashboard["excluded_ips"],
        )

    def test_update_and_delete_excluded_ip_from_view_stats_page(self):
        with self.app.test_client() as client:
            with client.session_transaction() as flask_session:
                flask_session[ADMIN_SESSION_KEY] = True
                flask_session[CSRF_SESSION_KEY] = "csrf-token"

            update_response = client.post(
                "/manage/views/excluded-ips/update",
                data={
                    "csrf_token": "csrf-token",
                    "original_ip": "114.221.164.47",
                    "ip": "114.221.164.48",
                    "label": "新测试机",
                },
                follow_redirects=False,
            )

            delete_response = client.post(
                "/manage/views/excluded-ips/delete",
                data={
                    "csrf_token": "csrf-token",
                    "original_ip": "114.221.164.48",
                },
                follow_redirects=False,
            )

        self.assertEqual(update_response.status_code, 302)
        self.assertEqual(delete_response.status_code, 302)
        self.assertNotIn(
            "114.221.164.48",
            [excluded_ip["ip"] for excluded_ip in self.stub_db_helper.dashboard["excluded_ips"]],
        )


if __name__ == "__main__":
    unittest.main()
