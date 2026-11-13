"""
app/poetry.py: 诗词数据加载、服务端用户偏好持久化及 Softmax 推荐采样引擎
"""
import os
import re
import json
import math
import random
import hashlib
import logging
import secrets
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from contextlib import contextmanager

from app.file_lock import file_lock

_thread_local = threading.local()


@contextmanager
def safe_poetry_lock(lpath: str):
    """
    可重入安全文件锁：防止在同一线程内由于嵌套调用（如 record_poem_like 内部调用 save_user_data）
    在 Windows 上对同一个文件发起二次文件描述符加锁导致互斥死锁。
    """
    if not hasattr(_thread_local, "locked_paths"):
        _thread_local.locked_paths = set()

    norm_lpath = os.path.normcase(os.path.abspath(lpath))
    target_dir = os.path.dirname(norm_lpath)
    if target_dir:
        os.makedirs(target_dir, exist_ok=True)

    if norm_lpath in _thread_local.locked_paths:
        yield None
    else:
        _thread_local.locked_paths.add(norm_lpath)
        try:
            with file_lock(lpath) as fd:
                yield fd
        finally:
            _thread_local.locked_paths.discard(norm_lpath)


logger = logging.getLogger(__name__)

# 基础路径常量
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DATASET_PATH = os.path.join(APP_DIR, "data", "poems.json")
DEFAULT_USER_DATA_PATH = os.path.join(APP_DIR, "data", "poetry_user_data.json")
DEFAULT_LOCK_PATH = os.path.join(APP_DIR, "data", ".poetry_user_data.lock")

# 权重增量标尺
WEIGHT_DELTA_POEM_LIKE = 2.0
WEIGHT_DELTA_EXCERPT_LIKE = 1.0

# 推荐算法默认超参数
DEFAULT_GAMMA = 1.5           # 温度缩放系数 (γ=1.5)
DEFAULT_EXPLORATION_RATE = 0.15 # 15% 探索余量
MAX_INTERACTION_HISTORY = 1000  # 历史流水最多保留条数

# 4D 维度系数
DIMENSION_WEIGHTS = {
    "style": 1.2,
    "mood": 1.2,
    "theme": 1.0,
    "dynasty": 0.8
}

# 涵盖所有常见中英文标点、引号、书名号、括号、破折号、省略号及各类全半角空白字符
POETRY_PUNCTUATION_PATTERN = re.compile(
    r"[，。！？、；：\s\u3000\xa0\u200b,.\!?;:\"'“”‘’（）《》〈〉【】〔〕——……—·]"
)

_poems_cache: Dict[str, Any] = {}
_cache_lock = threading.Lock()
_poetry_manager_instance = None


def get_empty_user_data() -> Dict[str, Any]:
    """生成合法的空用户偏好数据结构"""
    return {
        "version": 1,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "liked_poem_ids": [],
        "liked_excerpts": [],
        "tag_weights": {},
        "interaction_history": []
    }


def _is_text_in_poem(text: str, poem: Dict[str, Any]) -> bool:
    """
    校验词句是否属于指定诗词正文。
    先剥离中英文标点与空白字符以验证有效语义字符，
    再依次进行单行精确匹配、完整正文子串匹配与归一化文本子串匹配。
    """
    if not isinstance(text, str):
        return False
    cleaned = text.strip()
    if not cleaned:
        return False

    # 1. 归一化并剥离所有标点与空白符
    norm_cleaned = POETRY_PUNCTUATION_PATTERN.sub("", cleaned)
    if not norm_cleaned:
        # 若清洗后无任何有效语义字符（如单纯选了标点符号或空白），直接拒绝
        return False

    if not isinstance(poem, dict):
        return False

    content_lines = [line.strip() for line in poem.get("content", []) if isinstance(line, str)]
    if not content_lines:
        return False

    # 2. 单行精确匹配
    if cleaned in content_lines:
        return True

    # 3. 完整正文子串匹配（无换行与有换行跨行匹配）
    full_text = "".join(content_lines)
    if cleaned in full_text:
        return True
    full_text_with_newline = "\n".join(content_lines)
    if cleaned in full_text_with_newline:
        return True

    # 4. 剔除标点与空白后的归一化子串匹配
    norm_full = POETRY_PUNCTUATION_PATTERN.sub("", full_text)
    if norm_cleaned in norm_full:
        return True

    return False


