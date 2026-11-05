"""Interactive controls painted to match the approved design, and their painting helpers.

Every control shares one motion vocabulary: hover fades colors over 150 ms, a press scales
to 0.98 over 100 ms, and anything that travels (a thumb, a knob) moves over 200-250 ms on
the "move" curve. Keyboard focus shows a ring.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from PySide6.QtCore import QEvent, QKeyCombination, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFocusEvent,
    QFontMetrics,
    QKeyEvent,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import QAbstractButton, QComboBox, QHBoxLayout, QSizePolicy, QSlider, QWidget

from loop.ui import icons, motion, theme
from loop.ui.theme import qcolor

KEYBOARD_FOCUS = (
    Qt.FocusReason.TabFocusReason,
    Qt.FocusReason.BacktabFocusReason,
    Qt.FocusReason.ShortcutFocusReason,
    Qt.FocusReason.OtherFocusReason,
)


def paint_focus_ring(painter: QPainter, rect: QRectF, radius: float) -> None:
    painter.save()
    painter.setPen(QPen(theme.line(theme.ACCENT), 2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), radius - 1, radius - 1)
    painter.restore()


def surface(
    painter: QPainter, rect: QRectF, fill: QColor | str, border: QColor | str | None, radius: float
) -> None:
    painter.setBrush(QColor(fill))
    if border is None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect, radius, radius)
    else:
        painter.setPen(QPen(QColor(border), 1))
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)


# Painted button base


class Pressable(QAbstractButton):
    """A painted button with hover and press tweens and a keyboard focus ring."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self._hover = motion.Tweened(self, 0.0, lambda _v: self.update())
        self._press = motion.Tweened(self, 0.0, lambda _v: self.update())
        self.focus_visible = False

    def enterEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self.isEnabled():
            self._hover.to(1.0, theme.DUR_1)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt override
        self._hover.to(0.0, theme.DUR_1)
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self._press.to(1.0, theme.DUR_PRESS)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        self._press.to(0.0, theme.DUR_PRESS)
        super().mouseReleaseEvent(event)

    def focusInEvent(self, event: QFocusEvent) -> None:  # noqa: N802 - Qt override
        self.focus_visible = event.reason() in KEYBOARD_FOCUS
        super().focusInEvent(event)

    def focusOutEvent(self, event: QFocusEvent) -> None:  # noqa: N802 - Qt override
        self.focus_visible = False
        super().focusOutEvent(event)

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt override
        if event.type() == QEvent.Type.EnabledChange and not self.isEnabled():
            self._hover.snap(0.0)
            self._press.snap(0.0)
        super().changeEvent(event)

    @property
    def hover(self) -> float:
        return self._hover.value if self.isEnabled() else 0.0

    def _begin(self, painter: QPainter) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale = 1.0 - (1.0 - theme.PRESS_SCALE) * self._press.value
        if scale < 1.0:
            center = QRectF(self.rect()).center()
            painter.translate(center)
            painter.scale(scale, scale)
            painter.translate(-center)

    def _show_ring(self) -> bool:
        return self.hasFocus() and self.focus_visible


_TRANSPARENT = QColor(0, 0, 0, 0)

