"""Layout helpers and the display pieces of the design: lists, cards, notices, status, and progress."""

from __future__ import annotations

import math
from collections.abc import Iterable

import cv2
import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QFontMetrics,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from loop.ui import icons, motion, theme
from loop.ui.controls import Button, Pressable, paint_focus_ring, paint_spinner, surface
from loop.ui.theme import qcolor

# Small helpers


def text(content: str = "", role: str = "body", wrap: bool = False, rich_text: bool = False) -> QLabel:
    """A label in one of the design's text roles (see theme.ROLES)."""
    result = QLabel()
    result.setProperty("role", role)
    result.setFont(theme.role_font(role))
    result.setWordWrap(wrap)
    result.setTextFormat(Qt.TextFormat.RichText if rich_text else Qt.TextFormat.PlainText)
    result.setText(rich(content) if rich_text else content)
    return result


def set_tone(label: QLabel, tone: str) -> None:
    """Recolors a label: "ok", "warn", "error", "accent", "off", "strong", or "" for its role color."""
    if label.property("tone") != tone:
        label.setProperty("tone", tone or None)
        label.style().unpolish(label)
        label.style().polish(label)


def swap_text(label: QLabel, value: str) -> None:
    """Changes a label's text; the new text rises 4 px and fades in."""
    if label.text() != value:
        label.setText(value)
        motion.rise_in(label, theme.DUR_2, 4)


def rich(html: str) -> str:
    """Rich text with <b> drawn in the primary text color, as the design's <strong>."""
    return html.replace("<b>", f'<span style="color:{theme.TEXT}; font-weight:500">').replace(
        "</b>", "</span>"
    )


def row(*items: QWidget | int | None, spacing: int = 8, margins: tuple[int, int, int, int] = (0, 0, 0, 0)):
    """A horizontal layout; an int adds that much space, None a stretch."""
    layout = QHBoxLayout()
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    for item in items:
        if item is None:
            layout.addStretch(1)
        elif isinstance(item, int):
            layout.addSpacing(item)
        else:
            layout.addWidget(item)
    return layout


def column(spacing: int = 8, margins: tuple[int, int, int, int] = (0, 0, 0, 0)) -> QVBoxLayout:
    layout = QVBoxLayout()
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    return layout


def bgr_to_qimage(image: np.ndarray) -> QImage:
    rgb = np.ascontiguousarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    h, w = rgb.shape[:2]
    return QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


class Page(QScrollArea):
    """A scrolling page: 20 px padding (24 px at the bottom) and 20 px between sections."""

    def __init__(self, spacing: int = 20) -> None:
        super().__init__()
        self.body = QWidget()
        self.content = column(spacing, (20, 20, 20, 24))
        self.body.setLayout(self.content)
        self.setWidget(self.body)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def group(self, title: str, content: QWidget, link: QWidget | None = None) -> QVBoxLayout:
        """A section: a caps label (with an optional link on the right) above its content."""
        layout = column(8)
        head = row(text(title, "label"), None)
        if link is not None:
            head.addWidget(link)
        layout.addLayout(head)
        layout.addWidget(content)
        self.content.addLayout(layout)
        return layout

    def heading(self, title: str, description: str = "") -> None:
        layout = column(4)
        layout.addWidget(text(title, "title"))
        if description:
            layout.addWidget(text(description, "body-2", wrap=True))
        self.content.addLayout(layout)

    def scroll_to(self, widget: QWidget) -> None:
        QTimer.singleShot(0, self, lambda: self.ensureWidgetVisible(widget, 0, 20))


class Spinner(QWidget):
    def __init__(self, size: int = 16) -> None:
        super().__init__()
        self.setFixedSize(size, size)
        self._phase = 0.0
        self._loop = motion.Loop(self, 700, self._turn, always=True)

    def _turn(self, phase: float) -> None:
        self._phase = phase
        self.update()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        self._loop.set_running(True)
        super().showEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt override
        self._loop.set_running(False)
        super().hideEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        paint_spinner(painter, QRectF(self.rect()), self._phase, theme.TEXT)


# Tags, status text, and the live dot