def load_poems_dataset(dataset_path: Optional[str] = None) -> Dict[str, Any]:
    """加载 32 首精选诗词数据集（带内存缓存与 mtime 自动失效机制）"""
    global _poems_cache
    path = dataset_path or DEFAULT_DATASET_PATH
    mtime = os.path.getmtime(path) if os.path.exists(path) else 0

    with _cache_lock:
        cached = _poems_cache.get(path)
        if cached and cached.get("mtime") == mtime:
            return cached["data"]

    if not os.path.exists(path):
        logger.warning(f"Poetry dataset not found at {path}")
        return {"total": 0, "version": "1.0", "poems": [], "tags": {}}

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                data = {"total": len(data), "version": "1.0", "poems": data, "tags": {}}
            elif isinstance(data, dict) and "poems" not in data:
                data = {"total": 0, "version": "1.0", "poems": [], "tags": {}}

            with _cache_lock:
                _poems_cache[path] = {"mtime": mtime, "data": data}
            return data
    except Exception as e:
        logger.error(f"Failed to load poetry dataset from {path}: {e}")
        return {"total": 0, "version": "1.0", "poems": [], "tags": {}}


def load_user_data(user_data_path: Optional[str] = None) -> Dict[str, Any]:
    """
    加载服务端持久化偏好数据。
    若文件不存在返回默认空结构；若文件损坏则备份重命名并优雅降级。
    """
    path = user_data_path or DEFAULT_USER_DATA_PATH
    if not os.path.exists(path):
        return get_empty_user_data()

    max_io_retries = 5
    for attempt in range(max_io_retries):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    raise ValueError("User data root must be an object")
                data.setdefault("version", 1)
                data.setdefault("liked_poem_ids", [])
                data.setdefault("liked_excerpts", [])
                data.setdefault("tag_weights", {})
                data.setdefault("interaction_history", [])
                return data
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as e:
            logger.warning(f"Corrupted or invalid user data at {path}: {e}")
            try:
                corrupt_path = f"{path}.corrupt.{int(datetime.now().timestamp())}"
                os.replace(path, corrupt_path)
                logger.info(f"Corrupted user data moved to {corrupt_path}")
            except Exception as rename_err:
                logger.warning(f"Failed to move corrupt data file {path}: {rename_err}")
            return get_empty_user_data()
        except OSError as e:
            if attempt < max_io_retries - 1:
                time.sleep(0.01 * (attempt + 1))
                continue
            logger.error(f"Transient I/O error reading user data at {path} after {max_io_retries} attempts: {e}")
            return get_empty_user_data()

    return get_empty_user_data()


def save_user_data(
    data: Dict[str, Any],
    user_data_path: Optional[str] = None,
    lock_path: Optional[str] = None
) -> None:
    """
    进程安全地将用户偏好数据原子写入磁盘。
    使用 app.file_lock 互斥锁，并在同卷目录下使用临时文件 + flush + fsync + os.replace。
    """
    path = user_data_path or DEFAULT_USER_DATA_PATH
    lpath = lock_path or (path + ".lock")

    target_dir = os.path.dirname(path)
    if target_dir:
        os.makedirs(target_dir, exist_ok=True)

    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    content = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")

    with safe_poetry_lock(lpath):
        unique_suffix = f"{os.getpid()}_{threading.get_ident()}_{uuid.uuid4().hex[:8]}"
        temp_path = path + f".tmp.{unique_suffix}"
        try:
            with open(temp_path, "wb") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())

            max_retries = 8
            for attempt in range(max_retries):
                try:
                    os.replace(temp_path, path)
                    break
                except (PermissionError, OSError) as e:
                    is_sharing_err = isinstance(e, PermissionError) or getattr(e, "winerror", None) in (5, 32)
                    if not is_sharing_err or attempt == max_retries - 1:
                        logger.error(
                            f"Atomic replace failed from {temp_path} to {path} "
                            f"(attempt {attempt + 1}/{max_retries}): {e}"
                        )
                        raise
                    time.sleep(0.015 * (attempt + 1))
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass


