"""Import pyLabLib device modules without activating its optional Qt5 GUI.

The standard pyLabLib distribution provides current Python/Windows wheels for
the camera drivers, but its package initializer opportunistically imports
PyQt5. FluoraPressee only uses the device layer, so loading that second Qt
binding into the PyQt6 process is unnecessary and unsafe.
"""

from contextlib import contextmanager
import importlib
from importlib.abc import MetaPathFinder
import sys


_BLOCKED_BINDINGS = ("PyQt5", "PySide2")


class _BlockLegacyQtFinder(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in _BLOCKED_BINDINGS or fullname.startswith(
            tuple(f"{binding}." for binding in _BLOCKED_BINDINGS)
        ):
            raise ModuleNotFoundError(
                f"{fullname} is disabled: FluoraPressee uses only pyLabLib's device layer"
            )
        return None


@contextmanager
def _without_legacy_qt():
    already_loaded = [
        # Import hooks and extension modules may populate sys.modules from a
        # helper thread while API/Qt modules are loading. Iterate a stable
        # snapshot so this guard itself cannot raise "dictionary changed size".
        name for name in list(sys.modules)
        if name in _BLOCKED_BINDINGS
        or name.startswith(tuple(f"{binding}." for binding in _BLOCKED_BINDINGS))
    ]
    if already_loaded:
        raise RuntimeError(
            "A legacy Qt binding was loaded before pyLabLib's device layer: "
            + ", ".join(sorted(already_loaded))
        )

    finder = _BlockLegacyQtFinder()
    sys.meta_path.insert(0, finder)
    try:
        yield
    finally:
        sys.meta_path.remove(finder)


def import_pylablib_module(module_name):
    """Import and return a pyLabLib module while its Qt5 GUI is disabled."""
    if module_name != "pylablib" and not module_name.startswith("pylablib."):
        raise ValueError(f"Not a pyLabLib module: {module_name}")
    with _without_legacy_qt():
        return importlib.import_module(module_name)