class Tag(QLabel):
    """A 20 px tall label with a border; the accent version marks Auto click."""

    def __init__(self, label: str = "") -> None:
        super().__init__(label)
        self.setFont(theme.font(11, 500))
        self.setFixedHeight(20)
        self._accent: bool | None = None
        self.set_accent(False)

    def set_accent(self, accent: bool) -> None:
        if accent == self._accent:
            return
        self._accent = accent
        if accent:
            colors = theme.ACCENT, theme.rgba(theme.line(theme.ACCENT)), theme.rgba(theme.soft(theme.ACCENT))
        else:
            colors = theme.TEXT_2, theme.BORDER, "transparent"
        self.setStyleSheet(
            f"color: {colors[0]}; border: 1px solid {colors[1]}; background: {colors[2]};"
            f"border-radius: {theme.R_SM}px; padding: 0 6px;"
        )


# tone: (color, icon, weight)
STATE_TONES = {
    "ok": (theme.SUCCESS, "check-circle", 500),
    "warn": (theme.WARNING, "alert", 500),
    "info": (theme.TEXT_2, "check", 500),
    "none": (theme.TEXT_3, "", 400),
}


class StateText(QWidget):
    """A status word with its icon, such as "Working" or "Not checked"."""

    def __init__(self, label: str = "", tone: str = "none") -> None:
        super().__init__()
        self._text = ""
        self._tone = "none"
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.set_state(label, tone)

    @property
    def label(self) -> str:
        return self._text

    @property
    def tone(self) -> str:
        return self._tone

    def set_state(self, label: str, tone: str) -> None:
        if (label, tone) == (self._text, self._tone):
            return
        self._text, self._tone = label, tone
        self.setAccessibleName(label)
        self.setToolTip("")
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        weight = STATE_TONES[self._tone][2]
        return QSize(QFontMetrics(theme.font(12, weight)).horizontalAdvance(self._text) + 20 + 1, 20)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color, icon, weight = STATE_TONES[self._tone]
        cy = self.height() / 2
        if icon:
            icons.paint(painter, icon, QRectF(0, cy - 7, 14, 14), color)
        else:
            painter.setOpacity(0.8)
            painter.setPen(QPen(QColor(color), 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QRectF(2.75, cy - 4.25, 8.5, 8.5))
            painter.setOpacity(1.0)
        painter.setFont(theme.font(12, weight))
        painter.setPen(QColor(color))
        painter.drawText(
            QRectF(20, 0, self.width() - 20, self.height()), Qt.AlignmentFlag.AlignVCenter, self._text
        )


DOT_TONES = {
    "setup": theme.TEXT_3,
    "ready": theme.SUCCESS,
    "watch": theme.SUCCESS,
    "auto": theme.ACCENT,
    "paused": theme.WARNING,
    "error": theme.DANGER,
}


class LiveDot(QWidget):
    """The status dot. Watching pulses every 2 s; Auto click adds an orbiting arc.

    The widget is larger than the 10 px dot so the pulse has room; place it with a
    negative layout margin of `OVERHANG` so the dot itself lines up with the text edge.
    """

    OVERHANG = 10

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(30, 28)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.tone = "setup"
        self._color = motion.Tweened(self, 0.0, lambda _v: self.update())
        self._from = self._to = QColor(DOT_TONES["setup"])
        self._pulse = 0.0
        self._orbit = 0.0
        self._blip = 1.0
        self._pulse_loop = motion.Loop(self, 2000, self._on_pulse)
        self._orbit_loop = motion.Loop(self, 1200, self._on_orbit)
        self._blip_tween = motion.Tweened(self, 1.0, self._on_blip)
        self._allowed = True

    def set_tone(self, tone: str) -> None:
        if tone == self.tone:
            return
        self._from = self._current_color()
        self._to = QColor(DOT_TONES[tone])
        self.tone = tone
        self._color.snap(0.0)
        self._color.to(1.0, theme.DUR_2)
        self._apply_loops()

    def set_ambient_allowed(self, allowed: bool) -> None:
        """Ambient loops stop while the window is minimized."""
        self._allowed = allowed
        self._apply_loops()

    @property
    def pulsing(self) -> bool:
        return self._pulse_loop.running

    @property
    def orbiting(self) -> bool:
        return self._orbit_loop.running

    def blip(self) -> None:
        """One expanding ring, for a recognition or a completed click."""
        if motion.reduced():
            return
        self._blip_tween.snap(0.0)
        self._blip_tween.to(1.0, 600)

    def _apply_loops(self) -> None:
        live = self._allowed and self.isVisible()
        self._pulse_loop.set_running(live and self.tone in ("watch", "auto"))
        self._orbit_loop.set_running(live and self.tone == "auto")
        if not self._pulse_loop.running:
            self._pulse = 0.0
        self.update()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        self._apply_loops()

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().hideEvent(event)
        self._pulse_loop.set_running(False)
        self._orbit_loop.set_running(False)

    def _on_pulse(self, phase: float) -> None:
        self._pulse = phase
        self.update()

    def _on_orbit(self, phase: float) -> None:
        self._orbit = phase
        self.update()

    def _on_blip(self, value: float) -> None:
        self._blip = value
        self.update()

    def _current_color(self) -> QColor:
        return theme.mix(self._from, self._to, self._color.value)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = self._current_color()
        center = QPointF(self.width() / 2, self.height() / 2)
        if self.tone == "setup":
            painter.setPen(QPen(color, 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(center, 4.25, 4.25)
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawEllipse(center, 5, 5)
        if self._pulse_loop.running:
            # Scale 0.6 → 1.4 and fade out by 70% of the cycle.
            t = min(self._pulse / 0.7, 1.0)
            eased = 1 - (1 - t) ** 3
            radius = 9 * (0.6 + 0.8 * eased)
            self._ring(painter, center, radius, color, 0.6 * (1 - t))
        if self._blip < 1.0:
            radius = 9 * (0.6 + 1.4 * (1 - (1 - self._blip) ** 3))
            self._ring(painter, center, radius, color, 0.9 * (1 - self._blip))
        if self._orbit_loop.running:
            pen = QPen(color, 1.5)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            arc = QRectF(center.x() - 9.25, center.y() - 9.25, 18.5, 18.5)
            painter.drawArc(arc, round((135 - self._orbit * 360) * 16), -90 * 16)

    @staticmethod
    def _ring(painter: QPainter, center: QPointF, radius: float, color: QColor, opacity: float) -> None:
        if opacity <= 0:
            return
        painter.setPen(QPen(qcolor(color, opacity * color.alphaF()), 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(center, radius, radius)


# Lists, stats, cards, notices


class Rows(QFrame):
    """Rows on one surface with hairline dividers between them."""

    def __init__(self) -> None:
        super().__init__()
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(1, 1, 1, 1)
        self.body.setSpacing(0)

    def add(self, widget: QWidget) -> QWidget:
        self.body.addWidget(widget)
        return widget

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        surface(painter, QRectF(self.rect()), theme.SURFACE, theme.BORDER_SUBTLE, theme.R_LG)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setPen(QColor(theme.BORDER_SUBTLE))
        visible = [self.body.itemAt(i).widget() for i in range(self.body.count())]
        visible = [w for w in visible if w is not None and w.isVisible()]
        for widget in visible[1:]:
            y = widget.geometry().top()
            painter.drawLine(1, y, self.width() - 2, y)


class Row(QWidget):
    """One list row: 40 px minimum, 16 px side padding, 12 px between items."""

    def __init__(self, control: bool = False) -> None:
        super().__init__()
        self.setMinimumHeight(theme.H_ROW)
        self.body = QHBoxLayout(self)
        vertical = 12 if control else 0
        self.body.setContentsMargins(16, vertical, 16, vertical)
        self.body.setSpacing(12)


def field(title: str, help_text: str = "") -> tuple[QWidget, QLabel, QLabel]:
    """A title over help text, for setting rows."""
    box = QWidget()
    layout = column(2)
    box.setLayout(layout)
    title_label = text(title, "row-title")
    help_label = text(help_text, "help", wrap=True)
    layout.addWidget(title_label)
    layout.addWidget(help_label)
    help_label.setVisible(bool(help_text))
    box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    return box, title_label, help_label


class CountLabel(QLabel):
    """A number that counts up to new values over 300 ms; decreases jump."""

    def __init__(self, role: str = "stat") -> None:
        super().__init__("0")
        self.setProperty("role", role)
        self.setFont(theme.role_font(role))
        self.value = 0
        self._shown = 0.0
        self._from = 0
        self._tween = motion.Tweened(self, 1.0, self._step)

    def set_value(self, value: int) -> None:
        if value == self.value:
            return
        start = self.value
        self.value = value
        if value < start or value - start > 200 or motion.reduced():
            self._tween.snap(1.0)
            self.setText(str(value))
            return
        self._from = start
        self._tween.snap(0.0)
        self._tween.to(1.0, 300, _CUBIC_OUT)

    def _step(self, t: float) -> None:
        self.setText(str(round(self._from + (self.value - self._from) * t)))


_CUBIC_OUT = theme.bezier(0.33, 1, 0.68, 1)


class StatStrip(QFrame):
    """Equal cells on one surface, each a label above its value."""

    def __init__(self, cells: list[tuple[str, QLabel]]) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)
        self._cells: list[QWidget] = []
        for name, value in cells:
            cell = QWidget()
            box = column(2, (16, 10, 16, 12))
            cell.setLayout(box)
            box.addWidget(text(name, "stat-label"))
            box.addWidget(value)
            self._cells.append(cell)
            layout.addWidget(cell, 1)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        surface(painter, QRectF(self.rect()), theme.SURFACE, theme.BORDER_SUBTLE, theme.R_LG)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setPen(QColor(theme.BORDER_SUBTLE))
        for cell in self._cells[1:]:
            x = cell.geometry().left()
            painter.drawLine(x, 1, x, self.height() - 2)


class Card(QFrame):
    """A surface with 16 px padding and a 12 px gap between its parts."""

    def __init__(self) -> None:
        super().__init__()
        self.body = column(12, (16, 16, 16, 16))
        self.setLayout(self.body)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        surface(painter, QRectF(self.rect()), theme.SURFACE, theme.BORDER_SUBTLE, theme.R_LG)


NOTICE_TONES = {
    "info": ("info", theme.TEXT_2, theme.BORDER_SUBTLE),
    "ok": ("check-circle", theme.SUCCESS, theme.BORDER_SUBTLE),
    "warn": ("alert", theme.WARNING, None),
    "err": ("x-circle", theme.DANGER, None),
}


class Notice(QFrame):
    """A message with an icon and optional actions; rises in when shown or changed."""

    def __init__(
        self, kind: str = "info", message: str = "", fill: str = theme.ELEVATED, radius: int = theme.R_MD
    ) -> None:
        super().__init__()
        self._fill = fill
        self._radius = radius
        self.kind = kind
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)
        self._icon = QLabel()
        self._icon.setFixedSize(16, 18)
        self._icon.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignTop)
        texts = column(8)
        self.message = text("", "help", wrap=True)
        self.message.setTextFormat(Qt.TextFormat.RichText)
        self.message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        texts.addWidget(self.message)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        self._actions_box = QWidget()
        self._actions_box.setLayout(self.actions)
        self.actions.setContentsMargins(0, 0, 0, 0)
        texts.addWidget(self._actions_box)
        layout.addLayout(texts, 1)
        self.set(kind, message)

    def set(self, kind: str, message: str, actions: Iterable[QWidget] = ()) -> None:
        changed = (kind, message) != (self.kind, self.message.text())
        self.kind = kind
        self.message.setText(rich(message))
        icon, color, _ = NOTICE_TONES[kind]
        self._icon.setPixmap(icons.pixmap(icon, color, 16))
        while self.actions.count():
            item = self.actions.takeAt(0)
            if item.widget() is not None:
                item.widget().setParent(None)
        for widget in actions:
            self.actions.addWidget(widget)
        if actions:
            self.actions.addStretch(1)
        self._actions_box.setVisible(self.actions.count() > 0)
        self.setAccessibleName(self.message.text())
        self.update()
        if changed and self.isVisible():
            motion.rise_in(self)

    def show_message(self, kind: str, message: str, actions: Iterable[QWidget] = ()) -> None:
        was_visible = self.isVisible()
        self.set(kind, message, actions)
        self.show()
        if not was_visible:
            motion.rise_in(self)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        _icon, color, border = NOTICE_TONES[self.kind]
        line_color = border or theme.line(color)
        surface(painter, QRectF(self.rect()), self._fill, line_color, self._radius)


# Disclosure, stepper, scan bar, success mark, empty state


class _DisclosureHead(Pressable):
    def __init__(self, label: str) -> None:
        super().__init__()
        self.setText(label)
        self.setFixedHeight(34)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.turn = motion.Tweened(self, 0.0, lambda _v: self.update())

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        if self.hover > 0:
            surface(painter, rect, qcolor(theme.SURFACE, self.hover), None, theme.R_MD)
        color = theme.mix(theme.TEXT_2, theme.TEXT, max(self.hover, 1.0 if self.isChecked() else 0.0))
        painter.save()
        painter.translate(15, rect.center().y())
        painter.rotate(90 * self.turn.value)
        icons.paint(painter, "chevron", QRectF(-7, -7, 14, 14), color.name())
        painter.restore()
        painter.setFont(theme.font(13, 500))
        painter.setPen(color)
        painter.drawText(rect.adjusted(30, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, self.text())
        if self._show_ring():
            paint_focus_ring(painter, rect, theme.R_MD)


class Disclosure(QWidget):
    """A collapsed section: the chevron turns and the content expands over 250 ms."""

    def __init__(self, title: str, content: QWidget) -> None:
        super().__init__()
        layout = column(0, (0, 8, 0, 0))
        self.setLayout(layout)
        self.head = _DisclosureHead(title)
        self.head.setCheckable(True)
        self.head.toggled.connect(self.set_open)
        layout.addWidget(self.head)
        self.body = QWidget()
        inner = column(0, (0, 8, 0, 0))
        self.body.setLayout(inner)
        inner.addWidget(content)
        self.body.setMaximumHeight(0)
        self.body.hide()
        layout.addWidget(self.body)
        self._height = motion.Tweened(self, 0.0, self._grow)

    @property
    def is_open(self) -> bool:
        return self.head.isChecked()

    def set_open(self, open_: bool) -> None:
        if self.head.isChecked() != open_:
            self.head.setChecked(open_)
            return
        self.head.turn.to(1.0 if open_ else 0.0, theme.DUR_2, theme.EASE_MOVE)
        if open_:
            self.body.show()
            effect = QGraphicsOpacityEffect(self.body)
            effect.setOpacity(0.0)
            self.body.setGraphicsEffect(effect if not motion.reduced() else None)
        self._height.to(1.0 if open_ else 0.0, theme.DUR_3, theme.EASE_MOVE)

    def _grow(self, t: float) -> None:
        full = self.body.layout().sizeHint().height()
        self.body.setMaximumHeight(round(full * t) if t < 1.0 else 16777215)
        effect = self.body.graphicsEffect()
        if isinstance(effect, QGraphicsOpacityEffect):
            effect.setOpacity(min(1.0, t * 1.25))
            if t >= 1.0:
                self.body.setGraphicsEffect(None)
        if t <= 0.0 and not self.is_open:
            self.body.hide()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setPen(QColor(theme.BORDER_SUBTLE))
        painter.drawLine(0, 0, self.width(), 0)


class Stepper(QWidget):
    """Five equal segments; each is a 2 px bar over its label. Bars fill over 250 ms."""

    def __init__(self, names: list[str]) -> None:
        super().__init__()
        self._names = names
        self.step = 0
        self._fills = [motion.Tweened(self, 0.0, lambda _v: self.update()) for _ in names]
        self.setFixedHeight(2 + 6 + 15)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_step(self, step: int) -> None:
        self.step = step
        for index, fill in enumerate(self._fills):
            fill.to(1.0 if index <= step else 0.0, theme.DUR_3, theme.EASE_MOVE)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        count = len(self._names)
        gap = 6
        width = (self.width() - gap * (count - 1)) / count
        for index, name in enumerate(self._names):
            x = index * (width + gap)
            bar = QRectF(x, 0, width, 2)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.BORDER))
            painter.drawRoundedRect(bar, 1, 1)
            done, current = index < self.step, index == self.step
            fill = self._fills[index].value
            if fill > 0:
                painter.setBrush(QColor(theme.TEXT_2 if done else theme.TEXT))
                painter.drawRoundedRect(QRectF(x, 0, width * fill, 2), 1, 1)
            painter.setFont(theme.font(11, 500 if current else 400))
            painter.setPen(QColor(theme.TEXT if current else theme.TEXT_2 if done else theme.TEXT_3))
            painter.drawText(
                QRectF(x, 8, width, 15), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name
            )


class ScanBar(QWidget):
    """A 2 px bar with a highlight sweeping across while a check runs."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(2)
        self._phase = 0.0
        self._loop = motion.Loop(self, 1000, self._move)

    def _move(self, phase: float) -> None:
        self._phase = theme.EASE_MOVE.valueForProgress(phase)
        self.update()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        self._loop.set_running(True)
        super().showEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt override
        self._loop.set_running(False)
        super().hideEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(theme.BORDER_SUBTLE))
        if not self._loop.running:
            return
        width = self.width() * 0.35
        x = -width + self._phase * (self.width() + width * 2)
        gradient = QLinearGradient(x, 0, x + width, 0)
        gradient.setColorAt(0, qcolor(theme.TEXT, 0))
        gradient.setColorAt(0.5, QColor(theme.TEXT))
        gradient.setColorAt(1, qcolor(theme.TEXT, 0))
        painter.fillRect(QRectF(x, 0, width, 2), gradient)


class SuccessMark(QWidget):
    """A ring that draws over 400 ms, then a check over 250 ms after 200 ms."""

    def __init__(self, size: int = 48) -> None:
        super().__init__()
        self.setFixedSize(size, size)
        self._ring = motion.Tweened(self, 1.0, lambda _v: self.update())
        self._check = motion.Tweened(self, 1.0, lambda _v: self.update())

    def play(self) -> None:
        self._ring.snap(0.0)
        self._check.snap(0.0)
        self._ring.to(1.0, 400)
        self._check.to(1.0, theme.DUR_3, delay=200)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale = self.width() / 48
        painter.scale(scale, scale)
        pen = QPen(theme.line(theme.SUCCESS), 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(QRectF(3, 3, 42, 42), 90 * 16, -round(360 * 16 * self._ring.value))
        if self._check.value > 0:
            path = QPainterPath(QPointF(15, 24.5))
            path.lineTo(21, 30.5)
            path.lineTo(33, 17.5)
            pen = QPen(QColor(theme.SUCCESS), 2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            length = path.length() * self._check.value
            painter.drawPath(_partial(path, length))


def _partial(path: QPainterPath, length: float) -> QPainterPath:
    """The first `length` of a polyline path."""
    result = QPainterPath(path.elementAt(0))
    remaining = length
    previous = QPointF(path.elementAt(0).x, path.elementAt(0).y)
    for index in range(1, path.elementCount()):
        element = path.elementAt(index)
        point = QPointF(element.x, element.y)
        segment = math.dist((previous.x(), previous.y()), (point.x(), point.y()))
        if remaining >= segment:
            result.lineTo(point)
            remaining -= segment
            previous = point
            continue
        t = remaining / segment if segment else 0
        result.lineTo(previous + (point - previous) * t)
        break
    return result


class EmptyState(QFrame):
    """A dashed panel with an icon, a title, one sentence, and one action."""

    def __init__(self, icon: str, action: Button) -> None:
        super().__init__()
        layout = column(8, (24, 32, 24, 32))
        self.setLayout(layout)
        mark = QLabel()
        mark.setPixmap(icons.pixmap(icon, theme.TEXT_3, 20))
        layout.addWidget(mark, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(4)
        self.title = text("", "row-title")
        self.title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.body = text("", "help", wrap=True)
        self.body.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.body.setFixedWidth(250)
        layout.addWidget(self.title)
        layout.addLayout(row(None, self.body, None, spacing=0))
        layout.addSpacing(8)
        self.action = action
        layout.addWidget(action, 0, Qt.AlignmentFlag.AlignHCenter)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(theme.BORDER), 1, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), theme.R_LG, theme.R_LG)