# variant: (rest bg, hover bg, rest border, hover border, rest label, hover label)
_VARIANTS: dict[str, tuple[Any, ...]] = {
    "primary": (theme.TEXT, theme.WHITE, None, None, theme.BG, theme.BG),
    "accent": (theme.ACCENT, theme.ACCENT_HOVER, None, None, theme.BG, theme.BG),
    "secondary": (theme.ELEVATED, theme.HOVER, theme.BORDER, theme.BORDER_STRONG, theme.TEXT, theme.TEXT),
    "ghost": (qcolor(theme.ELEVATED, 0), theme.ELEVATED, None, None, theme.TEXT_2, theme.TEXT),
    "danger": (
        theme.ELEVATED,
        theme.soft(theme.DANGER),
        theme.BORDER,
        theme.line(theme.DANGER),
        theme.DANGER,
        theme.DANGER,
    ),
    "link": (_TRANSPARENT, _TRANSPARENT, None, None, theme.TEXT_2, theme.TEXT),
}
_DISABLED = {
    "primary": (theme.ELEVATED, theme.BORDER_SUBTLE, theme.TEXT_DISABLED),
    "accent": (theme.ELEVATED, theme.BORDER_SUBTLE, theme.TEXT_DISABLED),
    "secondary": (theme.SURFACE, theme.BORDER_SUBTLE, theme.TEXT_DISABLED),
    "ghost": (_TRANSPARENT, None, theme.TEXT_DISABLED),
    "danger": (theme.ELEVATED, theme.BORDER, theme.TEXT_DISABLED),
    "link": (_TRANSPARENT, None, theme.TEXT_DISABLED),
}
# size: (height, horizontal padding, font size, icon size, gap)
_SIZES = {"sm": (28, 10, 12, 14, 6), "md": (32, 12, 13, 16, 8), "lg": (40, 16, 14, 16, 8)}


class Button(Pressable):
    """A text button with an optional icon: primary, accent, secondary, ghost, danger, or link."""

    def __init__(
        self,
        label: str,
        on_click: Callable[[], Any] | None = None,
        variant: str = "secondary",
        size: str = "md",
        icon: str = "",
        icon_right: bool = False,
    ) -> None:
        super().__init__()
        self.setText(label)
        self.variant = variant
        self._size = size
        self._icon = icon
        self._icon_right = icon_right
        self._busy = False
        self._spin_phase = 0.0
        self._spin = motion.Loop(self, 700, self._turn, always=True)
        if on_click is not None:
            self.clicked.connect(lambda _checked=False: on_click())
        policy = QSizePolicy.Policy.Fixed
        self.setSizePolicy(policy, policy)

    def set_variant(self, variant: str) -> None:
        if variant != self.variant:
            self.variant = variant
            self.update()

    def set_icon(self, name: str) -> None:
        if name != self._icon:
            self._icon = name
            self.updateGeometry()
            self.update()

    def set_busy(self, busy: bool) -> None:
        """Shows a spinner in place of the icon."""
        self._busy = busy
        self._spin.set_running(busy)
        self.update()

    def setText(self, value: str) -> None:  # noqa: N802 - Qt override
        if value != self.text():
            super().setText(value)
            self.updateGeometry()

    def _metrics(self) -> tuple[int, int, int, int, int]:
        if self.variant == "link":
            return 20, 0, 12, 14, 6
        return _SIZES[self._size]

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        height, pad, size, icon, gap = self._metrics()
        width = QFontMetrics(theme.font(size, 500)).horizontalAdvance(self.text())
        if self._icon or self._busy:
            width += icon + (gap if self.text() else 0)
        return QSize(width + pad * 2, height)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return self.sizeHint()

    def colors(self) -> tuple[QColor, QColor | None, QColor]:
        if not self.isEnabled():
            bg, border, fg = _DISABLED[self.variant]
            return QColor(bg), QColor(border) if border else None, QColor(fg)
        bg, bg_hover, border, border_hover, fg, fg_hover = _VARIANTS[self.variant]
        h = self.hover
        mixed_border = theme.mix(border, border_hover, h) if border is not None else None
        return theme.mix(bg, bg_hover, h), mixed_border, theme.mix(fg, fg_hover, h)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        self._begin(painter)
        _height, pad, size, icon_size, gap = self._metrics()
        rect = QRectF(self.rect())
        bg, border, fg = self.colors()
        radius = theme.R_XS if self.variant == "link" else theme.R_MD
        if bg.alpha() or border is not None:
            surface(painter, rect, bg, border, radius)
        painter.setFont(theme.font(size, 500))
        text_width = painter.fontMetrics().horizontalAdvance(self.text())
        has_icon = bool(self._icon) or self._busy
        content = text_width + ((icon_size + (gap if self.text() else 0)) if has_icon else 0)
        x = rect.center().x() - content / 2
        if has_icon:
            ix = x + text_width + gap if self._icon_right else x
            if self._icon_right:
                ix += 2 * self.hover  # the arrow nudges on hover
            icon_rect = QRectF(ix, rect.center().y() - icon_size / 2, icon_size, icon_size)
            if self._busy:
                paint_spinner(painter, icon_rect, self._spin_phase, fg)
            else:
                icons.paint(painter, self._icon, icon_rect, fg.name())
            if not self._icon_right:
                x += icon_size + gap
        painter.setPen(fg)
        painter.drawText(
            QRectF(x, rect.top(), text_width + 1, rect.height()), Qt.AlignmentFlag.AlignVCenter, self.text()
        )
        if self._show_ring():
            paint_focus_ring(painter, rect, radius)

    def _turn(self, phase: float) -> None:
        self._spin_phase = phase
        self.update()


