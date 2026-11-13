import os
import tempfile
import unittest
from unittest.mock import patch

from app import create_app
from app.database import Blog
from app.excerpt import analyze_blog_content, enrich_blog_entry, format_blog_dates
import app.routes as routes_module


class _RedesignStubDatabaseHelper:
    def __init__(self, all_blogs, categories=None, dates=None):
        self.all_blogs = list(all_blogs)
        self.categories = categories if categories is not None else [
            {"name": "随笔", "num": 2},
            {"name": "诗词", "num": 1},
        ]
        self.dates = dates if dates is not None else [
            {"year": "2026", "month": "10", "num": 2},
            {"year": "2026", "month": "4", "num": 0},
            {"year": "2025", "month": "4", "num": 0},
            {"year": "2025", "month": "3", "num": 1},
        ]

    def get_recent_blogs(self, default_days=10):
        blogs = list(self.all_blogs[-default_days:])
        blogs.reverse()
        return blogs

    def get_all_blogs(self):
        return list(self.all_blogs)

    def get_blogs_by_category(self, category_name):
        return [b for b in self.all_blogs if b.get("category") == category_name]

    def get_blogs_by_date(self, year, month):
        return [
            b
            for b in self.all_blogs
            if str(b.get("year")) == str(year) and str(b.get("month")) == str(month)
        ]

    def get_all_categories(self):
        return [dict(item) for item in self.categories]

    def get_all_date(self):
        return [dict(item) for item in self.dates]

    def get_specify_blog(self, year, month, html_title):
        for item in self.all_blogs:
            if (
                str(item.get("year")) == str(year)
                and str(item.get("month")) == str(month)
                and item.get("html_title") == html_title
            ):
                blog = Blog()
                blog.from_dict(item)
                return blog
        return None

    def is_excluded_article_view_ip(self, ip):
        return True


def _make_blog_dict(html_title, title, category, date_str, time_str="10:00:00", content="普通散文内容。"):
    parts = date_str.split("-")
    year = str(int(parts[0]))
    month = str(int(parts[1]))
    return {
        "html_title": html_title,
        "title": title,
        "content": content,
        "category": category,
        "cover_url": "",
        "year": year,
        "month": month,
        "date": date_str,
        "time": time_str,
    }


