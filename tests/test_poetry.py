# tests/test_poetry.py
# -*- coding: utf-8 -*-
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app import create_app
from app.auth import CSRF_SESSION_KEY
from app.poetry import (
    PoetryManager,
    get_poetry_manager,
    get_daily_poem,
    load_poems_dataset,
    load_user_data,
    save_user_data,
    _is_text_in_poem,
    WEIGHT_DELTA_POEM_LIKE,
    WEIGHT_DELTA_EXCERPT_LIKE,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REAL_POEMS_PATH = PROJECT_ROOT / "app" / "data" / "poems.json"

APPROVED_DYNASTIES = {"唐代", "五代", "北宋", "南宋", "金代", "元代", "明代", "清代"}
APPROVED_STYLES = {"清丽婉约", "澄澈疏朗", "清骨入神", "俊逸风骨", "纤巧灵动", "纯粹深情"}
APPROVED_MOODS = {"幽微相思", "别后怀人", "独立清醒", "苍茫通达", "恬淡隐逸", "微寒羁旅", "闲愁清冷"}
APPROVED_THEMES = {"春水飞花", "梅雪孤枝", "秋风夜雨", "风雪千山", "烟火残棋", "孤星明月", "松花烹茶", "青帘画屏"}


class TestPoetryDatasetIntegrity(unittest.TestCase):
    """维度 1：诗词数据集与四维正交标签完整性测试"""

    def setUp(self):
        self.assertTrue(REAL_POEMS_PATH.exists(), f"诗词数据集文件不存在: {REAL_POEMS_PATH}")
        with open(REAL_POEMS_PATH, "r", encoding="utf-8") as f:
            self.data = json.load(f)

    def test_total_poem_count_is_exactly_32(self):
        """严格校验数据集总量为 32 首"""
        poems = self.data.get("poems", [])
        self.assertEqual(len(poems), 32, f"诗词数量应严格为 32 首，当前实际为 {len(poems)}")
        self.assertEqual(self.data.get("total"), 32)

    def test_unique_poem_ids(self):
        """确保所有诗词 ID 唯一无重复且遵循 poem_XX 规范"""
        poems = self.data.get("poems", [])
        ids = [p["id"] for p in poems if "id" in p]
        self.assertEqual(len(ids), 32)
        self.assertEqual(len(set(ids)), 32, "存在重复的诗词 ID")
        for pid in ids:
            self.assertTrue(pid.startswith("poem_"), f"ID 命名格式异常: {pid}")

    def test_required_fields_present_and_non_empty(self):
        """确保每首诗词的所有必填字段存在且非空"""
        required_fields = [
            "id", "dynasty", "author", "title", "content",
            "highlight", "commentary", "tags", "is_handwritten"
        ]
        for poem in self.data["poems"]:
            poem_id = poem.get("id", "UNKNOWN")
            for field in required_fields:
                self.assertIn(field, poem, f"诗词 {poem_id} 缺失必填字段: {field}")

            # content 必须是非空列表且各行为字符串
            self.assertIsInstance(poem["content"], list, f"诗词 {poem_id} content 必须为列表")
            self.assertGreater(len(poem["content"]), 0, f"诗词 {poem_id} content 不能为空")
            for line in poem["content"]:
                self.assertIsInstance(line, str)
                self.assertGreater(len(line.strip()), 0)

            # highlight 必须为非空字符串
            self.assertIsInstance(poem["highlight"], str)
            self.assertGreater(len(poem["highlight"].strip()), 0)

            # commentary 必须为非空微评
            self.assertIsInstance(poem["commentary"], str)
            self.assertGreater(len(poem["commentary"].strip()), 0)

            # is_handwritten 必须是布尔值
            self.assertIsInstance(poem["is_handwritten"], bool)

    def test_four_dimensional_orthogonal_tags(self):
        """严格校验四维标签正交性：dynasty、style、mood、theme"""
        for poem in self.data["poems"]:
            poem_id = poem.get("id")
            tags = poem.get("tags", {})
            self.assertIn("dynasty", tags, f"{poem_id} 缺失朝代标签")
            self.assertIn("style", tags, f"{poem_id} 缺失风格标签")
            self.assertIn("mood", tags, f"{poem_id} 缺失意境标签")
            self.assertIn("theme", tags, f"{poem_id} 缺失意象物候标签")

            self.assertIn(tags["dynasty"], APPROVED_DYNASTIES, f"{poem_id} 朝代标签无效: {tags['dynasty']}")
            self.assertIn(tags["style"], APPROVED_STYLES, f"{poem_id} 风格标签无效: {tags['style']}")
            self.assertIn(tags["mood"], APPROVED_MOODS, f"{poem_id} 意境标签无效: {tags['mood']}")
            self.assertIn(tags["theme"], APPROVED_THEMES, f"{poem_id} 意象标签无效: {tags['theme']}")

    def test_handwritten_flag_integrity(self):
        """校验亲笔手抄/黄金标杆标记：恰好 13 首国誉手抄篇目为 True，19 首为 False"""
        poems = self.data["poems"]
        handwritten_count = sum(1 for p in poems if p.get("is_handwritten") is True)
        self.assertEqual(handwritten_count, 13, f"亲笔手抄应为 13 首，实际为 {handwritten_count}")


class TestPoetryUserDataPersistence(unittest.TestCase):
    """维度 2：服务端偏好加载、初始化与容错测试"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_user_data_path = Path(self.temp_dir.name) / "poetry_user_data.json"
        self.manager = PoetryManager(
            poems_path=str(REAL_POEMS_PATH),
            user_data_path=str(self.test_user_data_path)
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_fallback_when_file_does_not_exist(self):
        """当用户偏好文件不存在时，优雅降级返回默认空状态而不抛出异常"""
        self.assertFalse(self.test_user_data_path.exists())
        prefs = self.manager.get_user_preferences()
        self.assertEqual(prefs["liked_poem_ids"], [])
        self.assertEqual(prefs["liked_excerpts"], [])
        self.assertEqual(prefs["tag_weights"], {})
        self.assertEqual(prefs["history_count"], 0)

    def test_directory_auto_creation_on_first_save(self):
        """当父级目录不存在时，自动递归创建目录并成功落盘"""
        nested_path = Path(self.temp_dir.name) / "sub1" / "sub2" / "user_data.json"
        manager = PoetryManager(poems_path=str(REAL_POEMS_PATH), user_data_path=str(nested_path))
        manager.record_interaction("poem_01", "view")
        self.assertTrue(nested_path.exists())

    def test_corrupted_json_recovery(self):
        """当持久化文件意外损坏（截断非法 JSON）时，安全降级而不崩溃"""
        with open(self.test_user_data_path, "w", encoding="utf-8") as f:
            f.write("{ invalid json corrupted ...")
        prefs = self.manager.get_user_preferences()
        self.assertIsInstance(prefs, dict)
        self.assertEqual(prefs["liked_poem_ids"], [])

    def test_atomic_save_and_reload(self):
        """验证原子写入后文件符合规范且能完整 reload"""
        data = {
            "version": 1,
            "liked_poem_ids": ["poem_01"],
            "liked_excerpts": [],
            "tag_weights": {"清丽婉约": 2.0},
            "interaction_history": []
        }
        save_user_data(data, user_data_path=str(self.test_user_data_path))
        loaded = load_user_data(str(self.test_user_data_path))
        self.assertEqual(loaded["liked_poem_ids"], ["poem_01"])
        self.assertEqual(loaded["tag_weights"], {"清丽婉约": 2.0})


class TestPoetryLikeAndUnlike(unittest.TestCase):
    """维度 3：整首诗词点赞与取消点赞 API 及幂等性测试"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_user_data_path = Path(self.temp_dir.name) / "poetry_user_data.json"
        self.manager = PoetryManager(
            poems_path=str(REAL_POEMS_PATH),
            user_data_path=str(self.test_user_data_path)
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_like_poem_persists_and_updates_weights(self):
        """点赞整篇诗词：正确添加 ID、按标签增量更新权重并持久化 (+2.0)"""
        result = self.manager.record_poem_like("poem_01", "like")
        self.assertTrue(result["liked"])
        self.assertIn("poem_01", self.manager.get_user_preferences()["liked_poem_ids"])

        weights = result["updated_tag_weights"]
        self.assertEqual(weights.get("清丽婉约"), WEIGHT_DELTA_POEM_LIKE)
        self.assertEqual(weights.get("北宋"), WEIGHT_DELTA_POEM_LIKE)
        self.assertEqual(weights.get("幽微相思"), WEIGHT_DELTA_POEM_LIKE)
        self.assertEqual(weights.get("梅雪孤枝"), WEIGHT_DELTA_POEM_LIKE)

    def test_like_poem_is_idempotent(self):
        """重复对同一首诗执行 like，不产生重复 ID 且权重不重复叠加"""
        self.manager.record_poem_like("poem_01", "like")
        self.manager.record_poem_like("poem_01", "like")
        liked_ids = self.manager.get_user_preferences()["liked_poem_ids"]
        self.assertEqual(liked_ids.count("poem_01"), 1)
        weights = self.manager.get_user_preferences()["tag_weights"]
        self.assertEqual(weights.get("清丽婉约"), WEIGHT_DELTA_POEM_LIKE)

    def test_unlike_poem_removes_id_and_decrements_weights(self):
        """取消点赞：移除 ID 并扣减对应标签权重（不低于下限并清理）"""
        self.manager.record_poem_like("poem_01", "like")
        result = self.manager.record_poem_like("poem_01", "unlike")
        self.assertFalse(result["liked"])
        self.assertNotIn("poem_01", self.manager.get_user_preferences()["liked_poem_ids"])
        weights = self.manager.get_user_preferences()["tag_weights"]
        self.assertNotIn("清丽婉约", weights)

    def test_unlike_when_not_liked_is_safe(self):
        """在未点赞状态下取消点赞，静默成功且不产生负权重"""
        result = self.manager.record_poem_like("poem_01", "unlike")
        self.assertFalse(result["liked"])
        weights = self.manager.get_user_preferences()["tag_weights"]
        self.assertEqual(weights, {})


class TestPoetryExcerptLike(unittest.TestCase):
    """维度 4：朱笔圈点词句点赞与取消点赞测试"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_user_data_path = Path(self.temp_dir.name) / "poetry_user_data.json"
        self.manager = PoetryManager(
            poems_path=str(REAL_POEMS_PATH),
            user_data_path=str(self.test_user_data_path)
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_excerpt_like_records_line_detail(self):
        """圈点词句：包含 text、poem_id、title、author、tags 与时间戳 (+1.0)"""
        text = "柳垂江上影，梅谢雪中枝。"
        result = self.manager.record_excerpt_like("poem_01", text, "like")
        self.assertTrue(result["liked"])
        excerpt = result["excerpt"]
        self.assertEqual(excerpt["poem_id"], "poem_01")
        self.assertEqual(excerpt["text"], text)
        self.assertIn("timestamp", excerpt)
        self.assertEqual(result["updated_tag_weights"]["清丽婉约"], WEIGHT_DELTA_EXCERPT_LIKE)

    def test_excerpt_like_validates_text_belongs_to_poem(self):
        """圈点词句若不在诗词正文中，抛出 ValueError"""
        with self.assertRaises(ValueError):
            self.manager.record_excerpt_like("poem_01", "绝不可能存在的乱入诗句", "like")

    def test_excerpt_like_is_idempotent(self):
        """重复圈点相同句子不产生重复项"""
        text = "柳垂江上影，梅谢雪中枝。"
        self.manager.record_excerpt_like("poem_01", text, "like")
        self.manager.record_excerpt_like("poem_01", text, "like")
        excerpts = self.manager.get_user_preferences()["liked_excerpts"]
        self.assertEqual(len(excerpts), 1)
        self.assertEqual(self.manager.get_user_preferences()["tag_weights"]["清丽婉约"], WEIGHT_DELTA_EXCERPT_LIKE)

    def test_excerpt_unlike_removes_from_list(self):
        """取消词句圈点：从已圈点列表中正确移除"""
        text = "柳垂江上影，梅谢雪中枝。"
        self.manager.record_excerpt_like("poem_01", text, "like")
        self.manager.record_excerpt_like("poem_01", text, "unlike")
        excerpts = self.manager.get_user_preferences()["liked_excerpts"]
        self.assertEqual(len(excerpts), 0)
        self.assertNotIn("清丽婉约", self.manager.get_user_preferences()["tag_weights"])

    def test_recalculate_tag_weights_consistency(self):
        """混合全篇点赞与词句圈点后，全量对账重算与实时更新完全吻合"""
        self.manager.record_poem_like("poem_01", "like")  # +2.0
        self.manager.record_excerpt_like("poem_01", "柳垂江上影，梅谢雪中枝。", "like")  # +1.0
        self.manager.record_poem_like("poem_02", "like")  # +2.0 (包含清丽婉约)

        realtime_weights = self.manager.get_user_preferences()["tag_weights"]
        recalculated = self.manager.recalculate_tag_weights()
        self.assertEqual(realtime_weights, recalculated)
        # 清丽婉约: 2.0 (poem_01) + 1.0 (excerpt) + 2.0 (poem_02) = 5.0
        self.assertEqual(recalculated.get("清丽婉约"), 5.0)

    def test_excerpt_pure_chinese_punctuation_rejected(self):
        """圈点纯中文标点必须被拒绝且返回明确错误提示，不产生脏数据"""
        poem = self.manager.get_poem_by_id("poem_01")
        for p in ["，", "。", "！", "？", "、", "；", "：", "“", "”", "‘", "’", "（）", "《》", "——", "……"]:
            with self.subTest(p=p):
                self.assertFalse(_is_text_in_poem(p, poem))
                with self.assertRaises(ValueError) as ctx:
                    self.manager.record_excerpt_like("poem_01", p, "like")
                self.assertEqual(str(ctx.exception), "圈点词句不能仅包含标点符号或空白")
        self.assertEqual(self.manager.get_user_preferences()["liked_excerpts"], [])
        self.assertEqual(self.manager.get_user_preferences()["tag_weights"], {})

    def test_excerpt_pure_ascii_punctuation_rejected(self):
        """圈点纯 ASCII 标点符号必须被拒绝"""
        poem = self.manager.get_poem_by_id("poem_01")
        for p in [",", ".", "!", "?", ";", ":", "\"", "'", " , . ! ? ; : "]:
            with self.subTest(p=p):
                self.assertFalse(_is_text_in_poem(p, poem))
                with self.assertRaises(ValueError) as ctx:
                    self.manager.record_excerpt_like("poem_01", p, "like")
                self.assertEqual(str(ctx.exception), "圈点词句不能仅包含标点符号或空白")

    def test_excerpt_pure_whitespace_rejected(self):
        """圈点纯空白字符必须被拒绝"""
        poem = self.manager.get_poem_by_id("poem_01")
        for ws in ["", " ", "   ", "\t", "\n", "\r\n", "\u3000", "\xa0", " \t \u3000 \n "]:
            with self.subTest(ws=repr(ws)):
                self.assertFalse(_is_text_in_poem(ws, poem))
                with self.assertRaises(ValueError) as ctx:
                    self.manager.record_excerpt_like("poem_01", ws, "like")
                self.assertEqual(str(ctx.exception), "圈点词句内容不能为空")

    def test_excerpt_mixed_punctuation_and_whitespace_rejected(self):
        """圈点混合标点与空白字符必须被拒绝"""
        poem = self.manager.get_poem_by_id("poem_01")
        for mix in [" ， ", " \t 。 \n ", "，。！？、", " , . ? ! \u3000 "]:
            with self.subTest(mix=repr(mix)):
                self.assertFalse(_is_text_in_poem(mix, poem))
                with self.assertRaises(ValueError) as ctx:
                    self.manager.record_excerpt_like("poem_01", mix, "like")
                self.assertEqual(str(ctx.exception), "圈点词句不能仅包含标点符号或空白")

    def test_excerpt_genuine_poetic_phrases_and_variations(self):
        """真实诗词名句、短语、带引号或英文标点的选段均能正常圈点"""
        poem = self.manager.get_poem_by_id("poem_01")
        valid_cases = [
            "柳垂江上影，梅谢雪中枝。",          # 原文带标点完整行
            "柳垂江上影",                      # 逗号前半句
            "梅谢雪中枝",                      # 逗号后半句
            "柳垂江上影,梅谢雪中枝",            # 英文标点替换
            "“柳垂江上影”",                    # 带中文引号
            "《东溪春近好同归》",              # 带书名号
            "浅酒欲邀谁劝——深情惟有君知",       # 带破折号
            "  \n 柳垂江上影，梅谢雪中枝。 \t ",  # 带首尾空白
            "柳垂  江上影",                    # 包含内部空格
            "柳垂\u3000江上影",                # 包含全角空格
            "深情惟有君知。\n东溪春近好同归。",   # 跨行带换行
            "深情惟有君知东溪春近",             # 跨行连续子串
            "浅酒",                           # 2 字意境词
            "梅",                            # 1 字诗眼
        ]
        for vc in valid_cases:
            with self.subTest(case=vc):
                self.assertTrue(_is_text_in_poem(vc, poem))

    def test_excerpt_invalid_phrases_and_safety(self):
        """错别字、乱序文本、其他诗词内容及超长字符串安全拦截"""
        poem = self.manager.get_poem_by_id("poem_01")
        invalid_cases = [
            "柳垂河上影，梅谢雪中枝。",           # 错别字
            "知君有惟情深",                     # 乱序
            "身外闲愁空满，眼中欢事常稀。",       # 其他诗词
            "床前明月光，疑是地上霜",            # 无关诗句
            "长" * 10000,                     # 超长字符串
            "柳垂[江]上影",                    # 非诗词方括号
            "(浅酒欲邀谁劝)",                  # 非诗词圆括号
        ]
        for ic in invalid_cases:
            with self.subTest(case=ic):
                self.assertFalse(_is_text_in_poem(ic, poem))
                with self.assertRaises(ValueError):
                    self.manager.record_excerpt_like("poem_01", ic, "like")


class TestTagWeightConvergenceAndRecommendation(unittest.TestCase):
    """维度 5：标签权重计算、收敛性与 Softmax 抽卡分布测试"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_user_data_path = Path(self.temp_dir.name) / "poetry_user_data.json"
        self.manager = PoetryManager(
            poems_path=str(REAL_POEMS_PATH),
            user_data_path=str(self.test_user_data_path)
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_softmax_probabilities_sum_to_one(self):
        """Softmax 计算得出的抽卡概率分布之和严格等于 1.0"""
        probs = self.manager.compute_recommendation_probabilities()
        self.assertEqual(len(probs), 32)
        total_prob = sum(probs.values())
        self.assertAlmostEqual(total_prob, 1.0, places=5)

    def test_convergence_toward_repeatedly_liked_style(self):
        """连续点赞具有特定风格的诗词后，该风格诗词的抽中概率显著高于其他风格"""
        # 点赞多首“清丽婉约”诗词
        self.manager.record_poem_like("poem_01", "like") # 晏几道 (清丽婉约)
        self.manager.record_poem_like("poem_02", "like") # 晏几道 (清丽婉约)
        self.manager.record_poem_like("poem_05", "like") # 秦观 (清丽婉约)

        probs = self.manager.compute_recommendation_probabilities()
        prob_wan_yue = probs["poem_01"]

        # 对比一首非婉约风格的诗词（如金代元好问俊逸风骨）
        other_poem_id = next(
            p["id"] for p in self.manager.get_all_poems()
            if p["tags"]["style"] != "清丽婉约"
        )
        self.assertGreater(prob_wan_yue, probs[other_poem_id])

    def test_exploration_diversity_margin_preserved(self):
        """即使从未被点赞的诗词，仍保持大于 0 的基础探索概率"""
        probs = self.manager.compute_recommendation_probabilities()
        for poem_id, p in probs.items():
            self.assertGreater(p, 0.0, f"诗词 {poem_id} 抽卡概率不得为 0")

    def test_pick_next_poem_returns_valid_poem(self):
        """pick_next_poem 能够返回合法的 Poem 字典"""
        poem = self.manager.pick_next_poem()
        self.assertIsNotNone(poem)
        self.assertIn("id", poem)
        self.assertIn("title", poem)

    def test_pick_next_poem_with_tag_filter(self):
        """带标签过滤的 pick_next_poem 返回符合条件的诗词"""
        poem = self.manager.pick_next_poem(tag_filter="清丽婉约")
        self.assertIsNotNone(poem)
        self.assertEqual(poem["tags"]["style"], "清丽婉约")


class TestInteractionLogging(unittest.TestCase):
    """维度 6：用户交互流水日志沉淀测试"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_user_data_path = Path(self.temp_dir.name) / "poetry_user_data.json"
        self.manager = PoetryManager(
            poems_path=str(REAL_POEMS_PATH),
            user_data_path=str(self.test_user_data_path)
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_record_flip_and_view_actions(self):
        """记录翻卡与查看行为，并在偏好中准确统计流水次数"""
        self.manager.record_interaction("poem_01", "view")
        self.manager.record_interaction("poem_01", "flip")
        self.manager.record_interaction("poem_02", "switch")

        prefs = self.manager.get_user_preferences()
        self.assertEqual(prefs["history_count"], 3)
        history = self.manager.get_interaction_history()
        self.assertEqual(len(history), 3)
        self.assertEqual(history[0]["action"], "view")
        self.assertEqual(history[1]["action"], "flip")

    def test_interaction_history_limit_to_1000(self):
        """流水超过 1000 条时 FIFO 淘汰最旧记录"""
        # 预先构造 999 条历史流水
        data = {
            "version": 1,
            "liked_poem_ids": [],
            "liked_excerpts": [],
            "tag_weights": {},
            "interaction_history": [
                {"id": f"evt_{i}", "poem_id": "poem_01", "action": "view", "timestamp": "2026-11-12T00:00:00Z"}
                for i in range(999)
            ]
        }
        save_user_data(data, user_data_path=str(self.test_user_data_path))

        # 再追加 5 条
        for _ in range(5):
            self.manager.record_interaction("poem_01", "view")

        history = self.manager.get_interaction_history()
        self.assertEqual(len(history), 1000)
        # 最早的记录应已被淘汰
        self.assertEqual(history[-1]["poem_id"], "poem_01")

    def test_invalid_action_raises_value_error(self):
        """非法动作类型抛出 ValueError"""
        with self.assertRaises(ValueError):
            self.manager.record_interaction("poem_01", "invalid_action_xyz")


class TestPoetryFlaskRoutes(unittest.TestCase):
    """维度 7：Flask 蓝图路由 HTTP 交互与响应码综合测试"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_user_data_path = Path(self.temp_dir.name) / "poetry_user_data.json"

        self.app = create_app()
        self.app.config.update(
            TESTING=True,
            POETRY_USER_DATA_PATH=str(self.test_user_data_path),
        )
        self.test_manager = PoetryManager(
            poems_path=str(REAL_POEMS_PATH),
            user_data_path=str(self.test_user_data_path)
        )
        self.patcher = patch("app.routes.get_poetry_manager", return_value=self.test_manager)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.temp_dir.cleanup()

    def test_get_poetry_page_returns_200_html(self):
        """GET /poetry 能够正常渲染 HTML 诗斋主页"""
        with self.app.test_client() as client:
            res = client.get("/poetry")
            self.assertEqual(res.status_code, 200)
            self.assertIn("text/html", res.content_type)
            html = res.get_data(as_text=True)
            self.assertIn("诗斋", html)

    def test_get_api_poetry_dataset_returns_json(self):
        """GET /api/poetry/dataset 返回 200 与 32 首数据"""
        with self.app.test_client() as client:
            res = client.get("/api/poetry/dataset")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(data["status"], "success")
            self.assertEqual(data["total"], 32)
            self.assertEqual(len(data["poems"]), 32)
            self.assertIn("tags", data)

    def test_get_api_poetry_user_preferences_returns_json(self):
        """GET /api/poetry/user_preferences 返回初始偏好结构"""
        with self.app.test_client() as client:
            res = client.get("/api/poetry/user_preferences")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(data["status"], "success")
            self.assertEqual(data["liked_poem_ids"], [])
            self.assertEqual(data["liked_excerpts"], [])

    def test_get_api_poetry_preferences_alias_returns_json(self):
        """GET /api/poetry/preferences 路由别名能够正常返回"""
        with self.app.test_client() as client:
            res = client.get("/api/poetry/preferences")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(data["status"], "success")

    def test_post_poetry_like_route(self):
        """POST /api/poetry/like 正确处理点赞请求"""
        with self.app.test_client() as client:
            res = client.post(
                "/api/poetry/like",
                json={"poem_id": "poem_01", "action": "like"}
            )
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data["liked"])
            self.assertIn("updated_tag_weights", data)

    def test_post_poetry_like_invalid_poem_id_returns_404(self):
        """POST /api/poetry/like 诗词 ID 不存在返回 404"""
        with self.app.test_client() as client:
            res = client.post(
                "/api/poetry/like",
                json={"poem_id": "poem_not_exist_999", "action": "like"}
            )
            self.assertEqual(res.status_code, 404)

    def test_post_poetry_like_invalid_action_returns_400(self):
        """POST /api/poetry/like action 不合法返回 400"""
        with self.app.test_client() as client:
            res = client.post(
                "/api/poetry/like",
                json={"poem_id": "poem_01", "action": "unknown_action"}
            )
            self.assertEqual(res.status_code, 400)

    def test_post_poetry_excerpt_like_route(self):
        """POST /api/poetry/excerpt_like 正确圈点词句"""
        with self.app.test_client() as client:
            res = client.post(
                "/api/poetry/excerpt_like",
                json={"poem_id": "poem_01", "text": "柳垂江上影，梅谢雪中枝。", "action": "like"}
            )
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data["liked"])
            self.assertEqual(data["excerpt"]["text"], "柳垂江上影，梅谢雪中枝。")

    def test_post_poetry_excerpt_like_invalid_text_returns_400(self):
        """POST /api/poetry/excerpt_like 圈点无关词句返回 400"""
        with self.app.test_client() as client:
            res = client.post(
                "/api/poetry/excerpt_like",
                json={"poem_id": "poem_01", "text": "这是完全不相关的乱写句子", "action": "like"}
            )
            self.assertEqual(res.status_code, 400)

    def test_post_poetry_excerpt_like_invalid_poem_returns_404(self):
        """POST /api/poetry/excerpt_like 诗词不存在返回 404"""
        with self.app.test_client() as client:
            res = client.post(
                "/api/poetry/excerpt_like",
                json={"poem_id": "poem_xyz", "text": "某句", "action": "like"}
            )
            self.assertEqual(res.status_code, 404)

    def test_post_poetry_interaction_route(self):
        """POST /api/poetry/interaction 正确记录翻卡流水"""
        with self.app.test_client() as client:
            res = client.post(
                "/api/poetry/interaction",
                json={"poem_id": "poem_01", "action": "flip"}
            )
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data["recorded"])
            self.assertEqual(data["action"], "flip")

    def test_post_poetry_interaction_invalid_action_returns_400(self):
        """POST /api/poetry/interaction action 不合法返回 400"""
        with self.app.test_client() as client:
            res = client.post(
                "/api/poetry/interaction",
                json={"poem_id": "poem_01", "action": "fly_to_moon"}
            )
            self.assertEqual(res.status_code, 400)

    def test_post_non_json_body_returns_400(self):
        """POST 非 JSON 请求体返回 400"""
        with self.app.test_client() as client:
            res = client.post(
                "/api/poetry/like",
                data="not json string",
                content_type="text/plain"
            )
            self.assertEqual(res.status_code, 400)

    def test_post_poetry_excerpt_like_pure_punctuation_returns_400(self):
        """POST /api/poetry/excerpt_like 提交纯标点符号返回 400 与明确提示语"""
        with self.app.test_client() as client:
            for punct in ["，", "。", "！", "、", "，。！？", " , . : ; "]:
                with self.subTest(punct=punct):
                    res = client.post(
                        "/api/poetry/excerpt_like",
                        json={"poem_id": "poem_01", "text": punct, "action": "like"}
                    )
                    self.assertEqual(res.status_code, 400)
                    data = res.get_json()
                    self.assertEqual(data["status"], "error")
                    self.assertEqual(data["message"], "圈点词句不能仅包含标点符号或空白")

    def test_post_poetry_excerpt_like_pure_whitespace_returns_400(self):
        """POST /api/poetry/excerpt_like 提交纯空白返回 400 与内容不能为空提示"""
        with self.app.test_client() as client:
            res = client.post(
                "/api/poetry/excerpt_like",
                json={"poem_id": "poem_01", "text": "   ", "action": "like"}
            )
            self.assertEqual(res.status_code, 400)
            data = res.get_json()
            self.assertEqual(data["status"], "error")
            self.assertIn("不能为空", data["message"])

    def test_post_poetry_excerpt_like_with_quotes_and_normalization_succeeds(self):
        """POST /api/poetry/excerpt_like 提交带引号的诗句能够正常圈点加权"""
        with self.app.test_client() as client:
            res = client.post(
                "/api/poetry/excerpt_like",
                json={"poem_id": "poem_01", "text": "“柳垂江上影”", "action": "like"}
            )
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data["liked"])
            self.assertIn("清丽婉约", data["updated_tag_weights"])


