"""Design tokens and the application stylesheet.

The values follow LOOP's design system: three near-black surfaces, one lavender
accent, Segoe UI for text and Cascadia Mono for numbers. Sizes are logical pixels.
"""

BG_0 = "#111114"  # window and title strip
BG_1 = "#16161A"  # views
BG_2 = "#1D1D23"  # panels
BG_3 = "#26262E"  # raised controls
LINE = "#2A2A33"
LINE_2 = "#3A3A46"
FG_1 = "#EDEDF2"
FG_2 = "#B3B3C0"
FG_3 = "#8B8B99"
ACCENT = "#B4A8F5"
ACCENT_HOVER = "#C4BAF8"
ACCENT_INK = "#17142A"
OK = "#7FCF9F"
WARN = "#E5B766"
ERR = "#F08A82"

TEXT_FONTS = '"Segoe UI Variable Text", "Segoe UI", sans-serif'
DISPLAY_FONTS = '"Segoe UI Variable Display", "Segoe UI", sans-serif'
MONO_FONTS = '"Cascadia Mono", "Consolas", monospace'

WINDOW_WIDTH = 392
WINDOW_HEIGHT = 384


def tint(color: str, alpha: float) -> str:
    """The color as a translucent rgba() value, for soft backgrounds and borders."""
    r, g, b = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r}, {g}, {b}, {alpha})"


