import unittest

from app import create_app
from app.auth import ADMIN_SESSION_KEY, CSRF_SESSION_KEY
import app.routes as routes_module


class StubDatabaseHelper:
    def __init__(self):
        self.insert_called = False

    def get_all_categories(self):
        return [{"name": "随笔", "num": 2}]

    def get_all_date(self):
        return [{"year": "2026", "month": "4", "num": 3}]

    def insert_blog(self, blog):
        self.insert_called = True
        return {"status": "success", "message": "ok", "html_title": blog.html_title}


class HomepageCoverRenderingTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.original_db_helper = routes_module.dbHelper
        self.stub_db_helper = StubDatabaseHelper()
        routes_module.dbHelper = self.stub_db_helper

    def tearDown(self):
        routes_module.dbHelper = self.original_db_helper

    def make_blog(self, html_title, title, cover_url=None):
        blog = {
            "html_title": html_title,
            "title": title,
            "content": "摘要内容\n\n![正文图片](/static/body.jpg)",
            "category": "随笔",
            "year": "2026",
            "month": "4",
            "date": "2026-04-30",
            "time": "10:00:00",
        }
        if cover_url is not None:
            blog["cover_url"] = cover_url
        return blog

    def test_homepage_mixes_cover_and_text_only_entries(self):
        blogs = [
            self.make_blog("featured", "最新文章", "/static/vendor/editor.md/examples/images/8.jpg"),
            self.make_blog("without_cover", "没有封面的文章"),
            self.make_blog("with_cover", "有封面的归档", "/static/vendor/editor.md/examples/images/4.jpg"),
        ]

        with self.app.test_request_context("/"):
            html = routes_module.init_index_with_blogs(blogs)

        self.assertIn('class="feature-article has-cover"', html)
        self.assertIn('class="feature-cover"', html)
        self.assertIn('src="/static/vendor/editor.md/examples/images/8.jpg"', html)
        self.assertIn('class="entry-line"', html)
        self.assertIn('class="entry-line has-cover"', html)
        self.assertIn('class="entry-cover"', html)
        self.assertIn("没有封面的文章", html)

    def test_invalid_cover_url_is_rejected_before_insert(self):
        with self.app.test_client() as client:
            with client.session_transaction() as session:
                session[ADMIN_SESSION_KEY] = True
                session[CSRF_SESSION_KEY] = "csrf-token"

            response = client.post(
                "/edit",
                headers={"X-CSRF-Token": "csrf-token"},
                data={
                    "html-title": "bad_cover",
                    "title": "Bad cover",
                    "content": "content",
                    "category": "随笔",
                    "cover-url": "http://example.com/cover.jpg",
                    "month": "",
                    "year": "",
                    "date": "",
                    "time": "",
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.stub_db_helper.insert_called)
        self.assertEqual(response.get_json()["status"], "error")


if __name__ == "__main__":
    unittest.main()
