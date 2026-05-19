import unittest

from app.view_filter import (
    is_crawler_user_agent,
    is_effective_reading_seconds,
    normalize_reading_seconds,
)


class ViewFilterTest(unittest.TestCase):
    def test_detects_common_crawler_and_script_user_agents(self):
        for user_agent in (
            "Mozilla/5.0 (compatible; bingbot/2.0)",
            "msnbot-40-77-167-123",
            "curl/8.13.0",
            "Go-http-client/1.1",
            "python-requests/2.32.0",
        ):
            with self.subTest(user_agent=user_agent):
                self.assertTrue(is_crawler_user_agent(user_agent))

    def test_allows_ordinary_browser_user_agent(self):
        self.assertFalse(
            is_crawler_user_agent(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0"
            )
        )

    def test_effective_reading_seconds_starts_at_fifteen_seconds(self):
        self.assertFalse(is_effective_reading_seconds(14))
        self.assertTrue(is_effective_reading_seconds(15))
        self.assertEqual(normalize_reading_seconds(-1), 0)


if __name__ == "__main__":
    unittest.main()
