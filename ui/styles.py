"""Fonts, colors, and cached CSS stylesheets."""

import os

from PyQt5.QtGui import QColor, QFont, QFontDatabase

from utils import resource_path

# ── Fonts ──

_FONT_DIR = resource_path("fonts")
_FONTS = {
    "app":   os.path.join(_FONT_DIR, "GTA Russian.ttf"),
    "pixel": os.path.join(_FONT_DIR, "web_ibm_mda.ttf"),
}
_font_families: dict[str, str | None] = {"app": None, "pixel": None}


def load_fonts():
    for key, path in _FONTS.items():
        if os.path.isfile(path) and _font_families[key] is None:
            fid = QFontDatabase.addApplicationFont(path)
            if fid >= 0:
                fams = QFontDatabase.applicationFontFamilies(fid)
                if fams:
                    _font_families[key] = fams[0]


def _make_font(key: str, size: int) -> QFont:
    family = _font_families.get(key)
    f = QFont(family) if family else QFont("Consolas" if key == "pixel" else "")
    f.setPixelSize(size)
    return f


def app_font(size: int) -> QFont:
    return _make_font("app", size)


def pixel_font(size: int) -> QFont:
    return _make_font("pixel", size)


# ── Colors ──

COLOR_RED    = QColor(200, 70, 70)
COLOR_YELLOW = QColor(220, 180, 50)
COLOR_GREEN  = QColor(80, 200, 80)

# ── Cached stylesheets ──

_btn_css = None
_input_css = None


def button_style():
    global _btn_css
    if _btn_css is None:
        ff = f"font-family: '{_font_families['app']}';" if _font_families["app"] else ""
        _btn_css = f"""
            QPushButton {{
                background: rgb(32,32,38); color: rgb(240,240,240);
                border: 1px solid rgba(255,255,255,20); border-radius: 5px;
                padding: 5px; font-size: 27px; {ff}
            }}
            QPushButton:hover {{ background: rgb(44,44,52); }}
        """
    return _btn_css


def input_style():
    global _input_css
    if _input_css is None:
        ff = f"font-family: '{_font_families['app']}';" if _font_families["app"] else ""
        _input_css = f"""
            QLineEdit {{
                background: rgb(32,32,38); color: rgb(240,240,240);
                border: 1px solid rgba(255,255,255,20); border-radius: 5px;
                padding: 3px; font-size: 27px; {ff}
            }}
            QLineEdit:disabled {{
                color: rgb(120,120,120); background: rgb(28,28,34);
            }}
        """
    return _input_css


def gated_border_style(color_rgb: str) -> str:
    ff = f"font-family: '{_font_families['app']}';" if _font_families.get("app") else ""
    return f"""
        QPushButton {{
            background: rgb(32,32,38); color: rgb(240,240,240);
            border: 1px solid {color_rgb}; border-radius: 5px;
            padding: 5px; font-size: 27px; {ff}
        }}
        QPushButton:hover {{ background: rgb(44,44,52); }}
    """
