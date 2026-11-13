import re
import unicodedata


_FENCED_CODE_BLOCK_RE = re.compile(r"(?m)^[ \t]*(?:```|~~~)")
_FENCED_CODE_LINE_RE = re.compile(r"(?m)^[ \t]*(?:```|~~~).*$")
_HTML_COMMENT_RE = re.compile(r"<!--[\s\S]*?-->")
_HTML_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>[\s\S]*?</\1>", re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"</?[a-zA-Z][a-zA-Z0-9:-]*(?:\s+[^<>]*)?/?>")
_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_INLINE_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_REFERENCE_DEF_RE = re.compile(r"^\s*\[[^\]]+\]:\s+\S+.*$")
_HEADING_PREFIX_RE = re.compile(r"^[ \t]*#{1,6}[ \t]*")
_BLOCKQUOTE_PREFIX_RE = re.compile(r"^[ \t]*(?:>[ \t]*)+")
_UNORDERED_LIST_PREFIX_RE = re.compile(r"^[ \t]*[-*+][ \t]+")
_ORDERED_LIST_PREFIX_RE = re.compile(r"^[ \t]*\d+\.[ \t]+")
_HORIZONTAL_RULE_RE = re.compile(r"^\s*([-*_])(?:\s*\1){2,}\s*$")
_TABLE_SEPARATOR_RE = re.compile(
    r"^\s*(?:\|\s*:?-{2,}:?\s*\|\s*|\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)+\|?\s*)$"
)
_INLINE_CODE_RE = re.compile(r"`([^`]*)`")
_BOLD_ASTERISK_RE = re.compile(r"\*\*(.+?)\*\*")
_BOLD_UNDERSCORE_RE = re.compile(r"__(.+?)__")
_STRIKE_RE = re.compile(r"~~(.+?)~~")
_ITALIC_ASTERISK_RE = re.compile(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)")
_DATE_RE = re.compile(r"^\s*(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\s*$")
_TIME_RE = re.compile(r"^\s*(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?\s*$")


def _get_field(blog, key, default=None):
    if isinstance(blog, dict):
        return blog.get(key, default)
    return getattr(blog, key, default)


def _strip_punctuation_and_whitespace(text):
    return "".join(
        ch
        for ch in text
        if not ch.isspace() and not unicodedata.category(ch).startswith(("P", "Z"))
    )


def _clean_markdown_lines(content):
    text = (content or "").replace("\r\n", "\n").replace("\r", "\n")
    has_code_block = bool(_FENCED_CODE_BLOCK_RE.search(text))

    text = _FENCED_CODE_LINE_RE.sub("", text)
    text = _HTML_COMMENT_RE.sub("", text)
    text = _HTML_SCRIPT_STYLE_RE.sub("", text)
    text = _HTML_TAG_RE.sub("", text)
    text = _IMAGE_RE.sub("", text)

    clean_lines = []
    for raw_line in text.split("\n"):
        if _REFERENCE_DEF_RE.match(raw_line):
            continue
        if _HORIZONTAL_RULE_RE.match(raw_line):
            continue
        if _TABLE_SEPARATOR_RE.match(raw_line):
            continue

        line = raw_line
        line = _BLOCKQUOTE_PREFIX_RE.sub("", line)
        line = _HEADING_PREFIX_RE.sub("", line)
        line = _UNORDERED_LIST_PREFIX_RE.sub("", line)
        line = _ORDERED_LIST_PREFIX_RE.sub("", line)
        line = _INLINE_LINK_RE.sub(r"\1", line)
        line = _INLINE_CODE_RE.sub(r"\1", line)
        line = _BOLD_ASTERISK_RE.sub(r"\1", line)
        line = _BOLD_UNDERSCORE_RE.sub(r"\1", line)
        line = _STRIKE_RE.sub(r"\1", line)
        line = _ITALIC_ASTERISK_RE.sub(r"\1", line)
        line = line.strip()
        if line:
            clean_lines.append(line)

    return clean_lines, has_code_block