class ExcerptAndFormattingTest(unittest.TestCase):
    def test_markdown_pipe_and_xss_sanitization(self):
        content = (
            "# 标题一\n\n"
            "![封面图](/media/cover.jpg)\n\n"
            "这一段散文里有普通竖线 | 不会被旧前端那样直接截断，并且包含足够多的字符以体现真实长段散文以及[站内链接](https://example.com)和`行内代码`。\n\n"
            "| 动作 | 组数 |\n"
            "| :--- | ---: |\n"
            "| 深蹲 | 5 组 |\n\n"
            "安全测试：</textarea><script>alert('xss')</script><div class=\"a\">保留正文</div>"
        )
        result = analyze_blog_content(content)

        self.assertFalse(result["is_verse"])
        self.assertIn("普通竖线 | 不会被旧前端那样直接截断", result["excerpt"])
        self.assertIn("站内链接", result["excerpt"])
        self.assertNotIn("https://example.com", result["excerpt"])
        self.assertNotIn("![封面图]", result["excerpt"])
        self.assertNotIn(":---", result["excerpt"])
        self.assertNotIn("</textarea>", result["excerpt"])
        self.assertNotIn("<script>", result["excerpt"])
        self.assertNotIn("alert('xss')", result["excerpt"])
        self.assertIn("保留正文", result["excerpt"])
        self.assertGreater(result["word_count"], 20)

    def test_inline_code_angle_brackets_preserved_while_raw_xss_stripped(self):
        content = (
            "把整篇 Markdown 原文塞入隐藏 `<textarea>`，再由 JS 解析，同时还存在 `</textarea>` 闭合注入隐患。"
            "另外支持 `QList<QString>` 与 `std::vector<int>` 泛型。"
            "而裸写的 </textarea><script>alert('xss')</script> 必须被清除。\n\n"
            "```html\n<textarea>code-block</textarea>\n```"
        )
        result = analyze_blog_content(content)

        self.assertFalse(result["is_verse"])
        self.assertIn("隐藏 <textarea>，", result["excerpt"])
        self.assertIn("存在 </textarea> 闭合注入隐患", result["excerpt"])
        self.assertIn("QList<QString>", result["excerpt"])
        self.assertIn("std::vector<int>", result["excerpt"])
        self.assertNotIn("<script>", result["excerpt"])
        self.assertNotIn("alert('xss')", result["excerpt"])
        self.assertNotIn("而裸写的 </textarea>", result["excerpt"])
        self.assertIn("<textarea>code-block</textarea>", result["excerpt"])

    def test_prose_truncation_adds_ellipsis_around_160_to_180_chars(self):
        long_prose = "雪泥鸿爪岁月留痕，灯下微光记事。" * 18  # 288 字
        result = analyze_blog_content(long_prose)

        self.assertFalse(result["is_verse"])
        self.assertTrue(result["excerpt"].endswith("…"))
        self.assertGreaterEqual(len(result["excerpt"]), 160)
        self.assertLessEqual(len(result["excerpt"]), 185)

    def test_verse_detection_and_line_preservation(self):
        poem = (
            "# 题冬夜\n\n"
            "朔风吹雪入寒窗，\n"
            "孤盏微明照旧章。\n"
            "莫道人间行路远，\n"
            "一壶春水煮新凉。\n"
            "夜深犹听疏钟起，\n"
            "月落平湖水自长。\n"
            "第七行不应出现在摘要里。\n"
            "第八行亦然。"
        )
        result = analyze_blog_content(poem)

        self.assertTrue(result["is_verse"])
        lines = result["excerpt"].split("\n")
        self.assertEqual(len(lines), 6)
        self.assertEqual(lines[0], "题冬夜")
        self.assertEqual(lines[-1], "夜深犹听疏钟起，")
        self.assertNotIn("月落平湖", result["excerpt"])

    def test_verse_negative_cases(self):
        # 1. 超过 12 行
        too_many_lines = "\n".join(f"第{i}句诗。" for i in range(1, 14))
        self.assertFalse(analyze_blog_content(too_many_lines)["is_verse"])

        # 2. 单行去标点空白后超过 28 字符
        too_long_line = "这一句实在太长了远远超过了二十八个汉字的诗词单行长度上限限制"
        self.assertFalse(analyze_blog_content(too_long_line)["is_verse"])

        # 3. 含有代码块围栏
        with_code = "```python\nx = 1\n```\n短句。"
        self.assertFalse(analyze_blog_content(with_code)["is_verse"])

        # 4. 单行短句按普通散文处理，避免误伤一句短随感
        self.assertFalse(
            analyze_blog_content("今天下了一整天的雨，出门买了一罐热咖啡。")["is_verse"]
        )

        # 5. 空内容或只有图片
        self.assertFalse(analyze_blog_content("![only](/img.png)")["is_verse"])
        self.assertEqual(analyze_blog_content("![only](/img.png)")["word_count"], 0)

    def test_word_count_excludes_markdown_and_whitespace(self):
        content = "## 标题\n\n**加粗** 与 `代码` [链接](https://a.b)\n![图](x.png)"
        result = analyze_blog_content(content)
        # 有效文字为：标题 + 加粗 + 与 + 代码 + 链接 = 9 个字
        self.assertEqual(result["word_count"], 9)

    def test_date_formatting_handles_padded_and_unpadded_dates(self):
        d1 = format_blog_dates({"date": "2026-10-18", "year": "2026", "month": "10"})
        self.assertEqual(d1["display_date"], "2026 年 10 月 18 日")
        self.assertEqual(d1["short_md"], "10.18")
        self.assertEqual(d1["year_str"], "2026")

        d2 = format_blog_dates({"date": "2026-9-5", "year": "2026", "month": "9"})
        self.assertEqual(d2["display_date"], "2026 年 09 月 05 日")
        self.assertEqual(d2["short_md"], "09.05")
        self.assertEqual(d2["year_str"], "2026")


