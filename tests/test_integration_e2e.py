import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import create_app
from app.auth import ADMIN_SESSION_KEY
from app.database import Blog, DatabaseHelper
from app.sqlite_store import SQLiteStore
import app.routes as routes_module


class RedesignIntegrationE2ETest(unittest.TestCase):
    """基于真实 SQLiteStore + DatabaseHelper 的全链路 DOM 集成断言。"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "integration_test.sqlite3"
        self.store = SQLiteStore(str(self.db_path), create=True)
        self.db_helper = DatabaseHelper(store=self.store)

        # 构造跨月份、跨分类、含诗词《折桂令》、含代码块与表格长文、以及单篇分类的数据
        entries = [
            {
                "html_title": "prose_tech_note",
                "title": "重构手记：纸墨排版与服务端摘要安全",
                "category": "技术随笔",
                "year": "2026",
                "month": "11",
                "date": "2026-11-10",
                "time": "21:30:00",
                "cover_url": "/static/vendor/editor.md/examples/images/8.jpg",
                "content": (
                    "## 为什么把摘要提取移回服务端\n\n"
                    "过去首页将全部 Markdown 原文塞入隐藏文本域再交给浏览器截断，"
                    "遇到普通竖线 | 或表格就会误截断，且存在闭合标签注入风险。\n\n"
                    "```python\n"
                    "def render_sheet(title: str) -> str:\n"
                    "    return f'<article class=\"reading-sheet\">{title}</article>'\n"
                    "```\n\n"
                    "| 模块 | 状态 | 备注 |\n"
                    "| :--- | :--- | :--- |\n"
                    "| 服务端摘要 | 已完成 | 支持诗词换行 |\n"
                    "| 纸面样式 | 已完成 | 深浅双主题适配 |\n\n"
                    "结尾安全探测：</textarea><script>window.__xss=1</script>"
                ),
            },
            {
                "html_title": "zheguiling_autumn",
                "title": "折桂令·秋怀",
                "category": "诗词",
                "year": "2026",
                "month": "10",
                "date": "2026-10-18",
                "time": "20:00:00",
                "cover_url": "",
                "content": (
                    "正秋风落叶长安，\n"
                    "几处寒砧，几度凭栏。\n"
                    "黄菊初开，青尊未老，红叶如丹。\n"
                    "莫辜负篱边酒暖，\n"
                    "且相随江上鸥闲。\n"
                    "尘世悲欢，一曲清歌，半枕南山。"
                ),
            },
            {
                "html_title": "single_cat_only_one",
                "title": "雨夜孤灯读书记",
                "category": "孤本札记",
                "year": "2026",
                "month": "9",
                "date": "2026-09-05",
                "time": "22:10:00",
                "cover_url": "",
                "content": (
                    "秋雨敲窗，灯下重读旧注。全书虽仅存一卷，字句却清澈见底，"
                    "恰如山中松雪，不染尘埃。写下这条单篇分类记录，用于验证单篇分类筛选页的呈现。"
                ),
            },
            {
                "html_title": "deleted_later_post",
                "title": "待删除测试篇（用于产生空归档月）",
                "category": "技术随笔",
                "year": "2025",
                "month": "4",
                "date": "2025-04-12",
                "time": "09:00:00",
                "cover_url": "",
                "content": "这篇会被删除，留下 num=0 的 2025.4 幽灵月份记录用于测试过滤。",
            },
        ]

        # 按时间从早到晚插入，确保列表和上下篇顺序清晰
        for item in reversed(entries):
            blog = Blog()
            blog.from_dict(item)
            res = self.db_helper.insert_blog(blog)
            self.assertEqual(res["status"], "success")

        # 删除 2025-04 文章，模拟真实数据库里残留 num=0 的空月份记录
        ghost_blog = self.db_helper.get_specify_blog("2025", "4", "deleted_later_post")
        self.assertIsNotNone(ghost_blog)
        self.db_helper.delete_blog(ghost_blog)

        self.app = create_app()
        self.app.config["TESTING"] = True
        self.original_db_helper = routes_module.dbHelper
        routes_module.dbHelper = self.db_helper

    def tearDown(self):
        routes_module.dbHelper = self.original_db_helper
        self.temp_dir.cleanup()

    def test_no_deprecated_cdn_or_hidden_textarea_across_pages(self):
        with self.app.test_client() as client:
            home_html = client.get("/").get_data(as_text=True)
            detail_html = client.get("/2026/11/prose_tech_note").get_data(as_text=True)
            verse_html = client.get("/2026/10/zheguiling_autumn").get_data(as_text=True)
            cat_html = client.get("/categorized_blogs/%E5%AD%A4%E6%9C%AC%E6%9C%AD%E8%AE%B0").get_data(as_text=True)
            poetry_html = client.get("/poetry").get_data(as_text=True)

            with client.session_transaction() as sess:
                sess[ADMIN_SESSION_KEY] = True
            edit_html = client.get("/edit").get_data(as_text=True)

        for name, html in [
            ("home", home_html),
            ("detail", detail_html),
            ("verse", verse_html),
            ("category", cat_html),
            ("poetry", poetry_html),
            ("edit", edit_html),
        ]:
            self.assertNotIn("github-markdown-light", html, f"{name} 不应再引用 github-markdown-light")
            self.assertNotIn("apps.bdimg.com", html, f"{name} 不应再引用停更的 apps.bdimg.com")

        self.assertIn("markdown-paper.css", detail_html)
        self.assertNotIn("<textarea", home_html)
        self.assertNotIn("preview.js", home_html)
        self.assertNotIn("marked.min.js", home_html)

    def test_homepage_sidebar_poetry_card_active_state_and_empty_month_filtered(self):
        with self.app.test_client() as client:
            html = client.get("/").get_data(as_text=True)

        # 侧栏含 _poetry_card 且「全部文章」选中
        self.assertIn('id="sidebarPoetryCard"', html)
        self.assertIn("今日诗笺", html)
        self.assertRegex(
            html,
            r'<a[^>]*href="/"[^>]*class="is-active"[^>]*aria-current="page"[^>]*>\s*<span>全部文章</span>\s*<em>3</em>',
        )
        # 空归档月 2025 · 04 被彻底过滤
        self.assertNotIn("2025 · 04", html)
        self.assertNotIn("/date_blogs/2025/4", html)
        self.assertIn("2026 · 11", html)
        self.assertIn("2026 · 10", html)
        self.assertIn("2026 · 09", html)

    def test_single_article_category_page_has_no_false_empty_or_featured_copy(self):
        with self.app.test_client() as client:
            html = client.get("/categorized_blogs/%E5%AD%A4%E6%9C%AC%E6%9C%AD%E8%AE%B0").get_data(as_text=True)

        self.assertIn('class="archive-filter-banner"', html)
        self.assertIn("分类：孤本札记", html)
        self.assertIn("共 1 篇文章", html)
        self.assertIn('class="timeline-section is-filtered"', html)
        self.assertIn("雨夜孤灯读书记", html)
        # 对应分类在侧栏和移动端均呈 is-active，且全部文章不再激活
        self.assertIn('href="/categorized_blogs/%E5%AD%A4%E6%9C%AC%E6%9C%AD%E8%AE%B0"\n                  class="is-active"', html)
        # 不应出现穿帮文案
        self.assertNotIn("新篇 ·", html)
        self.assertNotIn("近期归档", html)
        self.assertNotIn("共 0 篇旧文", html)
        self.assertNotIn("第一篇文章已经入档", html)

    def test_detail_pages_render_reading_sheet_verse_and_pagination(self):
        with self.app.test_client() as client:
            prose_html = client.get("/2026/11/prose_tech_note").get_data(as_text=True)
            verse_html = client.get("/2026/10/zheguiling_autumn").get_data(as_text=True)
            oldest_html = client.get("/2026/9/single_cat_only_one").get_data(as_text=True)

        # 详情页含 .reading-sheet 与安全 JSON 数据源
        self.assertIn('class="reading-sheet"', prose_html)
        self.assertIn('class="reading-pagination"', prose_html)
        self.assertIn("折桂令·秋怀", prose_html)
        self.assertIn("已至最新一篇", prose_html)
        self.assertNotIn("</textarea><script>window.__xss=1</script>", prose_html)
        match = re.search(
            r'<script id="markdown-source" type="application/json">(.*?)</script>',
            prose_html,
            re.S,
        )
        self.assertIsNotNone(match)
        self.assertIn("window.__xss=1", json.loads(match.group(1)))

        # 古诗词详情页含 is-verse-sheet 与上下篇双向导航
        self.assertIn('class="reading-sheet is-verse-sheet"', verse_html)
        self.assertIn('class="reading-article markdown-body is-verse"', verse_html)
        self.assertIn("← 上一篇", verse_html)
        self.assertIn("雨夜孤灯读书记", verse_html)
        self.assertIn("下一篇 →", verse_html)
        self.assertIn("重构手记：纸墨排版与服务端摘要安全", verse_html)

        # 最早一篇详情页含边界占位符
        self.assertIn("已是最早一篇", oldest_html)
        self.assertIn("折桂令·秋怀", oldest_html)


if __name__ == "__main__":
    unittest.main()