STYLESHEET = f"""
QWidget {{
    color: {FG_1};
    font-family: {TEXT_FONTS};
    font-size: 13px;
}}
QMainWindow, QWidget#View, QScrollArea, QScrollArea > QWidget > QWidget, QStackedWidget {{
    background: {BG_1};
}}
QWidget#TitleStrip {{
    background: {BG_0};
    border-bottom: 1px solid {LINE};
}}
QToolTip {{
    background: {BG_3};
    color: {FG_1};
    border: 1px solid {LINE_2};
    padding: 4px 6px;
}}

QLabel#Wordmark {{
    font-family: {DISPLAY_FONTS};
    font-size: 14px;
    font-weight: 600;
    letter-spacing: 2px;
}}
QLabel#Title {{ font-size: 16px; font-weight: 600; }}
QLabel#Timer {{
    font-family: {MONO_FONTS};
    font-size: 40px;
    font-weight: 500;
}}
QLabel#Timer[dim="true"] {{ color: {FG_3}; }}
QLabel#Numeral {{
    font-family: {MONO_FONTS};
    font-size: 20px;
    font-weight: 500;
}}
QLabel#Caption, QLabel#Help {{ color: {FG_3}; font-size: 12px; }}
QLabel#Secondary {{ color: {FG_2}; }}
QLabel#FieldLabel {{ font-size: 13px; }}
QLabel#SectionLabel {{
    color: {FG_3};
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 1px;
}}
QLabel#Error {{ color: {ERR}; font-size: 12px; }}
QLabel#Mono {{ font-family: {MONO_FONTS}; font-size: 12px; color: {FG_2}; }}

QLabel#Tag {{
    color: {FG_3};
    font-size: 11px;
    border: 1px solid {LINE_2};
    border-radius: 4px;
    padding: 0 6px;
}}
QLabel#Tag[kind="warn"] {{ color: {WARN}; border-color: {tint(WARN, 0.45)}; }}
QLabel#Kbd, QKeySequenceEdit#Kbd QLineEdit {{
    font-family: {MONO_FONTS};
    font-size: 12px;
    color: {FG_2};
    background: {BG_2};
    border: 1px solid {LINE_2};
    border-bottom-width: 2px;
    border-radius: 4px;
    padding: 1px 6px;
}}
QKeySequenceEdit#Kbd QLineEdit:focus {{ border-color: {ACCENT}; color: {FG_1}; }}

QFrame#Pill {{
    border-radius: 11px;
    border: 1px solid {LINE_2};
    background: {BG_2};
}}
QFrame#Pill QLabel {{ font-size: 12px; font-weight: 600; color: {FG_2}; }}
QFrame#Pill[state="running"] {{ border-color: {tint(OK, 0.4)}; background: {tint(OK, 0.1)}; }}
QFrame#Pill[state="running"] QLabel {{ color: {OK}; }}
QFrame#Pill[state="paused"] {{ border-color: {tint(WARN, 0.4)}; background: {tint(WARN, 0.1)}; }}
QFrame#Pill[state="paused"] QLabel {{ color: {WARN}; }}
QFrame#Pill[state="error"] {{ border-color: {tint(ERR, 0.4)}; background: {tint(ERR, 0.1)}; }}
QFrame#Pill[state="error"] QLabel {{ color: {ERR}; }}

QFrame#Panel {{
    background: {BG_2};
    border: 1px solid {LINE};
    border-radius: 8px;
}}
QFrame#Panel QLabel, QFrame#Notice QLabel {{ background: transparent; }}
QWidget#FieldRow[divided="true"] {{ border-top: 1px solid {LINE}; }}

QFrame#Notice {{ border-radius: 6px; border: 1px solid {LINE_2}; background: {BG_2}; }}
QFrame#Notice[kind="warn"] {{ border-color: {tint(WARN, 0.35)}; background: {tint(WARN, 0.08)}; }}
QFrame#Notice[kind="err"] {{ border-color: {tint(ERR, 0.35)}; background: {tint(ERR, 0.08)}; }}
QFrame#Notice[kind="ok"] {{ border-color: {tint(OK, 0.35)}; background: {tint(OK, 0.08)}; }}

QPushButton {{
    background: {BG_3};
    border: 1px solid {LINE_2};
    border-radius: 6px;
    padding: 0 12px;
    min-height: 30px;
    font-weight: 500;
}}
QPushButton:hover {{ background: #2E2E38; }}
QPushButton:pressed {{ background: {BG_2}; }}
QPushButton:disabled {{ color: {FG_3}; background: {BG_2}; border-color: {LINE}; }}
QPushButton:focus {{ outline: none; border-color: {ACCENT}; }}
QPushButton[size="sm"] {{ min-height: 26px; padding: 0 10px; font-size: 12px; }}
QPushButton[size="lg"] {{ min-height: 38px; font-size: 14px; font-weight: 600; }}
QPushButton[variant="primary"] {{ background: {ACCENT}; border-color: {ACCENT}; color: {ACCENT_INK}; }}
QPushButton[variant="primary"]:hover {{ background: {ACCENT_HOVER}; }}
QPushButton[variant="primary"]:focus {{ border-color: {FG_1}; }}
QPushButton[variant="primary"]:disabled {{
    background: {tint(ACCENT, 0.18)};
    border-color: transparent;
    color: {FG_3};
}}
QPushButton[variant="danger"] {{ color: {ERR}; border-color: {tint(ERR, 0.45)}; }}
QPushButton[variant="danger"]:hover {{ background: {tint(ERR, 0.12)}; }}
QPushButton[variant="warn"] {{
    background: {WARN};
    border-color: {WARN};
    color: {ACCENT_INK};
    font-weight: 600;
}}
QPushButton[variant="warn"]:disabled {{
    background: {tint(WARN, 0.18)};
    border-color: transparent;
    color: {FG_3};
}}
QPushButton[variant="ghost"] {{ background: transparent; border-color: transparent; color: {FG_2}; }}
QPushButton[variant="ghost"]:hover {{ background: {BG_3}; color: {FG_1}; }}
QPushButton[variant="ghost"]:focus {{ border-color: {ACCENT}; }}
QPushButton[variant="link"] {{
    background: transparent;
    border: none;
    color: {ACCENT};
    padding: 0;
    min-height: 0;
    font-size: 12px;
}}
QPushButton[variant="link"]:hover {{ text-decoration: underline; }}

QToolButton#IconButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 0;
}}
QToolButton#IconButton:hover {{ background: {BG_3}; }}
QToolButton#IconButton:focus {{ border-color: {ACCENT}; }}

QPushButton#ProfileLine {{
    background: transparent;
    border: 1px solid {LINE};
    border-radius: 6px;
    min-height: 28px;
    padding: 0 8px;
    text-align: left;
    color: {FG_2};
    font-size: 12px;
    font-weight: 400;
}}
QPushButton#ProfileLine:hover {{ background: {BG_2}; color: {FG_1}; }}
QPushButton#ProfileLine:focus {{ border-color: {ACCENT}; }}

QFrame#Seg {{
    background: {BG_0};
    border: 1px solid {LINE};
    border-radius: 6px;
}}
QFrame#Seg QPushButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    min-height: 24px;
    padding: 0 8px;
    color: {FG_3};
    font-size: 12px;
}}
QFrame#Seg QPushButton:hover {{ color: {FG_1}; }}
QFrame#Seg QPushButton:checked {{ background: {BG_3}; border-color: {LINE_2}; color: {FG_1}; }}
QFrame#Seg QPushButton[risk="true"]:checked {{
    background: {tint(WARN, 0.12)};
    border-color: {tint(WARN, 0.45)};
    color: {WARN};
}}
QFrame#Seg QPushButton:focus {{ border-color: {ACCENT}; }}
QFrame#Seg QPushButton:disabled {{ color: {LINE_2}; }}
QFrame#Seg QPushButton:checked:disabled {{ color: {FG_3}; }}

QLabel#Chip {{
    font-size: 12px;
    color: {FG_3};
    border: 1px dashed {LINE_2};
    border-radius: 4px;
    padding: 2px 6px;
}}
QLabel#Chip[done="true"] {{ color: {OK}; border: 1px solid {tint(OK, 0.4)}; background: {tint(OK, 0.08)}; }}

QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {BG_1};
    border: 1px solid {LINE_2};
    border-radius: 6px;
    padding: 0 8px;
    min-height: 26px;
    selection-background-color: {ACCENT};
    selection-color: {ACCENT_INK};
}}
QSpinBox, QDoubleSpinBox {{ font-family: {MONO_FONTS}; font-size: 12px; }}
QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{ color: {FG_3}; border-color: {LINE}; }}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; border: none; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background: {BG_3};
    border: 1px solid {LINE_2};
    selection-background-color: {tint(ACCENT, 0.2)};
    outline: none;
}}

QSlider::groove:horizontal {{ height: 4px; background: {LINE_2}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: {FG_1};
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}}
QSlider::sub-page:horizontal:disabled {{ background: {FG_3}; }}
QSlider:focus {{ outline: none; }}

QCheckBox {{ spacing: 8px; color: {FG_2}; }}
QCheckBox::indicator {{
    width: 14px;
    height: 14px;
    border: 1px solid {LINE_2};
    border-radius: 4px;
    background: {BG_1};
}}
QCheckBox::indicator:checked {{ background: {WARN}; border-color: {WARN}; }}
QCheckBox:focus {{ color: {FG_1}; }}

QListWidget {{
    background: transparent;
    border: none;
    outline: none;
}}
QListWidget::item {{ padding: 6px 8px; border-bottom: 1px solid {LINE}; color: {FG_2}; }}
QListWidget::item:selected {{ background: {tint(ACCENT, 0.14)}; color: {FG_1}; }}

QPlainTextEdit#Log {{
    background: {BG_1};
    border: none;
    font-family: {MONO_FONTS};
    font-size: 11px;
    selection-background-color: {tint(ACCENT, 0.3)};
}}

QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {LINE_2}; border-radius: 2px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: {FG_3}; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {LINE_2}; border-radius: 2px; min-width: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

QDialog {{ background: {BG_1}; }}
"""
