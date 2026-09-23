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
        self.calendar_template = (
            project_root / "templates" / "_diary_calendar.html"
        ).read_text(encoding="utf-8")
        self.milestone_template = (
            project_root / "templates" / "_diary_milestone.html"
        ).read_text(encoding="utf-8")
        self.calendar_stylesheet = (
            project_root / "static" / "css" / "diary-calendar.css"
        ).read_text(encoding="utf-8")
        self.calendar_javascript = (
            project_root / "static" / "js" / "diary-calendar.js"
        ).read_text(encoding="utf-8")

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
        self.assertIn("is_current_month", self.diary_template)
        self.assertIn('{% include "_diary_calendar.html" %}', self.diary_template)
        self.assertIn('{% include "_diary_milestone.html" %}', self.diary_template)
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
        self.assertIn("--diary-summary-line-step: 1.95rem", self.stylesheet)
        # 不支持 calc 变量时的兜底值也是 16 行：1.95rem × 16。
        self.assertIn("max-height: 31.2rem", self.stylesheet)
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

    def test_save_stays_on_diary_page_and_entries_link_to_detail(self):
        self.assertIn("window.location.reload();", self.javascript)
        self.assertNotIn("window.location.assign(result.data.detail_url)", self.javascript)
        self.assertIn("rememberStatus(message, tone)", self.javascript)
        self.assertIn("restoreStatus();", self.javascript)
        self.assertIn('<a class="diary-entry-link" href="{{ detail_url }}"', self.diary_template)
        self.assertIn(".diary-entry-link {", self.stylesheet)

    def test_complete_today_location_skips_a_second_geolocation_request(self):
        self.assertIn("{% set needs_location =", self.diary_template)
        self.assertIn("today_diary.location.latitude", self.diary_template)
        self.assertIn("today_diary.location.longitude", self.diary_template)
        self.assertIn('data-needs-location="{{ \'true\' if needs_location else \'false\' }}"', self.diary_template)
        self.assertIn('form.dataset.needsLocation !== "true"', self.javascript)

        skip_index = self.javascript.index('form.dataset.needsLocation !== "true"')
        geolocation_index = self.javascript.index("navigator.geolocation.getCurrentPosition")
        self.assertLess(skip_index, geolocation_index)

    def test_missing_original_coordinates_still_request_geolocation(self):
        self.assertIn("not today_diary.location.latitude", self.diary_template)
        self.assertIn("not today_diary.location.longitude", self.diary_template)
        self.assertIn("if (window.isSecureContext && navigator.geolocation)", self.javascript)
        self.assertIn("navigator.geolocation.getCurrentPosition", self.javascript)

    def test_diary_css_has_desktop_and_mobile_layout_rules(self):
        diary_styles = self.stylesheet.split("/* Diary */", 1)[1]

        self.assertIn(".diary-composer {", self.stylesheet)
        self.assertIn("grid-template-columns: minmax(0, 1fr)", self.stylesheet)
        self.assertIn("min-height: 200px", self.stylesheet)
        self.assertIn(".diary-entry.has-image", self.stylesheet)
        self.assertIn(".diary-entry.has-image {\n    grid-template-columns: var(--diary-date-col) minmax(0, 1fr) 168px", self.stylesheet)
        self.assertIn("@media (max-width: 767px)", self.stylesheet)
        self.assertIn(".diary-page .home-cover-kicker {\n        display: none", self.stylesheet)
        self.assertIn("--diary-line-step: 2rem", self.stylesheet)
        self.assertIn("line-height: var(--diary-line-step)", self.stylesheet)
        self.assertIn("background-size: 100% var(--diary-line-step)", self.stylesheet)
        self.assertIn("min-height: calc(var(--diary-line-step) * 7)", self.stylesheet)
        self.assertIn("background-attachment: local", self.stylesheet)
        self.assertIn("font-size: 16px", self.stylesheet)
        self.assertIn(".diary-detail-day {\n    color: var(--ink);\n    font-family: var(--font-latin);\n    font-size: 5.6rem", diary_styles)
        self.assertIn(".diary-detail-day {\n        font-size: 3.2rem", diary_styles)
        self.assertIn("var(--letter-rule) calc(var(--diary-line-step) - 1px)", diary_styles)
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

    def test_sidebar_calendar_replaces_the_week_strip_and_icons_are_shared(self):
        self.assertNotIn("diary-week-strip", self.diary_template)
        self.assertNotIn("diary-week", self.stylesheet)
        self.assertNotIn('type="month"', self.calendar_template)
        self.assertIn('<aside class="diary-side"', self.diary_template)
        self.assertIn('{% from "_diary_icons.html" import diary_icon %}', self.diary_template)
        self.assertIn('{% from "_diary_icons.html" import diary_icon %}', self.detail_template)
        self.assertIn('name == "clock"', self.icons_template)

    def test_visual_layout_keeps_desktop_compact_and_restores_mobile_writing_flow(self):
        mobile_styles = self.stylesheet.split("@media (max-width: 767px)", 1)[1]

        self.assertIn("Daily Notes", self.diary_template)
        self.assertIn("写下此刻", self.diary_template)
        self.assertIn("{{ today_date }} · {{ today_weekday }}", self.diary_template)
        self.assertIn('<header class="page-masthead diary-overview">', self.diary_template)
        self.assertIn('{{ page_seal("日记") }}', self.diary_template)
        self.assertIn(".diary-columns {\n    display: grid;\n    grid-template-columns: minmax(0, 1fr) 340px", self.stylesheet)
        self.assertIn(".diary-side {\n    position: sticky", self.stylesheet)
        self.assertIn(".diary-side {\n        position: static;\n        order: -1", mobile_styles)
        # 手机上整块卷头（题名和统计）都让给日历与写字那一行。
        self.assertIn(".diary-overview {\n        display: none", mobile_styles)
        self.assertIn(".diary-composer-date {\n    display: none", self.stylesheet)
        self.assertIn(".diary-composer-date {\n        display: flex", mobile_styles)
        textarea_index = self.diary_template.index('<textarea id="diary-content"')
        toolbar_index = self.diary_template.index('<div class="diary-editor-toolbar"')
        preview_index = self.diary_template.index('<div id="diary-image-preview-panel"')
        footer_index = self.diary_template.index('<div class="diary-form-footer">')
        self.assertLess(textarea_index, preview_index)
        self.assertLess(preview_index, footer_index)
        self.assertLess(footer_index, toolbar_index)
        self.assertIn('class="diary-image-button"', self.diary_template)
        self.assertNotIn("order: 2", mobile_styles)
        self.assertIn('textarea.value = ensureLeadingIndent(textarea.value);', self.javascript)
        self.assertIn('textarea.addEventListener("focus"', self.javascript)
        self.assertIn("border: 0", mobile_styles)
        self.assertIn("background: transparent", mobile_styles)

    def test_hidden_image_remove_control_is_not_rendered_visually(self):
        self.assertIn(
            ".diary-image-remove[hidden] {\n    display: none",
            self.stylesheet,
        )
        self.assertIn("{% if not existing_image %}hidden{% endif %}", self.diary_template)

    def test_calendar_card_collapses_with_a_height_transition_and_remembers_state(self):
        self.assertIn('data-calendar-collapse aria-expanded="true" aria-controls="diary-calendar-body"', self.calendar_template)
        self.assertIn('<div class="diary-calendar-body" id="diary-calendar-body">', self.calendar_template)
        self.assertIn("grid-template-rows: 1fr;", self.calendar_stylesheet)
        self.assertIn(".diary-calendar.is-collapsed .diary-calendar-body {\n    grid-template-rows: 0fr;", self.calendar_stylesheet)
        self.assertIn("transition: grid-template-rows 0.22s ease, opacity 0.22s ease;", self.calendar_stylesheet)
        self.assertIn("@media (prefers-reduced-motion: reduce)", self.calendar_stylesheet)
        self.assertIn('localStorage.getItem("diary-calendar:collapsed") === "1"', self.calendar_template)
        self.assertIn('localStorage.getItem("diary-calendar:mode") === "year"', self.calendar_template)
        self.assertIn('calendar.classList.add("is-static")', self.calendar_template)
        self.assertIn('calendar.classList.remove("is-static")', self.calendar_javascript)
        self.assertIn('remember(STORAGE_COLLAPSED, collapsed ? "1" : "0")', self.calendar_javascript)
        self.assertIn('remember(STORAGE_MODE, yearMode ? "year" : "month")', self.calendar_javascript)

    def test_calendar_has_month_and_year_views_and_mobile_keeps_this_week_when_collapsed(self):
        mobile_styles = self.calendar_stylesheet.split("@media (max-width: 767px)", 1)[1]

        self.assertIn('data-calendar-mode="month" aria-pressed="true"', self.calendar_template)
        self.assertIn('data-calendar-mode="year" aria-pressed="false"', self.calendar_template)
        self.assertIn('data-calendar-view="month"', self.calendar_template)
        self.assertIn('data-calendar-view="year"', self.calendar_template)
        self.assertIn("{% for week in month_calendar.weeks %}", self.calendar_template)
        self.assertIn("{% if week.current %} is-current-week{% endif %}", self.calendar_template)
        self.assertIn('href="#diary-editor"', self.calendar_template)
        self.assertIn("{% for month in year_overview %}", self.calendar_template)
        self.assertIn("url_for('main.diary', month=month.value)", self.calendar_template)
        self.assertIn('.diary-calendar.is-year [data-calendar-view="month"]', self.calendar_stylesheet)
        self.assertIn(".diary-month-week:not(.is-current-week) {\n        grid-template-rows: 0fr;", mobile_styles)
        self.assertIn("result.overview.forEach", self.calendar_javascript)
        self.assertNotIn("diary-activity-viewport", self.calendar_template)

    def test_milestone_shows_total_ratio_and_next_book(self):
        self.assertIn("milestone.total_number", self.milestone_template)
        self.assertIn("milestone.total_unit", self.milestone_template)
        self.assertIn("本《{{ milestone.last_title }}》", self.milestone_template)
        self.assertIn('role="progressbar"', self.milestone_template)
        self.assertIn('aria-valuenow="{{ milestone.percent }}"', self.milestone_template)
        self.assertIn("追上《{{ milestone.next_title }}》", self.milestone_template)
        self.assertIn("已经超过书单上的每一本", self.milestone_template)
        self.assertIn(".diary-milestone-bar span {", self.calendar_stylesheet)


if __name__ == "__main__":
    unittest.main()
