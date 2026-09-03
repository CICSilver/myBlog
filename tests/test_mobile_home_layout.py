import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

from flask import url_for

from app import create_app
import app.routes as routes_module


class _MobileChipParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.chips = []
        self._current = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = attributes.get("class", "").split()
        if tag == "a" and "mobile-filter-chip" in classes:
            self._current = {
                "attributes": attributes,
                "text": [],
            }

    def handle_data(self, data):
        if self._current is not None:
            self._current["text"].append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._current is not None:
            self._current["text"] = " ".join("".join(self._current["text"]).split())
            self.chips.append(self._current)
            self._current = None


class _StubDatabaseHelper:
    def __init__(self, blogs):
        self.blogs = blogs

    def get_recent_blogs(self):
        return list(self.blogs)

    def get_blogs_by_category(self, category_name):
        return [blog for blog in self.blogs if blog["category"] == category_name]

    def get_blogs_by_date(self, year, month):
        return [
            blog
            for blog in self.blogs
            if blog["year"] == year and blog["month"] == month
        ]

    def get_all_categories(self):
        return [
            {"name": "随笔", "num": 3},
            {"name": "阅读", "num": 1},
        ]

    def get_all_date(self):
        return [
            {"year": "2026", "month": "7", "num": 2},
            {"year": "2026", "month": "6", "num": 2},
        ]