class RedesignRoutesContractTest(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.app.config["POETRY_USER_DATA_PATH"] = os.path.join(
            self._temp_dir.name, "poetry_user_data.json"
        )
        self.original_db_helper = routes_module.dbHelper

        self.oldest = _make_blog_dict(
            "oldest_note",
            "最旧的文章",
            "随笔",
            "2025-3-5",
            "08:00:00",
            "旧时光 | 依然清晰。",
        )
        self.middle = _make_blog_dict(
            "middle_poem",
            "中间的诗",
            "诗词",
            "2026-10-1",
            "09:30:00",
            "秋风起，\n落叶飞。",
        )
        self.newest = _make_blog_dict(
            "newest_essay",
            "最新的文章",
            "随笔",
            "2026-10-18",
            "21:00:00",
            "新篇正文</textarea>安全测试。",
        )
        # 刻意打乱数据库存储顺序，验证详情页按全站时间顺序排序
        self.stub = _RedesignStubDatabaseHelper(
            [self.middle, self.newest, self.oldest]
        )
        routes_module.dbHelper = self.stub

    def tearDown(self):
        routes_module.dbHelper = self.original_db_helper
        self._temp_dir.cleanup()

    def test_index_filters_empty_dates_and_exposes_total_count_and_enriched_blogs(self):
        captured = {}

        def fake_render(template_name, **context):
            captured["template"] = template_name
            captured["context"] = context
            return "ok"

        with patch("app.routes.render_template", side_effect=fake_render):
            with self.app.test_client() as client:
                resp = client.get("/")

        self.assertEqual(resp.status_code, 200)
        ctx = captured["context"]
        self.assertIsNone(ctx["archive_filter"])
        self.assertEqual(ctx["total_blog_count"], 3)
        self.assertEqual(
            [(d["year"], d["month"], d["num"]) for d in ctx["dateList"]],
            [("2026", "10", 2), ("2025", "3", 1)],
        )
        first_blog = ctx["blogs"][0]
        self.assertIn("excerpt", first_blog)
        self.assertIn("is_verse", first_blog)
        self.assertIn("word_count", first_blog)
        self.assertEqual(first_blog["display_date"], "2025 年 03 月 05 日")
        self.assertEqual(first_blog["short_md"], "03.05")
        self.assertEqual(first_blog["year_str"], "2025")

    def test_category_route_sets_archive_filter_and_keeps_total_blog_count(self):
        captured = {}

        def fake_render(template_name, **context):
            captured["context"] = context
            return "ok"

        with patch("app.routes.render_template", side_effect=fake_render):
            with self.app.test_client() as client:
                resp = client.get("/categorized_blogs/随笔")

        self.assertEqual(resp.status_code, 200)
        ctx = captured["context"]
        self.assertEqual(
            ctx["archive_filter"],
            {"kind": "category", "label": "随笔", "count": 2},
        )
        self.assertEqual(ctx["total_blog_count"], 3)
        self.assertEqual(len(ctx["blogs"]), 2)

    def test_date_route_sets_archive_filter_with_zero_padded_label(self):
        captured = {}

        def fake_render(template_name, **context):
            captured["context"] = context
            return "ok"

        with patch("app.routes.render_template", side_effect=fake_render):
            with self.app.test_client() as client:
                resp = client.get("/date_blogs/2025/3")

        self.assertEqual(resp.status_code, 200)
        ctx = captured["context"]
        self.assertEqual(
            ctx["archive_filter"],
            {"kind": "date", "label": "2025 · 03", "year": "2025", "month": "3", "count": 1},
        )
        self.assertEqual(ctx["total_blog_count"], 3)
        self.assertEqual(len(ctx["blogs"]), 1)

    def test_blog_detail_adjacent_navigation_and_enrichment(self):
        captured = {}

        def fake_render(template_name, **context):
            captured[template_name] = context
            return "ok"

        with patch("app.routes.render_template", side_effect=fake_render):
            with self.app.test_client() as client:
                # 1. 最旧文章：previous_blog 为 None，next_blog 为中间文章
                client.get("/2025/3/oldest_note")
                oldest_ctx = captured["blog_detail.html"]
                self.assertIsNone(oldest_ctx["previous_blog"])
                self.assertEqual(oldest_ctx["next_blog"]["html_title"], "middle_poem")
                for key in ("title", "date", "category", "year", "month", "html_title"):
                    self.assertIn(key, oldest_ctx["next_blog"])

                # 2. 中间文章：既有 previous_blog 也有 next_blog，且 blog 挂载元数据
                client.get("/2026/10/middle_poem")
                mid_ctx = captured["blog_detail.html"]
                self.assertEqual(mid_ctx["previous_blog"]["html_title"], "oldest_note")
                self.assertEqual(mid_ctx["next_blog"]["html_title"], "newest_essay")
                self.assertTrue(mid_ctx["blog"]["is_verse"])
                self.assertEqual(mid_ctx["blog"]["display_date"], "2026 年 10 月 01 日")
                self.assertEqual(mid_ctx["blog"].short_md, "10.01")

                # 3. 最新文章：previous_blog 为中间文章，next_blog 为 None
                client.get("/2026/10/newest_essay")
                new_ctx = captured["blog_detail.html"]
                self.assertEqual(new_ctx["previous_blog"]["html_title"], "middle_poem")
                self.assertIsNone(new_ctx["next_blog"])
                self.assertNotIn("</textarea>", new_ctx["blog"]["excerpt"])

    def test_single_blog_has_no_neighbors(self):
        routes_module.dbHelper = _RedesignStubDatabaseHelper([self.oldest])
        captured = {}

        def fake_render(template_name, **context):
            captured[template_name] = context
            return "ok"

        with patch("app.routes.render_template", side_effect=fake_render):
            with self.app.test_client() as client:
                resp = client.get("/2025/3/oldest_note")

        self.assertEqual(resp.status_code, 200)
        ctx = captured["blog_detail.html"]
        self.assertIsNone(ctx["previous_blog"])
        self.assertIsNone(ctx["next_blog"])


if __name__ == "__main__":
    unittest.main()
