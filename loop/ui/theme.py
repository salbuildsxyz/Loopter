"""Design tokens, fonts, the palette, and the stylesheet for Loopter's dark interface.

Values come from the approved design's tokens (colors, type scale, spacing, radii, sizes,
and motion). Sizes are logical pixels. Text on the window background meets 4.5:1 contrast.
"""

from __future__ import annotations

import contextlib

from PySide6.QtCore import QEasingCurve, QPointF
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

# Neutrals
BG = "#0B0D12"  # window
SURFACE = "#12151C"  # lists, cards, segmented track
ELEVATED = "#191D27"  # controls, selected segment, toasts, key caps
HOVER = "#1F2430"  # hovered control fill
BORDER = "#2A2F3B"
BORDER_STRONG = "#353B49"
BORDER_SUBTLE = "#1E222C"
TEXT = "#F5F6FA"
TEXT_2 = "#959BAB"
TEXT_3 = "#7B8192"
TEXT_DISABLED = "#4A5060"
WHITE = "#FFFFFF"

# Accent and status, used sparingly
ACCENT = "#8B8CFF"
ACCENT_HOVER = "#A5A6FF"
SUCCESS = "#42C9A1"
WARNING = "#E5B567"
DANGER = "#F07178"

# Soft fills (12%) and line borders for each signal color
_SOFT_ALPHA = 0.12
_LINE_ALPHA = {ACCENT: 0.45, SUCCESS: 0.32, WARNING: 0.28, DANGER: 0.32}
SCRIM = QColor(4, 5, 8, round(0.66 * 255))
SHADE = QColor(6, 7, 10, round(0.55 * 255))  # dims the screenshot around a selection

# Type
TEXT_FAMILIES = ["Segoe UI Variable Text", "Segoe UI"]
DISPLAY_FAMILIES = ["Segoe UI Variable Display", "Segoe UI Variable Text", "Segoe UI"]
MONO_FAMILIES = ["Cascadia Mono", "Consolas"]

# Shape and size
R_XS, R_SM, R_MD, R_LG, R_XL = 4, 6, 8, 10, 12
H_CONTROL_SM, H_CONTROL, H_CONTROL_LG = 28, 32, 40
H_ROW = 40
H_TABS = 40
ICON_SM, ICON = 14, 16
WINDOW_WIDTH, WINDOW_HEIGHT = 480, 644  # client area; the native title bar adds the rest
MIN_WIDTH, MIN_HEIGHT = 480, 564

# Motion (ms)
DUR_1 = 150  # hover, color, small state
DUR_2 = 200  # toggles, selectors, text swaps, toasts
DUR_3 = 250  # pages, steps, modals, disclosures
DUR_EXIT = 140
DUR_PRESS = 100
PRESS_SCALE = 0.98
TOAST_HOLD = 2600


def bezier(x1: float, y1: float, x2: float, y2: float) -> QEasingCurve:
    curve = QEasingCurve(QEasingCurve.Type.BezierSpline)
    curve.addCubicBezierSegment(QPointF(x1, y1), QPointF(x2, y2), QPointF(1, 1))
    return curve


EASE_OUT = bezier(0.2, 0, 0, 1)  # entrances and hover
EASE_IN = bezier(0.4, 0, 1, 1)  # exits
EASE_MOVE = bezier(0.4, 0, 0.2, 1)  # anything that travels


def qcolor(color: str | QColor, alpha: float | None = None) -> QColor:
    result = QColor(color)
    if alpha is not None:
        result.setAlphaF(alpha)
    return result


def soft(color: str) -> QColor:
    return qcolor(color, _SOFT_ALPHA)


def line(color: str) -> QColor:
    return qcolor(color, _LINE_ALPHA[color])


def rgba(color: QColor) -> str:
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {color.alphaF():.2f})"


def mix(a: QColor | str, b: QColor | str, t: float) -> QColor:
    """Linear blend from a to b; t is clamped to 0..1."""
    a, b = QColor(a), QColor(b)
    t = min(max(t, 0.0), 1.0)
    return QColor.fromRgbF(
        a.redF() + (b.redF() - a.redF()) * t,
        a.greenF() + (b.greenF() - a.greenF()) * t,
        a.blueF() + (b.blueF() - a.blueF()) * t,
        a.alphaF() + (b.alphaF() - a.alphaF()) * t,
    )


def font(
    size: int = 13,
    weight: int = 400,
    *,
    display: bool = False,
    mono: bool = False,
    caps: bool = False,
    tabular: bool = False,
) -> QFont:
    result = QFont()
    result.setFamilies(MONO_FAMILIES if mono else DISPLAY_FAMILIES if display else TEXT_FAMILIES)
    result.setPixelSize(size)
    result.setWeight(QFont.Weight(weight))
    # Segoe UI Variable has no named Medium instance, so 500 needs the weight axis itself.
    with contextlib.suppress(AttributeError, TypeError):
        result.setVariableAxis(QFont.Tag("wght"), weight)
    result.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    if display:
        result.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 99)
    if caps:
        result.setCapitalization(QFont.Capitalization.AllUppercase)
        result.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, size * 0.06)
    if tabular:
        _enable_tabular_numbers(result)
    return result