class IconButton(Pressable):
    """A 30 × 30 transparent button with one icon and a tooltip."""

    def __init__(self, icon: str, tip: str, on_click: Callable[[], Any] | None = None) -> None:
        super().__init__()
        self._icon = icon
        self.setToolTip(tip)
        self.setAccessibleName(tip)
        self.setFixedSize(30, 30)
        if on_click is not None:
            self.clicked.connect(lambda _checked=False: on_click())

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        self._begin(painter)
        rect = QRectF(self.rect())
        h = self.hover
        if h > 0:
            surface(painter, rect, qcolor(theme.ELEVATED, h), None, theme.R_MD)
        color = theme.mix(theme.TEXT_2, theme.TEXT, h) if self.isEnabled() else QColor(theme.TEXT_DISABLED)
        icons.paint(painter, self._icon, QRectF(7, 7, 16, 16), color.name())
        if self._show_ring():
            paint_focus_ring(painter, rect, theme.R_MD)


def paint_spinner(painter: QPainter, rect: QRectF, phase: float, color: QColor | str) -> None:
    painter.save()
    ring = rect.adjusted(0.75, 0.75, -0.75, -0.75)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor(theme.BORDER), 1.5))
    painter.drawEllipse(ring)
    pen = QPen(QColor(color), 1.5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.drawArc(ring, round((90 - phase * 360) * 16), -90 * 16)
    painter.restore()


# Segmented control


class _SegOption(Pressable):
    def __init__(self, value: Any, label: str, icon: str, height: int, font_size: int, pad: int) -> None:
        super().__init__()
        self.value = value
        self.setText(label)
        self.setCheckable(True)
        self.setAccessibleName(label)
        self._icon = icon
        self._height = height
        self._font_size = font_size
        self._pad = pad
        self.tick = False
        self._on = motion.Tweened(self, 0.0, lambda _v: self.update())
        self.toggled.connect(lambda on: self._on.to(1.0 if on else 0.0, theme.DUR_1))

    def _content_width(self) -> int:
        width = QFontMetrics(theme.font(self._font_size, 500)).horizontalAdvance(self.text())
        if self.tick:
            width += 13 + 6
        if self._icon:
            width += 15 + 6
        return width

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return QSize(self._content_width() + self._pad * 2, self._height)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return QSize(self._content_width() + 8, self._height)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        self._begin(painter)
        rect = QRectF(self.rect())
        if not self.isEnabled():
            color = QColor(theme.TEXT_2 if self.isChecked() else theme.TEXT_DISABLED)
        else:
            color = theme.mix(theme.TEXT_2, theme.TEXT, max(self._on.value, self.hover))
        painter.setFont(theme.font(self._font_size, 500))
        x = rect.center().x() - self._content_width() / 2
        if self.tick:
            icons.paint(painter, "check", QRectF(x, rect.center().y() - 6.5, 13, 13), theme.SUCCESS)
            x += 19
        if self._icon:
            icons.paint(painter, self._icon, QRectF(x, rect.center().y() - 7.5, 15, 15), color.name())
            x += 21
        painter.setPen(color)
        painter.drawText(
            QRectF(x, rect.top(), rect.width(), rect.height()), Qt.AlignmentFlag.AlignVCenter, self.text()
        )
        if self._show_ring():
            paint_focus_ring(painter, rect, theme.R_MD)


class SegmentedControl(QWidget):
    """Options on one track with a single thumb that glides to the selected one.

    Picking an option emits `picked`; the owner decides whether to select it (Auto
    click, for example, asks for confirmation first).
    """

    picked = Signal(object)

    _HEIGHTS = {"sm": (26, 12), "md": (30, 13), "lg": (34, 13)}

    def __init__(self, options: Iterable[tuple[Any, str, str]], size: str = "md", fit: bool = False) -> None:
        super().__init__()
        height, font_size = self._HEIGHTS[size]
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(0)
        self.options: list[_SegOption] = []
        for value, label, icon in options:
            option = _SegOption(value, label, icon, height, font_size, 12 if fit else 8)
            option.setAutoExclusive(False)
            option.clicked.connect(lambda _c=False, o=option: self._pick(o))
            option.installEventFilter(self)
            if fit:
                option.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            else:
                option.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            layout.addWidget(option, 0 if fit else 1)
            self.options.append(option)
        if fit:
            self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        else:
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._value: Any = None
        self._risk = False
        self._from = QRectF()
        self._to = QRectF()
        self._travel = motion.Tweened(self, 1.0, lambda _v: self.update())
        self._risk_tween = motion.Tweened(self, 0.0, lambda _v: self.update())
        self.setAccessibleName("Options")

    def value(self) -> Any:
        return self._value

    def option(self, value: Any) -> _SegOption:
        return next(o for o in self.options if o.value == value)

    def set_value(self, value: Any, animate: bool = True) -> None:
        changed = value != self._value
        self._value = value
        for option in self.options:
            option.setChecked(option.value == value)
            option.setFocusPolicy(
                Qt.FocusPolicy.StrongFocus
                if option.value == value or value is None
                else Qt.FocusPolicy.ClickFocus
            )
        target = self._thumb_target()
        if changed and animate and not self._from.isNull() and self.isVisible():
            self._from = self._current_thumb()
            self._to = target
            self._travel.snap(0.0)
            self._travel.to(1.0, theme.DUR_3, theme.EASE_MOVE)
        else:
            self._from = self._to = target
            self._travel.snap(1.0)

    def set_risk(self, risk: bool) -> None:
        """Gives the thumb an accent border (Auto click is selected)."""
        if risk != self._risk:
            self._risk = risk
            self._risk_tween.to(1.0 if risk else 0.0, theme.DUR_2)

    def set_options_enabled(self, enabled: bool) -> None:
        for option in self.options:
            option.setEnabled(enabled)

    def set_tick(self, value: Any, tick: bool) -> None:
        option = self.option(value)
        if option.tick != tick:
            option.tick = tick
            option.updateGeometry()
            option.update()

    def _thumb_target(self) -> QRectF:
        chosen = next((o for o in self.options if o.value == self._value), None)
        return QRectF(chosen.geometry()) if chosen is not None else QRectF()

    def _current_thumb(self) -> QRectF:
        t = self._travel.value
        a, b = self._from, self._to
        if a.isNull():
            return b
        return QRectF(
            a.x() + (b.x() - a.x()) * t,
            a.y() + (b.y() - a.y()) * t,
            a.width() + (b.width() - a.width()) * t,
            a.height() + (b.height() - a.height()) * t,
        )

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        QTimer.singleShot(0, self, self._settle)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        QTimer.singleShot(0, self, self._settle)

    def _settle(self) -> None:
        if not self._travel.running:
            self._from = self._to = self._thumb_target()
            self.update()

    def _pick(self, option: _SegOption) -> None:
        option.setChecked(option.value == self._value)  # selection is the owner's decision
        if option.isEnabled():
            self.picked.emit(option.value)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt override
        if event.type() == QEvent.Type.KeyPress and watched in self.options:
            key = event.key()
            if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
                enabled = [o for o in self.options if o.isEnabled()]
                if watched in enabled and len(enabled) > 1:
                    step = 1 if key == Qt.Key.Key_Right else -1
                    target = enabled[(enabled.index(watched) + step) % len(enabled)]
                    target.setFocus(Qt.FocusReason.TabFocusReason)
                    self._pick(target)
                return True
        return super().eventFilter(watched, event)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        surface(painter, QRectF(self.rect()), theme.SURFACE, theme.BORDER_SUBTLE, theme.R_LG)
        thumb = self._current_thumb()
        if thumb.isNull() or self._value is None:
            return
        shadow = thumb.translated(0, 1)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 90))
        painter.drawRoundedRect(shadow, theme.R_MD, theme.R_MD)
        border = theme.mix(theme.BORDER, theme.line(theme.ACCENT), self._risk_tween.value)
        surface(painter, thumb, theme.ELEVATED, border, theme.R_MD)


