import unittest
from pathlib import Path


class MarkdownSoftBreakRenderingTest(unittest.TestCase):
    def setUp(self):
        project_root = Path(__file__).resolve().parents[1]
        self.index_source = (project_root / "templates" / "index.html").read_text(encoding="utf-8")
        self.detail_source = (project_root / "templates" / "blog_detail.html").read_text(encoding="utf-8")

    def test_pages_use_local_marked_renderer(self):
        local_marked_path = "vendor/editor.md/lib/marked.min.js"

        self.assertIn(local_marked_path, self.detail_source)
        self.assertNotIn("cdn.jsdelivr.net/npm/marked", self.index_source)
        self.assertNotIn("cdn.jsdelivr.net/npm/marked", self.detail_source)

    def test_detail_page_renders_single_newlines_as_line_breaks(self):
        options_index = self.detail_source.index("marked.setOptions")
        parse_index = self.detail_source.index("marked.parse(markdownContent)")

        self.assertLess(options_index, parse_index)
        self.assertIn("breaks: true", self.detail_source)
        self.assertIn("markdownPreview.textContent = markdownContent", self.detail_source)

    def test_homepage_excerpts_are_rendered_on_the_server(self):
        self.assertNotIn("marked", self.index_source)
        self.assertIn("{% for paragraph in featured.excerpt %}", self.index_source)


if __name__ == "__main__":
    unittest.main()
