import importlib.util
import unittest
from datetime import date
from pathlib import Path

from app import create_app
from app.auth import ADMIN_SESSION_KEY, CSRF_SESSION_KEY
from app.database import BodyMetric, Workout
from app.fitness_activity import activity_summary, build_chart
from app.fitness_model import balance, exercise_totals, records, trend_points, workout_totals
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
            "duration_min": 42, "rpe": 7, "weight_kg": 64.6, "note": "自测",
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