def _enable_tabular_numbers(f: QFont) -> None:
    # Font features need Qt 6.6 or later; Segoe UI digits are tabular already.
    with contextlib.suppress(AttributeError, TypeError):
        f.setFeature(QFont.Tag("tnum"), 1)


# Text roles: (size, weight, color, extra font options)
ROLES: dict[str, tuple[int, int, str, dict[str, bool]]] = {
    "status": (22, 600, TEXT, {"display": True}),
    "title-lg": (22, 600, TEXT, {"display": True}),
    "title": (20, 600, TEXT, {"display": True}),
    "modal-title": (16, 600, TEXT, {"display": True}),
    "lede": (14, 400, TEXT_2, {}),
    "body": (13, 400, TEXT, {}),
    "body-2": (13, 400, TEXT_2, {}),
    "row-title": (13, 500, TEXT, {}),
    "help": (12, 400, TEXT_2, {}),
    "caption": (12, 400, TEXT_3, {}),
    "label": (11, 500, TEXT_3, {"caps": True}),
    "stat-label": (11, 400, TEXT_3, {}),
    "stat": (16, 500, TEXT, {"tabular": True}),
    "brand": (12, 500, TEXT, {}),
    "mono": (11, 400, TEXT_2, {"mono": True}),
    "time": (11, 400, TEXT_3, {"mono": True}),
}
TONES = {"ok": SUCCESS, "warn": WARNING, "error": DANGER, "accent": ACCENT, "off": TEXT_3, "strong": TEXT}


def role_font(role: str) -> QFont:
    size, weight, _color, options = ROLES[role]
    return font(size, weight, **options)


def apply(app: QApplication) -> None:
    """Applies the style, palette, default font, and stylesheet to the application."""
    app.setStyle("Fusion")
    app.setFont(font(13))
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: BG,
        QPalette.ColorRole.WindowText: TEXT,
        QPalette.ColorRole.Base: ELEVATED,
        QPalette.ColorRole.AlternateBase: SURFACE,
        QPalette.ColorRole.Text: TEXT,
        QPalette.ColorRole.Button: ELEVATED,
        QPalette.ColorRole.ButtonText: TEXT,
        QPalette.ColorRole.Highlight: ACCENT,
        QPalette.ColorRole.HighlightedText: BG,
        QPalette.ColorRole.ToolTipBase: ELEVATED,
        QPalette.ColorRole.ToolTipText: TEXT,
        QPalette.ColorRole.PlaceholderText: TEXT_3,
        QPalette.ColorRole.Link: ACCENT,
    }
    for role, color in roles.items():
        palette.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(TEXT_DISABLED))
    app.setPalette(palette)
    app.setStyleSheet(stylesheet())


def stylesheet() -> str:
    role_rules = "\n".join(
        f'QLabel[role="{name}"] {{ color: {color}; }}' for name, (_, _, color, _) in ROLES.items()
    )
    tone_rules = "\n".join(f'QLabel[tone="{name}"] {{ color: {color}; }}' for name, color in TONES.items())
    return f"""
QMainWindow, QWidget#Root {{ background: {BG}; }}
QLabel {{ background: transparent; }}
{role_rules}
{tone_rules}
QToolTip {{
    background: {ELEVATED};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: {R_SM}px;
    padding: 4px 8px;
    font-size: 12px;
}}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 2px;
    min-height: 32px;
    margin: 2px 3px;
}}
QScrollBar::handle:vertical:hover {{ background: {BORDER_STRONG}; }}
QScrollBar:horizontal {{ height: 0; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

QComboBox {{
    background: {ELEVATED};
    border: 1px solid {BORDER};
    border-radius: {R_MD}px;
    padding: 0 30px 0 10px;
    min-height: {H_CONTROL - 2}px;
    max-height: {H_CONTROL - 2}px;
    font-size: 12px;
    color: {TEXT};
}}
QComboBox:hover {{ background: {HOVER}; border-color: {BORDER_STRONG}; }}
QComboBox:focus {{ border-color: {rgba(line(ACCENT))}; }}
QComboBox:disabled {{ color: {TEXT_DISABLED}; background: {SURFACE}; border-color: {BORDER_SUBTLE}; }}
QComboBox::drop-down {{ border: none; width: 0; }}
QComboBox::down-arrow {{ image: none; width: 0; }}
QComboBox QAbstractItemView {{
    background: {ELEVATED};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 4px;
    outline: none;
    selection-background-color: {HOVER};
    selection-color: {TEXT};
}}
QMenu {{
    background: {ELEVATED};
    border: 1px solid {BORDER};
    border-radius: {R_MD}px;
    padding: 4px;
    color: {TEXT};
    font-size: 12px;
}}
QMenu::item {{ padding: 6px 12px; border-radius: {R_SM}px; }}
QMenu::item:selected {{ background: {HOVER}; }}
QMenu::item:disabled {{ color: {TEXT_DISABLED}; }}
QMenu::separator {{ height: 1px; background: {BORDER_SUBTLE}; margin: 4px 6px; }}
QMessageBox {{ background: {SURFACE}; }}
"""
