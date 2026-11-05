"""The section tabs: text tabs with one underline that slides to the selected tab."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import QHBoxLayout, QWidget

from loop.ui import motion, theme
from loop.ui.controls import Pressable, paint_focus_ring

FLAG_COLORS = {"warn": theme.WARNING, "error": theme.DANGER}


class _Tab(Pressable):
    def __init__(self, label: str) -> None:
        super().__init__()
        self.setText(label)
        self.setCheckable(True)
        self.flag = ""
        self.setFixedHeight(theme.H_TABS)
        self._on = motion.Tweened(self, 0.0, lambda _v: self.update())
        self.toggled.connect(lambda on: self._on.to(1.0 if on else 0.0, theme.DUR_1))

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return QSize(QFontMetrics(theme.font(13, 500)).horizontalAdvance(self.text()) + 20, theme.H_TABS)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(theme.font(13, 500))
        painter.setPen(theme.mix(theme.TEXT_2, theme.TEXT, max(self.hover, self._on.value)))
        painter.drawText(QRectF(self.rect()), Qt.AlignmentFlag.AlignCenter, self.text())
        if self.flag:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(FLAG_COLORS[self.flag]))
            painter.drawEllipse(QRectF(self.width() - 8, 10, 6, 6))
        if self._show_ring():
            paint_focus_ring(painter, QRectF(self.rect()).adjusted(0, 4, 0, -4), theme.R_SM)


class TabBar(QWidget):
    """Text tabs with one underline that slides and resizes to the selected tab."""

    picked = Signal(int)

    def __init__(self, labels: list[str]) -> None:
        super().__init__()
        self.setFixedHeight(theme.H_TABS + 1)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 1)
        layout.setSpacing(2)
        self.tabs = [_Tab(label) for label in labels]
        for index, tab in enumerate(self.tabs):
            tab.clicked.connect(lambda _c=False, i=index: self.picked.emit(i))
            tab.installEventFilter(self)
            layout.addWidget(tab)
        layout.addStretch(1)
        self.current = 0
        self._from = self._to = (0.0, 0.0)
        self._travel = motion.Tweened(self, 1.0, lambda _v: self.update())
        self.setAccessibleName("Sections")

    def set_current(self, index: int, animate: bool = True) -> None:
        self.current = index
        for i, tab in enumerate(self.tabs):
            tab.setChecked(i == index)
            tab.setFocusPolicy(Qt.FocusPolicy.StrongFocus if i == index else Qt.FocusPolicy.ClickFocus)
        target = self._indicator_for(index)
        if animate and self.isVisible() and self._to != (0.0, 0.0):
            self._from = self._indicator()
            self._to = target
            self._travel.snap(0.0)
            self._travel.to(1.0, theme.DUR_3, theme.EASE_MOVE)
        else:
            self._from = self._to = target
            self._travel.snap(1.0)

    def set_flag(self, index: int, flag: str) -> None:
        if self.tabs[index].flag != flag:
            self.tabs[index].flag = flag
            self.tabs[index].update()

    def flag(self, index: int) -> str:
        return self.tabs[index].flag

    def _indicator_for(self, index: int) -> tuple[float, float]:
        geometry = self.tabs[index].geometry()
        return geometry.left() + 10.0, geometry.width() - 20.0

    def _indicator(self) -> tuple[float, float]:
        t = self._travel.value
        (x0, w0), (x1, w1) = self._from, self._to
        return x0 + (x1 - x0) * t, w0 + (w1 - w0) * t

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        QTimer.singleShot(0, self, lambda: self.set_current(self.current, animate=False))

    def eventFilter(self, watched, event: QEvent) -> bool:  # noqa: N802 - Qt override
        if event.type() == QEvent.Type.KeyPress and watched in self.tabs:
            key = event.key()
            count = len(self.tabs)
            moves = {
                Qt.Key.Key_Left: (self.current - 1) % count,
                Qt.Key.Key_Right: (self.current + 1) % count,
                Qt.Key.Key_Home: 0,
                Qt.Key.Key_End: count - 1,
            }
            if key in moves:
                self.picked.emit(moves[key])
                self.tabs[moves[key]].setFocus(Qt.FocusReason.TabFocusReason)
                return True
        return super().eventFilter(watched, event)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setPen(QColor(theme.BORDER_SUBTLE))
        painter.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        x, width = self._indicator()
        if width > 0:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.TEXT))
            painter.drawRoundedRect(QRectF(x, self.height() - 2, width, 2), 1, 1)