# Switch, checkbox, select, slider


class Switch(Pressable):
    """A 34 × 20 on/off switch whose knob slides over 200 ms."""

    def __init__(self, accessible_name: str = "") -> None:
        super().__init__()
        self.setCheckable(True)
        self.setFixedSize(34, 20)
        if accessible_name:
            self.setAccessibleName(accessible_name)
        self._on = motion.Tweened(self, 0.0, lambda _v: self.update())
        self.toggled.connect(lambda on: self._on.to(1.0 if on else 0.0, theme.DUR_2, theme.EASE_MOVE))

    def set_checked_quietly(self, checked: bool) -> None:
        self.blockSignals(True)
        self.setChecked(checked)
        self.blockSignals(False)
        self._on.snap(1.0 if checked else 0.0)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        on = self._on.value
        hover = self.hover * (1 - on)
        enabled = self.isEnabled()
        track = theme.mix(theme.ELEVATED, theme.ACCENT, on)
        border = theme.mix(theme.mix(theme.BORDER, theme.BORDER_STRONG, hover), theme.ACCENT, on)
        if not enabled:
            track, border = theme.mix(theme.SURFACE, theme.TEXT_DISABLED, on), QColor(theme.BORDER_SUBTLE)
        rect = QRectF(self.rect())
        surface(painter, rect, track, border, 10)
        knob_width = 14 + 2 * self._press.value
        travel = 14 - 2 * self._press.value * on
        knob = QRectF(3 + travel * on, 3, knob_width, 14)
        knob_color = theme.mix(theme.mix(theme.TEXT_2, theme.TEXT, hover), theme.BG, on)
        if not enabled:
            knob_color = QColor(theme.TEXT_DISABLED if not on else theme.SURFACE)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(knob_color)
        painter.drawRoundedRect(knob, 7, 7)
        if self._show_ring():
            paint_focus_ring(painter, rect, 10)


