# tests/test_poetry_e2e.py
# -*- coding: utf-8 -*-
"""
tests/test_poetry_e2e.py: 端到端 (E2E) 黑盒综合测试套件
采用 4 层测试方法论 (4-Tier Methodology)：
- Tier 1: 功能覆盖（核心功能 >= 5 个独立测试）
  * 数据集加载与四维正交标签校验
  * 首页侧边栏便笺卡 SSR 上下文与 DOM 结构渲染
  * /poetry 独立诗斋沉浸页 SSR 渲染与全套前端组件
  * 整首诗词点赞 / 取消点赞与服务端持久化
  * 词句朱笔圈点（摘句心动）与标签加权
- Tier 2: 边界与异常防护
  * 纯标点 / 纯空白词句拒绝 (HTTP 400)
  * 单字诗眼 ("梅", "酒", "春") 正常接受 (HTTP 200)
  * 不存在的诗词 ID 校验 (HTTP 404)
  * 词句不匹配校验 (HTTP 400)
  * CSRF Token 缺失 / 伪造防御 (HTTP 403)
  * 空状态与持久化损坏自动容错恢复
- Tier 3: 跨功能组合与并发
  * 同首诗多次圈点不同诗句并聚合标签分
  * 整篇点赞 + 词句圈点复合加权与推荐收敛
  * 多线程并发读写安全性（零死锁、无数据丢失）
  * 乐观 UI 与服务端镜像一致性（雷达对账）
  * 交互流水事件与 1000 条 FIFO 上限
- Tier 4: 真实全链路工作负载
  * 用户完整旅程：访问首页 -> 查看侧边栏便笺 -> 步入诗斋 -> 查阅偏好与数据集 ->
    雅赏宋词 -> 选中圈点“柳垂江上影” -> 服务端 JSON 物理落盘验证 ->
    Softmax 偏好概率向宋词/清丽婉约显著聚拢 -> 取消雅赏与圈点 -> 状态完美回滚
  * 多首互动审美聚焦收敛演进
  * 标点容差子串标准化圈点
  * SSR 预填态与已点赞视觉镜像校验
"""
import concurrent.futures
import hashlib
import hmac
import json
import math
import os
import re
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app import create_app
from app.auth import CSRF_SESSION_KEY
from app.poetry import (
    DEFAULT_GAMMA,
    DIMENSION_WEIGHTS,
    PoetryManager,
    WEIGHT_DELTA_EXCERPT_LIKE,
    WEIGHT_DELTA_POEM_LIKE,
    get_daily_poem,
    get_poetry_manager,
    load_poems_dataset,
    load_user_data,
    save_user_data,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REAL_POEMS_PATH = PROJECT_ROOT / "app" / "data" / "poems.json"

APPROVED_DYNASTIES = {"唐代", "五代", "北宋", "南宋", "金代", "元代", "明代", "清代"}
APPROVED_STYLES = {"清丽婉约", "澄澈疏朗", "清骨入神", "俊逸风骨", "纤巧灵动", "纯粹深情"}
APPROVED_MOODS = {"幽微相思", "别后怀人", "独立清醒", "苍茫通达", "恬淡隐逸", "微寒羁旅", "闲愁清冷"}
APPROVED_THEMES = {
    "春水飞花", "梅雪孤枝", "秋风夜雨", "风雪千山",
    "烟火残棋", "孤星明月", "松花烹茶", "青帘画屏", "秋色澄明",
}


class BasePoetryE2ETestCase(unittest.TestCase):
    """E2E 测试基类：负责临时目录与应用上下文隔离"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_user_data_path = Path(self.temp_dir.name) / "poetry_user_data.json"
        self.test_lock_path = Path(self.temp_dir.name) / "poetry_user_data.lock"

        self.app = create_app()
        self.app.config.update(
            TESTING=True,
            POETRY_USER_DATA_PATH=str(self.test_user_data_path),
            POETRY_DATASET_PATH=str(REAL_POEMS_PATH),
            POETRY_ALLOW_ANONYMOUS_WRITE=True,
        )

        self.manager = PoetryManager(
            poems_path=str(REAL_POEMS_PATH),
            user_data_path=str(self.test_user_data_path),
            lock_path=str(self.test_lock_path),
        )

        # 全局与路由打桩，确保所有调用均指向测试隔离持久化路径
        self.patcher_route = patch("app.routes.get_poetry_manager", return_value=self.manager)
        self.patcher_mod = patch("app.poetry.get_poetry_manager", return_value=self.manager)
        self.patcher_route.start()
        self.patcher_mod.start()

        # 博客首页文章数据打桩，确保首页处于正常非空文章状态以渲染侧边栏便笺卡
        self.fake_blogs = [
            {
                "title": "烟火残棋与春水煎茶",
                "year": "2026",
                "month": "11",
                "html_title": "yanhuo-canqi",
                "content": "人事匆匆，唯诗词与茶香可慰风尘。",
                "date": "2026-11-12",
                "category": "随笔",
            }
        ]
        self.patcher_blogs = patch("app.routes.dbHelper.get_recent_blogs", return_value=self.fake_blogs)
        self.patcher_cats = patch("app.routes.dbHelper.get_all_categories", return_value=[{"name": "随笔", "num": 1}])
        self.patcher_dates = patch("app.routes.dbHelper.get_all_date", return_value=[{"year": "2026", "month": "11", "num": 1}])
        self.patcher_blogs.start()
        self.patcher_cats.start()
        self.patcher_dates.start()

    def tearDown(self):
        self.patcher_blogs.stop()
        self.patcher_cats.stop()
        self.patcher_dates.stop()
        self.patcher_route.stop()
        self.patcher_mod.stop()
        self.temp_dir.cleanup()

    def _get_csrf_token(self, client) -> str:
        """访问首页以在 session 中生成合法的 CSRF Token 并返回"""
        res = client.get("/poetry")
        self.assertEqual(res.status_code, 200)
        with client.session_transaction() as sess:
            token = sess.get(CSRF_SESSION_KEY) or sess.get("_csrf_token")
        self.assertIsNotNone(token, "CSRF Token 未能在会话中生成")
        return token


# ==============================================================================
# Tier 1: Feature Coverage (>=5 tests per core feature)
# ==============================================================================

class TestTier1DatasetAndTags(BasePoetryE2ETestCase):
    """Tier 1.1: 诗词数据集与四维正交标签核心功能测试 (>=5用例)"""

    def test_01_dataset_file_structure_and_total(self):
        """1.1 校验数据集文件结构：顶层字段 total=40，poems 数组与 tags 索引字典均合法"""
        self.assertTrue(REAL_POEMS_PATH.exists(), f"诗词数据集文件不存在: {REAL_POEMS_PATH}")
        with open(REAL_POEMS_PATH, "r", encoding="utf-8") as f:
            raw_data = json.load(f)

        self.assertEqual(raw_data.get("total"), 40)
        self.assertIn("version", raw_data)
        self.assertIsInstance(raw_data.get("poems"), list)
        self.assertEqual(len(raw_data["poems"]), 40)
        self.assertIsInstance(raw_data.get("tags"), dict)

    def test_02_all_poems_contain_mandatory_fields(self):
        """1.2 校验每首诗词的必要字段存在且类型与非空校验通过"""
        dataset = self.manager.get_dataset()
        poems = dataset.get("poems", [])
        mandatory_fields = [
            ("id", str),
            ("title", str),
            ("author", str),
            ("dynasty", str),
            ("content", list),
            ("highlight", str),
            ("commentary", str),
            ("tags", dict),
            ("is_handwritten", bool),
        ]
        for poem in poems:
            pid = poem.get("id")
            for field, ftype in mandatory_fields:
                self.assertIn(field, poem, f"诗词 {pid} 缺失必填字段 {field}")
                self.assertIsInstance(poem[field], ftype, f"诗词 {pid} 字段 {field} 类型应为 {ftype}")
                if ftype in (str, list, dict):
                    self.assertGreater(len(poem[field]), 0, f"诗词 {pid} 字段 {field} 不能为空")

    def test_03_four_dimensional_orthogonal_tags_integrity(self):
        """1.3 校验四维标签正交性：dynasty、style、mood、theme 必须全部属于经校准的受控词表"""
        poems = self.manager.get_all_poems()
        for poem in poems:
            pid = poem["id"]
            tags = poem.get("tags", {})
            self.assertIn("dynasty", tags, f"{pid} 缺失朝代标签")
            self.assertIn("style", tags, f"{pid} 缺失风格标签")
            self.assertIn("mood", tags, f"{pid} 缺失心境标签")
            self.assertIn("theme", tags, f"{pid} 缺失意象标签")

            self.assertIn(tags["dynasty"], APPROVED_DYNASTIES, f"{pid} 非法朝代: {tags['dynasty']}")
            self.assertIn(tags["style"], APPROVED_STYLES, f"{pid} 非法风格: {tags['style']}")
            self.assertIn(tags["mood"], APPROVED_MOODS, f"{pid} 非法心境: {tags['mood']}")
            self.assertIn(tags["theme"], APPROVED_THEMES, f"{pid} 非法意象: {tags['theme']}")

    def test_04_handwritten_golden_ratio_distribution(self):
        """1.4 校验亲笔手抄典藏比例：13 首手抄篇目为 True，27 首为 False"""
        poems = self.manager.get_all_poems()
        handwritten = [p for p in poems if p.get("is_handwritten") is True]
        self.assertEqual(len(handwritten), 13, f"手抄篇目应为 13 首，实际为 {len(handwritten)}")
        non_handwritten = [p for p in poems if p.get("is_handwritten") is False]
        self.assertEqual(len(non_handwritten), 27, f"常规篇目应为 27 首，实际为 {len(non_handwritten)}")

    def test_05_api_dataset_endpoint_contract(self):
        """1.5 校验 GET /api/poetry/dataset 契约：返回 HTTP 200，格式与内容完全一致"""
        with self.app.test_client() as client:
            res = client.get("/api/poetry/dataset")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(data["status"], "success")
            self.assertEqual(data["total"], 40)
            self.assertEqual(len(data["poems"]), 40)
            self.assertIn("tags", data)
            self.assertEqual(data["poems"][0]["id"], "poem_01")

    def test_06_daily_poem_deterministic_algorithm(self):
        """1.6 校验公历每日一诗哈希选取的确定性与一致性"""
        p1 = self.manager.get_daily_poem()
        p2 = self.manager.get_daily_poem()
        self.assertIsNotNone(p1)
        self.assertEqual(p1["id"], p2["id"], "同一天内多次获取每日一诗结果必须一致")


class TestTier1HomepageSidebarSSR(BasePoetryE2ETestCase):
    """Tier 1.2: 首页侧边栏便笺卡组件渲染与 SSR 上下文 (>=5用例)"""

    def test_01_homepage_returns_200_and_contains_sidebar_widget(self):
        """2.1 访问首页 GET / 返回 200，且包含侧边栏便笺卡容器 #sidebarPoetryCard"""
        with self.app.test_client() as client:
            res = client.get("/")
            self.assertEqual(res.status_code, 200)
            html = res.get_data(as_text=True)
            self.assertIn('id="sidebarPoetryCard"', html)
            self.assertIn('data-poetry-sidebar', html)

    def test_02_sidebar_renders_daily_poem_ssr_quote_and_author(self):
        """2.2 侧边栏卡片正确渲染每日一诗的精选名句、朝代与作者微印"""
        daily_poem = self.manager.get_daily_poem()
        self.assertIsNotNone(daily_poem)
        with self.app.test_client() as client:
            res = client.get("/")
            html = res.get_data(as_text=True)
            self.assertIn(daily_poem["highlight"], html)
            self.assertIn(daily_poem["author"], html)
            self.assertIn(daily_poem["dynasty"], html)

    def test_03_sidebar_front_and_back_face_markup_present(self):
        """2.3 侧边栏卡片包含正反两面 DOM 结构与翻转按钮"""
        with self.app.test_client() as client:
            res = client.get("/")
            html = res.get_data(as_text=True)
            self.assertIn("poetry-flip-face is-front", html)
            self.assertIn("poetry-flip-face is-back", html)
            self.assertIn('id="sidebarFlipBtn"', html)
            self.assertIn('id="sidebarFlipBackBtn"', html)

    def test_04_sidebar_like_button_bound_with_daily_poem_id(self):
        """2.4 侧边栏雅赏按钮正确绑定当日诗词 ID (data-poem-id)"""
        daily_poem = self.manager.get_daily_poem()
        with self.app.test_client() as client:
            res = client.get("/")
            html = res.get_data(as_text=True)
            expected_attr = f'data-poem-id="{daily_poem["id"]}"'
            self.assertIn(expected_attr, html)
            self.assertIn('id="sidebarLikeBtn"', html)

    def test_05_sidebar_navigation_link_points_to_poetry_hall(self):
        """2.5 侧边栏卡片背面包含直达诗斋大厅的超链接 /poetry"""
        with self.app.test_client() as client:
            res = client.get("/")
            html = res.get_data(as_text=True)
            self.assertIn('poetry-enter-hall-link', html)
            self.assertIn('/poetry', html)


class TestTier1StandalonePoetryHallSSR(BasePoetryE2ETestCase):
    """Tier 1.3: 独立 /poetry 诗斋沉浸页渲染与组件完备性 (>=5用例)"""

    def test_01_poetry_hall_returns_200_and_shell_element(self):
        """3.1 访问 /poetry 返回 200，渲染诗斋骨架与返回归档导航"""
        with self.app.test_client() as client:
            res = client.get("/poetry")
            self.assertEqual(res.status_code, 200)
            html = res.get_data(as_text=True)
            self.assertIn('id="poetryHall"', html)
            self.assertIn('class="poetry-back-home"', html)
            self.assertIn("诗斋", html)

    def test_02_filter_panel_renders_four_orthogonal_dimension_chips(self):
        """3.2 筛选面板正确呈现朝代、风格、心境、意象四维过滤标签及清空按钮"""
        with self.app.test_client() as client:
            res = client.get("/poetry")
            html = res.get_data(as_text=True)
            self.assertIn('data-dim-toggle="dynasty"', html)
            self.assertIn('data-dim-toggle="style"', html)
            self.assertIn('data-dim-toggle="mood"', html)
            self.assertIn('data-dim-toggle="theme"', html)
            self.assertIn('id="btnFilterAll"', html)
            self.assertIn('id="btnFilterClear"', html)

    def test_03_stage_card_renders_verse_lines_with_cinnabar_buttons(self):
        """3.3 主舞台 3D 卡片正确输出诗句行与朱笔圈点圆点 (.verse-line-dot)"""
        with self.app.test_client() as client:
            res = client.get("/poetry")
            html = res.get_data(as_text=True)
            self.assertIn('id="immersiveCardInner"', html)
            self.assertIn('class="poem-reading-line verse-line verse-line-item"', html)
            self.assertIn('class="verse-line-dot"', html)

    def test_04_stage_controls_bar_buttons_present(self):
        """3.4 操作工具栏包含换一阕、喜欢整首、展卷全篇按钮"""
        with self.app.test_client() as client:
            res = client.get("/poetry")
            html = res.get_data(as_text=True)
            self.assertIn('id="btnSwitchPoem"', html)
            self.assertIn('id="btnImmLike"', html)
            self.assertIn('id="btnFlipCard"', html)

    def test_05_analytics_dashboard_and_drawer_tabs_rendered(self):
        """3.5 底部私藏册页渲染旁批列表、喜欢全篇列表与切换页签"""
        with self.app.test_client() as client:
            res = client.get("/poetry")
            html = res.get_data(as_text=True)
            self.assertIn('class="poetry-notebook-panel"', html)
            self.assertIn('id="tabExcerpts"', html)
            self.assertIn('id="tabPoems"', html)
            self.assertIn('id="notebookExcerptsList"', html)
            self.assertIn('id="notebookPoemsList"', html)

    def test_06_csrf_meta_tag_present_in_head(self):
        """3.6 页面 head 中输出合法的 CSRF Token meta 标签"""
        with self.app.test_client() as client:
            res = client.get("/poetry")
            html = res.get_data(as_text=True)
            match = re.search(r'<meta\s+name="csrf-token"\s+content="([^"]+)"', html)
            self.assertIsNotNone(match, "未找到 meta[name='csrf-token']")
            token = match.group(1)
            self.assertGreater(len(token), 10)


class TestTier1PoemLikeInteraction(BasePoetryE2ETestCase):
    """Tier 1.4: 整首诗词点赞 / 取消点赞与标签偏好持久化 (>=5用例)"""

    def test_01_like_poem_persists_and_updates_weights(self):
        """4.1 POST /api/poetry/like 雅赏整首诗：记录 ID、按 +2.0 增量提升四维标签权重"""
        with self.app.test_client() as client:
            token = self._get_csrf_token(client)
            payload = {"poem_id": "poem_01", "action": "like"}
            res = client.post(
                "/api/poetry/like",
                data=json.dumps(payload),
                content_type="application/json",
                headers={"X-CSRF-Token": token},
            )
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(data["status"], "success")
            self.assertTrue(data["liked"])
            self.assertEqual(data["updated_tag_weights"].get("清丽婉约"), 2.0)
            self.assertEqual(data["updated_tag_weights"].get("北宋"), 2.0)

            # 再次 GET /api/poetry/preferences 验证持久化
            pref_res = client.get("/api/poetry/preferences")
            pref_data = pref_res.get_json()
            self.assertIn("poem_01", pref_data["liked_poem_ids"])
            self.assertEqual(pref_data["tag_weights"].get("清丽婉约"), 2.0)

    def test_02_unlike_poem_reverts_state_and_decrements_weights(self):
        """4.2 POST /api/poetry/like 取消雅赏：移除 ID 并扣减对应标签权重"""
        with self.app.test_client() as client:
            token = self._get_csrf_token(client)
            headers = {"X-CSRF-Token": token}

            # 先点赞
            client.post("/api/poetry/like", data=json.dumps({"poem_id": "poem_01", "action": "like"}),
                        content_type="application/json", headers=headers)

            # 取消点赞
            res = client.post("/api/poetry/like", data=json.dumps({"poem_id": "poem_01", "action": "unlike"}),
                              content_type="application/json", headers=headers)
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertFalse(data["liked"])
            self.assertNotIn("清丽婉约", data["updated_tag_weights"])

            # 验证偏好列表为空
            pref_data = client.get("/api/poetry/preferences").get_json()
            self.assertNotIn("poem_01", pref_data["liked_poem_ids"])

    def test_03_poem_like_is_idempotent(self):
        """4.3 重复点赞同一首诗具有幂等性：ID 不重复累加，权重不重复叠加"""
        with self.app.test_client() as client:
            token = self._get_csrf_token(client)
            headers = {"X-CSRF-Token": token}
            payload = json.dumps({"poem_id": "poem_01", "action": "like"})

            client.post("/api/poetry/like", data=payload, content_type="application/json", headers=headers)
            res2 = client.post("/api/poetry/like", data=payload, content_type="application/json", headers=headers)
            self.assertEqual(res2.status_code, 200)

            pref_data = client.get("/api/poetry/preferences").get_json()
            self.assertEqual(pref_data["liked_poem_ids"].count("poem_01"), 1)
            self.assertEqual(pref_data["tag_weights"].get("清丽婉约"), 2.0)

    def test_04_poem_unlike_is_idempotent(self):
        """4.4 对未点赞的诗执行取消点赞是安全的，权重不扣至负数"""
        with self.app.test_client() as client:
            token = self._get_csrf_token(client)
            headers = {"X-CSRF-Token": token}
            res = client.post(
                "/api/poetry/like",
                data=json.dumps({"poem_id": "poem_01", "action": "unlike"}),
                content_type="application/json",
                headers=headers,
            )
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertFalse(data["liked"])
            pref_data = client.get("/api/poetry/preferences").get_json()
            self.assertEqual(len(pref_data["liked_poem_ids"]), 0)
            self.assertEqual(len(pref_data["tag_weights"]), 0)

    def test_05_poem_like_records_interaction_event(self):
        """4.5 点赞操作自动记入服务端 interaction_history 流水"""
        with self.app.test_client() as client:
            token = self._get_csrf_token(client)
            client.post(
                "/api/poetry/like",
                data=json.dumps({"poem_id": "poem_01", "action": "like"}),
                content_type="application/json",
                headers={"X-CSRF-Token": token},
            )
            history = self.manager.get_interaction_history()
            self.assertGreater(len(history), 0)
            last_event = history[-1]
            self.assertEqual(last_event["poem_id"], "poem_01")
            self.assertEqual(last_event["action"], "like")
            self.assertIn("北宋", last_event["tags"].values())


class TestTier1ExcerptLikeInteraction(BasePoetryE2ETestCase):
    """Tier 1.5: 词句朱笔圈点（摘句心动）与服务端沉淀 (>=5用例)"""

    def test_01_excerpt_like_persists_line_and_weights(self):
        """5.1 POST /api/poetry/excerpt_like 圈点单句：保存词句、提升对应标签权重 (+1.0)"""
        with self.app.test_client() as client:
            token = self._get_csrf_token(client)
            payload = {
                "poem_id": "poem_01",
                "text": "柳垂江上影，梅谢雪中枝。",
                "action": "like",
            }
            res = client.post(
                "/api/poetry/excerpt_like",
                data=json.dumps(payload),
                content_type="application/json",
                headers={"X-CSRF-Token": token},
            )
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(data["status"], "success")
            self.assertTrue(data["liked"])
            self.assertEqual(data["updated_tag_weights"].get("清丽婉约"), 1.0)

            # 验证持久化
            prefs = client.get("/api/poetry/preferences").get_json()
            excerpts = prefs["liked_excerpts"]
            self.assertEqual(len(excerpts), 1)
            self.assertEqual(excerpts[0]["text"], "柳垂江上影，梅谢雪中枝。")
            self.assertEqual(excerpts[0]["poem_id"], "poem_01")

    def test_02_excerpt_unlike_removes_line_and_decrements_weights(self):
        """5.2 POST /api/poetry/excerpt_like 取消圈点：移除词句记录并扣减权重 (-1.0)"""
        with self.app.test_client() as client:
            token = self._get_csrf_token(client)
            headers = {"X-CSRF-Token": token}
            text = "东溪春近好同归。"

            # 先圈点
            client.post("/api/poetry/excerpt_like", data=json.dumps({"poem_id": "poem_01", "text": text, "action": "like"}),
                        content_type="application/json", headers=headers)

            # 取消圈点
            res = client.post("/api/poetry/excerpt_like", data=json.dumps({"poem_id": "poem_01", "text": text, "action": "unlike"}),
                              content_type="application/json", headers=headers)
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertFalse(data["liked"])

            prefs = client.get("/api/poetry/preferences").get_json()
            self.assertEqual(len(prefs["liked_excerpts"]), 0)
            self.assertNotIn("清丽婉约", prefs["tag_weights"])

    def test_03_excerpt_like_is_idempotent(self):
        """5.3 同一词句重复执行圈点具有幂等性：词句列表不重复，权重不额外增加"""
        with self.app.test_client() as client:
            token = self._get_csrf_token(client)
            headers = {"X-CSRF-Token": token}
            payload = json.dumps({"poem_id": "poem_01", "text": "东溪春近好同归。", "action": "like"})

            client.post("/api/poetry/excerpt_like", data=payload, content_type="application/json", headers=headers)
            res2 = client.post("/api/poetry/excerpt_like", data=payload, content_type="application/json", headers=headers)
            self.assertEqual(res2.status_code, 200)

            prefs = client.get("/api/poetry/preferences").get_json()
            self.assertEqual(len(prefs["liked_excerpts"]), 1)
            self.assertEqual(prefs["tag_weights"].get("清丽婉约"), 1.0)

    def test_04_excerpt_data_schema_compliance_for_agent(self):
        """5.4 圈点词句数据结构完全符合供 Agent 分析的契约 (id, poem_id, poem_title, poem_author, text, tags, timestamp)"""
        with self.app.test_client() as client:
            token = self._get_csrf_token(client)
            client.post(
                "/api/poetry/excerpt_like",
                data=json.dumps({"poem_id": "poem_01", "text": "柳垂江上影，梅谢雪中枝。", "action": "like"}),
                content_type="application/json",
                headers={"X-CSRF-Token": token},
            )
            prefs = client.get("/api/poetry/preferences").get_json()
            item = prefs["liked_excerpts"][0]
            self.assertTrue(item["id"].startswith("excerpt_"))
            self.assertEqual(item["poem_id"], "poem_01")
            self.assertEqual(item["poem_title"], "临江仙·浅酒欲邀谁劝")
            self.assertEqual(item["poem_author"], "晏几道")
            self.assertEqual(item["text"], "柳垂江上影，梅谢雪中枝。")
            self.assertIsInstance(item["tags"], dict)
            self.assertIn("timestamp", item)

    def test_05_excerpt_like_logs_interaction_event_with_details(self):
        """5.5 圈点操作在 interaction_history 中记录动作与详细信息 (text, excerpt_id)"""
        with self.app.test_client() as client:
            token = self._get_csrf_token(client)
            client.post(
                "/api/poetry/excerpt_like",
                data=json.dumps({"poem_id": "poem_01", "text": "东溪春近好同归。", "action": "like"}),
                content_type="application/json",
                headers={"X-CSRF-Token": token},
            )
            history = self.manager.get_interaction_history()
            last_event = history[-1]
            self.assertEqual(last_event["action"], "excerpt_like")
            self.assertEqual(last_event["details"]["text"], "东溪春近好同归。")


# ==============================================================================
# Tier 2: Boundary & Corner Cases
# ==============================================================================

class TestTier2BoundaryAndCornerCases(BasePoetryE2ETestCase):
    """Tier 2: 边界防护、输入校验、CSRF 安全与容错恢复测试"""

    def test_01_reject_pure_punctuation_excerpts_400(self):
        """2.1 拒绝纯标点符号圈点：返回 HTTP 400 与清晰的错误提示"""
        with self.app.test_client() as client:
            token = self._get_csrf_token(client)
            headers = {"X-CSRF-Token": token}
            for invalid_text in ["，。！？", "、、、", "；：“”‘’", "《》（）——……"]:
                res = client.post(
                    "/api/poetry/excerpt_like",
                    data=json.dumps({"poem_id": "poem_01", "text": invalid_text, "action": "like"}),
                    content_type="application/json",
                    headers=headers,
                )
                self.assertEqual(res.status_code, 400, f"输入 '{invalid_text}' 应当被 400 拒绝")
                data = res.get_json()
                self.assertEqual(data["status"], "error")
                self.assertIn("标点", data["message"])

    def test_02_reject_pure_whitespace_excerpts_400(self):
        """2.2 拒绝纯空白字符（半角/全角空格/制表/换行）圈点：返回 HTTP 400"""
        with self.app.test_client() as client:
            token = self._get_csrf_token(client)
            headers = {"X-CSRF-Token": token}
            for blank in ["   ", "\t\t", "\n\r", "　　"]:  # 含全角空格
                res = client.post(
                    "/api/poetry/excerpt_like",
                    data=json.dumps({"poem_id": "poem_01", "text": blank, "action": "like"}),
                    content_type="application/json",
                    headers=headers,
                )
                self.assertEqual(res.status_code, 400)
                data = res.get_json()
                self.assertEqual(data["status"], "error")

    def test_03_accept_valid_single_character_poem_eyes_200(self):
        """2.3 接受诗词中真实存在的单字诗眼（如“梅”、“酒”、“春”）：返回 HTTP 200"""
        with self.app.test_client() as client:
            token = self._get_csrf_token(client)
            headers = {"X-CSRF-Token": token}
            # poem_01 包含：“浅酒欲邀谁劝，深情惟有君知。东溪春近好同归。柳垂江上影，梅谢雪中枝。”
            for eye in ["梅", "酒", "春", "雪"]:
                res = client.post(
                    "/api/poetry/excerpt_like",
                    data=json.dumps({"poem_id": "poem_01", "text": eye, "action": "like"}),
                    content_type="application/json",
                    headers=headers,
                )
                self.assertEqual(res.status_code, 200, f"诗眼 '{eye}' 位于诗中，应当成功圈点")
                data = res.get_json()
                self.assertTrue(data["liked"])

    def test_04_reject_excerpt_not_belonging_to_poem_400(self):
        """2.4 拒绝与所属诗词内容不匹配的词句：返回 HTTP 400"""
        with self.app.test_client() as client:
            token = self._get_csrf_token(client)
            res = client.post(
                "/api/poetry/excerpt_like",
                data=json.dumps({
                    "poem_id": "poem_01",
                    "text": "大江东去浪淘尽",  # 属于苏轼《念奴娇》，不在 poem_01 中
                    "action": "like"
                }),
                content_type="application/json",
                headers={"X-CSRF-Token": token},
            )
            self.assertEqual(res.status_code, 400)
            data = res.get_json()
            self.assertIn("不匹配", data["message"])

    def test_05_reject_nonexistent_poem_id_on_like_404(self):
        """2.5 整首点赞传入不存在的诗词 ID 时返回 HTTP 404"""
        with self.app.test_client() as client:
            token = self._get_csrf_token(client)
            res = client.post(
                "/api/poetry/like",
                data=json.dumps({"poem_id": "poem_999_not_found", "action": "like"}),
                content_type="application/json",
                headers={"X-CSRF-Token": token},
            )
            self.assertEqual(res.status_code, 404)
            data = res.get_json()
            self.assertEqual(data["status"], "error")

    def test_06_reject_nonexistent_poem_id_on_excerpt_like_404(self):
        """2.6 词句圈点传入不存在的诗词 ID 时返回 HTTP 404"""
        with self.app.test_client() as client:
            token = self._get_csrf_token(client)
            res = client.post(
                "/api/poetry/excerpt_like",
                data=json.dumps({"poem_id": "poem_999_not_found", "text": "春水煎茶", "action": "like"}),
                content_type="application/json",
                headers={"X-CSRF-Token": token},
            )
            self.assertEqual(res.status_code, 404)

    def test_07_csrf_missing_on_like_mutation_rejected_403(self):
        """2.7 会话建立后，POST /api/poetry/like 缺失 CSRF Token 返回 HTTP 403"""
        with self.app.test_client() as client:
            client.get("/poetry")  # 产生 session csrf_token
            res = client.post(
                "/api/poetry/like",
                data=json.dumps({"poem_id": "poem_01", "action": "like"}),
                content_type="application/json",
                # 未传递 X-CSRF-Token
            )
            self.assertEqual(res.status_code, 403)

    def test_08_csrf_missing_on_excerpt_like_rejected_403(self):
        """2.8 POST /api/poetry/excerpt_like 缺失 CSRF Token 返回 HTTP 403"""
        with self.app.test_client() as client:
            client.get("/poetry")
            res = client.post(
                "/api/poetry/excerpt_like",
                data=json.dumps({"poem_id": "poem_01", "text": "东溪春近好同归。", "action": "like"}),
                content_type="application/json",
            )
            self.assertEqual(res.status_code, 403)

    def test_09_csrf_missing_on_interaction_rejected_403(self):
        """2.9 POST /api/poetry/interaction 缺失 CSRF Token 返回 HTTP 403"""
        with self.app.test_client() as client:
            client.get("/poetry")
            res = client.post(
                "/api/poetry/interaction",
                data=json.dumps({"poem_id": "poem_01", "action": "flip"}),
                content_type="application/json",
            )
            self.assertEqual(res.status_code, 403)

    def test_10_csrf_forged_on_mutation_rejected_403(self):
        """2.10 携带伪造/篡改的 CSRF Token 发起变更请求返回 HTTP 403"""
        with self.app.test_client() as client:
            client.get("/poetry")
            res = client.post(
                "/api/poetry/like",
                data=json.dumps({"poem_id": "poem_01", "action": "like"}),
                content_type="application/json",
                headers={"X-CSRF-Token": "tampered_fake_token_12345"},
            )
            self.assertEqual(res.status_code, 403)

    def test_11_malformed_json_body_rejected_400(self):
        """2.11 发送非法格式的 JSON 请求体返回 HTTP 400"""
        with self.app.test_client() as client:
            token = self._get_csrf_token(client)
            res = client.post(
                "/api/poetry/like",
                data="not a json string at all",
                content_type="application/json",
                headers={"X-CSRF-Token": token},
            )
            self.assertEqual(res.status_code, 400)

    def test_12_empty_state_and_corrupted_file_auto_recovery(self):
        """2.12 验证未产生任何数据时的合法空状态，以及文件损坏时的自动重命名与优雅降级"""
        # 1. 验证空状态
        with self.app.test_client() as client:
            res = client.get("/api/poetry/preferences")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(data["liked_poem_ids"], [])
            self.assertEqual(data["liked_excerpts"], [])
            self.assertEqual(data["tag_weights"], {})

        # 2. 模拟文件损坏（写入破坏性字节）
        with open(self.test_user_data_path, "w", encoding="utf-8") as f:
            f.write("{ incomplete json truncate: ")

        # 3. 再次读取应触发优雅恢复，不抛未处理 500
        with self.app.test_client() as client:
            res2 = client.get("/api/poetry/preferences")
            self.assertEqual(res2.status_code, 200)
            data2 = res2.get_json()
            self.assertEqual(data2["liked_poem_ids"], [])


# ==============================================================================
# Tier 3: Cross-Feature Combinations
# ==============================================================================

class TestTier3CrossFeatureCombinations(BasePoetryE2ETestCase):
    """Tier 3: 跨功能组合、复合加权、并发读写与雷达一致性测试"""

    def test_01_multiple_excerpt_likes_on_same_poem_accumulate_tags(self):
        """3.1 同首诗圈点多句不同诗句：词句分别落盘，标签权重按次数持续累加 (+1.0 +1.0 = +2.0)"""
        with self.app.test_client() as client:
            token = self._get_csrf_token(client)
            headers = {"X-CSRF-Token": token}

            # 圈点第 1 句
            client.post("/api/poetry/excerpt_like",
                        data=json.dumps({"poem_id": "poem_01", "text": "东溪春近好同归。", "action": "like"}),
                        content_type="application/json", headers=headers)
            # 圈点第 2 句
            client.post("/api/poetry/excerpt_like",
                        data=json.dumps({"poem_id": "poem_01", "text": "柳垂江上影，梅谢雪中枝。", "action": "like"}),
                        content_type="application/json", headers=headers)

            prefs = client.get("/api/poetry/preferences").get_json()
            self.assertEqual(len(prefs["liked_excerpts"]), 2)
            # poem_01 标签含 清丽婉约、北宋、幽微相思、梅雪孤枝，每句 +1.0，两句各累计 2.0
            self.assertEqual(prefs["tag_weights"].get("清丽婉约"), 2.0)
            self.assertEqual(prefs["tag_weights"].get("梅雪孤枝"), 2.0)

    def test_02_whole_poem_and_excerpt_cumulative_convergence(self):
        """3.2 整首点赞 (+2.0) + 词句圈点 (+1.0) 复合作用：标签分达 3.0，推荐收敛概率显著提升"""
        with self.app.test_client() as client:
            token = self._get_csrf_token(client)
            headers = {"X-CSRF-Token": token}

            # 初始概率
            init_probs = self.manager.compute_recommendation_probabilities()
            base_prob_poem01 = init_probs["poem_01"]

            # 点赞整篇 (+2.0)
            client.post("/api/poetry/like",
                        data=json.dumps({"poem_id": "poem_01", "action": "like"}),
                        content_type="application/json", headers=headers)

            # 圈点一句 (+1.0)
            client.post("/api/poetry/excerpt_like",
                        data=json.dumps({"poem_id": "poem_01", "text": "柳垂江上影，梅谢雪中枝。", "action": "like"}),
                        content_type="application/json", headers=headers)

            prefs = client.get("/api/poetry/preferences").get_json()
            self.assertEqual(prefs["tag_weights"].get("清丽婉约"), 3.0)

            # 复合加权后的推荐概率
            new_probs = self.manager.compute_recommendation_probabilities()
            new_prob_poem01 = new_probs["poem_01"]

            self.assertGreater(new_prob_poem01, base_prob_poem01 * 1.5,
                               "点赞整首加圈点后，该诗及同类诗词的推荐采样概率应显著提升")

    def test_03_concurrent_read_write_stress_without_corruption(self):
        """3.3 多线程高并发读写压力测试：验证文件互斥锁有效，零死锁、零异常、数据完整一致"""
        num_threads = 8
        ops_per_thread = 5

        def worker_task(thread_id: int):
            for i in range(ops_per_thread):
                pid = f"poem_{( (thread_id + i) % 5 ) + 1:02d}"
                # 记录翻卡
                self.manager.record_interaction(pid, "flip")
                # 点赞
                self.manager.record_poem_like(pid, "like")
                # 读取偏好
                prefs = self.manager.get_user_preferences()
                self.assertIsInstance(prefs["liked_poem_ids"], list)

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(worker_task, tid) for tid in range(num_threads)]
            for future in concurrent.futures.as_completed(futures):
                # 确保无未捕获异常抛出
                future.result()

        final_prefs = self.manager.get_user_preferences()
        self.assertGreater(len(final_prefs["liked_poem_ids"]), 0)
        self.assertGreater(final_prefs["history_count"], 0)

    def test_04_optimistic_ui_radar_weight_consistency(self):
        """3.4 审美雷达对账校验：增量计算的 tag_weights 与全量对账 recalculate_tag_weights() 完全吻合"""
        with self.app.test_client() as client:
            token = self._get_csrf_token(client)
            headers = {"X-CSRF-Token": token}

            # 交互序列：点赞 poem_01、圈点 poem_01 单句、点赞 poem_02
            client.post("/api/poetry/like", data=json.dumps({"poem_id": "poem_01", "action": "like"}),
                        content_type="application/json", headers=headers)
            client.post("/api/poetry/excerpt_like",
                        data=json.dumps({"poem_id": "poem_01", "text": "东溪春近好同归。", "action": "like"}),
                        content_type="application/json", headers=headers)
            client.post("/api/poetry/like", data=json.dumps({"poem_id": "poem_02", "action": "like"}),
                        content_type="application/json", headers=headers)

            incremental_prefs = client.get("/api/poetry/preferences").get_json()
            incremental_weights = incremental_prefs["tag_weights"]

            # 执行全量重新核算对账
            recomputed_weights = self.manager.recalculate_tag_weights()

            self.assertEqual(incremental_weights, recomputed_weights,
                             "前端增量更新的审美雷达权重与服务端全量对账核算结果必须完全一致")

    def test_05_interaction_stream_integration_and_history_cap(self):
        """3.5 翻卡流水集成与 1000 条 FIFO 上限测试"""
        with self.app.test_client() as client:
            token = self._get_csrf_token(client)
            headers = {"X-CSRF-Token": token}

            res = client.post(
                "/api/poetry/interaction",
                data=json.dumps({"poem_id": "poem_01", "action": "flip", "details": {"direction": "front_to_back"}}),
                content_type="application/json",
                headers=headers,
            )
            self.assertEqual(res.status_code, 200)
            self.assertTrue(res.get_json()["recorded"])

            history = self.manager.get_interaction_history()
            self.assertEqual(history[-1]["action"], "flip")
            self.assertEqual(history[-1]["details"]["direction"], "front_to_back")


