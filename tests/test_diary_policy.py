import unittest
from datetime import datetime
from app.diary_policy import better_location, diary_date, distance_meters, location_needs_retry

class DiaryPolicyTest(unittest.TestCase):
    def test_month_and_leap_day_boundaries(self):
        for value, expected in [
            ("2028-03-01T04:00:59", "2028-02-29"),
            ("2028-03-01T04:01:00", "2028-03-01"),
            ("2026-09-10T00:00:00", "2026-09-09"),
        ]:
            self.assertEqual(diary_date(datetime.fromisoformat(value)).isoformat(), expected)

    def test_precision_boundary_and_zero_coordinates(self):
        for accuracy, expected in [(1000, False), (1001, True), (None, True), (0, False)]:
            self.assertEqual(location_needs_retry({"latitude": 0, "longitude": 0,
                                                  "accuracy_m": accuracy}), expected)

    def test_distance_spans_degrees_and_missing_coordinates(self):
        self.assertAlmostEqual(
            distance_meters({"latitude": 31, "longitude": 118}, {"latitude": 32, "longitude": 118}),
            111195.1,
            places=1,
        )
        self.assertEqual(distance_meters({"latitude": 31, "longitude": 118}, {"latitude": 31}), None)

    def test_untrusted_fix_yields_to_a_contradicting_reading(self):
        # 浦口汤泉 ±2000 米，实际人在江宁：两次定位隔了几十公里，旧的那次必然是错的。
        coarse = {"latitude": 32.13, "longitude": 118.49, "accuracy_m": 2000,
                  "formatted_address": "江苏省南京市浦口区汤泉街道"}
        for latitude, longitude, accuracy, expected in [
            (31.95, 118.84, 2500, True),
            (31.95, 118.84, 20, True),
            (32.131, 118.491, 2500, False),
            (32.131, 118.491, 20, True),
        ]:
            with self.subTest(longitude=longitude, accuracy=accuracy):
                self.assertIs(
                    better_location(coarse, {"latitude": latitude, "longitude": longitude,
                                             "accuracy_m": accuracy, "formatted_address": "江苏省南京市江宁区"}),
                    expected,
                )

    def test_trusted_fix_and_incomplete_reading_stay_untouched(self):
        far = {"latitude": 31.95, "longitude": 118.84, "accuracy_m": 20, "formatted_address": "江宁"}
        trusted = {"latitude": 32.13, "longitude": 118.49, "accuracy_m": 50, "formatted_address": "浦口"}
        coarse = {"latitude": 32.13, "longitude": 118.49, "accuracy_m": 2000, "formatted_address": "浦口"}
        self.assertFalse(better_location(trusted, far))
        self.assertFalse(better_location(coarse, dict(far, formatted_address="")))
        self.assertTrue(better_location({}, far))
