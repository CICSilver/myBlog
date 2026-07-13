import unittest
from pathlib import Path


class EditorMobileInputTest(unittest.TestCase):
    def setUp(self):
        project_root = Path(__file__).resolve().parents[1]
        self.template = project_root / "templates" / "edit.html"
        self.stylesheet = project_root / "static" / "css" / "style.css"
        self.source = self.template.read_text(encoding="utf-8")
        self.css_source = self.stylesheet.read_text(encoding="utf-8")

    def test_mobile_editor_forces_textarea_input_before_initialization(self):
        override_index = self.source.index("CodeMirror.defaults.inputStyle = 'textarea'")
        editor_index = self.source.index("editor = editormd")

        self.assertLess(override_index, editor_index)
        self.assertIn("let editor = null", self.source)
        self.assertIn("autoLoadModules: false", self.source)

    def test_enter_preserves_chinese_paragraph_indent(self):
        self.assertIn("editorInstance.cm.addKeyMap", self.source)
        self.assertIn("Enter: continueChineseParagraphIndent", self.source)
        self.assertIn("return CodeMirror.Pass", self.source)
        self.assertIn("lineText.startsWith(CHINESE_PARAGRAPH_INDENT)", self.source)
        self.assertIn("cm.replaceRange('\\n' + CHINESE_PARAGRAPH_INDENT", self.source)

    def test_editor_toolbar_hides_unused_buttons(self):
        for icon in ["emoji", "goto-line", "preview", "search", "help", "info"]:
            self.assertIn(f"'{icon}'", self.source)

        self.assertIn("HIDDEN_EDITOR_TOOLBAR_ICONS", self.source)
        self.assertIn("compactToolbarIcons(editormd.toolbarModes.full)", self.source)
        self.assertIn("icon === '|'", self.source)

    def test_codemirror_assets_are_loaded_by_template(self):
        self.assertIn("vendor/editor.md/lib/codemirror/codemirror.min.css", self.source)
        self.assertIn("vendor/editor.md/lib/codemirror/addon/dialog/dialog.css", self.source)
        self.assertIn("vendor/editor.md/lib/codemirror/addon/search/matchesonscrollbar.css", self.source)
        self.assertIn("vendor/editor.md/lib/codemirror/codemirror.min.js", self.source)
        self.assertIn("vendor/editor.md/lib/codemirror/modes.min.js", self.source)
        self.assertIn("vendor/editor.md/lib/codemirror/addons.min.js", self.source)

    def test_mobile_native_textarea_is_synced_to_existing_submit_path(self):
        self.assertIn("class=\"mobile-editor-shell\"", self.source)
        self.assertIn("class=\"mobile-editor-toolbar\"", self.source)
        self.assertIn('id="mobile-markdown-editor"', self.source)
        self.assertIn("class=\"mobile-markdown-editor\"", self.source)
        self.assertIn("is-mobile-native-editor", self.source)
        self.assertIn("shouldUseMobileNativeEditor", self.source)
        self.assertIn("navigator.maxTouchPoints > 0", self.source)
        self.assertIn("syncCodeMirrorFromMobileNativeEditor", self.source)
        self.assertIn("hiddenTextarea.value = mobileMarkdownEditor.value", self.source)
        self.assertIn("editor.cm.setValue(mobileMarkdownEditor.value)", self.source)
        self.assertIn("wasNativeEditor && !useNativeEditor", self.source)

    def test_mobile_editor_shell_has_expected_toolbar_actions(self):
        expected_actions = [
            "bold",
            "italic",
            "quote",
            "unordered-list",
            "heading-2",
            "chinese-indent",
            "image",
        ]

        self.assertEqual(self.source.count("data-mobile-editor-action="), len(expected_actions))
        for action in expected_actions:
            self.assertIn(f'data-mobile-editor-action="{action}"', self.source)

        self.assertIn("handleMobileEditorToolbarAction", self.source)
        self.assertIn("applyMobileInlineMarkdown('**', '**', '加粗文本')", self.source)
        self.assertIn("applyMobileInlineMarkdown('*', '*', '斜体文本')", self.source)
        self.assertIn("applyMobileLinePrefix(action)", self.source)
        self.assertIn("missingChineseIndentPrefix(lineText)", self.source)
        self.assertIn("finishMobileNativeEdit", self.source)

    def test_mobile_image_button_uploads_and_inserts_at_saved_caret(self):
        self.assertIn('id="mobile-image-button"', self.source)
        self.assertIn('data-mobile-editor-action="image"', self.source)
        self.assertIn('id="mobile-article-image-file"', self.source)
        self.assertIn('accept="image/*"', self.source)
        self.assertIn("articleImageSelectionStart = mobileMarkdownEditor.selectionStart", self.source)
        self.assertIn("formData.append('article-image', file)", self.source)
        self.assertIn("url_for('main.upload_article_image')", self.source)
        self.assertIn("insertArticleImageMarkdown(data.image_url, file.name)", self.source)
        self.assertIn("mobileMarkdownEditor.value = before + replacement + after", self.source)
        self.assertIn("finishMobileNativeEdit(caret, caret)", self.source)
        self.assertIn("isArticleImageUploading", self.source)

    def test_mobile_native_textarea_keeps_system_text_selection_available(self):
        self.assertIn(".mobile-editor-shell", self.css_source)
        self.assertIn(".editor-stage.is-mobile-native-editor .mobile-editor-shell", self.css_source)
        self.assertIn("display: flex", self.css_source)
        self.assertIn(".editor-stage.is-mobile-native-editor .mobile-markdown-editor", self.css_source)
        self.assertIn("-webkit-user-select: text", self.css_source)
        self.assertIn("user-select: text", self.css_source)
        self.assertIn("-webkit-touch-callout: default", self.css_source)
        self.assertIn("touch-action: auto", self.css_source)
        self.assertIn(".editor-stage.is-mobile-native-editor .CodeMirror", self.css_source)
        self.assertIn("display: none !important", self.css_source)


if __name__ == "__main__":
    unittest.main()
