"""训练日历与统计，全部从已保存的训练记录派生，不写库。"""

import calendar
from datetime import date, timedelta

from app.fitness_model import volume_by_day, workout_totals


WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

# 容量色阶的分档。按真实记录的分布挑的，让四档都用得上。
VOLUME_LEVELS = (400, 800, 1500)


def activity_level(volume):
    if not volume:
        return 0
    return 1 + sum(volume >= edge for edge in VOLUME_LEVELS)


def activity_summary(volumes, year, today):
    """连续周而不是连续天——一周练三次的人，连续天数永远是 1。"""
    weeks = {day.isocalendar()[:2] for day in volumes}
    streak = 0
    cursor = today
    if cursor.isocalendar()[:2] not in weeks:
        cursor -= timedelta(days=7)
    while cursor.isocalendar()[:2] in weeks:
        streak += 1
        if cursor < date.min + timedelta(days=7):
            break
        cursor -= timedelta(days=7)
    return {
        "year": year,
        "recorded_days": sum(day.year == year for day in volumes),
        "week_streak": streak,
        "today_recorded": today in volumes,
    }


def month_summary(workouts, year, month):
    sessions = [
        workout for workout in workouts
        if workout.entry_date.startswith("%04d-%02d-" % (year, month))
    ]
    return {
        "count": len(sessions),
        "sets": sum(workout_totals(workout)["sets"] for workout in sessions),
    }


def _day_entry(day, volumes, today):
    future = day > today
    recorded = day in volumes
    volume = volumes.get(day)
    if future:
        state = "尚未到来"
    elif not recorded:
        state = "没有训练"
    elif volume is None:
        state = "训练了，但当时没记重量"
    else:
        state = "容量 %s kg" % format_volume(volume)
    return {
        "date": day.isoformat(),
        "day": day.day,
        "label": "%d年%d月%d日 %s，%s" % (day.year, day.month, day.day, WEEKDAYS[day.weekday()], state),
        "volume": volume,
        "recorded": recorded,
        # 练了但算不出容量的那天既不是 0 也不是空白，界面上单独画。
        "partial": recorded and volume is None,
        "level": activity_level(volume),
        "today": day == today,
        "future": future,
    }


def build_month_calendar(volumes, year, month, today):
    """一个月，周一起头；补位格是 None。"""
    first = date(year, month, 1)
    if first > today.replace(day=1):
        raise ValueError("Month is in the future.")
    weeks = []
    week = [None] * first.weekday()
    for number in range(1, calendar.monthrange(year, month)[1] + 1):
        week.append(_day_entry(date(year, month, number), volumes, today))
        if len(week) == 7:
            weeks.append(week)
            week = []
    if week:
        week.extend([None] * (7 - len(week)))
        weeks.append(week)
    return {
        "year": year,
        "month": month,
        "value": "%04d-%02d" % (year, month),
        "recorded_days": sum(1 for day in volumes if (day.year, day.month) == (year, month)),
        "weeks": [
            {"days": days, "current": any(day and day["today"] for day in days)}
            for days in weeks
        ],
    }


def build_year_overview(volumes, year, today):
    months = []
    for month in range(1, 13):
        first = date(year, month, 1)
        cells = [None] * first.weekday()
        recorded = 0
        for number in range(1, calendar.monthrange(year, month)[1] + 1):
            day = date(year, month, number)
            if day in volumes:
                recorded += 1
            cells.append({
                "date": day.isoformat(),
                "level": activity_level(volumes.get(day)),
                "partial": day in volumes and volumes[day] is None,
                "today": day == today,
                "future": day > today,
            })
        months.append({
            "month": month,
            "label": "%d月" % month,
            "value": "%04d-%02d" % (year, month),
            "recorded_days": recorded,
            "future": first > today,
            "cells": cells,
        })
    return months


def build_activity_calendar(workouts, year, today):
    """整年，给年览的异步加载用。"""
    if not 1 <= year <= today.year:
        raise ValueError("Year is outside the fitness calendar range.")
    volumes = volume_by_day(workouts)
    return {
        **activity_summary(volumes, year, today),
        "today": today.isoformat(),
        "min_year": min([year, today.year] + [day.year for day in volumes]),
        "max_year": today.year,
        "overview": build_year_overview(volumes, year, today),
    }


def format_volume(volume):
    if volume is None:
        return "—"
    return "{:,}".format(int(volume)) if float(volume).is_integer() else "{:,.1f}".format(volume)


