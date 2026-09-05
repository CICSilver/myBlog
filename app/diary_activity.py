"""Read-only calendar statistics derived from saved diary entries."""

from datetime import date, timedelta


WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


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
        count = counts.get(day, 0)
        future = day > today
        state = "尚未到来" if future else (f"已记录 {count} 字" if count else "尚未记录")
        days.append({
            "date": day.isoformat(),
            "label": f"{day.year}年{day.month}月{day.day}日 {WEEKDAYS[day.weekday()]}，{state}",
            "count": count,
            "level": 0 if not count else 1 + sum(count >= n for n in (200, 500, 1000)),
            "today": day == today,
            "future": future,
        })
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
    }
