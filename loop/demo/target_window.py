"""A local window that plays the demo scenario. It is the only place LOOP may click."""

from __future__ import annotations

import math

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from loop import win32
from loop.capture import Region
from loop.demo import SCREEN_SIZE
from loop.demo.scenario import DemoScenario
from loop.input_guard import ClickTarget, InputGuard
from loop.ui import theme
from loop.ui.widgets import bgr_to_qimage


class DemoTargetWindow(QWidget):
    visibility_changed = Signal(bool)

    def __init__(self, guard: InputGuard) -> None:
        # Kept on top so scans and clicks see this window rather than whatever is behind it.
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle("LOOP Demo Target")
        self._guard = guard
        self._scenario = DemoScenario()
        self._pixmap = QPixmap()
        self._advance_timer = QTimer(self)
        self._advance_timer.setSingleShot(True)
        self._advance_timer.timeout.connect(self._advance)
        self._render()

    def _render(self) -> None:
        self._pixmap = QPixmap.fromImage(bgr_to_qimage(self._scenario.render()))
        screen = self._scenario.screen
        if screen.auto_advance_ms:
            self._advance_timer.start(screen.auto_advance_ms)
        self.update()

    def _advance(self) -> None:
        self._scenario.advance()
        self._render()

    def _fit_to_physical_size(self) -> None:
        # Size the client area so the fixture shows at exactly 1:1 physical pixels,
        # which keeps template matching independent of Windows display scaling.
        ratio = self.devicePixelRatioF()
        width, height = SCREEN_SIZE
        self.setFixedSize(math.ceil(width / ratio), math.ceil(height / ratio))

    def _publish_target(self) -> None:
        if not self.isVisible():
            self._guard.set_target(None)
            return
        width, height = SCREEN_SIZE
        if QGuiApplication.platformName() == "windows":
            hwnd = int(self.winId())
            client = win32.client_rect(hwnd)
        else:
            hwnd = 0
            ratio = self.devicePixelRatioF()
            origin = self.mapToGlobal(self.rect().topLeft())
            client = Region(round(origin.x() * ratio), round(origin.y() * ratio), width, height)
        region = Region(client.left, client.top, min(width, client.width), min(height, client.height))
        self._guard.set_target(ClickTarget(region, window=hwnd))

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        self._fit_to_physical_size()
        handle = self.windowHandle()
        if handle is not None:
            handle.screenChanged.connect(self._on_screen_changed, Qt.ConnectionType.UniqueConnection)
        self._publish_target()
        self.visibility_changed.emit(True)

    def _on_screen_changed(self, _screen) -> None:
        self._fit_to_physical_size()
        self._publish_target()

    def moveEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().moveEvent(event)
        self._publish_target()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._publish_target()

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().hideEvent(event)
        self._guard.set_target(None)
        self.visibility_changed.emit(False)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        ratio = self.devicePixelRatioF()
        x, y = round(event.position().x() * ratio), round(event.position().y() * ratio)
        if event.button() == Qt.MouseButton.LeftButton and self._scenario.press(x, y):
            self._render()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(theme.BG_0))
        self._pixmap.setDevicePixelRatio(self.devicePixelRatioF())
        painter.drawPixmap(0, 0, self._pixmap)