def build_chart(workouts, days, today, trend_window=3):
    """容量柱 + 近几次平均，交给模板画 SVG。

    起点往前多取 trend_window - 1 次训练：趋势线要在窗口第一天就有值，
    否则它会从图表三分之一处才开始，看着像渲染坏了。
    """
    from app.fitness_model import trend_points

    volumes = volume_by_day(workouts)
    start = today - timedelta(days=days - 1)
    span = [start + timedelta(days=offset) for offset in range(days)]
    seen = {workout.entry_date: workout for workout in workouts}

    points = {
        date.fromisoformat(point["date"]): point["value"]
        for point in trend_points(workouts, window=trend_window)
    }
    bars = []
    for day in span:
        volume = volumes.get(day)
        workout = seen.get(day.isoformat())
        totals = workout_totals(workout) if workout else None
        bars.append({
            "date": day.isoformat(),
            "label": "%d月%d日" % (day.month, day.day),
            "weekday": WEEKDAYS[day.weekday()],
            "volume": volume,
            "recorded": workout is not None,
            "partial": workout is not None and volume is None,
            "sets": totals["sets"] if totals else 0,
            "day_type": workout.day_type if workout else "",
            "today": day == today,
            "trend": points.get(day),
        })
    ceiling = _round_ceiling(max([volume for volume in volumes.values() if volume] or [1000]))
    return _with_geometry({"bars": bars, "max": ceiling, "days": days})


# SVG 画布。服务端把坐标算好，模板只负责输出，图表不依赖 JS 才出现。
CHART_WIDTH, CHART_HEIGHT = 1040, 150
CHART_LEFT, CHART_RIGHT = 36.0, 1032.0
CHART_BASE, CHART_TOP = 116.0, 14.0
BAR_WIDTH, BAR_RADIUS = 15.0, 4.0
# 练了但算不出容量的那天画成贴地的小短柱：不是 0，也不是空白。
STUB_HEIGHT = 5.0


def _with_geometry(chart):
    days = chart["days"]
    band = (CHART_RIGHT - CHART_LEFT) / days
    ceiling = float(chart["max"])

    def y_of(value):
        return CHART_BASE - (min(value, ceiling) / ceiling) * (CHART_BASE - CHART_TOP)

    def cx_of(index):
        return CHART_LEFT + (index + 0.5) * band

    peak = max(chart["bars"], key=lambda bar: bar["volume"] or 0)
    for index, bar in enumerate(chart["bars"]):
        centre = cx_of(index)
        bar["x"] = centre - band / 2.0
        bar["width"] = band
        bar["centre"] = round(centre, 1)
        bar["is_peak"] = bar is peak and bool(bar["volume"])
        if bar["partial"]:
            bar["path"] = _bar_path(centre - BAR_WIDTH / 2.0, CHART_BASE - STUB_HEIGHT,
                                    BAR_WIDTH, STUB_HEIGHT, 2.0)
        elif bar["volume"]:
            top = y_of(bar["volume"])
            bar["path"] = _bar_path(centre - BAR_WIDTH / 2.0, top, BAR_WIDTH,
                                    CHART_BASE - top, BAR_RADIUS)
            bar["label_y"] = round(top - 6, 1)
        else:
            bar["path"] = None

    points = [(cx_of(index), y_of(bar["trend"]))
              for index, bar in enumerate(chart["bars"]) if bar["trend"]]
    if len(points) > 1:
        line = "M%.1f %.1f " % points[0] + " ".join("L%.1f %.1f" % point for point in points[1:])
        chart["trend_path"] = line
        chart["area_path"] = "%s L%.1f %.1f L%.1f %.1f Z" % (
            line, points[-1][0], CHART_BASE, points[0][0], CHART_BASE)
    else:
        chart["trend_path"] = chart["area_path"] = None

    step = max(1, days // 6)
    chart["ticks"] = [
        {"x": round(cx_of(index), 1), "label": bar["label"]}
        for index, bar in enumerate(chart["bars"]) if index % step == 0
    ]
    chart["grid"] = [
        {"y": round(y_of(value), 1), "label": "{:,}".format(int(value))}
        for value in (0, ceiling / 2, ceiling)
    ]
    chart["viewbox"] = "0 0 %d %d" % (CHART_WIDTH, CHART_HEIGHT)
    chart["base"] = CHART_BASE
    chart["hit_top"] = CHART_TOP - 8
    chart["hit_height"] = CHART_BASE - CHART_TOP + 16
    return chart


def _bar_path(x, y, width, height, radius):
    """圆角封顶，底边是方的——柱子是从基线长出来的，不是浮在空中的胶囊。"""
    radius = min(radius, width / 2.0, height)
    return ("M%.1f %.1f V%.1f Q%.1f %.1f %.1f %.1f H%.1f Q%.1f %.1f %.1f %.1f V%.1f Z" % (
        x, y + height, y + radius, x, y, x + radius, y,
        x + width - radius, x + width, y, x + width, y + radius, y + height))


def _round_ceiling(value):
    """把纵轴顶端凑成整数，刻度才好读。"""
    for step in (500, 1000, 2000, 5000):
        if value <= step * 4:
            return int(-(-value // step) * step)
    return int(-(-value // 10000) * 10000)
