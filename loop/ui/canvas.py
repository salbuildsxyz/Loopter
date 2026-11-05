"""Screenshot preview with drag-to-select and match overlays. Coordinates are image pixels."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from loop.capture import Region
from loop.ui import theme

MIN_SELECTION = 4


class ImageCanvas(QWidget):
    selection_changed = Signal(object)  # Region | None

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(320, 160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._image: QImage | None = None
        self._selection: Region | None = None
        self._drag_origin: QPointF | None = None
        self._outline: Region | None = None
        self._marks: list[tuple[Region, str, str]] = []

    @property
    def selection(self) -> Region | None:
        return self._selection

    def set_image(self, image: QImage) -> None:
        self._image = image
        self._marks = []
        self._set_selection(None)
        self.update()

    def set_outline(self, region: Region | None) -> None:
        """Dashed outline for the current scan region (image coordinates)."""
        self._outline = region
        self.update()

    def set_marks(self, marks: list[tuple[Region, str, str]]) -> None:
        """Labeled boxes (image coordinates) drawn over the screenshot: (box, caption, color)."""
        self._marks = marks
        self.update()

    def select(self, region: Region | None) -> None:
        self._set_selection(region)
        self.update()

    def _set_selection(self, region: Region | None) -> None:
        self._selection = region
        self.selection_changed.emit(region)

    def _target_rect(self) -> QRectF:
        assert self._image is not None
        iw, ih = self._image.width(), self._image.height()
        scale = min(self.width() / iw, self.height() / ih)
        w, h = iw * scale, ih * scale
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def _to_image(self, point: QPointF) -> QPointF:
        rect = self._target_rect()
        scale = self._image.width() / rect.width()
        x = min(max((point.x() - rect.left()) * scale, 0), self._image.width())
        y = min(max((point.y() - rect.top()) * scale, 0), self._image.height())
        return QPointF(x, y)

    def _to_widget(self, region: Region) -> QRectF:
        rect = self._target_rect()
        scale = rect.width() / self._image.width()
        return QRectF(
            rect.left() + region.left * scale,
            rect.top() + region.top * scale,
            region.width * scale,
            region.height * scale,
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        if self._image is not None and event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = self._to_image(event.position())
            self._set_selection(None)
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        if self._drag_origin is None:
            return
        a, b = self._drag_origin, self._to_image(event.position())
        left, top = int(min(a.x(), b.x())), int(min(a.y(), b.y()))
        width, height = int(abs(a.x() - b.x())), int(abs(a.y() - b.y()))
        self._selection = Region(left, top, width, height) if width and height else None
        self.update()

    def mouseReleaseEvent(self, _event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        if self._drag_origin is None:
            return
        self._drag_origin = None
        selection = self._selection
        if selection and (selection.width < MIN_SELECTION or selection.height < MIN_SELECTION):
            selection = None
        self._set_selection(selection)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setPen(QPen(QColor(theme.LINE), 1))
        p.setBrush(QColor(theme.BG_0))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        if self._image is None:
            p.setPen(QColor(theme.FG_3))
            p.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "Capture a screenshot to begin",
            )
            return
        p.drawImage(self._target_rect(), self._image)
        p.setBrush(Qt.BrushStyle.NoBrush)
        if self._outline:
            p.setPen(QPen(QColor(theme.FG_3), 1, Qt.PenStyle.DashLine))
            p.drawRect(self._to_widget(self._outline))
        for box, caption, color in self._marks:
            rect = self._to_widget(box)
            p.setPen(QPen(QColor(color), 2))
            p.drawRect(rect)
            if caption:
                p.drawText(rect.bottomLeft() + QPointF(0, 14), caption)
        if self._selection:
            rect = self._to_widget(self._selection)
            fill = QColor(theme.ACCENT)
            fill.setAlpha(40)
            p.fillRect(rect, fill)
            p.setPen(QPen(QColor(theme.ACCENT), 1, Qt.PenStyle.DashLine))
            p.drawRect(rect)
