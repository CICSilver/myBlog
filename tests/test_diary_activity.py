import unittest
from datetime import date, timedelta
from types import SimpleNamespace

from app.diary_activity import activity_summary, build_activity_calendar, diary_activity_counts


class DiaryActivityTest(unittest.TestCase):
    def test_only_saved_nonempty_days_count_and_duplicates_are_deduplicated(self):
        entries = [
            SimpleNamespace(entry_date="2026-09-04", content="　　甲乙\n丙 丁"),
            SimpleNamespace(entry_date="2026-09-04", content="重复"),
            SimpleNamespace(entry_date="2026-09-03", content=" \n　"),
            SimpleNamespace(entry_date="2026-09-06", content="未来"),
            SimpleNamespace(entry_date="bad-date", content="坏日期"),
            SimpleNamespace(entry_date="2026-09-02", content=None),
        ]
        counts = diary_activity_counts(entries, date(2026, 9, 5))
        self.assertEqual(counts, {date(2026, 9, 4): 4})

    def test_streak_carries_across_new_year_and_today_can_be_pending(self):
        today = date(2026, 1, 3)
        counts = {today - timedelta(days=i): 50 for i in range(1, 6)}
        summary = activity_summary(counts, 2026, today)
        self.assertEqual(summary["recorded_days"], 2)
        self.assertEqual(summary["current_streak"], 5)
        self.assertFalse(summary["today_recorded"])
        counts[today] = 200
        self.assertEqual(activity_summary(counts, 2026, today)["current_streak"], 6)
        del counts[today]
        del counts[today - timedelta(days=1)]
        self.assertEqual(activity_summary(counts, 2026, today)["current_streak"], 0)

    def test_calendar_covers_every_date_once_with_seven_days_per_week(self):
        for year, expected_days, expected_weeks in ((2026, 365, 53), (2024, 366, 53), (2012, 366, 54), (1, 365, 53)):
            with self.subTest(year=year):
                result = build_activity_calendar({}, year, date(2026, 9, 5))
                days = [day for day in result["days"] if day]
                self.assertEqual(result["weeks"], expected_weeks)
                self.assertEqual(len(result["days"]), expected_weeks * 7)
                self.assertEqual(len(days), expected_days)
                self.assertEqual(len({day["date"] for day in days}), expected_days)
                for index, day in enumerate(result["days"]):
                    if day:
                        self.assertEqual(date.fromisoformat(day["date"]).weekday(), index % 7)
                self.assertEqual(len(result["months"]), 12)
                self.assertEqual(days[0]["date"], f"{year:04d}-01-01")
                self.assertEqual(days[-1]["date"], f"{year:04d}-12-31")

    def test_levels_today_future_and_empty_year(self):
        today = date(2026, 9, 5)
        counts = {date(2026, 9, i + 1): n for i, n in enumerate((1, 199, 200, 500, 1000))}
        result = build_activity_calendar(counts, 2026, today)
        by_date = {day["date"]: day for day in result["days"] if day}
        self.assertEqual([by_date[f"2026-09-0{i}"]["level"] for i in range(1, 6)], [1, 1, 2, 3, 4])
        self.assertTrue(by_date["2026-09-05"]["today"])
        self.assertTrue(by_date["2026-09-06"]["future"])
        self.assertEqual(by_date["2026-09-06"]["level"], 0)
        self.assertEqual(build_activity_calendar({}, 2024, today)["recorded_days"], 0)
        for year in (0, 2027):
            with self.assertRaises(ValueError):
                build_activity_calendar({}, year, today)


if __name__ == "__main__":
    unittest.main()
