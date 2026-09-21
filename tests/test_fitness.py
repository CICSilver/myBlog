import importlib.util
import unittest
from datetime import date
from pathlib import Path

from app import create_app
from app.auth import ADMIN_SESSION_KEY, CSRF_SESSION_KEY
from app.database import BodyMetric, Workout
from app.fitness_activity import activity_summary, build_body_chart, build_chart
from app.fitness_model import (
    balance,
    exercise_totals,
    movement_kind,
    records,
    trend_points,
    workout_totals,
)
import app.routes as routes_module


def workout(entry_date, day_type, exercises, **extra):
    return Workout(entry_date=entry_date, day_type=day_type, exercises=exercises, **extra)


def bilateral(name, *pairs):
    return {"name": name, "sets": [{"weight": w, "left": r, "right": None} for w, r in pairs]}


def unilateral(name, *triples):
    return {"name": name, "sets": [{"weight": w, "left": l, "right": r} for w, l, r in triples]}


class FitnessModelTest(unittest.TestCase):
    def test_bilateral_reps_are_the_whole_set(self):
        totals = exercise_totals(bilateral("深蹲", (10, 15), (10, 12)))
        self.assertEqual(totals["volume"], 10 * 15 + 10 * 12)
        self.assertEqual(totals["reps"], 27)

    def test_unilateral_reps_are_counted_per_side(self):
        totals = exercise_totals(unilateral("弯举", (8, 11, 11), (8, 5, 6)))
        self.assertEqual(totals["volume"], 8 * 22 + 8 * 11)
        self.assertEqual((totals["left"], totals["right"]), (16, 17))

    def test_static_holds_have_seconds_and_no_volume(self):
        totals = exercise_totals({"name": "平板支撑", "sets": [{"seconds": 43}, {"seconds": 57}]})
        self.assertEqual(totals["seconds"], 100)
        self.assertIsNone(totals["volume"])

    def test_a_missing_weight_makes_the_volume_unknown_not_zero(self):
        totals = exercise_totals(unilateral("划船", (None, 8, 8), (10, 8, 8)))
        self.assertIsNone(totals["volume"])
        # 次数照样算得出来，缺的只是重量。
        self.assertEqual((totals["left"], totals["right"]), (16, 16))

    def test_one_sided_set_only_counts_the_side_that_trained(self):
        totals = exercise_totals(unilateral("抬腕", (6.5, None, 15), (6.5, 15, None)))
        self.assertEqual((totals["left"], totals["right"]), (15, 15))
        self.assertEqual(totals["volume"], 6.5 * 15 * 2)

    def test_workout_volume_is_unknown_when_any_exercise_is(self):
        session = workout("2026-09-06", "上肢", [
            unilateral("弯举", (8, 10, 10)),
            unilateral("划船", (None, 8, 8)),
        ])
        self.assertIsNone(workout_totals(session)["volume"])
        self.assertTrue(workout_totals(session)["partial"])
        self.assertEqual(workout_totals(session)["sets"], 2)

    def test_balance_reports_the_side_that_is_ahead(self):
        rows = balance([workout("2026-09-18", "上肢", [unilateral("弯举", (8, 90, 110))])])
        self.assertEqual(rows[0]["name"], "弯举")
        self.assertEqual((rows[0]["left"], rows[0]["right"]), (90, 110))
        self.assertEqual(rows[0]["bias"], 20)   # 右侧领先 20 个百分点
        self.assertTrue(rows[0]["off"])

    def test_flye_is_logged_one_side_at_a_time(self):
        totals = exercise_totals(unilateral("飞鸟", (5.5, 12, 12)))
        self.assertEqual(movement_kind("飞鸟"), "unilateral")
        self.assertEqual(movement_kind("反向飞鸟"), "unilateral")
        self.assertEqual(totals["reps"], 24)          # 左右各 12
        self.assertEqual(totals["volume"], 5.5 * 24)

    def test_a_unilateral_record_needs_both_sides(self):
        best = dict(records([workout("2026-09-18", "上肢", [unilateral("卧推", (10, 14, 8))])]))
        # 强侧做到 14 次也不算数，纪录停在弱侧的 8 次。
        self.assertEqual(best["卧推"]["reps"], 8)
        self.assertEqual(best["卧推"]["weight"], 10)

    def test_trend_skips_sessions_whose_volume_is_unknown(self):
        sessions = [
            workout("2026-09-01", "下肢", [bilateral("深蹲", (10, 10))]),          # 100
            workout("2026-09-03", "下肢", [bilateral("深蹲", (None, 10))]),        # 未知
            workout("2026-09-05", "下肢", [bilateral("深蹲", (10, 20))]),          # 200
            workout("2026-09-07", "下肢", [bilateral("深蹲", (10, 30))]),          # 300
        ]
        points = trend_points(sessions, window=3)
        self.assertEqual([point["date"] for point in points], ["2026-09-07"])
        self.assertEqual(points[0]["value"], 200.0)


