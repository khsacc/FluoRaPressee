import ast
from pathlib import Path
import unittest


class MainWindowShortcutTests(unittest.TestCase):
    def test_measurement_buttons_have_the_requested_shortcuts(self):
        source_path = Path(__file__).parents[1] / "src" / "ui" / "main_window.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        assignments = {}

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or len(node.args) != 1:
                continue
            if not isinstance(node.func, ast.Attribute) or node.func.attr != "setShortcut":
                continue
            owner = node.func.value
            shortcut = node.args[0]
            if (
                isinstance(owner, ast.Attribute)
                and isinstance(shortcut, ast.Call)
                and isinstance(shortcut.func, ast.Name)
                and shortcut.func.id == "QKeySequence"
                and len(shortcut.args) == 1
                and isinstance(shortcut.args[0], ast.Constant)
            ):
                assignments[owner.attr] = shortcut.args[0].value

        self.assertEqual(assignments.get("btn_single"), "F5")
        self.assertEqual(assignments.get("btn_acq_bg"), "Ctrl+B")
        self.assertEqual(assignments.get("btn_save_data"), "Ctrl+S")


if __name__ == "__main__":
    unittest.main()