class TestPoetryCSRFProtection(unittest.TestCase):
    """维度 7：诗词接口 CSRF 防护与 Token 校验安全性测试"""

    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_user_data_path = Path(self.temp_dir.name) / "test_user_data.json"
        self.test_manager = PoetryManager(
            poems_path=str(REAL_POEMS_PATH),
            user_data_path=str(self.test_user_data_path)
        )
        self.patcher = patch("app.routes.get_poetry_manager", return_value=self.test_manager)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.temp_dir.cleanup()

    def test_post_like_valid_session_valid_header_passes_200(self):
        """携带有效 Session 与有效 X-CSRF-Token 能够正常通过 (200)"""
        with self.app.test_client() as client:
            with client.session_transaction() as sess:
                sess[CSRF_SESSION_KEY] = "token_valid_123"
            res = client.post(
                "/api/poetry/like",
                headers={"X-CSRF-Token": "token_valid_123"},
                json={"poem_id": "poem_01", "action": "like"}
            )
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data.get("liked"))

    def test_post_like_valid_session_missing_header_rejected_403(self):
        """携带有效 Session 但缺失 CSRF Header/Form 时严格拒绝 (403)"""
        with self.app.test_client() as client:
            with client.session_transaction() as sess:
                sess[CSRF_SESSION_KEY] = "token_valid_123"
            res = client.post(
                "/api/poetry/like",
                json={"poem_id": "poem_01", "action": "like"}
            )
            self.assertEqual(res.status_code, 403)

    def test_post_like_valid_session_forged_header_rejected_403(self):
        """携带有效 Session 但传入伪造 CSRF Token 时严格拒绝 (403)"""
        with self.app.test_client() as client:
            with client.session_transaction() as sess:
                sess[CSRF_SESSION_KEY] = "token_valid_123"
            res = client.post(
                "/api/poetry/like",
                headers={"X-CSRF-Token": "token_forged_999"},
                json={"poem_id": "poem_01", "action": "like"}
            )
            self.assertEqual(res.status_code, 403)

    def test_post_like_valid_session_empty_header_rejected_403(self):
        """携带有效 Session 但传入空字符串 Token 时严格拒绝 (403)"""
        with self.app.test_client() as client:
            with client.session_transaction() as sess:
                sess[CSRF_SESSION_KEY] = "token_valid_123"
            res = client.post(
                "/api/poetry/like",
                headers={"X-CSRF-Token": ""},
                json={"poem_id": "poem_01", "action": "like"}
            )
            self.assertEqual(res.status_code, 403)

    def test_post_like_valid_session_xc_csrf_token_header_passes_200(self):
        """支持 X-CSRFToken 请求头形式 (200)"""
        with self.app.test_client() as client:
            with client.session_transaction() as sess:
                sess[CSRF_SESSION_KEY] = "token_valid_xc"
            res = client.post(
                "/api/poetry/like",
                headers={"X-CSRFToken": "token_valid_xc"},
                json={"poem_id": "poem_01", "action": "like"}
            )
            self.assertEqual(res.status_code, 200)

    def test_post_excerpt_like_csrf_enforcement(self):
        """词句圈点接口对有效、缺失、伪造 Token 的完整安全校验"""
        with self.app.test_client() as client:
            with client.session_transaction() as sess:
                sess[CSRF_SESSION_KEY] = "token_valid_123"

            res_valid = client.post(
                "/api/poetry/excerpt_like",
                headers={"X-CSRF-Token": "token_valid_123"},
                json={"poem_id": "poem_01", "text": "柳垂江上影，梅谢雪中枝。", "action": "like"}
            )
            self.assertEqual(res_valid.status_code, 200)

            res_missing = client.post(
                "/api/poetry/excerpt_like",
                json={"poem_id": "poem_01", "text": "柳垂江上影，梅谢雪中枝。", "action": "like"}
            )
            self.assertEqual(res_missing.status_code, 403)

            res_forged = client.post(
                "/api/poetry/excerpt_like",
                headers={"X-CSRF-Token": "token_forged_999"},
                json={"poem_id": "poem_01", "text": "柳垂江上影，梅谢雪中枝。", "action": "like"}
            )
            self.assertEqual(res_forged.status_code, 403)

    def test_post_interaction_csrf_enforcement(self):
        """翻卡交互流水接口对有效、缺失、伪造 Token 的完整安全校验"""
        with self.app.test_client() as client:
            with client.session_transaction() as sess:
                sess[CSRF_SESSION_KEY] = "token_valid_123"

            res_valid = client.post(
                "/api/poetry/interaction",
                headers={"X-CSRF-Token": "token_valid_123"},
                json={"poem_id": "poem_01", "action": "flip"}
            )
            self.assertEqual(res_valid.status_code, 200)

            res_missing = client.post(
                "/api/poetry/interaction",
                json={"poem_id": "poem_01", "action": "flip"}
            )
            self.assertEqual(res_missing.status_code, 403)

            res_forged = client.post(
                "/api/poetry/interaction",
                headers={"X-CSRF-Token": "token_forged_999"},
                json={"poem_id": "poem_01", "action": "flip"}
            )
            self.assertEqual(res_forged.status_code, 403)

    def test_post_routes_without_session_allow_headless_requests(self):
        """无 Session 状态下的纯 API 请求允许直接放行"""
        with self.app.test_client() as client:
            res = client.post(
                "/api/poetry/like",
                json={"poem_id": "poem_01", "action": "like"}
            )
            self.assertEqual(res.status_code, 200)