def _apply_tag_weight_delta(tag_weights: Dict[str, float], tags: Dict[str, str], delta: float) -> None:
    """增减各标签权重得分，截断于 >= 0.0 并清理非正键"""
    for _, tag_val in tags.items():
        if tag_val and isinstance(tag_val, str):
            k = tag_val.strip()
            cur = float(tag_weights.get(k, 0.0))
            new_v = round(cur + delta, 2)
            if new_v <= 0.0:
                tag_weights.pop(k, None)
            else:
                tag_weights[k] = new_v


def _append_interaction_event(
    data: Dict[str, Any],
    poem_id: str,
    action: str,
    tags: Optional[Dict[str, str]] = None,
    details: Optional[Dict[str, Any]] = None
) -> None:
    """记录用户行为流水，并维持最多 1000 条 FIFO 滚动上限"""
    history = data.setdefault("interaction_history", [])
    now_iso = datetime.now(timezone.utc).isoformat()
    evt_id = f"evt_{int(datetime.now().timestamp() * 1000)}_{len(history) + 1}"

    event = {
        "id": evt_id,
        "poem_id": poem_id,
        "action": action,
        "timestamp": now_iso,
        "tags": tags or {}
    }
    if details:
        event["details"] = details

    history.append(event)
    if len(history) > MAX_INTERACTION_HISTORY:
        del history[:len(history) - MAX_INTERACTION_HISTORY]


