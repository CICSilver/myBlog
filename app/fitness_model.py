"""训练动作库与从训练记录派生的统计。

动作库是封闭的：录入时从这里选，不自由输入。每个动作的 kind 决定它的记法，
录入界面据此长出对应形态的表格，而不是让记录的人每次去选：

    bilateral   双侧同时完成，reps 是这一组的总次数（深蹲、臀桥、提踵、侧平举）
    unilateral  单侧轮流完成，左右各记一个次数（弯举、划船、卧推、抬腕、飞鸟）
    static      静力保持，只有秒数，没有重量和次数（平板支撑）
"""

from datetime import date


# (名称, 记法, 部位)
MOVEMENTS = (
    ("深蹲", "bilateral", "下肢"),
    ("臀桥", "bilateral", "下肢"),
    ("提踵", "bilateral", "下肢"),
    ("弯举", "unilateral", "上肢"),
    ("划船", "unilateral", "上肢"),
    ("卧推", "unilateral", "上肢"),
    ("抬腕", "unilateral", "上肢"),
    ("飞鸟", "unilateral", "上肢"),
    ("侧平举", "bilateral", "上肢"),
    ("平板支撑", "static", "核心"),
)

MOVEMENT_KIND = {name: kind for name, kind, _ in MOVEMENTS}
MOVEMENT_PART = {name: part for name, _, part in MOVEMENTS}
DAY_TYPES = ("上肢", "下肢", "休息")

# 手头哑铃的档位。录入时从这里选，避免把 6.5 打成 65。
DUMBBELL_STEPS = (4.5, 5.5, 6.5, 8.0, 9.0, 10.0)


def movement_kind(name):
    return MOVEMENT_KIND.get(name, "bilateral")


def weight_options(workouts=()):
    """已知档位，加上历史里出现过的其它重量。"""
    used = {
        entry["weight"]
        for workout in workouts
        for exercise in workout.exercises
        for entry in exercise.get("sets", ())
        if entry.get("weight")
    }
    return sorted(set(DUMBBELL_STEPS) | used)


def set_volume(entry, kind):
    """一组搬起的公斤数；缺重量或缺次数时返回 None，而不是当成 0。"""
    if kind == "static" or entry.get("weight") is None:
        return None
    left, right = entry.get("left"), entry.get("right")
    if kind == "unilateral":
        if left is None and right is None:
            return None
        return entry["weight"] * ((left or 0) + (right or 0))
    if left is None:
        return None
    return entry["weight"] * left


def exercise_totals(exercise):
    """单个动作的小计。volume 为 None 表示这个动作里有组缺数字。"""
    kind = movement_kind(exercise.get("name"))
    volume, complete = 0, True
    left = right = seconds = 0
    entries = exercise.get("sets") or []
    for entry in entries:
        if kind == "static":
            seconds += entry.get("seconds") or 0
            continue
        value = set_volume(entry, kind)
        if value is None:
            complete = False
        else:
            volume += value
        left += entry.get("left") or 0
        right += entry.get("right") or 0
    total = left + right
    return {
        "name": exercise.get("name"),
        "kind": kind,
        "sets": len(entries),
        # 静力动作没有容量可言，是 None 而不是 0——0 会读成“举了 0 公斤”。
        "volume": None if kind == "static" else (volume if complete else None),
        "left": left,
        "right": right,
        "seconds": seconds,
        "reps": left if kind == "bilateral" else total,
        "imbalance": (abs(left - right) * 200.0 / total) if (kind == "unilateral" and total) else 0.0,
        "weights": sorted({entry["weight"] for entry in entries if entry.get("weight")}),
        "notes": [entry["note"] for entry in entries if entry.get("note")],
    }


def workout_totals(workout):
    volume, complete, sets = 0, True, 0
    for exercise in workout.exercises:
        totals = exercise_totals(exercise)
        sets += totals["sets"]
        if totals["kind"] == "static":
            continue
        if totals["volume"] is None:
            complete = False
        else:
            volume += totals["volume"]
    return {"volume": volume if complete else None, "sets": sets, "partial": not complete}


def volume_by_day(workouts):
    """{date: 容量}。缺数字的那天记成 None，好跟“没练”区分开。"""
    result = {}
    for workout in workouts:
        try:
            day = date.fromisoformat(workout.entry_date)
        except (TypeError, ValueError):
            continue
        result[day] = workout_totals(workout)["volume"]
    return result


def balance(workouts):
    """每个单侧动作的左右累计次数，偏差大的排在前面。"""
    totals = {}
    for workout in workouts:
        for exercise in workout.exercises:
            summary = exercise_totals(exercise)
            if summary["kind"] != "unilateral":
                continue
            slot = totals.setdefault(summary["name"], {"name": summary["name"], "left": 0, "right": 0})
            slot["left"] += summary["left"]
            slot["right"] += summary["right"]
    rows = []
    for slot in totals.values():
        total = slot["left"] + slot["right"]
        # 右侧领先为正，单位是百分点；界面上的刻度就按它偏移。
        bias = round((slot["right"] - slot["left"]) * 200.0 / total) if total else 0
        rows.append({**slot, "bias": bias, "off": abs(bias) >= 8})
    rows.sort(key=lambda row: -abs(row["bias"]))
    return rows


def records(workouts):
    """每个动作的最好成绩：先看重量，同重量再看次数。

    单侧动作按弱侧计——左手 10kg×12、右手 10kg×8 只算 10kg×8，
    这样纪录和左右平衡是同一个方向使劲，不会互相打架。
    """
    best = {}
    for workout in sorted(workouts, key=lambda item: item.entry_date):
        for exercise in workout.exercises:
            name = exercise.get("name")
            kind = movement_kind(name)
            for entry in exercise.get("sets") or []:
                if kind == "static":
                    value = entry.get("seconds")
                    if value and value > (best.get(name, {}).get("reps") or 0):
                        best[name] = {"weight": None, "reps": value, "unit": "秒",
                                      "date": workout.entry_date}
                    continue
                if entry.get("weight") is None:
                    continue
                if kind == "unilateral":
                    sides = [value for value in (entry.get("left"), entry.get("right")) if value]
                    reps = min(sides) if sides else None
                else:
                    reps = entry.get("left")
                if not reps:
                    continue
                current = best.get(name)
                if (current is None
                        or entry["weight"] > current["weight"]
                        or (entry["weight"] == current["weight"] and reps > current["reps"])):
                    best[name] = {"weight": entry["weight"], "reps": reps, "unit": "次",
                                  "date": workout.entry_date}
    return [(name, best[name]) for name, _, _ in MOVEMENTS if name in best]


def trend_points(workouts, window=3):
    """近 window 次训练的平均容量，只取容量完整的那几次。

    按“次”平均而不是按日历天——把休息日算进分母会把这条线压到柱子底下，
    看上去像噪声而不是趋势。
    """
    known = [
        (workout.entry_date, workout_totals(workout)["volume"])
        for workout in sorted(workouts, key=lambda item: item.entry_date)
    ]
    known = [(day, volume) for day, volume in known if volume]
    return [
        {"date": day, "value": sum(value for _, value in known[index - window + 1:index + 1]) / float(window)}
        for index, (day, _) in enumerate(known)
        if index >= window - 1
    ]
