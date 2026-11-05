"""Small reusable widgets built on the design tokens."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

import cv2
import numpy as np
from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from loop.ui import icons, theme


def label(text: str = "", name: str = "", wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget


def restyle(widget: QWidget) -> None:
    """Re-applies the stylesheet after a dynamic property change, including to children."""
    for w in (widget, *widget.findChildren(QWidget)):
        w.style().unpolish(w)
        w.style().polish(w)


def set_style_property(widget: QWidget, name: str, value: Any) -> None:
    if widget.property(name) != value:
        widget.setProperty(name, value)
        restyle(widget)


def button(
    text: str,
    on_click: Callable[[], object] | None = None,
    variant: str = "",
    size: str = "",
    icon: str = "",
    icon_color: str = theme.FG_2,
) -> QPushButton:
    widget = QPushButton(text)
    if variant:
        widget.setProperty("variant", variant)
    if size:
        widget.setProperty("size", size)
    if icon:
        widget.setIcon(icons.icon(icon, icon_color))
        widget.setIconSize(QSize(14, 14) if size == "sm" else QSize(16, 16))
    if on_click is not None:
        widget.clicked.connect(on_click)
    return widget


def bgr_to_qimage(image: np.ndarray) -> QImage:
    rgb = np.ascontiguousarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    h, w = rgb.shape[:2]
    return QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


def row(*widgets: QWidget | int | None, spacing: int = 8, margins: tuple[int, int, int, int] = (0,) * 4):
    """A horizontal layout; an int adds that much stretch, None a stretch of 1."""
    layout = QHBoxLayout()
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    for item in widgets:
        if item is None:
            layout.addStretch(1)
        elif isinstance(item, int):
            layout.addSpacing(item)
        else:
            layout.addWidget(item)
    return layout


class IconButton(QToolButton):
    """A square icon-only button with an accessible name, and an optional attention dot."""

    def __init__(self, name: str, text: str, on_click: Callable[[], object] | None = None) -> None:
        super().__init__()
        self.setObjectName("IconButton")
        self.setIcon(icons.icon(name))
        self.setIconSize(QSize(16, 16))
        self.setFixedSize(28, 28)
        self.setToolTip(text)
        self.setAccessibleName(text)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._badge = ""
        if on_click is not None:
            self.clicked.connect(on_click)

    @property
    def badge(self) -> str:
        return self._badge

    def set_badge(self, color: str) -> None:
        """Shows a small dot in `color`, or none for ""."""
        self._badge = color
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().paintEvent(event)
        if self._badge:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(QColor(theme.BG_0), 1.5))
            painter.setBrush(QColor(self._badge))
            painter.drawEllipse(QRectF(self.width() - 10, 3, 7, 7))


class SegmentedControl(QFrame):
    """A row of mutually exclusive buttons, like a radio group."""

    selected = Signal(object)

    def __init__(self, options: Iterable[tuple[Any, str, str]], risky: Iterable[Any] = ()) -> None:
        """`options` are (value, text, icon name or "") tuples."""
        super().__init__()
        self.setObjectName("Seg")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        self._group = QButtonGroup(self)
        self.buttons: dict[Any, QPushButton] = {}
        risky = set(risky)
        for value, text, icon_name in options:
            widget = QPushButton(text)
            widget.setCheckable(True)
            widget.setCursor(Qt.CursorShape.PointingHandCursor)
            if value in risky:
                widget.setProperty("risk", True)
            if icon_name:
                checked = theme.WARN if value in risky else theme.FG_1
                widget.setIcon(icons.icon(icon_name, theme.FG_3, checked, size=14))
                widget.setIconSize(QSize(14, 14))
            widget.clicked.connect(lambda _=False, v=value: self.selected.emit(v))
            self._group.addButton(widget)
            self.buttons[value] = widget
            layout.addWidget(widget, 1)

    def value(self) -> Any:
        return next((v for v, b in self.buttons.items() if b.isChecked()), None)

    def set_value(self, value: Any) -> None:
        if value in self.buttons:
            self.buttons[value].setChecked(True)
        elif (checked := self._group.checkedButton()) is not None:
            # Unchecking an exclusive group's button needs exclusivity off for a moment.
            self._group.setExclusive(False)
            checked.setChecked(False)
            self._group.setExclusive(True)


class StatusPill(QFrame):
    """Session state as an icon and a word on a tinted background."""

    _ICONS = {"idle": "idle", "paused": "pause", "error": "alert", "stopped": "stop"}
    _COLORS = {"running": theme.OK, "paused": theme.WARN, "error": theme.ERR}

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Pill")
        self.setFixedHeight(22)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(7, 0, 9, 0)
        layout.setSpacing(5)
        self._icon = QLabel()
        self._icon.setFixedSize(12, 12)
        self._text = QLabel()
        layout.addWidget(self._icon)
        layout.addWidget(self._text)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def text(self) -> str:
        return self._text.text()

    def set_state(self, state: str, text: str) -> None:
        color = self._COLORS.get(state, theme.FG_2)
        if state == "running":
            self._icon.setPixmap(_dot(color))
        else:
            self._icon.setPixmap(icons.pixmap(self._ICONS.get(state, "idle"), color, 12))
        self._text.setText(text)
        self.setAccessibleName(f"Status: {text}")
        set_style_property(self, "state", state)


def _dot(color: str) -> QPixmap:
    """A filled dot, the running state's mark (12 px, drawn at twice the size)."""
    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawEllipse(QRectF(6, 6, 12, 12))
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return pixmap