class PoetryManager:
    """诗词业务管理类：负责诗词读取、持久化、点赞圈点与推荐概率推演"""

    def __init__(
        self,
        poems_path: Optional[str] = None,
        user_data_path: Optional[str] = None,
        lock_path: Optional[str] = None
    ):
        self.poems_path = str(poems_path) if poems_path else DEFAULT_DATASET_PATH
        self.user_data_path = str(user_data_path) if user_data_path else DEFAULT_USER_DATA_PATH
        self.lock_path = str(lock_path) if lock_path else (self.user_data_path + ".lock")

    def get_dataset(self) -> Dict[str, Any]:
        """获取完整诗词数据集字典"""
        return load_poems_dataset(self.poems_path)

    def get_all_poems(self) -> List[Dict[str, Any]]:
        """获取全部 40 首精选正向诗词列表（严格排除 negative_anchors 负向校准样本）"""
        dataset = self.get_dataset()
        return dataset.get("poems", [])

    def is_text_in_poem(self, poem_id: str, text: str) -> bool:
        """
        校验词句是否属于指定诗词正文。
        内部复用 _is_text_in_poem，未找到诗词或正文不匹配均返回 False。
        """
        poem = self.get_poem_by_id(poem_id)
        if not poem:
            return False
        return _is_text_in_poem(text, poem)

    def get_poem_by_id(self, poem_id: str) -> Optional[Dict[str, Any]]:
        """根据 ID 检索单首诗词"""
        poems = self.get_all_poems()
        return next((p for p in poems if p.get("id") == poem_id), None)

    def get_daily_poem(self) -> Optional[Dict[str, Any]]:
        """根据当天公历日期哈希稳定选取每日一诗，确保全站当天一致且零随机晃动"""
        poems = self.get_all_poems()
        if not poems:
            return None
        today_str = datetime.now().strftime("%Y-%m-%d")
        idx = int(hashlib.md5(today_str.encode("utf-8")).hexdigest(), 16) % len(poems)
        return poems[idx]

    def get_user_preferences(self) -> Dict[str, Any]:
        """读取当前用户偏好与点赞数据"""
        with safe_poetry_lock(self.lock_path):
            data = load_user_data(self.user_data_path)
            return {
                "status": "success",
                "version": data.get("version", 1),
                "liked_poem_ids": list(data.get("liked_poem_ids", [])),
                "liked_excerpts": list(data.get("liked_excerpts", [])),
                "tag_weights": dict(data.get("tag_weights", {})),
                "history_count": len(data.get("interaction_history", []))
            }

    def record_poem_like(
        self,
        poem_id: str,
        action: str,
        tags: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """整首诗词点赞/取消点赞"""
        poem = self.get_poem_by_id(poem_id)
        if poem is None:
            raise ValueError(f"未找到指定的诗词: {poem_id}")

        resolved_tags = tags or poem.get("tags", {})

        with safe_poetry_lock(self.lock_path):
            data = load_user_data(self.user_data_path)
            liked_ids = list(data.get("liked_poem_ids", []))
            tag_weights = data.setdefault("tag_weights", {})
            delta = 0.0

            if action == "like":
                if poem_id not in liked_ids:
                    liked_ids.append(poem_id)
                    delta = WEIGHT_DELTA_POEM_LIKE
            elif action == "unlike":
                if poem_id in liked_ids:
                    liked_ids.remove(poem_id)
                    delta = -WEIGHT_DELTA_POEM_LIKE
            else:
                raise ValueError(f"非法操作类型: {action}")

            data["liked_poem_ids"] = liked_ids

            if delta != 0.0 and resolved_tags:
                _apply_tag_weight_delta(tag_weights, resolved_tags, delta)

            _append_interaction_event(
                data,
                poem_id=poem_id,
                action=action,
                tags=resolved_tags
            )

            save_user_data(data, user_data_path=self.user_data_path, lock_path=self.lock_path)
            is_liked = poem_id in liked_ids
            return {
                "status": "success",
                "poem_id": poem_id,
                "liked": is_liked,
                "updated_tag_weights": dict(tag_weights),
                "message": "诗词已收藏至心动阁" if is_liked else "已取消收藏"
            }

    def toggle_poem_like(
        self,
        poem_id: str,
        action: str,
        tags: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """整首点赞别名接口"""
        return self.record_poem_like(poem_id, action, tags)

    def record_excerpt_like(
        self,
        poem_id: str,
        text: str,
        action: str,
        tags: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """词句朱笔圈点（喜欢/取消喜欢）"""
        poem = self.get_poem_by_id(poem_id)
        if poem is None:
            raise ValueError(f"未找到指定的诗词: {poem_id}")

        cleaned_text = text.strip()
        if not cleaned_text:
            raise ValueError("圈点词句内容不能为空")

        norm_text = POETRY_PUNCTUATION_PATTERN.sub("", cleaned_text)
        if not norm_text:
            raise ValueError("圈点词句不能仅包含标点符号或空白")

        if not _is_text_in_poem(cleaned_text, poem):
            raise ValueError(f"圈点词句与所属诗词内容不匹配: '{cleaned_text}' 不在 {poem_id} 中")

        resolved_tags = tags or poem.get("tags", {})

        with safe_poetry_lock(self.lock_path):
            data = load_user_data(self.user_data_path)
            excerpts = data.setdefault("liked_excerpts", [])
            tag_weights = data.setdefault("tag_weights", {})

            existing_idx = next(
                (i for i, exc in enumerate(excerpts) if exc.get("poem_id") == poem_id and exc.get("text") == cleaned_text),
                -1
            )
            delta = 0.0
            target_excerpt = None

            if action == "like":
                if existing_idx == -1:
                    exc_id = f"excerpt_{int(datetime.now().timestamp())}_{secrets.token_hex(3)}"
                    target_excerpt = {
                        "id": exc_id,
                        "poem_id": poem_id,
                        "poem_title": poem.get("title", ""),
                        "poem_author": poem.get("author", ""),
                        "text": cleaned_text,
                        "tags": resolved_tags,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }
                    excerpts.append(target_excerpt)
                    delta = WEIGHT_DELTA_EXCERPT_LIKE
                else:
                    target_excerpt = excerpts[existing_idx]
            elif action == "unlike":
                if existing_idx != -1:
                    target_excerpt = excerpts.pop(existing_idx)
                    delta = -WEIGHT_DELTA_EXCERPT_LIKE
            else:
                raise ValueError(f"非法操作类型: {action}")

            if delta != 0.0 and resolved_tags:
                _apply_tag_weight_delta(tag_weights, resolved_tags, delta)

            _append_interaction_event(
                data,
                poem_id=poem_id,
                action="excerpt_like" if action == "like" else "excerpt_unlike",
                tags=resolved_tags,
                details={"text": cleaned_text, "excerpt_id": target_excerpt.get("id") if target_excerpt else None}
            )

            save_user_data(data, user_data_path=self.user_data_path, lock_path=self.lock_path)
            is_liked = action == "like" or (existing_idx != -1 and action != "unlike")
            return {
                "status": "success",
                "poem_id": poem_id,
                "liked": is_liked,
                "excerpt": target_excerpt,
                "updated_tag_weights": dict(tag_weights),
                "message": "词句已朱笔圈点藏录" if is_liked else "已取消词句圈点"
            }

    def toggle_excerpt_like(
        self,
        poem_id: str,
        text: str,
        action: str,
        tags: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """词句圈点别名接口"""
        return self.record_excerpt_like(poem_id, text, action, tags)

    def record_interaction(
        self,
        poem_id: str,
        action: str,
        tags: Optional[Dict[str, str]] = None,
        details: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """记录翻卡与浏览行为流水"""
        valid_actions = {
            "view", "flip", "switch", "filter_tag",
            "like", "unlike", "excerpt_like", "excerpt_unlike"
        }
        if action not in valid_actions:
            raise ValueError(f"不支持的交互动作类型: {action}")

        poem = self.get_poem_by_id(poem_id)
        resolved_tags = tags or (poem.get("tags", {}) if poem else {})

        with safe_poetry_lock(self.lock_path):
            data = load_user_data(self.user_data_path)
            _append_interaction_event(
                data,
                poem_id=poem_id,
                action=action,
                tags=resolved_tags,
                details=details
            )
            save_user_data(data, user_data_path=self.user_data_path, lock_path=self.lock_path)
            return {
                "status": "success",
                "recorded": True,
                "action": action,
                "poem_id": poem_id
            }

    def get_interaction_history(self) -> List[Dict[str, Any]]:
        """获取行为流水历史"""
        with safe_poetry_lock(self.lock_path):
            data = load_user_data(self.user_data_path)
            return list(data.get("interaction_history", []))

    def compute_recommendation_probabilities(
        self,
        tag_filter: Optional[Any] = None,
        temperature: float = DEFAULT_GAMMA,
        explore_prob: float = DEFAULT_EXPLORATION_RATE,
        excluded_ids: Optional[List[str]] = None
    ) -> Dict[str, float]:
        """
        计算每首诗词在当前偏好下的抽卡概率分布。
        结合四维标签加权得分、Softmax 温度调节及探索余量，总和严格为 1.0。
        """
        with safe_poetry_lock(self.lock_path):
            all_poems = self.get_all_poems()
            if not all_poems:
                return {}

            # 标签过滤
            candidates = all_poems
            if tag_filter:
                if isinstance(tag_filter, str):
                    candidates = [
                        p for p in all_poems
                        if tag_filter in p.get("tags", {}).values()
                    ]
                elif isinstance(tag_filter, dict):
                    candidates = [
                        p for p in all_poems
                        if all(p.get("tags", {}).get(k) == v for k, v in tag_filter.items())
                    ]
                if not candidates:
                    candidates = all_poems

            excluded_set = set(excluded_ids or [])
            filtered_candidates = [p for p in candidates if p.get("id") not in excluded_set]
            if not filtered_candidates:
                filtered_candidates = candidates

            n = len(filtered_candidates)
            if n == 1:
                return {filtered_candidates[0]["id"]: 1.0}

            user_data = load_user_data(self.user_data_path)
            tag_weights = user_data.get("tag_weights", {})

            # 计算打分
            scores: List[float] = []
            for p in filtered_candidates:
                s = 1.0
                if p.get("is_handwritten"):
                    s += 0.5

                p_tags = p.get("tags", {})
                for dim, coef in DIMENSION_WEIGHTS.items():
                    t_val = p_tags.get(dim)
                    if t_val and t_val in tag_weights:
                        s += coef * float(tag_weights[t_val])

                scores.append(s)

            # Softmax 温度缩放（数值防溢出减最大值）
            gamma = max(0.1, float(temperature))
            scaled_scores = [gamma * s for s in scores]
            max_scaled = max(scaled_scores)
            exp_scores = [math.exp(s - max_scaled) for s in scaled_scores]
            sum_exp = sum(exp_scores)
            if sum_exp <= 0.0:
                sum_exp = 1.0
            softmax_probs = [z / sum_exp for z in exp_scores]

            # 融合探索余量
            eps = max(0.0, min(1.0, float(explore_prob)))
            uniform_p = 1.0 / n
            blended = [
                (1.0 - eps) * p + eps * uniform_p
                for p in softmax_probs
            ]

            total_p = sum(blended)
            normalized = [p / total_p for p in blended]

            return {
                filtered_candidates[i]["id"]: normalized[i]
                for i in range(n)
            }

    def pick_next_poem(
        self,
        poems: Optional[List[Dict[str, Any]]] = None,
        tag_filter: Optional[Any] = None,
        weights: Optional[Dict[str, float]] = None,
        temperature: float = DEFAULT_GAMMA,
        explore_prob: float = DEFAULT_EXPLORATION_RATE,
        excluded_ids: Optional[List[str]] = None
    ) -> Optional[Dict[str, Any]]:
        """基于 Softmax 偏好分布采样下一首诗词"""
        all_poems = poems or self.get_all_poems()
        if not all_poems:
            return None

        probs = self.compute_recommendation_probabilities(
            tag_filter=tag_filter,
            temperature=temperature,
            explore_prob=explore_prob,
            excluded_ids=excluded_ids
        )
        if not probs:
            return random.choice(all_poems)

        poem_ids = list(probs.keys())
        prob_values = list(probs.values())
        selected_id = random.choices(poem_ids, weights=prob_values, k=1)[0]
        return next((p for p in all_poems if p.get("id") == selected_id), all_poems[0])

    def recalculate_tag_weights(self) -> Dict[str, float]:
        """根据当前已有点赞与圈点全量对账重算 tag_weights"""
        poems_by_id = {p["id"]: p for p in self.get_all_poems()}
        with safe_poetry_lock(self.lock_path):
            data = load_user_data(self.user_data_path)
            recomputed: Dict[str, float] = {}

            # 1. 整首点赞 (+2.0)
            for pid in data.get("liked_poem_ids", []):
                poem = poems_by_id.get(pid)
                if poem and "tags" in poem:
                    _apply_tag_weight_delta(recomputed, poem["tags"], WEIGHT_DELTA_POEM_LIKE)

            # 2. 词句圈点 (+1.0)
            for exc in data.get("liked_excerpts", []):
                tags = exc.get("tags")
                if not tags and exc.get("poem_id") in poems_by_id:
                    tags = poems_by_id[exc["poem_id"]].get("tags")
                if tags:
                    _apply_tag_weight_delta(recomputed, tags, WEIGHT_DELTA_EXCERPT_LIKE)

            data["tag_weights"] = recomputed
            save_user_data(data, user_data_path=self.user_data_path, lock_path=self.lock_path)
            return dict(recomputed)


def get_poetry_manager(
    poems_path: Optional[str] = None,
    user_data_path: Optional[str] = None,
    lock_path: Optional[str] = None
) -> PoetryManager:
    """获取 PoetryManager 单例或定制实例"""
    global _poetry_manager_instance

    try:
        from flask import current_app, has_app_context
        if has_app_context() and current_app:
            cfg_user_path = current_app.config.get("POETRY_USER_DATA_PATH")
            cfg_poems_path = current_app.config.get("POETRY_DATASET_PATH")
            if cfg_user_path or cfg_poems_path:
                return PoetryManager(
                    poems_path=poems_path or cfg_poems_path,
                    user_data_path=user_data_path or cfg_user_path,
                    lock_path=lock_path
                )
    except Exception:
        pass

    if _poetry_manager_instance is None or poems_path is not None or user_data_path is not None:
        mgr = PoetryManager(poems_path=poems_path, user_data_path=user_data_path, lock_path=lock_path)
        if poems_path is None and user_data_path is None:
            _poetry_manager_instance = mgr
        return mgr
    return _poetry_manager_instance


# 模块级别对外便捷调用函数
def toggle_poem_like(
    poem_id: str,
    action: str,
    tags: Optional[Dict[str, str]] = None,
    user_data_path: Optional[str] = None,
    lock_path: Optional[str] = None
) -> Dict[str, Any]:
    mgr = get_poetry_manager(user_data_path=user_data_path, lock_path=lock_path)
    return mgr.record_poem_like(poem_id, action, tags)


def record_poem_like(
    poem_id: str,
    action: str,
    tags: Optional[Dict[str, str]] = None,
    user_data_path: Optional[str] = None,
    lock_path: Optional[str] = None
) -> Dict[str, Any]:
    return toggle_poem_like(poem_id, action, tags, user_data_path, lock_path)


def toggle_excerpt_like(
    poem_id: str,
    text: str,
    action: str,
    tags: Optional[Dict[str, str]] = None,
    user_data_path: Optional[str] = None,
    lock_path: Optional[str] = None
) -> Dict[str, Any]:
    mgr = get_poetry_manager(user_data_path=user_data_path, lock_path=lock_path)
    return mgr.record_excerpt_like(poem_id, text, action, tags)


def record_excerpt_like(
    poem_id: str,
    text: str,
    action: str,
    tags: Optional[Dict[str, str]] = None,
    user_data_path: Optional[str] = None,
    lock_path: Optional[str] = None
) -> Dict[str, Any]:
    return toggle_excerpt_like(poem_id, text, action, tags, user_data_path, lock_path)


def record_interaction(
    poem_id: str,
    action: str,
    tags: Optional[Dict[str, str]] = None,
    details: Optional[Dict[str, Any]] = None,
    user_data_path: Optional[str] = None,
    lock_path: Optional[str] = None
) -> Dict[str, Any]:
    mgr = get_poetry_manager(user_data_path=user_data_path, lock_path=lock_path)
    return mgr.record_interaction(poem_id, action, tags, details)


def recalculate_tag_weights(
    user_data: Optional[Dict[str, Any]] = None,
    poems_by_id: Optional[Dict[str, Dict[str, Any]]] = None
) -> Dict[str, float]:
    mgr = get_poetry_manager()
    return mgr.recalculate_tag_weights()


def pick_next_poem(
    poems: Optional[List[Dict[str, Any]]] = None,
    tag_filter: Optional[Any] = None,
    weights: Optional[Dict[str, float]] = None,
    temperature: float = DEFAULT_GAMMA,
    explore_prob: float = DEFAULT_EXPLORATION_RATE,
    excluded_ids: Optional[List[str]] = None
) -> Optional[Dict[str, Any]]:
    mgr = get_poetry_manager()
    return mgr.pick_next_poem(
        poems=poems,
        tag_filter=tag_filter,
        weights=weights,
        temperature=temperature,
        explore_prob=explore_prob,
        excluded_ids=excluded_ids
    )


def compute_recommendation_probabilities(
    tag_filter: Optional[Any] = None,
    temperature: float = DEFAULT_GAMMA,
    explore_prob: float = DEFAULT_EXPLORATION_RATE,
    excluded_ids: Optional[List[str]] = None
) -> Dict[str, float]:
    mgr = get_poetry_manager()
    return mgr.compute_recommendation_probabilities(
        tag_filter=tag_filter,
        temperature=temperature,
        explore_prob=explore_prob,
        excluded_ids=excluded_ids
    )


def get_user_preferences(
    user_data_path: Optional[str] = None,
    lock_path: Optional[str] = None
) -> Dict[str, Any]:
    mgr = get_poetry_manager(user_data_path=user_data_path, lock_path=lock_path)
    return mgr.get_user_preferences()


def get_interaction_history(
    user_data_path: Optional[str] = None,
    lock_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    mgr = get_poetry_manager(user_data_path=user_data_path, lock_path=lock_path)
    return mgr.get_interaction_history()


def is_text_in_poem(
    poem_id: str,
    text: str,
    poems_path: Optional[str] = None
) -> bool:
    mgr = get_poetry_manager(poems_path=poems_path)
    return mgr.is_text_in_poem(poem_id, text)


def get_daily_poem(
    poems_path: Optional[str] = None,
    user_data_path: Optional[str] = None,
    lock_path: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    mgr = get_poetry_manager(poems_path=poems_path, user_data_path=user_data_path, lock_path=lock_path)
    return mgr.get_daily_poem()

