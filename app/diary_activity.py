"""Read-only calendar statistics derived from saved diary entries."""

import calendar
from datetime import date, timedelta


WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

# Well-known works, ordered by the approximate character count of a common
# edition. The diary's yearly total is compared against this ladder.
WORD_MILESTONES = (
    ("狂人日记", 4_700),
    ("道德经", 5_200),
    ("论语", 16_000),
    ("阿Q正传", 21_000),
    ("倾城之恋", 30_000),
    ("边城", 60_000),
    ("呐喊", 70_000),
    ("呼兰河传", 100_000),
    ("骆驼祥子", 110_000),
    ("活着", 120_000),
    ("三体", 190_000),
    ("围城", 250_000),
    ("聊斋志异", 400_000),
    ("白鹿原", 500_000),
    ("三国演义", 640_000),
    ("红楼梦", 730_000),
    ("西游记", 820_000),
    ("水浒传", 960_000),
    ("平凡的世界", 1_040_000),
)


def diary_activity_counts(diaries, today):
    counts = {}
    for diary in diaries:
        try:
            day = date.fromisoformat(diary.entry_date)
        except (TypeError, ValueError):
            continue
        if day > today or day.isoformat() != diary.entry_date:
            continue
        content = diary.content if isinstance(diary.content, str) else ""
        count = sum(not char.isspace() for char in content)
        if count:
            # A legacy duplicate must never turn one day into two check-ins.
            counts[day] = max(counts.get(day, 0), count)
    return counts


def activity_summary(counts, year, today):
    streak = 0
    cursor = today if today in counts else today - timedelta(days=1)
    while cursor in counts:
        streak += 1
        if cursor == date.min:
            break
        cursor -= timedelta(days=1)
    return {
        "year": year,
        "recorded_days": sum(day.year == year for day in counts),
        "current_streak": streak,
        "today_recorded": today in counts,
    }


def activity_level(count):
    return 0 if not count else 1 + sum(count >= n for n in (200, 500, 1000))


def _day_entry(day, counts, today):
    count = counts.get(day, 0)
    future = day > today
    state = "尚未到来" if future else (f"已记录 {count} 字" if count else "尚未记录")
    return {
        "date": day.isoformat(),
        "day": day.day,
        "label": f"{day.year}年{day.month}月{day.day}日 {WEEKDAYS[day.weekday()]}，{state}",
        "count": count,
        "level": activity_level(count),
        "today": day == today,
        "future": future,
    }


def build_activity_calendar(counts, year, today):
    if not 1 <= year <= today.year:
        raise ValueError("Year is outside the diary calendar range.")
    first = date(year, 1, 1)
    last = date(year, 12, 31)
    start = first - timedelta(days=first.weekday())
    weeks = ((last - start).days + 7) // 7
    days = []
    for offset in range(weeks * 7):
        day = start + timedelta(days=offset)
        if day.year != year:
            days.append(None)
            continue
        days.append(_day_entry(day, counts, today))
    return {
        **activity_summary(counts, year, today),
        "today": today.isoformat(),
        "min_year": min([year, today.year] + [day.year for day in counts]),
        "max_year": today.year,
        "weeks": weeks,
        "months": [
            {"label": f"{month}月", "column": (date(year, month, 1) - start).days // 7}
            for month in range(1, 13)
        ],
        "days": days,
        "overview": build_year_overview(counts, year, today),
        "char_total": year_char_total(counts, year),
    }


def build_month_calendar(counts, year, month, today):
    """One month as Monday-first weeks; padding cells are None."""
    first = date(year, month, 1)
    if first > today.replace(day=1):
        raise ValueError("Month is in the future.")
    days_in_month = calendar.monthrange(year, month)[1]
    weeks = []
    week = [None] * first.weekday()
    for day_number in range(1, days_in_month + 1):
        week.append(_day_entry(date(year, month, day_number), counts, today))
        if len(week) == 7:
            weeks.append(week)
            week = []
    if week:
        week.extend([None] * (7 - len(week)))
        weeks.append(week)
    return {
        "year": year,
        "month": month,
        "value": f"{year:04d}-{month:02d}",
        "recorded_days": sum(1 for day in counts if (day.year, day.month) == (year, month)),
        "weeks": [
            {"days": days, "current": any(day and day["today"] for day in days)}
            for days in weeks
        ],
    }


def build_year_overview(counts, year, today):
    """Twelve compact months for the year view; each cell only carries a level."""
    months = []
    for month in range(1, 13):
        first = date(year, month, 1)
        cells = [None] * first.weekday()
        recorded = 0
        for day_number in range(1, calendar.monthrange(year, month)[1] + 1):
            day = date(year, month, day_number)
            count = counts.get(day, 0)
            if count:
                recorded += 1
            cells.append({
                "date": day.isoformat(),
                "level": activity_level(count),
                "today": day == today,
                "future": day > today,
            })
        months.append({
            "month": month,
            "label": f"{month}月",
            "value": f"{year:04d}-{month:02d}",
            "recorded_days": recorded,
            "future": first > today,
            "cells": cells,
        })
    return months


def year_char_total(counts, year):
    return sum(count for day, count in counts.items() if day.year == year)


def format_char_count(total):
    """Return (number, unit) so templates can size the two parts differently."""
    if total >= 10_000:
        number = f"{total / 10_000:.1f}"
        if number.endswith(".0"):
            number = number[:-2]
        return number, "万字"
    return f"{total:,}", "字"


def word_milestone(total, milestones=WORD_MILESTONES):
    """Compare a character total against the milestone ladder."""
    passed = [work for work in milestones if total >= work[1]]
    upcoming = [work for work in milestones if total < work[1]]
    last = passed[-1] if passed else None
    following = upcoming[0] if upcoming else None
    base = last[1] if last else 0
    if following:
        progress = (total - base) / (following[1] - base)
    else:
        progress = 1.0
    number, unit = format_char_count(total)
    remaining = following[1] - total if following else 0
    remaining_number, remaining_unit = format_char_count(remaining)
    return {
        "total": total,
        "total_number": number,
        "total_unit": unit,
        "passed_count": len(passed),
        "last_title": last[0] if last else None,
        "ratio": (round(total / last[1], 1) if last else None),
        "next_title": following[0] if following else None,
        "remaining": remaining,
        "remaining_text": f"{remaining_number} {remaining_unit}" if following else "",
        "progress": max(0.0, min(1.0, progress)),
        "percent": int(round(max(0.0, min(1.0, progress)) * 100)),
    }
