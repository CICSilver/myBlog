import os
import tempfile
import unittest

from tinydb import TinyDB

import app.database as database_module
from app.database import Blog, DatabaseHelper, normalize_cover_url, normalize_html_title


class BlogHtmlTitleTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = TinyDB(os.path.join(self.temp_dir.name, "blog_db.json"))
        self.helper = DatabaseHelper()
        self.helper.date_table = self.db.table("date")
        self.helper.category_table = self.db.table("categories")
        self.helper.blog_table = self.db.table("blogs")
        self._snapshot_history = database_module._snapshot_history
        database_module._snapshot_history = lambda reason: None

    def tearDown(self):
        database_module._snapshot_history = self._snapshot_history
        self.db.close()
        self.temp_dir.cleanup()

    def make_blog(self, html_title="", title="测试标题", category="测试"):
        blog = Blog()
        blog.html_title = html_title
        blog.title = title
        blog.content = "content"
        blog.category = category
        blog.year = "2026"
        blog.month = "4"
        blog.date = "2026-04-29"
        blog.time = "10:00:00"
        return blog

    def test_normalizes_manual_and_fallback_titles(self):
        self.assertEqual(normalize_html_title("Manual Title", "ignored"), "manual_title")
        self.assertEqual(normalize_html_title("", "随笔"), "sui_bi")

    def test_normalizes_supported_cover_urls(self):
        self.assertEqual(normalize_cover_url(""), "")
        self.assertEqual(normalize_cover_url("  /static/covers/post.jpg  "), "/static/covers/post.jpg")
        self.assertEqual(
            normalize_cover_url("https://example.com/covers/post.jpg"),
            "https://example.com/covers/post.jpg",
        )

    def test_rejects_unsupported_cover_urls(self):
        invalid_urls = [
            "javascript:alert(1)",
            "http://example.com/cover.jpg",
            "//example.com/cover.jpg",
            "/uploads/cover.jpg",
            "https://example.com/cover image.jpg",
        ]

        for url in invalid_urls:
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    normalize_cover_url(url)

    def test_insert_generates_html_title_when_blank(self):
        blog = self.make_blog(html_title="", title="随笔")

        response = self.helper.insert_blog(blog)

        self.assertEqual(response["status"], "success")
        self.assertEqual(blog.html_title, "sui_bi")
        self.assertIsNotNone(self.helper.get_specify_blog("2026", "4", "sui_bi"))

    def test_insert_appends_suffix_for_duplicate_html_title(self):
        first = self.make_blog(html_title="manual title", title="First")
        second = self.make_blog(html_title="manual_title", title="Second")
        third = self.make_blog(html_title="manual_title", title="Third")

        self.helper.insert_blog(first)
        self.helper.insert_blog(second)
        self.helper.insert_blog(third)

        self.assertEqual(first.html_title, "manual_title")
        self.assertEqual(second.html_title, "manual_title_1")
        self.assertEqual(third.html_title, "manual_title_2")

    def test_update_uses_original_key_and_suffixes_changed_html_title(self):
        original = self.make_blog(html_title="old_title", title="Old")
        existing = self.make_blog(html_title="target_title", title="Existing")
        updated = self.make_blog(html_title="target_title", title="Updated")

        self.helper.insert_blog(original)
        self.helper.insert_blog(existing)
        response = self.helper.update_blog(
            updated,
            original_key=("2026", "4", "old_title"),
        )

        self.assertEqual(response["status"], "success")
        self.assertEqual(updated.html_title, "target_title_1")
        self.assertIsNone(self.helper.get_specify_blog("2026", "4", "old_title"))
        self.assertEqual(
            self.helper.get_specify_blog("2026", "4", "target_title").title,
            "Existing",
        )
        self.assertEqual(
            self.helper.get_specify_blog("2026", "4", "target_title_1").title,
            "Updated",
        )

    def test_insert_preserves_full_width_line_indentation(self):
        content = "\u3000\u3000第一段\n\u3000\u3000第二段"
        blog = self.make_blog(html_title="indented_insert")
        blog.content = content

        response = self.helper.insert_blog(blog)

        self.assertEqual(response["status"], "success")
        self.assertEqual(
            self.helper.get_specify_blog("2026", "4", "indented_insert").content,
            content,
        )

    def test_update_preserves_full_width_line_indentation(self):
        original = self.make_blog(html_title="indented_update", title="Original")
        updated = self.make_blog(html_title="indented_update", title="Updated")
        updated.content = "\u3000\u3000第一段\n普通行\n\u3000\u3000第三段"

        self.helper.insert_blog(original)
        response = self.helper.update_blog(
            updated,
            original_key=("2026", "4", "indented_update"),
        )

        self.assertEqual(response["status"], "success")
        self.assertEqual(
            self.helper.get_specify_blog("2026", "4", "indented_update").content,
            updated.content,
        )

    def test_insert_and_update_preserve_cover_url(self):
        original = self.make_blog(html_title="cover_url", title="Original")
        original.cover_url = "/static/covers/original.jpg"
        updated = self.make_blog(html_title="cover_url", title="Updated")
        updated.cover_url = "https://example.com/cover.jpg"

        self.helper.insert_blog(original)
        self.helper.update_blog(updated, original_key=("2026", "4", "cover_url"))

        stored = self.helper.get_specify_blog("2026", "4", "cover_url")
        self.assertEqual(stored.cover_url, "https://example.com/cover.jpg")

    def test_old_blog_record_without_cover_url_reads_empty(self):
        blog = self.make_blog(html_title="legacy_record")
        blog_data = blog.to_dict()
        del blog_data["cover_url"]
        self.helper.blog_table.insert(blog_data)

        stored = self.helper.get_specify_blog("2026", "4", "legacy_record")

        self.assertEqual(stored.cover_url, "")


if __name__ == "__main__":
    unittest.main()