class Switch(QAbstractButton):
    """An on/off switch. Space toggles it like a check box."""

    def __init__(self, accessible_name: str = "") -> None:
        super().__init__()
        self.setCheckable(True)
        self.setFixedSize(34, 20)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(accessible_name)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return QSize(34, 20)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        on, enabled = self.isChecked(), self.isEnabled()
        track = QColor(theme.ACCENT if on else theme.BG_3)
        if not enabled:
            track.setAlphaF(0.4)
        border = QColor(theme.ACCENT if self.hasFocus() else (theme.ACCENT if on else theme.LINE_2))
        painter.setPen(QPen(border, 1))
        painter.setBrush(track)
        painter.drawRoundedRect(QRectF(0.5, 0.5, 33, 19), 9.5, 9.5)
        knob = QColor(theme.ACCENT_INK if on else theme.FG_2)
        if not enabled:
            knob.setAlphaF(0.5)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(knob)
        painter.drawEllipse(QRectF(17 if on else 3, 3, 14, 14))


class Panel(QFrame):
    """A raised group of field rows separated by hairlines."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Panel")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(12, 0, 12, 0)
        self.body.setSpacing(0)

    def add_row(self, title: str, help_text: str = "", control: QWidget | None = None) -> FieldRow:
        field = FieldRow(title, help_text, control)
        if self.body.count():
            field.setProperty("divided", True)
        self.body.addWidget(field)
        return field


class FieldRow(QWidget):
    """A label with help text on the left and a control on the right."""

    def __init__(self, title: str, help_text: str = "", control: QWidget | None = None) -> None:
        super().__init__()
        self.setObjectName("FieldRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 10)
        layout.setSpacing(12)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.title = label(title, "FieldLabel", wrap=True)
        text.addWidget(self.title)
        self.help = label(help_text, "Help", wrap=True)
        self.help.setVisible(bool(help_text))
        text.addWidget(self.help)
        self.error = label("", "Error", wrap=True)
        self.error.hide()
        text.addWidget(self.error)
        layout.addLayout(text, 1)
        if control is not None:
            layout.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
            if not control.accessibleName():
                control.setAccessibleName(title)

    def set_error(self, message: str) -> None:
        self.error.setText(message)
        self.error.setVisible(bool(message))


class Notice(QFrame):
    """An icon and a short message on a tinted background: kind is ok, warn, or err."""

    _ICONS = {"ok": ("check", theme.OK), "warn": ("alert", theme.WARN), "err": ("alert", theme.ERR)}

    def __init__(self, text: str = "", kind: str = "warn") -> None:
        super().__init__()
        self.setObjectName("Notice")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)
        self._icon = QLabel()
        self._icon.setFixedSize(16, 16)
        layout.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignTop)
        self.text = label(text, "Secondary", wrap=True)
        self.text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.text, 1)
        self.set_kind(kind)

    def set_kind(self, kind: str) -> None:
        name, color = self._ICONS[kind]
        self._icon.setPixmap(icons.pixmap(name, color, 16))
        set_style_property(self, "kind", kind)

    def show_message(self, text: str, kind: str) -> None:
        self.text.setText(text)
        self.set_kind(kind)
        self.show()


def section(title: str) -> QLabel:
    return label(title.upper(), "SectionLabel")


class ElidedLabel(QLabel):
    """A one-line label that shortens its text with an ellipsis; the full text is its tooltip."""

    def __init__(self, name: str = "") -> None:
        super().__init__()
        if name:
            self.setObjectName(name)
        self._full = ""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def full_text(self) -> str:
        return self._full

    def setText(self, text: str) -> None:  # noqa: N802 - Qt override
        self._full = text
        self.setToolTip(text if text else "")
        self._elide()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        elided = self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideRight, self.width())
        super().setText(elided)
