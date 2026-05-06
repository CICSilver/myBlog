import unittest
from pathlib import Path


class MarkdownSoftBreakRenderingTest(unittest.TestCase):
    def setUp(self):
        project_root = Path(__file__).resolve().parents[1]
        self.detail_source = (project_root / "templates" / "blog_detail.html").read_text(encoding="utf-8")
        self.preview_source = (project_root / "static" / "js" / "preview.js").read_text(encoding="utf-8")

    def test_detail_page_renders_single_newlines_as_line_breaks(self):
        options_index = self.detail_source.index("marked.setOptions")
        parse_index = self.detail_source.index("marked.parse(markdownContent)")

        self.assertLess(options_index, parse_index)
        self.assertIn("breaks: true", self.detail_source)

    def test_homepage_preview_renders_single_newlines_as_line_breaks(self):
        options_index = self.preview_source.index("marked.setOptions({ breaks: true })")
        parse_index = self.preview_source.index("marked.parse(previewMarkdown)")

        self.assertLess(options_index, parse_index)


if __name__ == "__main__":
    unittest.main()
