import unittest
from pathlib import Path


class MobileArticleLayoutTest(unittest.TestCase):
    def setUp(self):
        project_root = Path(__file__).resolve().parents[1]
        self.stylesheet = (project_root / "static" / "css" / "style.css").read_text(
            encoding="utf-8"
        )
        self.markdown_paper_css = (
            project_root / "static" / "css" / "markdown-paper.css"
        ).read_text(encoding="utf-8")
        self.detail_template = (
            project_root / "templates" / "blog_detail.html"
        ).read_text(encoding="utf-8")
        self.index_template = (project_root / "templates" / "index.html").read_text(
            encoding="utf-8"
        )
        self.mobile_styles = self.stylesheet.split("@media (max-width: 760px)", 1)[1]
        self.desktop_styles = self.stylesheet.split("@media (max-width: 760px)", 1)[0]

    def test_detail_header_hides_only_its_mobile_note(self):
        self.assertIn(
            ".detail-page .home-cover-note {\n        display: none",
            self.mobile_styles,
        )
        self.assertIn(
            '.detail-page .home-cover-main {\n        grid-template-columns: minmax(0, 1fr) 72px',
            self.mobile_styles,
        )
        self.assertNotIn("detail-page", self.index_template)

    def test_mobile_detail_uses_one_continuous_reading_surface(self):
        self.assertIn(".detail-page .reading-sheet {", self.mobile_styles)
        self.assertIn(".detail-page .reading-shell {\n        gap: 12px", self.mobile_styles)
        self.assertIn('class="reading-sheet', self.detail_template)
        self.assertIn('class="reading-header"', self.detail_template)
        self.assertIn('class="reading-pagination"', self.detail_template)

    def test_mobile_reading_title_and_horizontal_padding_are_fixed_and_narrow(self):
        self.assertIn(".detail-page .reading-title {\n        font-size: 1.72rem", self.mobile_styles)
        self.assertIn("line-height: 1.24", self.mobile_styles)
        self.assertIn("padding: 26px 18px 24px", self.mobile_styles)
        self.assertIn("font-size: 0.98rem", self.markdown_paper_css)
        self.assertIn("line-height: 1.88", self.markdown_paper_css)

    def test_mobile_cover_images_code_and_tables_fit_the_reading_width(self):
        self.assertIn(".detail-page .reading-cover {\n        margin: 0 0 20px", self.mobile_styles)
        self.assertIn(".reading-shell {\n    display: grid;\n    grid-template-columns: minmax(0, 1fr);\n    min-width: 0;", self.desktop_styles)
        self.assertIn(".reading-sheet {\n    min-width: 0;", self.desktop_styles)
        self.assertIn(".reading-article {\n    min-width: 0;\n    overflow-x: auto;", self.desktop_styles)
        self.assertIn(".markdown-body pre {", self.markdown_paper_css)
        self.assertIn("overflow-x: auto", self.markdown_paper_css)
        self.assertIn(".markdown-body table {", self.markdown_paper_css)
        self.assertIn(".markdown-body img.article-image {", self.markdown_paper_css)
        self.assertIn("margin: 1.2rem auto", self.markdown_paper_css)
        self.assertIn("border-radius: var(--radius-sm)", self.markdown_paper_css)

    def test_desktop_cards_and_article_template_remain_intact(self):
        self.assertIn(".reading-sheet {\n    min-width: 0;\n    background: var(--surface-strong);", self.desktop_styles)
        self.assertIn("padding: 42px 52px 36px;", self.desktop_styles)
        self.assertIn('class="reading-sheet', self.detail_template)
        self.assertIn('class="reading-article markdown-body', self.detail_template)


if __name__ == "__main__":
    unittest.main()
