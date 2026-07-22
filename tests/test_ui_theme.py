import unittest

from src.ui_theme import apply_application_style, colored_button_style


class _FakeApplication:
    def __init__(self, style=""):
        self._style = style

    def styleSheet(self):
        return self._style

    def setStyleSheet(self, style):
        self._style = style


class UiThemeTests(unittest.TestCase):
    def test_application_theme_is_additive_and_idempotent(self):
        app = _FakeApplication("QLabel { color: red; }")

        apply_application_style(app)
        apply_application_style(app)

        self.assertIn("QLabel { color: red; }", app.styleSheet())
        self.assertEqual(app.styleSheet().count("FluoraPressee application theme"), 1)
        self.assertIn("QPushButton:pressed", app.styleSheet())
        self.assertIn("QPushButton:focus", app.styleSheet())
        self.assertIn("QPushButton:disabled", app.styleSheet())

    def test_colored_button_style_has_tactile_states(self):
        style = colored_button_style(
            "background-color: blue; color: white;",
            "background-color: gray; color: white;",
        )

        self.assertIn("background-color: blue", style)
        self.assertIn("border-bottom: 3px", style)
        self.assertIn("QPushButton:hover:!pressed", style)
        self.assertIn("QPushButton:pressed", style)
        self.assertIn("QPushButton:focus", style)
        self.assertIn("QPushButton:disabled", style)


if __name__ == "__main__":
    unittest.main()
