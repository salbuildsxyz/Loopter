"""Floating layers inside the window: toasts and the Auto click confirmation."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QPropertyAnimation, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QKeyEvent, QMouseEvent, QPainter
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QWidget
from shiboken6 import isValid

from loop.ui import icons, motion, theme
from loop.ui.controls import Button, CheckBox, KeyCaps, surface
from loop.ui.widgets import Notice, column, row, text

TOAST_ICONS = {"ok": ("check-circle", theme.SUCCESS), "warn": ("alert", theme.WARNING)}
TOAST_ICONS |= {"err": ("x-circle", theme.DANGER), "info": ("info", theme.TEXT_2)}
SHADOW = 12  # room around a toast for its shadow


def paint_shadow(painter: QPainter, rect: QRectF, radius: float) -> None:
    painter.setPen(Qt.PenStyle.NoPen)
    for spread, alpha in ((10, 14), (6, 24), (3, 40), (1, 60)):
        painter.setBrush(QColor(0, 0, 0, alpha))
        painter.drawRoundedRect(
            rect.adjusted(-spread, -spread + 4, spread, spread + 4), radius + spread, radius + spread
        )


class Toast(QWidget):
    def __init__(self, parent: QWidget, message: str, kind: str) -> None:
        super().__init__(parent)
        self.message = message
        self.kind = kind
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAccessibleName(message)
        self.setAccessibleDescription("alert" if kind == "err" else "status")
        self.leaving = False

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        width = QFontMetrics(theme.font(13)).horizontalAdvance(self.message) + 12 + 15 + 10 + 14
        return QSize(width + SHADOW * 2, 36 + SHADOW * 2)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        body = QRectF(self.rect()).adjusted(SHADOW, SHADOW, -SHADOW, -SHADOW)
        paint_shadow(painter, body, theme.R_LG)
        surface(painter, body, theme.ELEVATED, theme.BORDER, theme.R_LG)
        icon, color = TOAST_ICONS.get(self.kind, TOAST_ICONS["info"])
        icons.paint(painter, icon, QRectF(body.left() + 12, body.center().y() - 7.5, 15, 15), color)
        painter.setFont(theme.font(13))
        painter.setPen(QColor(theme.TEXT))
        metrics = painter.fontMetrics()
        available = int(body.width() - 12 - 15 - 10 - 14)
        shown = metrics.elidedText(self.message, Qt.TextElideMode.ElideRight, available)
        painter.drawText(body.adjusted(37, 0, -14, 0), Qt.AlignmentFlag.AlignVCenter, shown)


class ToastHost(QWidget):
    """Shows up to two toasts centered near the bottom of the window. They never block clicks."""

    MAX_TOASTS = 2

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.toasts: list[Toast] = []
        self.bottom = 16
        parent.installEventFilter(self)
        self.setGeometry(parent.rect())

    def eventFilter(self, watched, event: QEvent) -> bool:  # noqa: N802 - Qt override
        if watched is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self.setGeometry(self.parentWidget().rect())
            self._layout(animate=False)
        return False

    def set_bottom(self, bottom: int) -> None:
        self.bottom = bottom
        self._layout(animate=False)

    def show_message(self, message: str, kind: str = "info") -> None:
        toast = Toast(self, message, kind)
        self.toasts.append(toast)
        while len(self.toasts) > self.MAX_TOASTS:
            old = self.toasts.pop(0)
            old.deleteLater()
        self.raise_()
        toast.show()
        self._layout(animate=True, entering=toast)
        QTimer.singleShot(theme.TOAST_HOLD, toast, lambda: self._dismiss(toast))

    def messages(self) -> list[str]:
        return [t.message for t in self.toasts if isValid(t) and not t.leaving]

    def _targets(self) -> list[tuple[Toast, QPoint]]:
        placed = []
        y = self.height() - self.bottom + SHADOW
        for toast in reversed([t for t in self.toasts if isValid(t)]):
            hint = toast.sizeHint()
            width = min(hint.width(), self.width() - 48 + SHADOW * 2)
            toast.resize(width, hint.height())
            y -= hint.height() - SHADOW * 2 + 8
            placed.append((toast, QPoint(round((self.width() - width) / 2), y - SHADOW)))
        return placed

    def _layout(self, animate: bool, entering: Toast | None = None) -> None:
        for toast, target in self._targets():
            if toast is entering and animate and not motion.reduced():
                toast.move(target + QPoint(0, 8))
                self._animate(toast, target, 0.0, 1.0, theme.DUR_2, theme.EASE_OUT)
            else:
                toast.move(target)

    def _dismiss(self, toast: Toast) -> None:
        if not isValid(toast) or toast.leaving:
            return
        toast.leaving = True

        def remove() -> None:
            if toast in self.toasts:
                self.toasts.remove(toast)
            toast.deleteLater()

        if motion.reduced():
            remove()
            return
        self._animate(toast, toast.pos() + QPoint(0, 4), 1.0, 0.0, theme.DUR_EXIT, theme.EASE_IN, remove)

    @staticmethod
    def _animate(
        toast: Toast, target: QPoint, start: float, end: float, duration: int, easing, done=None
    ) -> None:
        effect = QGraphicsOpacityEffect(toast)
        effect.setOpacity(start)
        toast.setGraphicsEffect(effect)
        fade = QPropertyAnimation(effect, b"opacity", toast)
        fade.setDuration(duration)
        fade.setStartValue(start)
        fade.setEndValue(end)
        fade.setEasingCurve(easing)
        move = QPropertyAnimation(toast, b"pos", toast)
        move.setDuration(duration)
        move.setStartValue(toast.pos())
        move.setEndValue(target)
        move.setEasingCurve(easing)
        if done is not None:
            fade.finished.connect(done)
        else:
            fade.finished.connect(lambda: isValid(toast) and toast.setGraphicsEffect(None))
        fade.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        move.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)


class _ModalIcon(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(32, 32)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        surface(painter, QRectF(self.rect()), theme.soft(theme.ACCENT), theme.line(theme.ACCENT), theme.R_MD)
        icons.paint(painter, "pointer", QRectF(8, 8, 16, 16), theme.ACCENT)


class _Card(QFrame):
    """The dialog surface; `divided` gets a hairline above and below it."""

    divided: QWidget | None = None

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        surface(painter, QRectF(self.rect()), theme.SURFACE, theme.BORDER, theme.R_XL)
        if self.divided is not None:
            area = self.divided.geometry()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            painter.setPen(QColor(theme.BORDER_SUBTLE))
            painter.drawLine(area.left(), area.top(), area.right(), area.top())
            painter.drawLine(area.left(), area.bottom(), area.right(), area.bottom())


def _safeguard(icon: str, content: QWidget) -> QHBoxLayout:
    mark = QLabel()
    mark.setPixmap(icons.pixmap(icon, theme.TEXT_3, 14))
    mark.setFixedSize(14, 18)
    mark.setAlignment(Qt.AlignmentFlag.AlignBottom)
    layout = row(spacing=10)
    layout.addWidget(mark, 0, Qt.AlignmentFlag.AlignTop)
    layout.addWidget(content, 1)
    return layout


class AutoClickDialog(QWidget):
    """Asks before Auto click is turned on: real clicks, the safeguards, and the risk."""

    accepted = Signal()
    rejected = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._scrim = motion.Tweened(self, 0.0, lambda _v: self.update())
        self.closing = False
        self.card = _Card()
        self.card.setParent(self)
        self.card.setAccessibleName("Turn on Auto click?")
        layout = column(12, (20, 20, 20, 20))
        self.card.setLayout(layout)
        layout.addLayout(row(_ModalIcon(), text("Turn on Auto click?", "modal-title"), None, spacing=12))
        layout.addWidget(
            text(
                "Loopter will press your saved buttons with real mouse clicks during your sessions.",
                "body-2",
                wrap=True,
            )
        )
        guards = QWidget()
        guards_layout = column(8, (0, 12, 0, 12))
        guards.setLayout(guards_layout)
        self.keys = KeyCaps()
        stops = QWidget()
        stops.setLayout(row(self.keys, text("stops everything instantly.", "help"), None, spacing=6))
        for icon, content in (
            (
                "pointer",
                text("Clicks only the game window in front — never Loopter itself.", "help", wrap=True),
            ),
            (
                "pause",
                text("Waits until you haven't used the mouse or keyboard for 2 seconds.", "help", wrap=True),
            ),
            ("keyboard", stops),
            ("refresh", text("Asks again after every restart or emergency stop.", "help", wrap=True)),
        ):
            guards_layout.addLayout(_safeguard(icon, content))
        self.card.divided = guards
        layout.addWidget(guards)
        layout.addWidget(
            Notice(
                "warn",
                "Automating input may break a game's terms of service and can lead to account restrictions. "
                "Loopter isn't undetectable. Only use it where automation is allowed.",
            )
        )
        self.accept_box = CheckBox("I understand and accept the risk")
        self.accept_box.toggled.connect(lambda on: self.confirm_button.setEnabled(on))
        layout.addWidget(self.accept_box)
        self.cancel_button = Button("Cancel", self.cancel, "secondary")
        self.confirm_button = Button("Turn on Auto click", self.confirm, "accent")
        self.confirm_button.setEnabled(False)
        layout.addSpacing(4)
        layout.addLayout(row(None, self.cancel_button, self.confirm_button))
        self.hide()

    @property
    def is_open(self) -> bool:
        return self.isVisible() and not self.closing

    def open(self, hotkey: str) -> None:
        self.keys.set_shortcut(hotkey)
        self.accept_box.setChecked(False)
        self.confirm_button.setEnabled(False)
        self.closing = False
        self.setGeometry(self.parentWidget().rect())
        self._place_card()
        self.raise_()
        self.show()
        self._scrim.snap(0.0)
        self._scrim.to(1.0, theme.DUR_2)
        self._animate_card(True)
        self.cancel_button.setFocus(Qt.FocusReason.OtherFocusReason)

    def confirm(self) -> None:
        if self.accept_box.isChecked():
            self._close(self.accepted)

    def cancel(self) -> None:
        self._close(self.rejected)

    def _close(self, signal) -> None:
        if not self.isVisible() or self.closing:
            return
        self.closing = True
        self._scrim.to(0.0, theme.DUR_EXIT, theme.EASE_IN)

        def done() -> None:
            self.hide()
            self.closing = False

        self._animate_card(False, done)
        signal.emit()

    def _animate_card(self, entering: bool, done=None) -> None:
        final = self._card_position()
        duration = motion.ms(theme.DUR_3 if entering else theme.DUR_EXIT)
        if duration <= 0:
            self.card.move(final)
            if done:
                done()
            return
        effect = QGraphicsOpacityEffect(self.card)
        self.card.setGraphicsEffect(effect)
        fade = QPropertyAnimation(effect, b"opacity", self.card)
        fade.setDuration(duration)
        fade.setStartValue(0.0 if entering else 1.0)
        fade.setEndValue(1.0 if entering else 0.0)
        move = QPropertyAnimation(self.card, b"pos", self.card)
        move.setDuration(duration)
        move.setStartValue(final + QPoint(0, 6) if entering else final)
        move.setEndValue(final if entering else final + QPoint(0, 4))
        for animation in (fade, move):
            animation.setEasingCurve(theme.EASE_OUT if entering else theme.EASE_IN)

        def finished() -> None:
            if isValid(self.card):
                self.card.setGraphicsEffect(None)
            if done:
                done()

        fade.finished.connect(finished)
        fade.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        move.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def _card_position(self) -> QPoint:
        return QPoint(
            round((self.width() - self.card.width()) / 2), round((self.height() - self.card.height()) / 2)
        )

    def _place_card(self) -> None:
        width = min(420, self.width() - 40)
        self.card.setFixedSize(width, self.card.layout().totalHeightForWidth(width))
        self.card.move(self._card_position())

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._place_card()

    def focusNextPrevChild(self, forward: bool) -> bool:  # noqa: N802 - Qt override
        """Keeps keyboard focus inside the dialog while it is open."""
        items = [w for w in (self.accept_box, self.cancel_button, self.confirm_button) if w.isEnabled()]
        current = next((i for i, w in enumerate(items) if w.hasFocus()), -1)
        items[(current + (1 if forward else -1)) % len(items)].setFocus(Qt.FocusReason.TabFocusReason)
        return True

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt override
        if event.key() == Qt.Key.Key_Escape:
            self.cancel()
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        if not self.card.geometry().contains(event.position().toPoint()):
            self.cancel()
        event.accept()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        scrim = QColor(theme.SCRIM)
        scrim.setAlphaF(scrim.alphaF() * self._scrim.value)
        painter.fillRect(self.rect(), scrim)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        paint_shadow(painter, QRectF(self.card.geometry()), theme.R_XL)