class CheckBox(Pressable):
    """A 16 px checkbox with its label; the check scales in over 200 ms."""

    def __init__(self, label: str) -> None:
        super().__init__()
        self.setText(label)
        self.setCheckable(True)
        self._on = motion.Tweened(self, 0.0, lambda _v: self.update())
        self.toggled.connect(lambda on: self._on.to(1.0 if on else 0.0, theme.DUR_2))
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return QSize(26 + QFontMetrics(theme.font(13)).horizontalAdvance(self.text()) + 2, 22)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        on = self._on.value
        box = QRectF(0, 3, 16, 16)
        scale = 1.0 - 0.08 * self._press.value
        center = box.center()
        box = QRectF(center.x() - 8 * scale, center.y() - 8 * scale, 16 * scale, 16 * scale)
        border = theme.mix(theme.mix(theme.BORDER_STRONG, theme.TEXT_3, self.hover), theme.TEXT, on)
        surface(painter, box, theme.mix(theme.ELEVATED, theme.TEXT, on), border, theme.R_XS)
        if on > 0:
            size = 12 * (0.6 + 0.4 * on)
            painter.setOpacity(min(1.0, on * 1.5))
            icons.paint(
                painter,
                "check",
                QRectF(center.x() - size / 2, center.y() - size / 2, size, size),
                theme.BG,
                stroke=2.5,
            )
            painter.setOpacity(1.0)
        if self._show_ring():
            paint_focus_ring(painter, box.adjusted(-2, -2, 2, 2), theme.R_XS + 2)
        painter.setFont(theme.font(13))
        painter.setPen(QColor(theme.TEXT))
        painter.drawText(
            QRectF(26, 0, self.width() - 26, self.height()), Qt.AlignmentFlag.AlignVCenter, self.text()
        )


