import unittest
from pathlib import Path

from app import create_app
from app.database import Blog
import app.routes as routes_module


class StubDatabaseHelper:
    def __init__(self, blog):
        self.blog = blog

    def get_specify_blog(self, year, month, html_title):
        return self.blog


class ArticleImageRenderingTest(unittest.TestCase):
    def setUp(self):
        self.project_root = Path(__file__).resolve().parents[1]
        self.detail_template = (self.project_root / "templates" / "blog_detail.html").read_text(
            encoding="utf-8"
        )
        self.stylesheet = (self.project_root / "static" / "css" / "style.css").read_text(
            encoding="utf-8"
        )
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.original_db_helper = routes_module.dbHelper

        self.blog = Blog(
            html_title="with_images",
            title="有图片的文章",
            content="正文\n\n![正文图片](/static/body.jpg)",
            category="随笔",
            cover_url="/media/covers/2026/05/cover.jpg",
        )
        self.blog.year = "2026"
        self.blog.month = "5"
        self.blog.date = "2026-05-19"
        self.blog.time = "14:10:00"
        routes_module.dbHelper = StubDatabaseHelper(self.blog)

    def tearDown(self):
        routes_module.dbHelper = self.original_db_helper

    def test_detail_page_renders_cover_image_and_image_viewer(self):
        with self.app.test_client() as client:
            response = client.get("/2026/5/with_images")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('class="reading-cover"', html)
        self.assertIn('data-article-image-trigger', html)
        self.assertIn('src="/media/covers/2026/05/cover.jpg"', html)
        self.assertIn('alt="有图片的文章 封面"', html)
        self.assertIn('id="article-image-viewer"', html)
        self.assertIn('id="article-image-viewer-img"', html)
        self.assertIn("![正文图片](/static/body.jpg)", html)

    def test_detail_page_has_visible_markdown_fallback_and_escaped_source(self):
        self.blog.content = "第一段\n\n</textarea>\n\n![正文图片](/static/body.jpg)"

        with self.app.test_client() as client:
            response = client.get("/2026/5/with_images")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('data-markdown-fallback', html)
        self.assertIn("第一段", html)
        self.assertIn("&lt;/textarea&gt;", html)
        self.assertIn('<textarea id="markdown-content" hidden>', html)
        self.assertNotIn('<textarea id="markdown-content" hidden></textarea>', html)

    def test_detail_page_enhances_markdown_images_after_rendering(self):
        self.assertIn("function enhanceArticleImages(container)", self.detail_template)
        self.assertIn("container.querySelectorAll('img')", self.detail_template)
        self.assertIn("image.classList.add('article-image')", self.detail_template)
        self.assertIn("openArticleImageViewer(image.currentSrc || image.src", self.detail_template)
        self.assertIn("document.querySelectorAll('[data-article-image-trigger]')", self.detail_template)
        self.assertIn("data-article-image-close", self.detail_template)
        self.assertIn("event.key === 'Escape'", self.detail_template)

    def test_detail_page_image_styles_are_present(self):
        self.assertIn(".reading-cover", self.stylesheet)
        self.assertIn(".reading-cover-button", self.stylesheet)
        self.assertIn(".markdown-body img.article-image", self.stylesheet)
        self.assertIn("cursor: zoom-in", self.stylesheet)
        self.assertIn(".article-image-viewer", self.stylesheet)
        self.assertIn(".article-image-viewer.is-visible", self.stylesheet)
        self.assertIn(".article-image-viewer-backdrop", self.stylesheet)
        self.assertIn(".article-image-viewer-close", self.stylesheet)


if __name__ == "__main__":
    unittest.main()
