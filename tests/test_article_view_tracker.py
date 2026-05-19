import unittest
from pathlib import Path


class ArticleViewTrackerTest(unittest.TestCase):
    def setUp(self):
        project_root = Path(__file__).resolve().parents[1]
        self.detail_template = (project_root / "templates" / "blog_detail.html").read_text(
            encoding="utf-8"
        )
        self.tracker_source = (
            project_root / "static" / "js" / "article_view_tracker.js"
        ).read_text(encoding="utf-8")

    def test_detail_page_loads_tracker_only_when_tracking_config_exists(self):
        self.assertIn("{% if article_view_tracking %}", self.detail_template)
        self.assertIn("window.BLOG_ARTICLE_VIEW_TRACKING", self.detail_template)
        self.assertIn("js/article_view_tracker.js", self.detail_template)

    def test_tracker_waits_for_effective_visible_reading_time(self):
        self.assertIn("document.visibilityState === 'visible'", self.tracker_source)
        self.assertIn("seconds < minimumSeconds", self.tracker_source)
        self.assertIn("reading_seconds: seconds", self.tracker_source)
        self.assertIn("'X-CSRF-Token': window.BLOG_CSRF_TOKEN || ''", self.tracker_source)
        self.assertIn("keepalive: true", self.tracker_source)
        self.assertIn("view_session_id: viewSessionId", self.tracker_source)


if __name__ == "__main__":
    unittest.main()