class Select(QComboBox):
    """A 168 × 32 dropdown with the design's chevron."""

    def __init__(self, accessible_name: str = "") -> None:
        super().__init__()
        self.setFixedWidth(168)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(theme.font(12))
        if accessible_name:
            self.setAccessibleName(accessible_name)

    def set_items(self, items: list[tuple[str, Any]], current: Any) -> None:
        self.blockSignals(True)
        self.clear()
        for label, data in items:
            self.addItem(label, data)
        index = self.findData(current)
        self.setCurrentIndex(max(index, 0))
        self.blockSignals(False)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = theme.TEXT_2 if self.isEnabled() else theme.TEXT_DISABLED
        icons.paint(painter, "down", QRectF(self.width() - 24, self.height() / 2 - 7, 14, 14), color)


class StopSlider(QSlider):
    """A slider with a few named stops: 4 px track, accent fill, 14 px thumb."""

    def __init__(self, stops: int, accessible_name: str) -> None:
        super().__init__(Qt.Orientation.Horizontal)
        self.setRange(0, stops - 1)
        self.setPageStep(1)
        self.setFixedHeight(20)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(accessible_name)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self._hover = motion.Tweened(self, 0.0, lambda _v: self.update())
        self._focus_visible = False

    def enterEvent(self, event) -> None:  # noqa: N802 - Qt override
        self._hover.to(1.0, theme.DUR_1)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt override
        self._hover.to(0.0, theme.DUR_1)
        super().leaveEvent(event)

    def focusInEvent(self, event: QFocusEvent) -> None:  # noqa: N802 - Qt override
        self._focus_visible = event.reason() in KEYBOARD_FOCUS
        super().focusInEvent(event)

    def _x_for(self, value: int) -> float:
        span = max(self.maximum() - self.minimum(), 1)
        return 7 + (self.width() - 14) * (value - self.minimum()) / span

    def _value_at(self, x: float) -> int:
        span = max(self.maximum() - self.minimum(), 1)
        ratio = min(max((x - 7) / max(self.width() - 14, 1), 0.0), 1.0)
        return self.minimum() + round(ratio * span)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            self.setValue(self._value_at(event.position().x()))
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.setValue(self._value_at(event.position().x()))

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        event.accept()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        cy = self.height() / 2
        x = self._x_for(self.value())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.BORDER))
        painter.drawRoundedRect(QRectF(0, cy - 2, self.width(), 4), 2, 2)
        painter.setBrush(QColor(theme.ACCENT if self.isEnabled() else theme.TEXT_DISABLED))
        painter.drawRoundedRect(QRectF(0, cy - 2, x, 4), 2, 2)
        radius = 7 * (1 + 0.15 * self._hover.value)
        if self.hasFocus() and self._focus_visible:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(theme.line(theme.ACCENT), 2))
            painter.drawEllipse(QPointF(x, cy), radius + 3, radius + 3)
            painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 128))
        painter.drawEllipse(QPointF(x, cy + 1), radius, radius)
        painter.setBrush(QColor(theme.TEXT))
        painter.drawEllipse(QPointF(x, cy), radius, radius)


# Key caps


def paint_keycaps(painter: QPainter, keys: list[str], left: float, center_y: float) -> float:
    """Draws key caps starting at `left`; returns their total width."""
    painter.setFont(theme.font(11, mono=True))
    metrics = painter.fontMetrics()
    x = left
    for key in keys:
        width = max(20, metrics.horizontalAdvance(key) + 10)
        cap = QRectF(x, center_y - 10, width, 20)
        surface(painter, cap, theme.ELEVATED, theme.BORDER, 5)
        painter.setPen(QPen(QColor(theme.BORDER), 2))
        painter.drawLine(
            QPointF(cap.left() + 3, cap.bottom() - 1), QPointF(cap.right() - 3, cap.bottom() - 1)
        )
        painter.setPen(QColor(theme.TEXT))
        painter.drawText(cap.adjusted(0, 0, 0, -1), Qt.AlignmentFlag.AlignCenter, key)
        x += width + 3
    return x - left - 3 if keys else 0