class MobileHomeLayoutTest(unittest.TestCase):
    def setUp(self):
        project_root = Path(__file__).resolve().parents[1]
        self.stylesheet = (project_root / "static" / "css" / "style.css").read_text(
            encoding="utf-8"
        )
        self.index_template = (project_root / "templates" / "index.html").read_text(
            encoding="utf-8"
        )
        self.mobile_styles = self.stylesheet.split(
            "@media (max-width: 760px)", 1
        )[1]
        self.desktop_styles = self.stylesheet.split(
            "@media (max-width: 760px)", 1
        )[0]
        self.blogs = [
            self.make_blog("latest", "最新文章", "随笔", "2026", "7", "31"),
            self.make_blog("summer", "夏日随笔", "随笔", "2026", "7", "18"),
            self.make_blog("reading", "读书札记", "阅读", "2026", "6", "27"),
            self.make_blog("river", "沿河散记", "随笔", "2026", "6", "9"),
        ]

        self.app = create_app()
        self.app.config["TESTING"] = True
        self.original_db_helper = routes_module.dbHelper
        routes_module.dbHelper = _StubDatabaseHelper(self.blogs)

    def tearDown(self):
        routes_module.dbHelper = self.original_db_helper

    @staticmethod
    def make_blog(html_title, title, category, year, month, day):
        return {
            "html_title": html_title,
            "title": title,
            "content": "正文摘要内容。\n\n第二行内容。",
            "category": category,
            "year": year,
            "month": month,
            "date": "{0}-{1}-{2}".format(year, month.zfill(2), day),
            "time": "10:00:00",
        }

    @staticmethod
    def parse_mobile_chips(response_html):
        parser = _MobileChipParser()
        parser.feed(response_html)
        return parser.chips

    @staticmethod
    def css_rule_body(css, selector):
        for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css, re.S):
            selectors = [part.strip() for part in match.group(1).split(",")]
            if selector in selectors:
                return re.sub(r"\s+", " ", match.group(2)).strip()
        raise AssertionError("CSS rule not found: {0}".format(selector))

    def test_homepage_renders_mobile_filter_links_counts_and_archive_groups(self):
        with self.app.test_client() as client:
            response = client.get("/")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        with self.app.test_request_context("/"):
            category_url = url_for(
                "main.categorized_blogs", categoryName="随笔"
            )
            date_url = url_for("main.archived_blogs", year="2026", month="7")

        chips = self.parse_mobile_chips(html)
        self.assertGreaterEqual(len(chips), 5)
        chip_text = [chip["text"] for chip in chips]
        self.assertTrue(any(text.startswith("全部") and "4" in text for text in chip_text))
        self.assertTrue(any(text.startswith("随笔") and "3" in text for text in chip_text))
        self.assertTrue(any(text.startswith("阅读") and "1" in text for text in chip_text))
        self.assertTrue(any(text.startswith("2026.7") and "2" in text for text in chip_text))
        self.assertIn('class="mobile-archive-controls"', html)
        self.assertIn('class="mobile-filter-heading"', html)
        self.assertIn('class="mobile-filter-chips"', html)
        self.assertIn('class="mobile-archive-details"', html)
        self.assertIn('class="mobile-archive-panel"', html)
        self.assertIn("分类索引", html)
        self.assertIn("时间归档", html)
        self.assertIn(category_url, html)
        self.assertIn(date_url, html)
        self.assertGreaterEqual(html.count('href="{0}"'.format(category_url)), 2)
        self.assertGreaterEqual(html.count('href="{0}"'.format(date_url)), 2)

    def test_homepage_and_category_request_mark_the_active_filter_chip(self):
        with self.app.test_client() as client:
            homepage = client.get("/").get_data(as_text=True)
            category_page = client.get(
                "/categorized_blogs/%E9%9A%8F%E7%AC%94"
            ).get_data(as_text=True)

        homepage_chips = self.parse_mobile_chips(homepage)
        all_chip = next(chip for chip in homepage_chips if chip["text"].startswith("全部"))
        category_chip = next(chip for chip in homepage_chips if chip["text"].startswith("随笔"))
        self.assertIn("is-active", all_chip["attributes"].get("class", "").split())
        self.assertEqual(all_chip["attributes"].get("aria-current"), "page")
        self.assertNotIn(
            "is-active", category_chip["attributes"].get("class", "").split()
        )

        category_chips = self.parse_mobile_chips(category_page)
        all_chip = next(chip for chip in category_chips if chip["text"].startswith("全部"))
        category_chip = next(chip for chip in category_chips if chip["text"].startswith("随笔"))
        self.assertNotIn("is-active", all_chip["attributes"].get("class", "").split())
        self.assertIn("is-active", category_chip["attributes"].get("class", "").split())
        self.assertEqual(category_chip["attributes"].get("aria-current"), "page")

    def test_mobile_controls_are_hidden_by_default_and_desktop_sidebar_remains(self):
        controls = self.css_rule_body(self.desktop_styles, ".mobile-archive-controls")
        details = self.css_rule_body(self.desktop_styles, ".mobile-archive-details")
        self.assertIn("display: none", controls)
        self.assertIn("display: none", details)
        self.assertIn('class="archive-sidebar"', self.index_template)
        self.assertIn(".archive-sidebar", self.desktop_styles)

    def test_home_mobile_rules_are_scoped_and_preserve_the_b_feed_hierarchy(self):
        sidebar = self.css_rule_body(self.mobile_styles, ".home-page .archive-sidebar")
        entry_stream = self.css_rule_body(self.mobile_styles, ".home-page .entry-stream")
        feature = self.css_rule_body(self.mobile_styles, ".home-page .feature-article")
        chips = self.css_rule_body(self.mobile_styles, ".home-page .mobile-filter-chips")
        chip = self.css_rule_body(self.mobile_styles, ".home-page .mobile-filter-chip")
        entry_line = self.css_rule_body(self.mobile_styles, ".home-page .entry-line")
        dark_feature = self.css_rule_body(
            self.mobile_styles,
            'html[data-theme="dark"] .home-page .feature-article',
        )

        self.assertIn("display: none", sidebar)
        for declaration in ("padding: 0", "border: 0", "border-radius: 0"):
            self.assertIn(declaration, entry_stream)
        self.assertIn("background:", feature)
        self.assertIn("color:", feature)
        self.assertIn("display: flex", chips)
        self.assertIn("overflow-x: auto", chips)
        self.assertIn("flex-wrap: nowrap", chips)
        self.assertIn("padding:", chip)
        self.assertIn("border-radius:", chip)
        self.assertIn("padding:", entry_line)
        self.assertIn("border-bottom:", entry_line)
        self.assertIn("background:", dark_feature)
        self.assertIn("color:", dark_feature)


if __name__ == "__main__":
    unittest.main()
