#!/usr/bin/env python3
"""把导出的训练记录 JSON 导入 workouts / body_metrics 表。

    python scripts/import_fitness_log.py fitness_log.json [--apply]

默认只打印将要写入的内容（dry run），加 --apply 才真的落库。已存在同一天
记录的话会跳过，不覆盖手写的内容。

归一化的三条规则（和界面里的记法一致）：

  * 名称变体合并到主动作，变体名保留成那一组的备注；
  * 凡是出现过 reps_left / reps_right 的动作算单侧，它的 `reps: N` 是每侧 N 次；
    其余动作是双侧，`reps: N` 就是这一组的总次数；
  * weight_kg / reps 为 null 的组照样导入，数字留空——“当时没记”和“举了 0 公斤”
    不是一回事，容量统计会把这样的一天标成未记录而不是零。
"""

import argparse
import json
import os
import sys
from collections import OrderedDict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import BodyMetric, DatabaseHelper, Workout  # noqa: E402
from app.fitness_model import MOVEMENT_KIND, MOVEMENT_PART, movement_kind  # noqa: E402


# 原始名称 -> (主动作, 留作备注的变体名)
ALIASES = {
    "单臂卧推": ("卧推", ""),
    "卧推（不断电推法）": ("卧推", "不断电推法"),
    "卧推加练": ("卧推", "加练"),
    "划船（扶床单手撑变式）": ("划船", "扶床单手撑变式"),
    "哑铃深蹲": ("深蹲", ""),
    "抬腕（腕弯举）": ("抬腕", ""),
    "腕弯举（左）": ("抬腕", "仅左侧"),
    "腕弯举（右）": ("抬腕", "仅右侧"),
}


def normalize(document):
    unilateral = {
        ALIASES.get(exercise["name"], (exercise["name"], ""))[0]
        for session in document["sessions"]
        for exercise in session["exercises"]
        for entry in exercise["sets"]
        if "reps_left" in entry or "reps_right" in entry
    }

    workouts = []
    for session in document["sessions"]:
        merged = OrderedDict()
        for raw in session["exercises"]:
            name, variant = ALIASES.get(raw["name"], (raw["name"], ""))
            if name not in MOVEMENT_KIND:
                raise SystemExit("动作库里没有「%s」，先在 fitness_model.MOVEMENTS 里加上。" % name)
            kind = movement_kind(name)
            if kind != "static" and (name in unilateral) != (kind == "unilateral"):
                print("  提示：「%s」在记录里是%s，动作库里是%s"
                      % (name, "单侧" if name in unilateral else "双侧",
                         "单侧" if kind == "unilateral" else "双侧"))
            slot = merged.setdefault(name, {"name": name, "sets": []})
            notes = [note for note in (variant, raw.get("note")) if note]
            for index, entry in enumerate(raw["sets"]):
                # 动作级的备注挂到它第一组上，跟着动作走而不是拼成一整天的流水账。
                # variant 单独传：它决定这一组是不是只练了一侧，不能混在备注文本里判断。
                note = "；".join(notes) if index == 0 else variant
                slot["sets"].append(_convert(entry, kind, variant, note))

        exercises = list(merged.values())
        lower = sum(1 for item in exercises if MOVEMENT_PART[item["name"]] == "下肢")
        upper = sum(1 for item in exercises if MOVEMENT_PART[item["name"]] == "上肢")
        workouts.append(Workout(
            entry_date=session["date"],
            day_type="下肢" if lower > upper else "上肢",
            exercises=exercises,
            note="原记录类型：" + session["day_type"],
            created_at=session["date"] + "T00:00:00",
            updated_at=session["date"] + "T00:00:00",
        ))
    return workouts


def _convert(entry, kind, variant, note):
    if "duration_sec" in entry:
        return {"seconds": entry["duration_sec"], "note": note}
    weight = entry.get("weight_kg")
    if "reps_left" in entry or "reps_right" in entry:
        left, right = entry.get("reps_left"), entry.get("reps_right")
    else:
        reps = entry.get("reps")
        if kind != "unilateral":
            left, right = reps, None
        elif variant == "仅左侧":
            left, right = reps, None      # 另一侧当时没练，不是没记
        elif variant == "仅右侧":
            left, right = None, reps
        else:
            left = right = reps
    return {"weight": weight, "left": left, "right": right, "note": note}


def body_metrics(document):
    metrics = {}
    for reading in document["body_metrics"].get("weight_kg", []):
        if reading.get("date"):
            metrics.setdefault(reading["date"], {})["weight_kg"] = reading["value"]
        else:
            # 没有日期的起步体重没法放上时间轴，这里只提示，不猜一个日期。
            print("  跳过无日期的体重 %s kg（%s）" % (reading["value"], reading.get("note") or ""))
    for reading in document["body_metrics"].get("waist_cm", []):
        if reading.get("date"):
            metrics.setdefault(reading["date"], {})["waist_cm"] = reading["value"]
    return [BodyMetric(measured_date=day, **values) for day, values in sorted(metrics.items())]


def main():
    parser = argparse.ArgumentParser(description="导入训练记录 JSON")
    parser.add_argument("source")
    parser.add_argument("--apply", action="store_true", help="真的写库；不加就只预览")
    args = parser.parse_args()

    with open(args.source, encoding="utf-8") as handle:
        document = json.load(handle)

    workouts = normalize(document)
    metrics = body_metrics(document)
    helper = DatabaseHelper()
    existing = {workout.entry_date for workout in helper.get_all_workouts()}

    print("\n%-12s %-5s %-5s %s" % ("日期", "类型", "组数", "动作"))
    written = skipped = 0
    for workout in workouts:
        sets = sum(len(exercise["sets"]) for exercise in workout.exercises)
        mark = "  已存在，跳过" if workout.entry_date in existing else ""
        print("%-12s %-5s %-5d %s%s" % (
            workout.entry_date, workout.day_type, sets,
            "、".join(exercise["name"] for exercise in workout.exercises), mark))
        if workout.entry_date in existing:
            skipped += 1
            continue
        if args.apply:
            helper._insert_with_random_id(helper.workout_table, workout.to_dict())
        written += 1

    for metric in metrics:
        print("身体数据 %s: %s" % (metric.measured_date,
                                {k: v for k, v in metric.to_dict().items() if v}))
        if args.apply:
            helper.save_body_metric(metric)

    print("\n%d 次训练%s，跳过 %d 次，身体数据 %d 条。"
          % (written, "已写入" if args.apply else " 待写入（dry run）", skipped, len(metrics)))
    if not args.apply:
        print("确认无误后加 --apply 重新运行。")


if __name__ == "__main__":
    main()