class FitnessChartTest(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 9, 18)
        self.sessions = [
            workout("2026-09-16", "下肢", [bilateral("深蹲", (10, 15))]),
            workout("2026-09-17", "上肢", [unilateral("弯举", (None, 10, 10))]),
        ]

    def test_a_day_without_a_weight_gets_a_stub_not_a_full_bar(self):
        chart = build_chart(self.sessions, 5, self.today)
        bars = {bar["date"]: bar for bar in chart["bars"]}
        self.assertTrue(bars["2026-09-17"]["partial"])
        self.assertIsNotNone(bars["2026-09-17"]["path"])
        self.assertIsNone(bars["2026-09-18"]["path"])   # 那天没练，不画柱子
        self.assertFalse(bars["2026-09-18"]["recorded"])

    def test_streak_counts_weeks_because_nobody_trains_daily(self):
        summary = activity_summary(
            {date(2026, 9, 16): 500, date(2026, 9, 9): 500, date(2026, 9, 2): 500},
            2026, self.today)
        self.assertEqual(summary["week_streak"], 3)


class FitnessBodyChartTest(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 9, 20)
        self.metrics = [
            BodyMetric(measured_date="2026-09-06", waist_cm=88),
            BodyMetric(measured_date="2026-09-09", weight_kg=65),
            BodyMetric(measured_date="2026-09-19", weight_kg=63.4, waist_cm=84),
            BodyMetric(measured_date="2026-09-20", weight_kg=63.5),
        ]

    def test_each_quantity_gets_its_own_scale(self):
        # 公斤和厘米共用一根纵轴的话，谁高谁低是排版凑出来的，不是数据里的。
        # 所以两格各自铺满自己的值域：各自的最低点都落在同一个相对位置。
        chart = build_body_chart(self.metrics, self.today)
        weight, waist = chart["panels"]
        self.assertEqual((weight["key"], waist["key"]), ("weight", "waist"))
        # 刻度标各自的最高最低，不是一根共用的轴。
        self.assertEqual([line["label"] for line in weight["grid"]], ["63.4", "65"])
        self.assertEqual([line["label"] for line in waist["grid"]], ["84", "88"])
        # 两格上下分开，画布上不重叠——否则又成了两条线挤一根轴。
        self.assertLess(weight["base"], waist["top"])
        for panel in (weight, waist):
            highest = min(panel["marks"], key=lambda mark: mark["y"])
            lowest = max(panel["marks"], key=lambda mark: mark["y"])
            self.assertGreater(highest["value"], lowest["value"])
            self.assertGreaterEqual(highest["y"], panel["top"])
            self.assertLessEqual(lowest["y"], panel["base"])

    def test_the_two_panels_share_one_timeline(self):
        chart = build_body_chart(self.metrics, self.today)
        weight, waist = chart["panels"]
        same_day = [mark for mark in weight["marks"] if mark["label"] == "9月19日"][0]
        self.assertEqual(same_day["x"], waist["marks"][-1]["x"])
        # 起点是最早的那次读数（腰围 9/6），终点是今天。
        self.assertEqual(waist["marks"][0]["x"], 44.0)
        self.assertEqual(weight["marks"][-1]["x"], 1006.0)

    def test_a_single_reading_still_draws(self):
        chart = build_body_chart([BodyMetric(measured_date="2026-09-20", weight_kg=63.4)], self.today)
        panel = chart["panels"][0]
        self.assertIsNone(panel["path"])       # 一个点连不成线
        self.assertEqual(len(panel["marks"]), 1)
        self.assertEqual(panel["latest"]["text"], "63.4")

    def test_readings_on_consecutive_days_do_not_stack_their_labels(self):
        chart = build_body_chart(self.metrics, self.today)
        positions = [tick["x"] for tick in chart["ticks"]]
        self.assertEqual(positions, sorted(positions))
        self.assertTrue(all(second - first >= 72
                            for first, second in zip(positions, positions[1:])))
        self.assertEqual(positions[-1], 1006.0)   # 最后一次读数一定标出来

    def test_no_readings_means_no_chart(self):
        self.assertIsNone(build_body_chart([], self.today))
        self.assertIsNone(build_body_chart([BodyMetric(measured_date="2026-09-20")], self.today))


