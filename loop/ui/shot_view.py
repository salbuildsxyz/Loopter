"""The capture preview: an empty prompt, a loading state, or the screenshot with a selection box.

The box is kept in percent of the screenshot. Drag on empty space to draw it, drag the box
to move it, drag its corner to resize it, or nudge it with the arrow keys (Shift: faster).
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QImage,
    QKeyEvent,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

from loop.ui import motion, theme
from loop.ui.widgets import Spinner, SuccessMark, row, text

HANDLE = 11
BOX_TONES = {"ok": theme.ACCENT, "bad": theme.WARNING, "saved": theme.SUCCESS}


def clamp(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)


class ShotView(QWidget):
    edited = Signal()  # the user drew, moved, resized, or nudged the box

    def __init__(self) -> None:
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self.setAccessibleName("Screenshot")
        self.mode = "empty"  # empty, loading, edit, saved
        self.image: QImage | None = None
        self._ratio = 16 / 9
        self.box: QRectF | None = None  # percent of the screenshot
        self.tag = ""
        self.tone = "ok"
        self._from = QRectF()
        self._travel = motion.Tweened(self, 1.0, lambda _v: self.update())
        self._drag: tuple[str, QPointF, QRectF | None] | None = None
        self._shimmer = 0.0
        self._shimmer_loop = motion.Loop(self, 1100, self._on_shimmer)
        self._saved = motion.Tweened(self, 0.0, lambda _v: self.update())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        self.empty = QWidget()
        empty_layout = QVBoxLayout(self.empty)
        empty_layout.setSpacing(12)
        empty_layout.addStretch(1)
        self.empty_text = text("", "help")
        self.empty_text.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addWidget(self.empty_text)
        self.empty_actions = row(spacing=8)
        empty_layout.addLayout(self.empty_actions)
        empty_layout.addStretch(1)
        layout.addWidget(self.empty)

        self.loading = QWidget()
        loading_layout = QVBoxLayout(self.loading)
        loading_layout.setSpacing(12)
        loading_layout.addStretch(1)
        spinner_row = row(None, Spinner(16), None)
        loading_layout.addLayout(spinner_row)
        caption = text("Taking a screenshot…", "help")
        caption.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        loading_layout.addWidget(caption)
        loading_layout.addStretch(1)
        self.loading.setAccessibleName("Taking a screenshot")
        layout.addWidget(self.loading)

        self.success = SuccessMark(36)
        self.success.setParent(self)
        self._show_mode()

    # Size: the preview always has the screenshot's aspect ratio (16:9 before there is one).

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return QSize(400, round(400 / self._ratio))

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._fit_height()
        self._place_success()

    def _fit_height(self) -> None:
        height = max(round(self.width() / self._ratio), 90)
        if self.height() != height or self.minimumHeight() != height:
            self.setFixedHeight(height)

    # State

    def show_empty(self, message: str) -> None:
        self.mode = "empty"
        self.image = None
        self.box = None
        self._set_ratio(16 / 9)
        self.empty_text.setText(message)
        self._show_mode()

    def show_loading(self) -> None:
        self.mode = "loading"
        self.image = None
        self.box = None
        self._set_ratio(16 / 9)
        self._show_mode()

    def show_image(self, image: QImage, box: QRectF | None) -> None:
        self.mode = "edit"
        self.image = image
        self._set_ratio(image.width() / max(image.height(), 1))
        self.box = QRectF(box) if box is not None else None
        self._from = QRectF(self.box) if self.box is not None else QRectF()
        self._travel.snap(1.0)
        self._saved.snap(0.0)
        self._show_mode()
        motion.rise_in(self, theme.DUR_3, 0)

    def set_box(self, box: QRectF | None, animate: bool = True) -> None:
        """Moves the box (to the next suggestion, for example) over 250 ms."""
        previous = self._shown_box()
        self.box = QRectF(box) if box is not None else None
        if animate and previous is not None and self.box is not None and self.isVisible():
            self._from = previous
            self._travel.snap(0.0)
            self._travel.to(1.0, theme.DUR_3, theme.EASE_MOVE)
        else:
            self._from = QRectF(self.box) if self.box is not None else QRectF()
            self._travel.snap(1.0)
        self.update()

    def set_label(self, tag: str, tone: str) -> None:
        self.tag, self.tone = tag, tone
        self.setAccessibleDescription(f"Selected area: {tag}" if self.box is not None else "")
        self.update()

    def show_saved(self) -> None:
        self.mode = "saved"
        self.tone = "saved"
        self._show_mode()
        self._saved.snap(0.0)
        self._saved.to(1.0, theme.DUR_2)
        self.success.play()

    def unsave(self) -> None:
        self.mode = "edit"
        self._show_mode()

    def _set_ratio(self, ratio: float) -> None:
        if abs(ratio - self._ratio) > 1e-3:
            self._ratio = ratio
            self._fit_height()

    def _show_mode(self) -> None:
        self.empty.setVisible(self.mode == "empty")
        self.loading.setVisible(self.mode == "loading")
        self.success.setVisible(self.mode == "saved")
        self._shimmer_loop.set_running(self.mode == "loading")
        editing = self.mode == "edit"
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus if editing else Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.CrossCursor if editing else Qt.CursorShape.ArrowCursor)
        self.setAccessibleName(
            "Screenshot. Drag to select your button, or use the arrow keys to move the box. "
            "Hold Shift to move faster."
            if editing
            else "Screenshot"
        )
        self._place_success()
        self.update()

    def _place_success(self) -> None:
        size = self.success.size()
        self.success.move(
            round((self.width() - size.width()) / 2), round((self.height() - size.height()) / 2)
        )

    def _on_shimmer(self, phase: float) -> None:
        self._shimmer = phase
        self.update()

    # Geometry

    def _shown_box(self) -> QRectF | None:
        if self.box is None:
            return None
        t = self._travel.value
        a, b = self._from, self.box
        if a.isNull() or t >= 1.0:
            return QRectF(b)
        return QRectF(
            a.x() + (b.x() - a.x()) * t,
            a.y() + (b.y() - a.y()) * t,
            a.width() + (b.width() - a.width()) * t,
            a.height() + (b.height() - a.height()) * t,
        )

    def _to_widget(self, box: QRectF) -> QRectF:
        sx, sy = self.width() / 100, self.height() / 100
        return QRectF(box.x() * sx, box.y() * sy, box.width() * sx, box.height() * sy)

    def _to_percent(self, point: QPointF) -> QPointF:
        return QPointF(point.x() / max(self.width(), 1) * 100, point.y() / max(self.height(), 1) * 100)

    def _handle_rect(self, box: QRectF) -> QRectF:
        corner = self._to_widget(box).bottomRight()
        return QRectF(corner.x() - 5.5, corner.y() - 5.5, HANDLE, HANDLE)

    # Mouse and keyboard

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        if self.mode != "edit" or event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        start = self._to_percent(event.position())
        box = QRectF(self.box) if self.box is not None else None
        if box is not None and self._handle_rect(box).adjusted(-3, -3, 3, 3).contains(event.position()):
            mode = "resize"
        elif box is not None and box.contains(start):
            mode = "move"
        else:
            mode = "draw"
        self._drag = (mode, start, box)
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        if self._drag is None:
            self._update_cursor(event.position())
            return
        mode, start, b0 = self._drag
        p = self._to_percent(event.position())
        dx, dy = p.x() - start.x(), p.y() - start.y()
        if mode == "move" and b0 is not None:
            box = QRectF(
                clamp(b0.x() + dx, 0, 100 - b0.width()),
                clamp(b0.y() + dy, 0, 100 - b0.height()),
                b0.width(),
                b0.height(),
            )
        elif mode == "resize" and b0 is not None:
            box = QRectF(
                b0.x(),
                b0.y(),
                clamp(b0.width() + dx, 1, 100 - b0.x()),
                clamp(b0.height() + dy, 1, 100 - b0.y()),
            )
        else:
            x = clamp(min(start.x(), p.x()), 0, 100)
            y = clamp(min(start.y(), p.y()), 0, 100)
            box = QRectF(x, y, clamp(abs(dx), 1, 100 - x), clamp(abs(dy), 1, 100 - y))
        self.set_box(box, animate=False)
        self.edited.emit()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        self._drag = None
        super().mouseReleaseEvent(event)

    def _update_cursor(self, position: QPointF) -> None:
        if self.mode != "edit":
            return
        box = self.box
        if box is not None and self._handle_rect(box).adjusted(-3, -3, 3, 3).contains(position):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif box is not None and box.contains(self._to_percent(position)):
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.setCursor(Qt.CursorShape.CrossCursor)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt override
        moves = {
            Qt.Key.Key_Left: (-1, 0),
            Qt.Key.Key_Right: (1, 0),
            Qt.Key.Key_Up: (0, -1),
            Qt.Key.Key_Down: (0, 1),
        }
        if self.mode != "edit" or self.box is None or event.key() not in moves:
            return super().keyPressEvent(event)
        step = 2.0 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 0.5
        dx, dy = moves[event.key()]
        box = QRectF(self.box)
        box.moveTo(
            clamp(box.x() + dx * step, 0, 100 - box.width()),
            clamp(box.y() + dy * step, 0, 100 - box.height()),
        )
        self.set_box(box, animate=False)
        self.edited.emit()
        event.accept()

    # Painting

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(self.rect())
        frame = QPainterPath()
        frame.addRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), theme.R_MD, theme.R_MD)
        painter.save()
        painter.setClipPath(frame)
        painter.fillRect(rect, QColor(theme.BG))
        if self.mode == "empty":
            self._paint_dots(painter)
        elif self.mode == "loading":
            self._paint_shimmer(painter)
        elif self.image is not None:
            painter.drawImage(rect, self.image)
            self._paint_selection(painter)
            if self.mode == "saved":
                painter.fillRect(rect, QColor(6, 7, 10, round(0.5 * 255 * self._saved.value)))
        painter.restore()
        painter.setPen(QPen(QColor(theme.BORDER_SUBTLE), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(frame)
        if self.hasFocus() and self.mode == "edit" and self.box is None:
            painter.setPen(QPen(theme.line(theme.ACCENT), 2))
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), theme.R_MD, theme.R_MD)

    def _paint_dots(self, painter: QPainter) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 10))
        for y in range(6, self.height(), 12):
            for x in range(6, self.width(), 12):
                painter.drawEllipse(QPointF(x, y), 0.6, 0.6)

    def _paint_shimmer(self, painter: QPainter) -> None:
        if not self._shimmer_loop.running:
            return
        width = self.width() * 2
        offset = self.width() * 1.5 - self._shimmer * width
        gradient = QLinearGradient(offset, 0, offset + width, self.height() * 0.36)
        gradient.setColorAt(0.3, QColor(255, 255, 255, 0))
        gradient.setColorAt(0.5, QColor(255, 255, 255, 13))
        gradient.setColorAt(0.7, QColor(255, 255, 255, 0))
        painter.fillRect(self.rect(), gradient)

    def _paint_selection(self, painter: QPainter) -> None:
        shown = self._shown_box()
        if shown is None:
            return
        box = self._to_widget(shown)
        outside = QPainterPath()
        outside.addRect(QRectF(self.rect()))
        hole = QPainterPath()
        hole.addRoundedRect(box, theme.R_XS, theme.R_XS)
        if self.mode == "edit":
            painter.fillPath(outside.subtracted(hole), theme.SHADE)
        color = QColor(BOX_TONES[self.tone])
        painter.setPen(QPen(color, 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(box, theme.R_XS, theme.R_XS)
        if self.mode == "edit":
            handle = self._handle_rect(shown)
            painter.setPen(QPen(QColor(theme.BG), 2))
            painter.setBrush(QColor(theme.TEXT))
            painter.drawRoundedRect(handle, 3, 3)
            if self.hasFocus():
                painter.setPen(QPen(theme.line(theme.ACCENT), 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(box.adjusted(-3, -3, 3, 3), theme.R_XS + 2, theme.R_XS + 2)
        if self.tag:
            self._paint_tag(painter, box, shown, color)

    def _paint_tag(self, painter: QPainter, box: QRectF, shown: QRectF, color: QColor) -> None:
        painter.setFont(theme.font(10, 500))
        width = painter.fontMetrics().horizontalAdvance(self.tag) + 12
        below = shown.y() + shown.height() < 86
        top = box.bottom() + 4 if below else box.top() - 21
        pill = QRectF(box.left() - 0.75, top, width, 17)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(pill, theme.R_XS, theme.R_XS)
        painter.setPen(QColor(theme.BG))
        painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, self.tag)