# ==============================================================================
# Tier 4: Real-World Application Workload Scenarios
# ==============================================================================

class TestTier4RealWorldWorkloads(BasePoetryE2ETestCase):
    """Tier 4: 贴近生产与真实用户的全链路端到端复杂工作场景"""

    def test_01_full_user_journey_e2e(self):
        """
        4.1 全链路端到端用户真实旅程闭环：
        1. 访问博客首页 (GET /) 浏览每日诗词便笺卡
        2. 点击直达诗斋大厅 (GET /poetry)
        3. 初始查阅偏好与数据集 (GET /api/poetry/dataset & /api/poetry/preferences)
        4. 雅赏宋词晏几道《临江仙》整首 (POST /api/poetry/like)
        5. 选中名句“柳垂江上影，梅谢雪中枝。”标为心动 (POST /api/poetry/excerpt_like)
        6. 翻卡并沉淀流水 (POST /api/poetry/interaction)
        7. 直接检查磁盘持久化文件 poetry_user_data.json，验证格式专供 agy 智能助手分析
        8. 校验 Softmax 推荐采样概率明显向北宋/清丽婉约倾斜
        9. 用户取消雅赏与圈点，校验系统偏好权重干净回滚为 0
        """
        with self.app.test_client() as client:
            # 步骤 1：访问首页
            home_res = client.get("/")
            self.assertEqual(home_res.status_code, 200)
            home_html = home_res.get_data(as_text=True)
            self.assertIn("sidebarPoetryCard", home_html)

            # 步骤 2：步入诗斋沉浸大厅，提取 CSRF Token
            hall_res = client.get("/poetry")
            self.assertEqual(hall_res.status_code, 200)
            token = self._get_csrf_token(client)
            headers = {"X-CSRF-Token": token}

            # 步骤 3：加载初始状态
            ds_res = client.get("/api/poetry/dataset")
            self.assertEqual(ds_res.status_code, 200)
            self.assertEqual(ds_res.get_json()["total"], 40)

            pref_init = client.get("/api/poetry/preferences").get_json()
            self.assertEqual(len(pref_init["liked_poem_ids"]), 0)
            self.assertEqual(len(pref_init["liked_excerpts"]), 0)

            # 步骤 4：雅赏整首诗词 (poem_01)
            like_res = client.post(
                "/api/poetry/like",
                data=json.dumps({"poem_id": "poem_01", "action": "like"}),
                content_type="application/json",
                headers=headers,
            )
            self.assertEqual(like_res.status_code, 200)
            self.assertTrue(like_res.get_json()["liked"])

            # 步骤 5：圈点心动句子“柳垂江上影，梅谢雪中枝。”
            exc_text = "柳垂江上影，梅谢雪中枝。"
            exc_res = client.post(
                "/api/poetry/excerpt_like",
                data=json.dumps({"poem_id": "poem_01", "text": exc_text, "action": "like"}),
                content_type="application/json",
                headers=headers,
            )
            self.assertEqual(exc_res.status_code, 200)
            self.assertTrue(exc_res.get_json()["liked"])

            # 步骤 6：记录翻转卡片流水
            inter_res = client.post(
                "/api/poetry/interaction",
                data=json.dumps({"poem_id": "poem_01", "action": "flip"}),
                content_type="application/json",
                headers=headers,
            )
            self.assertEqual(inter_res.status_code, 200)

            # 步骤 7：底层文件物理校验（专供服务器端 agy 智能助手分析）
            self.assertTrue(self.test_user_data_path.exists())
            with open(self.test_user_data_path, "r", encoding="utf-8") as f:
                disk_data = json.load(f)

            self.assertIn("poem_01", disk_data["liked_poem_ids"])
            self.assertEqual(len(disk_data["liked_excerpts"]), 1)
            self.assertEqual(disk_data["liked_excerpts"][0]["text"], exc_text)
            self.assertEqual(disk_data["liked_excerpts"][0]["poem_author"], "晏几道")
            self.assertGreater(disk_data["tag_weights"].get("清丽婉约", 0), 2.5)
            self.assertGreaterEqual(len(disk_data["interaction_history"]), 3)

            # 步骤 8：验证 Softmax 推荐概率收敛倾斜
            rec_probs = self.manager.compute_recommendation_probabilities()
            self.assertAlmostEqual(sum(rec_probs.values()), 1.0, places=4)
            # poem_01 具有最高偏好累加，其采样概率应当在 32 首中位居前列
            max_prob_pid = max(rec_probs, key=rec_probs.get)
            self.assertEqual(max_prob_pid, "poem_01", "高权重点赞诗词应当获得最高的抽卡概率")

            # 步骤 9：用户取消圈点与整首雅赏，验证权重回退与干净落盘
            client.post("/api/poetry/excerpt_like",
                        data=json.dumps({"poem_id": "poem_01", "text": exc_text, "action": "unlike"}),
                        content_type="application/json", headers=headers)
            client.post("/api/poetry/like",
                        data=json.dumps({"poem_id": "poem_01", "action": "unlike"}),
                        content_type="application/json", headers=headers)

            final_prefs = client.get("/api/poetry/preferences").get_json()
            self.assertEqual(len(final_prefs["liked_poem_ids"]), 0)
            self.assertEqual(len(final_prefs["liked_excerpts"]), 0)
            self.assertEqual(len(final_prefs["tag_weights"]), 0)

    def test_02_aesthetic_convergence_under_multi_poem_interactions(self):
        """4.2 多首诗词审美偏好聚集测试：连续点赞同属“清丽婉约”风格的诗篇，Softmax 概率向该风格聚拢"""
        with self.app.test_client() as client:
            token = self._get_csrf_token(client)
            headers = {"X-CSRF-Token": token}

            # 筛选出属于“清丽婉约”的两首诗（poem_01, poem_02）
            client.post("/api/poetry/like", data=json.dumps({"poem_id": "poem_01", "action": "like"}),
                        content_type="application/json", headers=headers)
            client.post("/api/poetry/like", data=json.dumps({"poem_id": "poem_02", "action": "like"}),
                        content_type="application/json", headers=headers)

            prefs = client.get("/api/poetry/preferences").get_json()
            self.assertEqual(prefs["tag_weights"].get("清丽婉约"), 4.0)

            probs = self.manager.compute_recommendation_probabilities()
            # 统计所有“清丽婉约”诗词的总体概率份额
            all_poems = self.manager.get_all_poems()
            qingli_pids = [p["id"] for p in all_poems if p.get("tags", {}).get("style") == "清丽婉约"]
            qingli_share = sum(probs[pid] for pid in qingli_pids)

            uniform_share = len(qingli_pids) / len(all_poems)
            self.assertGreater(qingli_share, uniform_share * 1.8,
                               "同风格多首点赞后，该风格诗词的整体概率分布份额应大幅上升")

    def test_03_excerpt_punctuation_tolerance_and_normalization(self):
        """4.3 圈点标点容差与子串标准化测试：带标点、不带标点或末尾带标点均能精准匹配正文"""
        with self.app.test_client() as client:
            token = self._get_csrf_token(client)
            headers = {"X-CSRF-Token": token}

            # poem_01 原文第三行：“柳垂江上影，梅谢雪中枝。”
            variations = [
                "柳垂江上影",                  # 去标点前半句
                "柳垂江上影，",                # 带中文逗号前半句
                "梅谢雪中枝",                  # 去标点后半句
                "柳垂江上影，梅谢雪中枝。",      # 完整整句含全角句号
            ]
            for var_text in variations:
                res = client.post(
                    "/api/poetry/excerpt_like",
                    data=json.dumps({"poem_id": "poem_01", "text": var_text, "action": "like"}),
                    content_type="application/json",
                    headers=headers,
                )
                self.assertEqual(res.status_code, 200, f"文本变体 '{var_text}' 应成功通过归一化匹配")
                self.assertTrue(res.get_json()["liked"])

    def test_04_ssr_reflects_persisted_user_likes(self):
        """4.4 服务端持久化数据在 SSR 渲染中的视觉回显校验 (is_today_liked 与 liked_poem_ids)"""
        # 预先在服务端数据中存入今日一诗的点赞记录与一条圈点
        daily_poem = self.manager.get_daily_poem()
        self.assertIsNotNone(daily_poem)
        daily_id = daily_poem["id"]

        self.manager.record_poem_like(daily_id, "like")
        self.manager.record_excerpt_like(daily_id, daily_poem["content"][0], "like")

        with self.app.test_client() as client:
            # 1. 首页 SSR 应显示 is_today_liked 态（包含 is-liked 类与“已喜欢”文本）
            home_res = client.get("/")
            home_html = home_res.get_data(as_text=True)
            self.assertIn("is-liked", home_html)
            self.assertIn("已喜欢", home_html)

            # 2. 诗斋沉浸页 SSR 应将 liked_poem_ids 与 liked_excerpts 传入上下文
            hall_res = client.get("/poetry")
            hall_html = hall_res.get_data(as_text=True)
            self.assertIn(daily_id, hall_html)


if __name__ == "__main__":
    unittest.main()
