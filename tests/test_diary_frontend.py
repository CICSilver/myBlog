import unittest
from pathlib import Path


class DiaryFrontendTest(unittest.TestCase):
    def setUp(self):
        project_root = Path(__file__).resolve().parents[1]
        self.diary_template = (project_root / "templates" / "diary.html").read_text(
            encoding="utf-8"
        )
        self.detail_template = (
            project_root / "templates" / "diary_detail.html"
        ).read_text(encoding="utf-8")
        self.icons_template = (
            project_root / "templates" / "_diary_icons.html"
        ).read_text(encoding="utf-8")
        self.header_template = (
            project_root / "templates" / "_site_header.html"
        ).read_text(encoding="utf-8")
        self.index_template = (project_root / "templates" / "index.html").read_text(
            encoding="utf-8"
        )
        self.javascript = (project_root / "static" / "js" / "diary.js").read_text(
            encoding="utf-8"
        )
        self.stylesheet = (project_root / "static" / "css" / "style.css").read_text(
            encoding="utf-8"
        )

    def test_diary_template_keeps_the_route_and_form_contract(self):
        self.assertIn('id="diary-form"', self.diary_template)
        self.assertIn("url_for('main.diary')", self.diary_template)
        self.assertIn('enctype="multipart/form-data"', self.diary_template)
        self.assertIn('name="content"', self.diary_template)
        self.assertIn('name="diary-image"', self.diary_template)
        for field_name in ["remove-image", "latitude", "longitude", "accuracy"]:
            self.assertIn('name="{0}"'.format(field_name), self.diary_template)

        self.assertIn("today_date", self.diary_template)
        self.assertIn("today_weekday", self.diary_template)
        self.assertIn("today_diary", self.diary_template)
        self.assertIn("current_week", self.diary_template)
        self.assertIn("is_current_month", self.diary_template)
        self.assertIn("week_day.detail_url", self.diary_template)
        self.assertIn("{% if week_day.detail_url %}", self.diary_template)
        self.assertIn("{% if is_current_month %}", self.diary_template)
        self.assertIn("更新日记", self.diary_template)
        self.assertIn("存入日记", self.diary_template)

    def test_templates_use_the_private_diary_media_endpoint(self):
        endpoint = "url_for('main.media_diary_image', filename="

        self.assertIn(endpoint, self.diary_template)
        self.assertIn(endpoint, self.detail_template)
        self.assertIn("diary.image_url", self.diary_template)
        self.assertIn("diary.image_url", self.detail_template)

    def test_diary_has_no_mood_field(self):
        combined_source = "\n".join(
            [self.diary_template, self.detail_template, self.javascript, self.stylesheet]
        ).lower()

        self.assertNotIn("mood", combined_source)
        self.assertNotIn("心情", combined_source)

    def test_plain_text_indent_uses_beforeinput_and_keydown_fallback(self):
        self.assertIn('addEventListener("beforeinput"', self.javascript)
        self.assertIn('event.inputType !== "insertLineBreak"', self.javascript)
        self.assertIn('event.inputType !== "insertParagraph"', self.javascript)
        self.assertIn('addEventListener("keydown"', self.javascript)
        self.assertIn('event.key !== "Enter"', self.javascript)
        self.assertIn('textarea.setRangeText(replacement', self.javascript)
        self.assertIn('replacement = "\\n　　"', self.javascript)
        self.assertIn('lineBeforeCaret === "　　"', self.javascript)
        self.assertIn('addEventListener("compositionstart"', self.javascript)
        self.assertIn('addEventListener("compositionend"', self.javascript)
        self.assertIn("supportsBeforeInput", self.javascript)

    def test_summary_is_limited_to_sixteen_lines_and_expands_only_when_needed(self):
        self.assertIn("--diary-summary-line-step", self.stylesheet)
        self.assertIn("max-height: 28.48rem", self.stylesheet)
        self.assertIn("max-height: calc(var(--diary-summary-line-step) * 16)", self.stylesheet)
        self.assertIn("white-space: pre-wrap", self.stylesheet)
        self.assertIn("inner.scrollHeight > outer.clientHeight", self.javascript)
        self.assertIn("readMore.hidden = false", self.javascript)
        self.assertIn('data-diary-read-more hidden', self.diary_template)
        self.assertIn("阅读全文", self.diary_template)

    def test_summary_initializes_without_the_editor_and_refreshes_on_resize(self):
        refresh_index = self.javascript.index("refreshDiarySummaries();")
        form_index = self.javascript.index('const form = document.getElementById("diary-form")')

        self.assertLess(refresh_index, form_index)
        self.assertIn("function refreshDiarySummaries()", self.javascript)
        self.assertIn('window.addEventListener("resize", refreshDiarySummaries)', self.javascript)
        self.assertIn("readMore.hidden = true", self.javascript)

    def test_geolocation_failure_does_not_block_submission(self):
        self.assertIn("window.isSecureContext && navigator.geolocation", self.javascript)
        self.assertIn("navigator.geolocation.getCurrentPosition", self.javascript)
        self.assertIn("enableHighAccuracy: true", self.javascript)
        self.assertIn("timeout: 10000", self.javascript)
        self.assertIn("maximumAge: 0", self.javascript)
        self.assertIn("未取得定位，仍会保存日记。", self.javascript)
        self.assertIn("当前环境无法定位，仍会保存日记。", self.javascript)
        self.assertGreaterEqual(self.javascript.count("sendForm();"), 3)
        self.assertIn('"X-CSRF-Token": window.BLOG_CSRF_TOKEN || ""', self.javascript)
        self.assertNotIn("apiKey", self.javascript)

    def test_diary_css_has_desktop_and_mobile_layout_rules(self):
        diary_styles = self.stylesheet.split("/* Diary */", 1)[1]

        self.assertIn(".diary-composer {", self.stylesheet)
        self.assertIn("grid-template-columns: 186px minmax(0, 1fr)", self.stylesheet)
        self.assertIn(".diary-entry.has-image", self.stylesheet)
        self.assertIn("grid-template-columns: 160px minmax(0, 1fr) 176px", self.stylesheet)
        self.assertIn("@media (max-width: 767px)", self.stylesheet)
        self.assertIn(".diary-page .home-cover-plum", self.stylesheet)
        self.assertIn("left: -30px", self.stylesheet)
        self.assertIn("--diary-line-step: 2rem", self.stylesheet)
        self.assertIn("line-height: var(--diary-line-step)", self.stylesheet)
        self.assertIn("background-size: 100% var(--diary-line-step)", self.stylesheet)
        self.assertIn("min-height: calc(var(--diary-line-step) * 12)", self.stylesheet)
        self.assertIn("background-attachment: local", self.stylesheet)
        self.assertIn("font-size: 16px", self.stylesheet)
        self.assertIn("font-size: 5.6rem", diary_styles)
        self.assertIn("font-size: 3.2rem", diary_styles)
        self.assertNotIn("font-size: clamp(", diary_styles)

    def test_shared_header_title_is_optional_for_other_pages(self):
        self.assertIn(
            '{% set cover_section_title = site_cover_section_title | default("") %}',
            self.header_template,
        )
        self.assertIn("{% if cover_section_title %}", self.header_template)
        self.assertIn("home-cover-section-title", self.header_template)
        self.assertIn('{% include "_site_header.html" %}', self.index_template)
        self.assertNotIn("site_cover_section_title", self.index_template)
        self.assertIn(".diary-page .home-cover-section-title {\n    display: none", self.stylesheet)
        self.assertIn(".diary-page .home-cover-section-title {\n        display: inline-flex", self.stylesheet)

    def test_detail_template_exposes_weather_location_and_adjacent_entries(self):
        self.assertIn("diary.weather.condition", self.detail_template)
        self.assertIn("diary.weather.temperature_c", self.detail_template)
        self.assertIn("diary.weather.report_time", self.detail_template)
        self.assertIn("diary.location.formatted_address", self.detail_template)
        self.assertIn("diary.location.poi_name", self.detail_template)
        self.assertIn("diary.location.accuracy_m", self.detail_template)
        self.assertIn("diary.location and diary.location.formatted_address", self.detail_template)
        self.assertIn("首次发表时间", self.detail_template)
        self.assertIn('diary_icon("clock")', self.detail_template)
        self.assertIn("previous_diary", self.detail_template)
        self.assertIn("next_diary", self.detail_template)
        self.assertIn("{% if is_today %}", self.detail_template)
        self.assertIn("编辑今天", self.detail_template)

    def test_list_uses_day_weekday_time_and_main_before_optional_image(self):
        main_index = self.diary_template.index('<div class="diary-entry-main">')
        image_index = self.diary_template.index('<a class="diary-entry-image"')

        self.assertIn("diary.entry_date[8:10]", self.diary_template)
        self.assertIn("diary.entry_date[5:7]", self.diary_template)
        self.assertIn("diary.weekday_label", self.diary_template)
        self.assertIn("diary.created_at[11:16]", self.diary_template)
        self.assertIn('diary_icon("clock")', self.diary_template)
        self.assertLess(main_index, image_index)
        self.assertIn("diary.location.province", self.diary_template)
        self.assertIn(
            "diary.location and (diary.location.city or diary.location.district or diary.location.province)",
            self.diary_template,
        )

    def test_week_strip_is_current_month_only_and_icons_are_shared(self):
        self.assertIn(
            '{% if is_current_month %}\n      <nav class="diary-week-strip"',
            self.diary_template,
        )
        self.assertIn('{% from "_diary_icons.html" import diary_icon %}', self.diary_template)
        self.assertIn('{% from "_diary_icons.html" import diary_icon %}', self.detail_template)
        self.assertIn('name == "clock"', self.icons_template)


if __name__ == "__main__":
    unittest.main()
