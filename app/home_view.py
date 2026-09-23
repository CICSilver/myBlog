"""首页展示用的纯函数：摘要、诗词识别、中文数字、岁时图。"""
import re
from datetime import date

READING_CHARS_PER_MINUTE = 400
VERSE_MAX_LINES = 16
VERSE_MAX_LINE_CHARS = 24
VERSE_MAX_TOTAL_CHARS = 260

_CN_DIGITS = "〇一二三四五六七八九"
_CN_MONTHS = ("一", "二", "三", "四", "五", "六", "七", "八", "九", "十", "十一", "十二")

_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_HR_RE = re.compile(r"^\s*([-*_=])(\s*\1){2,}\s*$")
_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s*")
_QUOTE_RE = re.compile(r"^\s{0,3}>\s?")
_LIST_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_EMPHASIS_RE = re.compile(r"(\*\*|__|\*|~~|`)")
_MARKUP_HINT_RE = re.compile(r"(```|~~~|!\[|\]\(|^\s{0,3}#|^\s*(?:[-*+]|\d+[.)])\s+|<[a-zA-Z/])", re.M)
_LEADING_SPACE_RE = re.compile(r"^[\s　]+")


def cn_year(year):
    """2026 -> 二〇二六"""
    return "".join(_CN_DIGITS[int(ch)] for ch in str(year) if ch.isdigit())


def cn_month(month):
    """7 -> 七月"""
    return _CN_MONTHS[int(month) - 1] + "月"


def cn_number(value):
    """0-99 的中文数字：12 -> 十二，20 -> 二十。"""
    value = int(value)
    if value < 10:
        return _CN_DIGITS[value]
    tens, ones = divmod(value, 10)
    head = "" if tens == 1 else _CN_DIGITS[tens]
    return head + "十" + (_CN_DIGITS[ones] if ones else "")


def cn_date(value):
    """2026-07-31 -> 二〇二六年七月三十一日；无法解析时原样返回。"""
    parsed = _parse_date(value)
    if not parsed:
        return str(value or "")
    return "{0}年{1}{2}日".format(cn_year(parsed.year), cn_month(parsed.month), cn_number(parsed.day))


def plain_lines(markdown_text):
    """把 Markdown 粗略转换成纯文本行，保留空行作为段落分隔。"""
    text = (markdown_text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = []
    in_fence = False
    for raw in text.split("\n"):
        if _FENCE_RE.match(raw):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if _HR_RE.match(raw):
            lines.append("")
            continue
        line = _IMAGE_RE.sub("", raw)
        line = _LINK_RE.sub(r"\1", line)
        line = _HTML_TAG_RE.sub("", line)
        line = _HEADING_RE.sub("", line)
        line = _QUOTE_RE.sub("", line)
        line = _LIST_RE.sub("", line)
        line = _EMPHASIS_RE.sub("", line)
        line = _LEADING_SPACE_RE.sub("", line).rstrip()
        lines.append(line)
    return lines


def char_count(markdown_text):
    return sum(len(re.sub(r"\s", "", line)) for line in plain_lines(markdown_text))


def verse_lines(markdown_text):
    """短句分行、没有 Markdown 结构的内容视为诗词，返回各行；否则返回空列表。"""
    source = markdown_text or ""
    if _MARKUP_HINT_RE.search(source):
        return []
    lines = [line for line in plain_lines(source) if line]
    if not 2 <= len(lines) <= VERSE_MAX_LINES:
        return []
    if any(len(line) > VERSE_MAX_LINE_CHARS for line in lines):
        return []
    if sum(len(line) for line in lines) > VERSE_MAX_TOTAL_CHARS:
        return []
    return lines


def excerpt_paragraphs(markdown_text, limit):
    """截取约 limit 个字符的段落列表，末段超出时以省略号结尾。"""
    result = []
    remaining = limit
    for paragraph in (line for line in plain_lines(markdown_text) if line):
        if remaining <= 0:
            break
        if len(paragraph) > remaining:
            result.append(paragraph[:remaining].rstrip("，、；：,;: ") + "……")
            break
        result.append(paragraph)
        remaining -= len(paragraph)
    return result


def _parse_date(value):
    try:
        year, month, day = (int(part) for part in str(value).split("-")[:3])
        return date(year, month, day)
    except (TypeError, ValueError):
        return None


def build_entry(blog, excerpt_limit):
    """为模板补充展示字段，不修改原始 blog。"""
    entry = dict(blog)
    content = blog.get("content") or ""
    parsed = _parse_date(blog.get("date"))
    count = char_count(content)
    lines = verse_lines(content)

    entry["char_count"] = count
    entry["read_minutes"] = max(1, round(count / READING_CHARS_PER_MINUTE))
    entry["is_verse"] = bool(lines)
    entry["verse_lines"] = lines
    entry["verse_chars"] = max([len(line) for line in lines] + [len(blog.get("title") or "")]) if lines else 0
    entry["excerpt"] = [] if lines else excerpt_paragraphs(content, excerpt_limit)
    entry["day_label"] = parsed.strftime("%m.%d") if parsed else ""
    entry["year_label"] = str(parsed.year) if parsed else str(blog.get("year", ""))
    entry["month_key"] = (parsed.year, parsed.month) if parsed else None
    entry["month_label"] = "{0}年{1}".format(cn_year(parsed.year), cn_month(parsed.month)) if parsed else ""
    entry["weekday"] = "一二三四五六日"[parsed.weekday()] if parsed else ""
    return entry


def build_entries(blogs, featured_limit=240, stream_limit=110):
    entries = []
    previous_month = None
    for index, blog in enumerate(blogs):
        entry = build_entry(blog, featured_limit if index == 0 else stream_limit)
        entry["starts_month"] = entry["month_key"] is not None and entry["month_key"] != previous_month
        previous_month = entry["month_key"]
        entries.append(entry)
    return entries


def archive_stats(all_blogs):
    dates = [d for d in (_parse_date(blog.get("date")) for blog in all_blogs) if d]
    first = min(dates) if dates else None
    return {
        "count": len(all_blogs),
        "chars": sum(char_count(blog.get("content")) for blog in all_blogs),
        "since": first.strftime("%Y.%m") if first else "",
    }


def archive_calendar(all_blogs, active_year=None, active_month=None):
    """按年排列 12 个月的篇数，供首页“岁时图”使用，最新年份在前。"""
    counts = {}
    for blog in all_blogs:
        parsed = _parse_date(blog.get("date"))
        if parsed:
            counts[(parsed.year, parsed.month)] = counts.get((parsed.year, parsed.month), 0) + 1
    if not counts:
        return []

    peak = max(counts.values())
    years = sorted({year for year, _ in counts}, reverse=True)
    calendar = []
    for year in years:
        months = []
        for month in range(1, 13):
            num = counts.get((year, month), 0)
            months.append({
                "year": str(year),
                "month": str(month),
                "label": _CN_MONTHS[month - 1],
                "num": num,
                "level": 0 if not num else min(4, 1 + (num * 3) // peak),
                "active": str(year) == str(active_year) and str(month) == str(active_month),
            })
        calendar.append({
            "year": str(year),
            "year_cn": cn_year(year),
            "total": sum(item["num"] for item in months),
            "months": months,
        })
    return calendar
