import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

from flask import url_for

from app import create_app
import app.routes as routes_module


class _LinkParser(HTMLParser):
    """Collect <a> elements carrying a given class, with their text and attributes."""

    def __init__(self, class_name):
        super().__init__()
        self.class_name = class_name
        self.links = []
        self._current = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()
        if tag == "a" and self.class_name in classes:
            self._current = {"attributes": attributes, "text": []}

    def handle_data(self, data):
        if self._current is not None:
            self._current["text"].append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._current is not None:
            self._current["text"] = " ".join("".join(self._current["text"]).split())
            self.links.append(self._current)
            self._current = None


class _StubDatabaseHelper:
    def __init__(self, blogs):
        self.blogs = blogs

    def get_all_blogs(self):
        return list(reversed(self.blogs))

    def get_recent_blogs(self):
        return list(self.blogs)

    def get_blogs_by_category(self, category_name):
        return [blog for blog in reversed(self.blogs) if blog["category"] == category_name]

    def get_blogs_by_date(self, year, month):
        return [
            blog
            for blog in reversed(self.blogs)
            if blog["year"] == year and blog["month"] == month
        ]

    def get_all_categories(self):
        return [
            {"name": "随笔", "num": 3},
            {"name": "阅读", "num": 1},
            {"name": "空分类", "num": 0},
        ]


class HomeLayoutTest(unittest.TestCase):
    def setUp(self):
        project_root = Path(__file__).resolve().parents[1]
        self.home_styles = (project_root / "static" / "css" / "home.css").read_text(encoding="utf-8")
        self.index_template = (project_root / "templates" / "index.html").read_text(encoding="utf-8")
        self.mobile_styles = self.home_styles.split("@media (max-width: 760px)", 1)[1]
        self.desktop_styles = self.home_styles.split("@media (max-width: 760px)", 1)[0]
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
            "date": "{0}-{1}-{2}".format(year, month.zfill(2), day.zfill(2)),
            "time": "10:00:00",
        }

    @staticmethod
    def links(response_html, class_name):
        parser = _LinkParser(class_name)
        parser.feed(response_html)
        return parser.links

    @staticmethod
    def css_rule_body(css, selector):
        for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css, re.S):
            selectors = [part.strip() for part in match.group(1).split(",")]
            if selector in selectors:
                return re.sub(r"\s+", " ", match.group(2)).strip()
        raise AssertionError("CSS rule not found: {0}".format(selector))

    def test_homepage_renders_category_chips_with_counts(self):
        with self.app.test_client() as client:
            html = client.get("/").get_data(as_text=True)

        chips = [chip["text"] for chip in self.links(html, "filter-chip")]
        self.assertEqual(chips, ["全部 4", "随笔 3", "阅读 1"])
        self.assertNotIn("空分类", html)

    def test_homepage_and_category_request_mark_the_active_filter_chip(self):
        with self.app.test_client() as client:
            homepage = client.get("/").get_data(as_text=True)
            category_page = client.get("/categorized_blogs/%E9%9A%8F%E7%AC%94").get_data(as_text=True)

        def chip(html, label):
            return next(item for item in self.links(html, "filter-chip") if item["text"].startswith(label))

        self.assertIn("is-active", chip(homepage, "全部")["attributes"]["class"].split())
        self.assertEqual(chip(homepage, "全部")["attributes"].get("aria-current"), "page")
        self.assertNotIn("is-active", chip(homepage, "随笔")["attributes"]["class"].split())

        self.assertNotIn("is-active", chip(category_page, "全部")["attributes"]["class"].split())
        self.assertIn("is-active", chip(category_page, "随笔")["attributes"]["class"].split())
        self.assertEqual(chip(category_page, "随笔")["attributes"].get("aria-current"), "page")

    def test_homepage_lists_latest_entry_then_the_trail(self):
        with self.app.test_client() as client:
            html = client.get("/").get_data(as_text=True)

        self.assertIn('class="home-hero"', html)
        self.assertIn("泥留鸿爪", html)
        self.assertIn('id="latest-title"', html)
        self.assertLess(html.index("最新文章"), html.index("夏日随笔"))
        self.assertEqual(html.count('class="trace-entry'), 3)
        self.assertEqual(html.count("data-trail-node"), 1 + 2 + 3)
        self.assertIn('data-side="left"', html)
        self.assertIn('data-side="right"', html)
        self.assertIn("二〇二六年七月", html)
        self.assertIn("二〇二六年六月", html)

    def test_season_map_links_months_that_have_entries(self):
        with self.app.test_client() as client:
            html = client.get("/").get_data(as_text=True)
        with self.app.test_request_context("/"):
            july = url_for("main.archived_blogs", year="2026", month="7")
            may = url_for("main.archived_blogs", year="2026", month="5")

        cells = self.links(html, "season-cell")
        self.assertEqual(len(cells), 2)
        self.assertIn('href="{0}"'.format(july), html)
        self.assertNotIn('href="{0}"'.format(may), html)
        self.assertIn("2026年7月，2 篇", html)

    def test_filtered_pages_use_the_compact_hero(self):
        with self.app.test_client() as client:
            category_page = client.get("/categorized_blogs/%E9%9A%8F%E7%AC%94").get_data(as_text=True)
            month_page = client.get("/date_blogs/2026/6").get_data(as_text=True)

        self.assertIn('class="home-hero is-compact"', category_page)
        self.assertIn("凡 3 篇", category_page)
        self.assertNotIn('id="latest-title"', category_page)
        self.assertEqual(category_page.count('class="trace-entry'), 3)

        self.assertIn("二〇二六年六月", month_page)
        self.assertIn("凡 2 篇", month_page)
        self.assertIn('class="season-cell level-4 is-active"', month_page)

    def test_mobile_rules_move_the_trail_to_a_left_rail(self):
        entry = self.css_rule_body(self.mobile_styles, ".trace-entry")
        stamp = self.css_rule_body(self.mobile_styles, ".trace-stamp")
        chips = self.css_rule_body(self.mobile_styles, ".home-filter")

        self.assertIn("grid-template-columns: var(--rail) minmax(0, 1fr)", entry)
        self.assertIn("display: none", stamp)
        self.assertIn("flex-wrap: nowrap", chips)
        self.assertIn("overflow-x: auto", chips)

    def test_desktop_layout_keeps_the_trail_in_a_centre_gutter(self):
        entry = self.css_rule_body(self.desktop_styles, ".trace-entry")
        self.assertIn("grid-template-columns: minmax(0, 1fr) var(--gutter) minmax(0, 1fr)", entry)
        self.assertIn("html.reveal-ready .reveal", self.desktop_styles)
        self.assertIn("prefers-reduced-motion: reduce", self.desktop_styles)


if __name__ == "__main__":
    unittest.main()
