import unittest

from app import create_app
from app.database import Blog
from app.home_view import (
    archive_calendar,
    archive_stats,
    build_entries,
    char_count,
    cn_date,
    cn_number,
    excerpt_paragraphs,
    plain_lines,
    verse_lines,
)
import app.routes as routes_module


POEM = "　　一轮明月高悬，山也未眠，人也未眠。\r\n　　螽鸣鼓瑟，风捎桐信，影驳禅院。\r\n　　望舒莫怪，佳期难见。"
PROSE = "　　" + "夜风很凉，多少有些想出门走走。" * 8 + "\r\n\r\n------------\r\n\r\n　　第二段。"
TECH = "这个问题分为**两种**情况。\r\n\r\n1. 检查`plugins`目录\r\n```\r\nexport QT_PLUGIN_PATH=/usr/local\r\n```\r\n![图](/a.png) 见[文档](http://x)"


def blog(date, content="正文", title="标题", category="随笔"):
    year, month, _ = date.split("-")
    return {
        "html_title": "t" + date,
        "title": title,
        "content": content,
        "category": category,
        "year": year,
        "month": str(int(month)),
        "date": date,
        "time": "10:00:00",
    }


class HomeViewHelpersTest(unittest.TestCase):
    def test_chinese_numerals(self):
        self.assertEqual(cn_number(9), "九")
        self.assertEqual(cn_number(12), "十二")
        self.assertEqual(cn_number(20), "二十")
        self.assertEqual(cn_number(31), "三十一")
        self.assertEqual(cn_date("2026-07-31"), "二〇二六年七月三十一日")
        self.assertEqual(cn_date("not-a-date"), "not-a-date")

    def test_plain_lines_strip_markdown_but_keep_line_breaks(self):
        lines = [line for line in plain_lines(TECH) if line]
        self.assertEqual(lines[0], "这个问题分为两种情况。")
        self.assertEqual(lines[1], "检查plugins目录")
        self.assertEqual(lines[2], "见文档")
        self.assertNotIn("export QT_PLUGIN_PATH=/usr/local", " ".join(lines))

    def test_short_unformatted_lines_are_verse(self):
        self.assertEqual(len(verse_lines(POEM)), 3)
        self.assertEqual(verse_lines(POEM)[0], "一轮明月高悬，山也未眠，人也未眠。")
        self.assertEqual(verse_lines(PROSE), [])
        self.assertEqual(verse_lines(TECH), [])
        self.assertEqual(verse_lines("只有一行"), [])

    def test_excerpt_truncates_with_ellipsis_and_skips_rules(self):
        paragraphs = excerpt_paragraphs(PROSE, 40)
        self.assertEqual(len(paragraphs), 1)
        self.assertTrue(paragraphs[0].endswith("……"))
        self.assertLessEqual(len(paragraphs[0]), 42)
        self.assertEqual(excerpt_paragraphs(PROSE, 500)[-1], "第二段。")

    def test_char_count_ignores_whitespace_and_markup(self):
        self.assertEqual(char_count("　　你好，\r\n世界 **强调**"), len("你好，世界强调"))

    def test_entries_flag_month_changes_and_verse(self):
        entries = build_entries([
            blog("2026-09-19", PROSE),
            blog("2026-09-12", POEM),
            blog("2026-07-31"),
        ])
        self.assertEqual([entry["starts_month"] for entry in entries], [True, False, True])
        self.assertEqual(entries[0]["day_label"], "09.19")
        self.assertEqual(entries[0]["weekday"], "六")
        self.assertTrue(entries[1]["is_verse"])
        self.assertEqual(entries[1]["excerpt"], [])
        self.assertEqual(entries[1]["verse_chars"], 17)
        self.assertEqual(entries[2]["month_label"], "二〇二六年七月")

    def test_archive_calendar_and_stats(self):
        blogs = [
            blog("2025-03-28"),
            blog("2026-05-01"),
            blog("2026-05-05"),
            blog("2026-05-16"),
            blog("2026-05-17"),
            blog("2026-09-19"),
        ]
        calendar = archive_calendar(blogs, "2026", "9")
        self.assertEqual([year["year"] for year in calendar], ["2026", "2025"])
        may = calendar[0]["months"][4]
        september = calendar[0]["months"][8]
        self.assertEqual((may["num"], may["level"]), (4, 4))
        self.assertEqual((september["num"], september["level"], september["active"]), (1, 1, True))
        self.assertEqual(calendar[0]["months"][0]["level"], 0)
        self.assertEqual(calendar[1]["total"], 1)

        stats = archive_stats(blogs)
        self.assertEqual(stats["count"], 6)
        self.assertEqual(stats["since"], "2025.03")
        self.assertEqual(archive_calendar([]), [])


class _DetailStub:
    def __init__(self, blog_obj):
        self.blog = blog_obj

    def get_specify_blog(self, year, month, html_title):
        return self.blog

    def is_excluded_article_view_ip(self, ip):
        return True


class VerseDetailPageTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.original_db_helper = routes_module.dbHelper

    def tearDown(self):
        routes_module.dbHelper = self.original_db_helper

    def render(self, content):
        blog_obj = Blog()
        blog_obj.from_dict(blog("2026-09-12", content, title="蟾宫曲·不见月"))
        routes_module.dbHelper = _DetailStub(blog_obj)
        with self.app.test_client() as client:
            return client.get("/2026/9/t2026-09-12").get_data(as_text=True)

    def test_verse_posts_render_on_the_vertical_sheet(self):
        html = self.render(POEM)
        self.assertIn('class="verse-sheet reading-verse"', html)
        self.assertIn("--verse-chars: 17", html)
        self.assertIn("二〇二六年九月十二日 · Silver", html)
        self.assertNotIn('id="markdown-preview"', html)

    def test_prose_posts_keep_the_markdown_article(self):
        html = self.render(PROSE)
        self.assertIn('class="reading-article markdown-body"', html)
        self.assertNotIn("verse-sheet", html)


if __name__ == "__main__":
    unittest.main()
