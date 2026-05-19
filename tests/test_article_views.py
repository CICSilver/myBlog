import os
import tempfile
import unittest

from tinydb import TinyDB

from app import create_app
from app.auth import ADMIN_SESSION_KEY
from app.database import Blog, DatabaseHelper
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

    def get_article_view_dashboard(self, recent_limit=100):
        return self.dashboard


class ArticleViewRouteTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.original_db_helper = routes_module.dbHelper
        self.stub_db_helper = StubArticleViewHelper()
        routes_module.dbHelper = self.stub_db_helper

    def tearDown(self):
        routes_module.dbHelper = self.original_db_helper

    def test_article_detail_records_view_with_remote_addr(self):
        with self.app.test_client() as client:
            response = client.get(
                "/2026/5/hello",
                environ_overrides={"REMOTE_ADDR": "198.51.100.10"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.stub_db_helper.recorded_views), 1)
        self.assertEqual(self.stub_db_helper.recorded_views[0]["ip"], "198.51.100.10")
        self.assertEqual(self.stub_db_helper.recorded_views[0]["path"], "/2026/5/hello")

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

    def test_article_detail_uses_forwarded_ip_when_trusted(self):
        self.app.config["BLOG_TRUST_PROXY_HEADERS"] = True

        with self.app.test_client() as client:
            response = client.get(
                "/2026/5/hello",
                headers={"X-Forwarded-For": "203.0.113.9, 198.51.100.10"},
                environ_overrides={"REMOTE_ADDR": "198.51.100.10"},
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
        self.assertIn("Hello", html)
        self.assertIn("203.0.113.8", html)
        self.assertIn("/2026/5/hello", html)


if __name__ == "__main__":
    unittest.main()
