"""Application-wide Qt widget styling helpers."""


_THEME_MARKER = "/* FluoraPressee application theme */"


APPLICATION_STYLE_SHEET = f"""
{_THEME_MARKER}
QPushButton {{
    background-color: palette(button);
    color: palette(button-text);
    border: 1px solid palette(mid);
    border-bottom: 3px solid palette(dark);
    border-radius: 4px;
    padding: 5px 10px;
    min-height: 16px;
}}
QPushButton:hover:!pressed {{
    border-color: palette(highlight);
    border-bottom-color: palette(dark);
}}
QPushButton:pressed {{
    border-style: inset;
    border-bottom-width: 1px;
    padding-top: 7px;
    padding-bottom: 5px;
}}
QPushButton:focus {{
    border: 2px solid palette(highlight);
    border-bottom: 3px solid palette(highlight);
    padding: 4px 9px 5px 9px;
}}
QPushButton:disabled {{
    background-color: palette(midlight);
    color: palette(mid);
    border-color: palette(mid);
    border-bottom-color: palette(mid);
}}
"""


def apply_application_style(app):
    """Apply the shared theme once without discarding caller-provided QSS."""
    existing = app.styleSheet()
    if _THEME_MARKER not in existing:
        app.setStyleSheet(f"{existing}\n{APPLICATION_STYLE_SHEET}" if existing else APPLICATION_STYLE_SHEET)


def colored_button_style(enabled_style, disabled_style):
    """Return tactile button QSS while preserving the requested role colours."""
    return f"""
QPushButton {{
    {enabled_style}
    border: 1px solid rgba(0, 0, 0, 120);
    border-bottom: 3px solid rgba(0, 0, 0, 175);
    border-radius: 4px;
    padding: 5px 10px;
    min-height: 16px;
}}
QPushButton:hover:!pressed {{
    border-color: rgba(255, 255, 255, 210);
    border-bottom-color: rgba(0, 0, 0, 175);
}}
QPushButton:pressed {{
    border-style: inset;
    border-bottom-width: 1px;
    padding-top: 7px;
    padding-bottom: 5px;
}}
QPushButton:focus {{
    border: 2px solid #90CAF9;
    border-bottom: 3px solid #64B5F6;
    padding: 4px 9px 5px 9px;
}}
QPushButton:disabled {{
    {disabled_style}
    border: 1px solid #7A7A7A;
    border-bottom: 2px solid #707070;
}}
"""
