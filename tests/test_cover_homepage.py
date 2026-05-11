import re
import unittest
from pathlib import Path

from flask import session

from app import create_app
from app.auth import ADMIN_SESSION_KEY, CSRF_SESSION_KEY
from app.database import Blog
import app.routes as routes_module


class StubDatabaseHelper:
    def __init__(self):
        self.insert_called = False
        self.last_inserted_blog = None
        self.specified_blog = None

    def get_all_blogs(self):
        return []

    def get_all_categories(self):
        return [{"name": "随笔", "num": 2}]

    def get_all_date(self):
        return [{"year": "2026", "month": "4", "num": 3}]

    def insert_blog(self, blog):
        self.insert_called = True
        self.last_inserted_blog = blog
        return {"status": "success", "message": "ok", "html_title": blog.html_title}

    def get_specify_blog(self, year, month, html_title):
        return self.specified_blog


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

    def test_media_cover_url_is_accepted_on_insert(self):
        with self.app.test_client() as client:
            with client.session_transaction() as session:
                session[ADMIN_SESSION_KEY] = True
                session[CSRF_SESSION_KEY] = "csrf-token"

            response = client.post(
                "/edit",
                headers={"X-CSRF-Token": "csrf-token"},
                data={
                    "html-title": "media_cover",
                    "title": "Media cover",
                    "content": "content",
                    "category": "随笔",
                    "cover-url": "/media/covers/2026/05/upload.jpg",
                    "month": "",
                    "year": "",
                    "date": "",
                    "time": "",
                    "action": "insert",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.stub_db_helper.insert_called)
        self.assertEqual(self.stub_db_helper.last_inserted_blog.cover_url, "/media/covers/2026/05/upload.jpg")

    def test_edit_page_renders_cover_upload_control(self):
        with self.app.test_client() as client:
            with client.session_transaction() as flask_session:
                flask_session[ADMIN_SESSION_KEY] = True

            response = client.get("/edit")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('type="hidden"', html)
        self.assertIn('id="cover-url"', html)
        self.assertIn('name="cover-url"', html)
        self.assertIn('id="cover-file"', html)
        self.assertIn('name="cover-image"', html)
        self.assertIn('class="cover-dropzone"', html)
        self.assertIn('id="cover-plus"', html)
        self.assertIn('>+</span>', html)
        self.assertIn("dragenter", html)
        self.assertIn("dragover", html)
        self.assertIn("drop", html)
        self.assertIn('fetch("/edit/cover"', html)
        self.assertNotIn('type="text"\n          id="cover-url"', html)

    def test_edit_page_previews_existing_cover(self):
        blog = Blog()
        blog.html_title = "existing"
        blog.title = "Existing"
        blog.content = "content"
        blog.category = "随笔"
        blog.cover_url = "/media/covers/2026/05/existing.jpg"
        blog.year = "2026"
        blog.month = "5"
        blog.date = "2026-05-11"
        blog.time = "10:00:00"
        self.stub_db_helper.specified_blog = blog

        with self.app.test_client() as client:
            with client.session_transaction() as flask_session:
                flask_session[ADMIN_SESSION_KEY] = True

            response = client.get("/edit/2026/5/existing")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('class="cover-dropzone has-cover"', html)
        self.assertIn('src="/media/covers/2026/05/existing.jpg"', html)
        self.assertIn('value="/media/covers/2026/05/existing.jpg"', html)
        self.assertIn("已设置封面", html)

    def test_homepage_cover_hides_admin_menu_when_logged_out(self):
        blogs = [self.make_blog("featured", "最新文章")]

        with self.app.test_request_context("/"):
            html = routes_module.init_index_with_blogs(blogs)

        self.assertIn('class="home-cover"', html)
        self.assertIn('aria-label="Archive Note"', html)
        self.assertIn('泥留鸿爪，旧游成文。', html)
        self.assertIn('class="home-cover-plum"', html)
        self.assertIn('class="pull-light-cord"', html)
        self.assertIn('class="admin-bookmark-trigger is-inert"', html)
        self.assertNotIn('class="site-toolbar"', html)
        self.assertNotIn("Personal Edition", html)
        self.assertNotIn("theme-toggle-icon", html)
        self.assertNotIn('data-admin-bookmark-trigger', html)
        self.assertNotIn('data-admin-bookmark-menu', html)
        self.assertNotIn('onclick="navigateToWriting()">写作', html)
        self.assertNotIn('onclick="navigateToManage()">管理', html)
        self.assertNotIn('onclick="logout()">退出', html)
        self.assertNotIn('<p class="section-label">Archive Note</p>', html)

    def test_homepage_cover_shows_bookmark_menu_when_logged_in(self):
        blogs = [self.make_blog("featured", "最新文章")]

        with self.app.test_request_context("/"):
            session[ADMIN_SESSION_KEY] = True
            html = routes_module.init_index_with_blogs(blogs)

        self.assertIn('class="home-cover"', html)
        self.assertNotIn('class="site-toolbar"', html)
        self.assertIn('class="admin-bookmark has-menu"', html)
        self.assertIn('data-admin-bookmark-trigger', html)
        self.assertIn('data-admin-bookmark-menu', html)
        self.assertIn('aria-expanded="false"', html)
        self.assertIn('onclick="navigateToWriting()">写作', html)
        self.assertIn('onclick="navigateToManage()">管理', html)
        self.assertIn('onclick="logout()">退出', html)
        self.assertNotIn('disabled aria-disabled="true">管理', html)
        self.assertNotIn('disabled aria-disabled="true">退出', html)
        self.assertNotIn('class="header-btn-grp"', html)

    def test_edit_page_uses_shared_cover_header(self):
        with self.app.test_client() as client:
            with client.session_transaction() as flask_session:
                flask_session[ADMIN_SESSION_KEY] = True

            response = client.get("/edit")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('class="home-cover"', html)
        self.assertIn("Creative Writing Archive", html)
        self.assertIn("Silver&#39;s Blog", html)
        self.assertIn('class="theme-toggle cover-theme-toggle"', html)
        self.assertIn('class="pull-light-cord"', html)
        self.assertNotIn("theme-toggle-icon", html)
        self.assertIn('class="admin-bookmark has-menu"', html)
        self.assertIn('data-admin-bookmark-trigger', html)
        self.assertIn('data-admin-bookmark-menu', html)
        self.assertIn('onclick="navigateToWriting()">写作', html)
        self.assertIn('onclick="navigateToManage()">管理', html)
        self.assertIn('onclick="logout()">退出', html)
        self.assertNotIn('class="header-btn-grp"', html)
        self.assertNotIn('class="site-toolbar"', html)

    def test_manage_page_uses_shared_cover_header(self):
        with self.app.test_client() as client:
            with client.session_transaction() as flask_session:
                flask_session[ADMIN_SESSION_KEY] = True

            response = client.get("/manage")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('class="home-cover"', html)
        self.assertIn("博客数据管理", html)
        self.assertIn('class="theme-toggle cover-theme-toggle"', html)
        self.assertIn('class="pull-light-cord"', html)
        self.assertIn('class="admin-bookmark has-menu"', html)
        self.assertNotIn('class="site-toolbar"', html)
        self.assertNotIn("theme-toggle-icon", html)

    def test_shared_cover_header_stacks_bookmark_menu_above_page_panels(self):
        css = (Path(__file__).resolve().parents[1] / "static" / "css" / "style.css").read_text(
            encoding="utf-8"
        )

        home_cover = re.search(r"\.home-cover\s*\{(?P<body>[^}]*)\}", css, re.S)
        writing_topbar = re.search(r"\.writing-topbar\s*\{(?P<body>[^}]*)\}", css, re.S)

        self.assertIsNotNone(home_cover)
        self.assertIsNotNone(writing_topbar)
        self.assertIn("position: relative;", home_cover.group("body"))
        self.assertIn("z-index: 50;", home_cover.group("body"))
        self.assertNotIn(".edit-page .home-cover", css)
        self.assertIn("position: sticky;", writing_topbar.group("body"))
        self.assertIn("z-index: 25;", writing_topbar.group("body"))
        self.assertIn(".cover-plus[hidden]", css)
        self.assertIn(".cover-remove-button[hidden]", css)


if __name__ == "__main__":
    unittest.main()