class FitnessRouteDatabase:
    def __init__(self, workouts=()):
        self.workouts = {item.entry_date: item for item in workouts}
        self.saved = []
        self.metrics = []

    def get_all_workouts(self):
        return sorted(self.workouts.values(), key=lambda item: item.entry_date, reverse=True)

    def get_workouts_by_month(self, year, month):
        prefix = "{0:04d}-{1:02d}-".format(int(year), int(month))
        return [item for item in self.get_all_workouts() if item.entry_date.startswith(prefix)]

    def get_workout_by_date(self, entry_date):
        return self.workouts.get(entry_date)

    def save_workout(self, item, today):
        self.saved.append(item)
        self.workouts[item.entry_date] = item
        return {"status": "success", "operation": "inserted", "message": "今日训练保存成功。"}

    def get_body_metrics(self):
        return list(self.metrics)

    def save_body_metric(self, metric):
        self.metrics.append(metric)
        return "inserted"


class FitnessRouteTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.original = routes_module.dbHelper
        self.database = FitnessRouteDatabase([
            workout("2026-09-16", "下肢", [bilateral("深蹲", (10, 15), (10, 12))]),
        ])
        routes_module.dbHelper = self.database
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session[ADMIN_SESSION_KEY] = True
            session[CSRF_SESSION_KEY] = "token"

    def tearDown(self):
        routes_module.dbHelper = self.original

    def post(self, payload):
        return self.client.post("/fitness", json=payload, headers={"X-CSRF-Token": "token"})

    def today(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from app.diary_policy import diary_date
        return diary_date(datetime.now(ZoneInfo(self.app.config["BLOG_TIMEZONE"]))).isoformat()

    def test_page_requires_an_admin_session(self):
        anonymous = self.app.test_client()
        self.assertEqual(anonymous.get("/fitness").status_code, 302)

    def test_page_renders_the_month(self):
        response = self.client.get("/fitness?month=2026-09")
        self.assertEqual(response.status_code, 200)
        self.assertIn("深蹲", response.get_data(as_text=True))

    def test_movements_already_logged_today_leave_the_picker(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from app.diary_policy import diary_date
        today = diary_date(datetime.now(ZoneInfo(self.app.config["BLOG_TIMEZONE"]))).isoformat()
        self.database.workouts[today] = workout(today, "上肢", [unilateral("弯举", (8, 11, 11))])
        html = self.client.get("/fitness").get_data(as_text=True)
        self.assertIn('data-move="弯举" data-kind="unilateral" hidden', html)
        self.assertIn('data-move="划船" data-kind="unilateral">', html)

    def test_a_saved_set_carries_no_completion_state(self):
        # 组是做完之后补录的，不存在“未完成的组”，勾去掉了；表头的占位
        # 也要跟着少一列，不然表头和组行会错开。
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from app.diary_policy import diary_date
        today = diary_date(datetime.now(ZoneInfo(self.app.config["BLOG_TIMEZONE"]))).isoformat()
        self.database.workouts[today] = workout(today, "上肢", [unilateral("飞鸟", (5.5, 12, 12))])
        html = self.client.get("/fitness").get_data(as_text=True)
        self.assertIn('data-move="飞鸟" data-kind="unilateral" hidden', html)
        self.assertNotIn("data-set-check", html)
        self.assertNotIn("is-done", html)

    def test_the_log_no_longer_asks_how_long_it_took(self):
        html = self.client.get("/fitness").get_data(as_text=True)
        self.assertNotIn("duration_min", html)
        self.assertNotIn("训练时长", html)

    def test_saving_clears_the_draft_instead_of_leaving_it_behind(self):
        # 存完不删草稿的话，下次进来页面顶上会一直挂着"有一份未保存草稿"。
        # 而且"丢弃"和"保存"都是点按钮，按钮一律排一次草稿写入——不把那个
        # 定时器掐掉，600ms 后它又把刚删掉的写回来，点多少次都没用。
        javascript = (Path(__file__).resolve().parents[1]
                      / "static" / "js" / "fitness.js").read_text(encoding="utf-8")
        drop = javascript[javascript.index("function dropDraft()"):]
        drop = drop[:drop.index("}")]
        self.assertIn("window.clearTimeout(draftTimer)", drop)
        self.assertIn("removeItem(DRAFT_KEY)", drop)
        # 存成功那条路径上也得删一次，不然记录已经更新了草稿还挂着。
        saved = javascript[javascript.index("submit.addEventListener"):]
        self.assertIn("dropDraft();", saved)
        # 提示条自己那两个按钮不该再排一次写入。
        self.assertIn('if (event.target.closest(".fit-draft-bar")) return;', javascript)

    def test_the_session_note_is_not_the_first_set_note(self):
        # 组备注和整场备注共用 data-field="note"，按属性取会先撞上第一条
        # 组备注，把它当成这一场的总结存下去。
        javascript = (Path(__file__).resolve().parents[1]
                      / "static" / "js" / "fitness.js").read_text(encoding="utf-8")
        self.assertNotIn("""const note = form.querySelector('[data-field="note"]')""", javascript)
        self.assertEqual(javascript.count('form.querySelector("#fit-note")'), 2)

    def test_the_body_chart_only_appears_once_something_was_measured(self):
        self.database.metrics = []
        html = self.client.get("/fitness").get_data(as_text=True)
        self.assertNotIn('data-chart-view="body"', html)
        self.assertNotIn("data-chart-switch", html)   # 只有一张图就不给切换

        self.database.metrics = [
            BodyMetric(measured_date="2026-09-16", weight_kg=63.4, waist_cm=84),
        ]
        html = self.client.get("/fitness").get_data(as_text=True)
        self.assertIn('data-chart-view="body"', html)
        self.assertIn("data-chart-switch", html)
        self.assertIn("体重与腰围", html)

    def test_the_volume_chart_is_the_one_showing_first(self):
        self.database.metrics = [BodyMetric(measured_date="2026-09-16", weight_kg=63.4)]
        html = self.client.get("/fitness").get_data(as_text=True)
        volume = html.index('data-chart-view="volume"')
        body = html.index('data-chart-view="body"')
        self.assertNotIn("hidden", html[volume:volume + 120])
        self.assertIn("hidden", html[body:body + 120])

    def test_the_chart_is_called_the_training_volume_not_the_capacity(self):
        html = self.client.get("/fitness").get_data(as_text=True)
        self.assertIn("每日训练量", html)
        self.assertNotIn("每日训练容量", html)

    def test_sidebar_keeps_the_wrapper_the_sticky_logic_needs(self):
        # 外层撑满整行、内层位移——少了这层包裹，方向感知吸附就没有位移
        # 空间，会安静地失效而不报错。
        html = self.client.get("/fitness").get_data(as_text=True)
        self.assertIn('class="fit-side"', html)
        self.assertIn('class="fit-side-inner"', html)

    def test_body_metric_can_be_saved_on_its_own(self):
        # 早上称完就能存，不用先凑出一次完整的训练。
        response = self.client.post("/fitness/body", json={"weight_kg": 64.6},
                                    headers={"X-CSRF-Token": "token"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.database.metrics[-1].weight_kg, 64.6)

    def test_waist_can_be_saved_on_its_own(self):
        response = self.client.post("/fitness/body", json={"waist_cm": 86.5},
                                    headers={"X-CSRF-Token": "token"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.database.metrics[-1].waist_cm, 86.5)
        self.assertIsNone(self.database.metrics[-1].weight_kg)

    def test_waist_field_does_not_prefill_a_stale_reading(self):
        # 填着上次的数字会看着像今天量过；旧值只作为标签旁的提示出现。
        self.database.metrics.append(BodyMetric(measured_date="2026-09-06", waist_cm=88))
        html = self.client.get("/fitness").get_data(as_text=True)
        self.assertIn('data-body-field="waist_cm" value=""', html)
        self.assertIn("上次 88", html)

    def test_body_metric_rejects_an_empty_payload(self):
        response = self.client.post("/fitness/body", json={},
                                    headers={"X-CSRF-Token": "token"})
        self.assertEqual(response.status_code, 400)

    def test_body_metric_rejects_an_absurd_weight(self):
        response = self.client.post("/fitness/body", json={"weight_kg": 900},
                                    headers={"X-CSRF-Token": "token"})
        self.assertEqual(response.status_code, 400)

    def test_body_metric_needs_the_csrf_token(self):
        self.assertEqual(self.client.post("/fitness/body", json={"weight_kg": 65}).status_code, 403)

    def test_body_metric_needs_a_login(self):
        anonymous = self.app.test_client()
        self.assertEqual(anonymous.post("/fitness/body", json={"weight_kg": 65}).status_code, 401)

    def test_page_tells_the_draft_whether_today_is_already_saved(self):
        # 前端据此决定草稿是静默恢复还是先问一句——服务端已有记录时
        # 直接覆盖，等于偷偷回滚了一次保存。
        self.assertIn('data-saved="0"', self.client.get("/fitness").get_data(as_text=True))
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from app.diary_policy import diary_date
        today = diary_date(datetime.now(ZoneInfo(self.app.config["BLOG_TIMEZONE"]))).isoformat()
        self.database.workouts[today] = workout(today, "上肢", [unilateral("弯举", (8, 11, 11))])
        self.assertIn('data-saved="1"', self.client.get("/fitness").get_data(as_text=True))

    def test_future_month_is_rejected(self):
        self.assertEqual(self.client.get("/fitness?month=2999-01").status_code, 400)

    def test_saving_rejects_a_movement_outside_the_library(self):
        response = self.post({"day_type": "上肢",
                              "exercises": [{"name": "引体向上", "sets": [{"weight": 10, "left": 5}]}]})
        self.assertEqual(response.status_code, 400)
        self.assertIn("引体向上", response.get_json()["message"])

    def test_saving_rejects_an_absurd_weight(self):
        response = self.post({"day_type": "下肢",
                              "exercises": [{"name": "深蹲", "sets": [{"weight": 900, "left": 5}]}]})
        self.assertEqual(response.status_code, 400)

    def test_a_rest_day_cannot_carry_exercises(self):
        response = self.post({"day_type": "休息",
                              "exercises": [{"name": "深蹲", "sets": [{"weight": 10, "left": 5}]}]})
        self.assertEqual(response.status_code, 400)

    def test_a_completely_empty_set_is_refused(self):
        response = self.post({"day_type": "上肢",
                              "exercises": [{"name": "弯举", "sets": [{}]}]})
        self.assertEqual(response.status_code, 400)
        self.assertIn("空组", response.get_json()["message"])

    def test_a_weight_without_reps_is_kept_and_leaves_the_volume_unknown(self):
        # 真实记录里就有这种：练了、重量记了，次数当时忘了。
        response = self.post({"entry_date": self.today(), "day_type": "上肢",
                              "exercises": [{"name": "弯举", "sets": [{"weight": 8}]}]})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.get_json()["totals"]["volume"])
        self.assertTrue(response.get_json()["totals"]["partial"])

    def test_set_notes_survive_a_save(self):
        # 回归：前端收集数据时漏了 note，而保存是整条替换文档，
        # 结果编辑一次当天记录就会把导入进来的备注全部抹掉。
        response = self.post({
            "entry_date": self.today(), "day_type": "上肢",
            "exercises": [{"name": "划船", "sets": [
                {"weight": 10, "left": 12, "right": 15, "note": "首次上10kg；站姿微屈膝"},
                {"weight": 10, "left": 8, "right": 14},
            ]}],
        })
        self.assertEqual(response.status_code, 200)
        saved = self.database.saved[-1].exercises[0]["sets"]
        self.assertEqual(saved[0]["note"], "首次上10kg；站姿微屈膝")
        self.assertEqual(saved[1]["note"], "")

    def test_saving_stores_the_session_and_the_body_weight(self):
        response = self.post({
            "entry_date": self.today(),
            "day_type": "上肢",
            "exercises": [{"name": "弯举", "sets": [{"weight": 8, "left": 11, "right": 10}]}],
            "rpe": 7, "weight_kg": 64.6, "note": "自测",
        })
        self.assertEqual(response.status_code, 200)
        saved = self.database.saved[0]
        self.assertEqual(saved.rpe, 7)
        self.assertEqual(saved.exercises[0]["sets"][0]["right"], 10)
        self.assertEqual(self.database.metrics[0].weight_kg, 64.6)

    def test_saving_another_day_is_refused(self):
        self.assertEqual(self.post({"entry_date": "2020-01-01", "day_type": "休息",
                                    "exercises": []}).status_code, 409)

    def test_saving_requires_the_csrf_token(self):
        self.assertEqual(self.client.post("/fitness", json={"day_type": "休息"}).status_code, 403)


class FitnessImportTest(unittest.TestCase):
    """导入脚本不是包的一部分，按路径加载。"""

    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / "scripts" / "import_fitness_log.py"
        spec = importlib.util.spec_from_file_location("import_fitness_log", path)
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def normalize(self, sessions):
        return self.module.normalize({"sessions": sessions})

    def test_a_bare_reps_on_a_unilateral_movement_means_per_side(self):
        result = self.normalize([{"date": "2026-09-02", "day_type": "上肢", "exercises": [
            {"name": "弯举", "sets": [{"weight_kg": 6.5, "reps": 8}]}]}])
        entry = result[0].exercises[0]["sets"][0]
        self.assertEqual((entry["left"], entry["right"]), (8, 8))

    def test_a_bare_reps_on_a_bilateral_movement_is_the_total(self):
        result = self.normalize([{"date": "2026-09-03", "day_type": "腿", "exercises": [
            {"name": "哑铃深蹲", "sets": [{"weight_kg": 6.5, "reps": 15}]}]}])
        entry = result[0].exercises[0]["sets"][0]
        self.assertEqual((entry["left"], entry["right"]), (15, None))
        self.assertEqual(result[0].day_type, "下肢")

    def test_variants_merge_into_the_main_movement(self):
        result = self.normalize([{"date": "2026-09-13", "day_type": "上肢", "exercises": [
            {"name": "卧推", "sets": [{"weight_kg": 6.5, "reps": 15}]},
            {"name": "卧推加练", "sets": [{"weight_kg": 10, "reps_left": 8, "reps_right": 12}]}]}])
        exercises = result[0].exercises
        self.assertEqual([item["name"] for item in exercises], ["卧推"])
        self.assertEqual(len(exercises[0]["sets"]), 2)
        self.assertEqual(exercises[0]["sets"][1]["note"], "加练")

    def test_a_side_only_variant_does_not_credit_the_other_side(self):
        # 回归：带伤病备注时，「仅左侧」标记曾被拼进长备注里而失效，
        # 结果只练了左手的那一组被当成两侧都练。
        result = self.normalize([{"date": "2026-09-09", "day_type": "休息日", "exercises": [
            {"name": "腕弯举（右）", "sets": [{"weight_kg": 6.5, "reps": 15}]},
            {"name": "腕弯举（左）", "sets": [{"weight_kg": 6.5, "reps": 15}],
             "note": "左腕小指侧正握卷腕即痛，当即停练左侧"}]}])
        sets = result[0].exercises[0]["sets"]
        self.assertEqual([(entry["left"], entry["right"]) for entry in sets],
                         [(None, 15), (15, None)])

    def test_static_holds_survive_the_import(self):
        result = self.normalize([{"date": "2026-09-02", "day_type": "上肢", "exercises": [
            {"name": "平板支撑", "sets": [{"duration_sec": 43}]}]}])
        self.assertEqual(result[0].exercises[0]["sets"][0], {"seconds": 43, "note": ""})

    def test_an_undated_reading_is_skipped_rather_than_guessed(self):
        metrics = self.module.body_metrics({"body_metrics": {
            "weight_kg": [{"date": None, "value": 63}, {"date": "2026-09-09", "value": 65}]}})
        self.assertEqual([(item.measured_date, item.weight_kg) for item in metrics],
                         [("2026-09-09", 65)])


if __name__ == "__main__":
    unittest.main()
