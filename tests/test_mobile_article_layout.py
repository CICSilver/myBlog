import unittest
from pathlib import Path


class MobileArticleLayoutTest(unittest.TestCase):
    def setUp(self):
        project_root = Path(__file__).resolve().parents[1]
        self.stylesheet = (project_root / "static" / "css" / "style.css").read_text(
            encoding="utf-8"
        )
        self.detail_template = (
            project_root / "templates" / "blog_detail.html"
        ).read_text(encoding="utf-8")
        self.index_template = (project_root / "templates" / "index.html").read_text(
            encoding="utf-8"
        )
        self.mobile_styles = self.stylesheet.split("@media (max-width: 760px)", 1)[1]
        self.desktop_styles = self.stylesheet.split("@media (max-width: 760px)", 1)[0]

    def test_shared_header_hides_its_note_on_mobile(self):
        self.assertIn(
            ".home-cover-note {\n        display: none",
            self.mobile_styles,
        )
        self.assertNotIn("detail-page", self.index_template)

    def test_mobile_detail_uses_one_continuous_reading_surface(self):
        self.assertIn(
            ".detail-page .reading-lead,\n    .detail-page .reading-article {",
            self.mobile_styles,
        )
        self.assertIn("border: 0", self.mobile_styles)
        self.assertIn("border-radius: 0", self.mobile_styles)
        self.assertIn("background: transparent", self.mobile_styles)
        self.assertIn("box-shadow: none", self.mobile_styles)
        self.assertIn("backdrop-filter: none", self.mobile_styles)
        self.assertIn(".detail-page .reading-shell {\n        gap: 10px", self.mobile_styles)

    def test_mobile_reading_title_and_horizontal_padding_are_fixed_and_narrow(self):
        self.assertIn(".detail-page .reading-title {\n        font-size: 2.1rem", self.mobile_styles)
        self.assertIn("line-height: 1.15", self.mobile_styles)
        self.assertIn(".detail-page .reading-lead {\n        gap: 10px;\n        padding: 18px 10px 10px", self.mobile_styles)
        self.assertIn(".detail-page .reading-article {\n        padding: 18px 8px 32px", self.mobile_styles)
        self.assertIn("font-size: 1rem", self.mobile_styles)
        self.assertIn("line-height: 1.9", self.mobile_styles)
        self.assertNotIn("font-size: clamp", self.mobile_styles)

    def test_mobile_cover_images_code_and_tables_fit_the_reading_width(self):
        self.assertIn(".detail-page .reading-cover {\n        padding: 0 8px 4px", self.mobile_styles)
        self.assertIn(".detail-page .reading-cover-button {\n        border-radius: 8px", self.mobile_styles)
        self.assertIn(".detail-page .reading-article.markdown-body pre {", self.mobile_styles)
        self.assertIn("overflow-x: auto", self.mobile_styles)
        self.assertIn("padding: 12px", self.mobile_styles)
        self.assertIn(".detail-page .reading-article.markdown-body table {", self.mobile_styles)
        self.assertIn(".detail-page .reading-article.markdown-body img.article-image {", self.mobile_styles)
        self.assertIn("margin: 1.2rem auto", self.mobile_styles)
        self.assertIn("border-radius: 8px", self.mobile_styles)

    def test_desktop_article_is_an_open_reading_column(self):
        self.assertIn(
            ".reading-shell {\n    display: grid;\n    gap: 44px;\n    max-width: 720px",
            self.desktop_styles,
        )
        self.assertNotIn(".hero-copyblock,\n.reading-lead", self.desktop_styles)
        self.assertIn(".reading-article.markdown-body {\n    font-family: var(--font-serif)", self.desktop_styles)
        self.assertIn('class="reading-lead"', self.detail_template)
        self.assertIn('class="reading-article markdown-body"', self.detail_template)


if __name__ == "__main__":
    unittest.main()