class TestPoetryConcurrencyAndErrorIsolation(unittest.TestCase):
    """维度 8：并发读写争用、退避重试与假性损坏防御测试"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.user_data_path = Path(self.temp_dir.name) / "poetry_user_data.json"
        self.lock_path = Path(self.temp_dir.name) / "poetry_user_data.json.lock"
        self.manager = PoetryManager(
            poems_path=str(REAL_POEMS_PATH),
            user_data_path=str(self.user_data_path),
            lock_path=str(self.lock_path)
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_transient_os_error_never_creates_corrupt_backup(self):
        """[关键防御] 遭遇暂态 PermissionError 时，原文件必须完好保留，严禁误挪为 .corrupt"""
        initial_data = {
            "version": 1,
            "liked_poem_ids": ["poem_01", "poem_02"],
            "liked_excerpts": [],
            "tag_weights": {"清丽婉约": 4.0},
            "interaction_history": []
        }
        save_user_data(initial_data, user_data_path=str(self.user_data_path))
        self.assertTrue(self.user_data_path.exists())

        orig_open = open
        def mock_open_err(*args, **kwargs):
            if str(args[0]) == str(self.user_data_path) and "r" in args[1]:
                raise PermissionError(13, "Permission denied (simulated lock conflict)")
            return orig_open(*args, **kwargs)

        with patch("builtins.open", side_effect=mock_open_err):
            data = load_user_data(str(self.user_data_path))
            self.assertEqual(data["liked_poem_ids"], [])

        self.assertTrue(self.user_data_path.exists(), "原健康数据文件被意外移走！")
        corrupt_files = list(Path(self.temp_dir.name).glob("*.corrupt.*"))
        self.assertEqual(len(corrupt_files), 0, "不应生成任何 .corrupt 备份文件")

        recovered = load_user_data(str(self.user_data_path))
        self.assertEqual(recovered["liked_poem_ids"], ["poem_01", "poem_02"])
        self.assertEqual(recovered["tag_weights"]["清丽婉约"], 4.0)

    def test_real_json_decode_error_still_moves_to_corrupt(self):
        """真正的 JSON 反序列化损坏时，仍应安全隔离为 .corrupt.<timestamp> 并返回空结构"""
        with open(self.user_data_path, "w", encoding="utf-8") as f:
            f.write("<<< INVALID BROKEN JSON DATA >>>")

        data = load_user_data(str(self.user_data_path))
        self.assertEqual(data["liked_poem_ids"], [])

        corrupt_files = list(Path(self.temp_dir.name).glob("*.corrupt.*"))
        self.assertEqual(len(corrupt_files), 1, "真正损坏的 JSON 文件应该被重命名备份")

    def test_os_replace_backoff_retry_succeeds_after_transient_failure(self):
        """验证 save_user_data 在前两次遇到 Windows 句柄冲突后，通过重试退避最终成功落盘"""
        calls = {"count": 0}
        orig_replace = os.replace

        def flaky_replace(src, dst):
            if "poetry_user_data.json" in dst and calls["count"] < 2:
                calls["count"] += 1
                raise PermissionError(5, "拒绝访问 (Simulated Windows lock)")
            return orig_replace(src, dst)

        data = {
            "version": 1,
            "liked_poem_ids": ["poem_05"],
            "liked_excerpts": [],
            "tag_weights": {},
            "interaction_history": []
        }
        with patch("os.replace", side_effect=flaky_replace):
            save_user_data(data, user_data_path=str(self.user_data_path))

        self.assertEqual(calls["count"], 2)
        saved = load_user_data(str(self.user_data_path))
        self.assertEqual(saved["liked_poem_ids"], ["poem_05"])

    def test_concurrent_reader_writer_contention_no_permission_error(self):
        """高频并发读写争用下，系统无崩溃且无 PermissionError 抛出"""
        all_poems = self.manager.get_all_poems()
        self.manager.record_poem_like("poem_01", "like")

        stop_event = threading.Event()
        reader_errors = []
        writer_errors = []

        def reader_worker():
            while not stop_event.is_set():
                try:
                    prefs = self.manager.get_user_preferences()
                    probs = self.manager.compute_recommendation_probabilities()
                    self.assertGreater(len(probs), 0)
                except Exception as e:
                    reader_errors.append(e)
                time.sleep(0.005)

        def writer_worker():
            for i in range(15):
                try:
                    p = all_poems[i % len(all_poems)]
                    action = "like" if i % 2 == 0 else "unlike"
                    self.manager.record_poem_like(p["id"], action)
                except Exception as e:
                    writer_errors.append(e)
                time.sleep(0.005)

        r_threads = [threading.Thread(target=reader_worker) for _ in range(4)]
        w_threads = [threading.Thread(target=writer_worker) for _ in range(2)]

        for t in r_threads + w_threads:
            t.start()

        for t in w_threads:
            t.join()

        stop_event.set()
        for t in r_threads:
            t.join(timeout=1.0)

        self.assertEqual(len(writer_errors), 0, f"写入线程发生错误: {writer_errors}")
        self.assertEqual(len(reader_errors), 0, f"读取线程发生错误: {reader_errors}")


class TestPoetryTemplateAndIntegration(unittest.TestCase):
    """维度 6：诗词前台模板渲染、组件嵌入及 CSRF 交互集成测试"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.user_data_path = Path(self.temp_dir.name) / "poetry_user_data.json"
        self.lock_path = Path(self.temp_dir.name) / ".poetry_user_data.lock"

        self.env_patch = patch.dict(os.environ, {
            "BLOG_USER_DATA_PATH": str(self.user_data_path),
            "BLOG_SECRET_KEY": "test-secret-key-poetry-template",
            "BLOG_ENV": "development",
        })
        self.env_patch.start()

        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def tearDown(self):
        self.env_patch.stop()
        self.temp_dir.cleanup()

    def test_daily_poem_selection_stability(self):
        """测试 get_daily_poem 函数稳定输出且数据完整"""
        daily_1 = get_daily_poem()
        daily_2 = get_daily_poem()
        self.assertIsNotNone(daily_1)
        self.assertEqual(daily_1["id"], daily_2["id"])
        self.assertIn("title", daily_1)
        self.assertIn("author", daily_1)
        self.assertIn("content", daily_1)
        self.assertIn("highlight", daily_1)
        self.assertIn("tags", daily_1)

    def test_poetry_hall_route_returns_200_and_renders_full_ui(self):
        """测试 /poetry 诗斋大厅正常渲染全套 UI 与核心组件"""
        response = self.client.get("/poetry")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)

        # 校验页面结构与标题
        self.assertIn("诗斋", html)
        self.assertIn("澄澈如水洗 · 诗斋沉浸大厅", html)
        self.assertIn("poetry.css", html)
        self.assertIn("poetry.js", html)
        self.assertIn('name="csrf-token"', html)

        # 校验四维正交标签
        self.assertIn("朝代维度", html)
        self.assertIn("风格维度", html)
        self.assertIn("心境氛围", html)
        self.assertIn("意象物候", html)

        # 校验核心卡片与舞台
        self.assertIn("immersiveCardInner", html)
        self.assertIn("知己微评", html)
        self.assertIn("全篇精排赏析", html)

        # 校验操作栏
        self.assertIn("btnSwitchPoem", html)
        self.assertIn("btnImmLike", html)
        self.assertIn("btnFlipCard", html)
        self.assertIn("btnToggleDrawer", html)

        # 校验偏好雷达与看板
        self.assertIn("radarChartContainer", html)
        self.assertIn("实时审美偏好沉淀看板", html)
        self.assertIn("收敛指数", html)
        self.assertIn("审美藏阁", html)

        # 校验划词圈点浮标
        self.assertIn("excerptPopover", html)
        self.assertIn("btnPopoverExcerptLike", html)

    def test_index_page_includes_sidebar_poetry_card(self):
        """测试首页侧边栏成功嵌入每日诗词便笺卡"""
        fake_blogs = [
            {
                "title": "测试文章",
                "year": "2026",
                "month": "11",
                "html_title": "test-blog",
                "content": "测试正文",
                "date": "2026-11-12",
                "category": "随笔"
            }
        ]
        with patch("app.routes.dbHelper.get_recent_blogs", return_value=fake_blogs), \
             patch("app.routes.dbHelper.get_all_categories", return_value=[{"name": "随笔", "num": 1}]), \
             patch("app.routes.dbHelper.get_all_date", return_value=[{"year": "2026", "month": "11", "num": 1}]):
            response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)

        # 校验侧边栏卡片存在
        self.assertIn("sidebarPoetryCard", html)
        self.assertIn("今日素笺 · 雅集", html)
        self.assertIn("sidebarCardInner", html)
        self.assertIn("sidebarQuote", html)
        self.assertIn("sidebarAuthor", html)
        self.assertIn("sidebarLikeBtn", html)
        self.assertIn("sidebarFlipBtn", html)
        self.assertIn("poetry.css", html)
        self.assertIn("poetry.js", html)

        # 校验移动端快捷入口
        self.assertIn("诗斋", html)

    def test_site_header_contains_poetry_nav_link(self):
        """测试全站顶栏导航具备每日诗词快速链接"""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("/poetry", html)
        self.assertIn("每日诗词", html)

    def test_csrf_token_propagation_in_poetry_post_requests(self):
        """测试诗词点赞与词句圈点 API 严格执行 CSRF 校验"""
        with self.client.session_transaction() as sess:
            sess[CSRF_SESSION_KEY] = "valid-csrf-token-12345"

        # 1. 无 CSRF Token 发起整篇点赞 -> 403 拒绝
        resp_no_csrf = self.client.post(
            "/api/poetry/like",
            json={"poem_id": "poem_01", "action": "like"}
        )
        self.assertEqual(resp_no_csrf.status_code, 403)

        # 2. 携带有效 CSRF Token 发起整篇点赞 -> 200 成功
        resp_with_csrf = self.client.post(
            "/api/poetry/like",
            headers={"X-CSRFToken": "valid-csrf-token-12345"},
            json={"poem_id": "poem_01", "action": "like"}
        )
        self.assertEqual(resp_with_csrf.status_code, 200)
        data = resp_with_csrf.get_json()
        self.assertEqual(data.get("status"), "success")
        self.assertTrue(data.get("liked"))

        # 3. 携带有效 CSRF Token 发起词句圈点 -> 200 成功
        resp_excerpt = self.client.post(
            "/api/poetry/excerpt_like",
            headers={"X-CSRFToken": "valid-csrf-token-12345"},
            json={
                "poem_id": "poem_01",
                "text": "东溪春近好同归",
                "action": "like"
            }
        )
        self.assertEqual(resp_excerpt.status_code, 200)
        excerpt_data = resp_excerpt.get_json()
        self.assertEqual(excerpt_data.get("status"), "success")
        self.assertTrue(excerpt_data.get("liked"))


if __name__ == "__main__":
    unittest.main()