def keycaps_width(keys: list[str]) -> int:
    metrics = QFontMetrics(theme.font(11, mono=True))
    return sum(max(20, metrics.horizontalAdvance(k) + 10) for k in keys) + 3 * max(len(keys) - 1, 0)


def split_keys(shortcut: str) -> list[str]:
    return [part for part in shortcut.split("+") if part]


class KeyCaps(QWidget):
    """The emergency-stop shortcut drawn as key caps."""

    def __init__(self, shortcut: str = "") -> None:
        super().__init__()
        self._keys: list[str] = []
        self.set_shortcut(shortcut)

    def set_shortcut(self, shortcut: str) -> None:
        self._keys = split_keys(shortcut)
        self.setFixedSize(max(keycaps_width(self._keys), 1), 22)
        self.setAccessibleName(shortcut)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        paint_keycaps(painter, self._keys, 0, self.height() / 2)


class HotkeyButton(Pressable):
    """Shows the shortcut; press it, then press a new combination to change it."""

    recorded = Signal(str)  # Qt portable text, such as "Ctrl+Shift+F12"
    rejected = Signal(str)  # why a combination cannot be used

    def __init__(self) -> None:
        super().__init__()
        self._keys: list[str] = []
        self.recording = False
        self.clicked.connect(lambda _c=False: self.set_recording(not self.recording))
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def set_shortcut(self, shortcut: str) -> None:
        self._keys = split_keys(shortcut)
        self._describe()
        self.updateGeometry()
        self.update()

    def set_recording(self, recording: bool) -> None:
        self.recording = recording
        self._describe()
        self.updateGeometry()
        self.update()

    def _describe(self) -> None:
        if self.recording:
            self.setAccessibleName("Recording. Press a new key combination, or Escape to cancel.")
        else:
            self.setAccessibleName(f"Emergency stop shortcut: {'+'.join(self._keys)}. Press to change.")

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        if self.recording:
            return QSize(QFontMetrics(theme.font(12)).horizontalAdvance("Press new keys…") + 22, 32)
        return QSize(keycaps_width(self._keys) + 14, 32)

    def focusOutEvent(self, event: QFocusEvent) -> None:  # noqa: N802 - Qt override
        if self.recording:
            self.set_recording(False)
        super().focusOutEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt override
        if not self.recording:
            super().keyPressEvent(event)
            return
        event.accept()
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.set_recording(False)
            return
        if key in (Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta):
            return
        modifiers = event.modifiers() & (
            Qt.KeyboardModifier.ControlModifier
            | Qt.KeyboardModifier.AltModifier
            | Qt.KeyboardModifier.ShiftModifier
        )
        if not modifiers:
            self.rejected.emit("Use at least one of Ctrl, Alt, or Shift")
            return
        sequence = QKeySequence(QKeyCombination(modifiers, Qt.Key(key)))
        self.set_recording(False)
        self.recorded.emit(sequence.toString(QKeySequence.SequenceFormat.PortableText))

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        self._begin(painter)
        rect = QRectF(self.rect())
        if self.recording:
            surface(painter, rect, theme.soft(theme.ACCENT), theme.line(theme.ACCENT), theme.R_MD)
            painter.setFont(theme.font(12))
            painter.setPen(QColor(theme.ACCENT))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Press new keys…")
        else:
            fill = qcolor(theme.SURFACE, self.hover)
            border = theme.mix(theme.BORDER_SUBTLE, theme.BORDER, self.hover)
            surface(painter, rect, fill, border, theme.R_MD)
            paint_keycaps(painter, self._keys, 7, rect.center().y())
        if self._show_ring():
            paint_focus_ring(painter, rect, theme.R_MD)