def is_verse_lines(clean_lines, has_code_block=False):
    if has_code_block or not (1 <= len(clean_lines) <= 12):
        return False
    return all(len(_strip_punctuation_and_whitespace(line)) <= 28 for line in clean_lines)


def analyze_blog_content(content, max_prose_chars=170, max_verse_lines=6):
    """提取安全摘要、诗词判定及正文字数统计。"""
    clean_lines, has_code_block = _clean_markdown_lines(content)
    is_verse = is_verse_lines(clean_lines, has_code_block=has_code_block)
    word_count = sum(len(re.sub(r"\s+", "", line)) for line in clean_lines)

    if not clean_lines:
        excerpt = ""
    elif is_verse:
        excerpt = "\n".join(clean_lines[:max_verse_lines])
    else:
        prose = re.sub(r"\s+", " ", " ".join(clean_lines)).strip()
        if len(prose) <= max_prose_chars:
            excerpt = prose
        else:
            excerpt = prose[:max_prose_chars].rstrip() + "…"

    return {
        "excerpt": excerpt,
        "is_verse": is_verse,
        "word_count": word_count,
    }


def format_blog_dates(blog):
    """规范化博客日期显示字段：display_date, short_md, year_str。"""
    raw_date = str(_get_field(blog, "date", "") or "").strip()
    match = _DATE_RE.match(raw_date)
    if match:
        year_num, month_num, day_num = int(match.group(1)), int(match.group(2)), int(match.group(3))
        return {
            "display_date": f"{year_num:04d} 年 {month_num:02d} 月 {day_num:02d} 日",
            "short_md": f"{month_num:02d}.{day_num:02d}",
            "year_str": f"{year_num:04d}",
        }

    year_val = str(_get_field(blog, "year", "") or "").strip()
    month_val = str(_get_field(blog, "month", "") or "").strip()
    year_str = year_val.zfill(4) if year_val.isdigit() else year_val
    short_md = month_val.zfill(2) if month_val.isdigit() else ""
    display_date = raw_date or (
        f"{year_str} 年 {short_md} 月" if year_str and short_md else year_str
    )
    return {
        "display_date": display_date,
        "short_md": short_md,
        "year_str": year_str,
    }


def enrich_blog_entry(blog):
    """为单篇博客挂载 excerpt / is_verse / word_count / 日期展示字段。"""
    if blog is None:
        return None

    content = _get_field(blog, "content", "") or ""
    metadata = analyze_blog_content(content)
    metadata.update(format_blog_dates(blog))

    if isinstance(blog, dict):
        enriched = dict(blog)
        enriched.update(metadata)
        return enriched

    for key, value in metadata.items():
        setattr(blog, key, value)
    return blog


def enrich_blog_list(blogs):
    """为博客列表中的每一项挂载派生元数据，返回新列表以保留原接口兼容性。"""
    return [enrich_blog_entry(blog) for blog in (blogs or [])]


def blog_sort_key(blog, fallback_index=0):
    """生成用于全局时间顺序排序的键（由旧到新）。"""
    raw_date = str(_get_field(blog, "date", "") or "").strip()
    date_match = _DATE_RE.match(raw_date)
    if date_match:
        date_tuple = (int(date_match.group(1)), int(date_match.group(2)), int(date_match.group(3)))
    else:
        raw_year = str(_get_field(blog, "year", "") or "").strip()
        raw_month = str(_get_field(blog, "month", "") or "").strip()
        year_num = int(raw_year) if raw_year.isdigit() else 0
        month_num = int(raw_month) if raw_month.isdigit() else 0
        date_tuple = (year_num, month_num, 0)

    raw_time = str(_get_field(blog, "time", "") or "").strip()
    time_match = _TIME_RE.match(raw_time)
    if time_match:
        time_tuple = (
            int(time_match.group(1)),
            int(time_match.group(2)),
            int(time_match.group(3) or 0),
        )
    else:
        time_tuple = (0, 0, 0)

    return (date_tuple, time_tuple, fallback_index)
