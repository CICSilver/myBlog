import unittest
from pathlib import Path


class EditorMobileInputTest(unittest.TestCase):
    def setUp(self):
        self.template = Path(__file__).resolve().parents[1] / "templates" / "edit.html"
        self.source = self.template.read_text(encoding="utf-8")

    def test_mobile_editor_forces_textarea_input_before_initialization(self):
        override_index = self.source.index("CodeMirror.defaults.inputStyle = 'textarea'")
        editor_index = self.source.index("editor = editormd")

        self.assertLess(override_index, editor_index)
        self.assertIn("let editor = null", self.source)
        self.assertIn("autoLoadModules: false", self.source)

    def test_codemirror_assets_are_loaded_by_template(self):
        self.assertIn("vendor/editor.md/lib/codemirror/codemirror.min.css", self.source)
        self.assertIn("vendor/editor.md/lib/codemirror/addon/dialog/dialog.css", self.source)
        self.assertIn("vendor/editor.md/lib/codemirror/addon/search/matchesonscrollbar.css", self.source)
        self.assertIn("vendor/editor.md/lib/codemirror/codemirror.min.js", self.source)
        self.assertIn("vendor/editor.md/lib/codemirror/modes.min.js", self.source)
        self.assertIn("vendor/editor.md/lib/codemirror/addons.min.js", self.source)


if __name__ == "__main__":
    unittest.main()
