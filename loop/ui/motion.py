"""Motion: reduced-motion support and small animation helpers.

Every animation runs on Qt's animation framework, so nothing blocks the UI. Transitions
animate opacity and position only, so layouts never jump. With reduced motion (the app
setting, or Windows' "Animation effects" turned off) values change instantly and
looping effects stop.
"""

from __future__ import annotations

import ctypes
from collections.abc import Callable

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QObject,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    QTimer,
    QVariantAnimation,
    Signal,
    Slot,
)
from PySide6.QtWidgets import QGraphicsOpacityEffect, QStackedWidget, QWidget
from shiboken6 import isValid

from loop import win32
from loop.ui import theme


class _Motion(QObject):
    changed = Signal(bool)  # reduced

    def __init__(self) -> None:
        super().__init__()
        self._user = False
        self._system = system_prefers_reduced_motion()

    @property
    def reduced(self) -> bool:
        return self._user or self._system

    def set_user_preference(self, reduced: bool) -> None:
        before = self.reduced
        self._user = reduced
        if self.reduced != before:
            self.changed.emit(self.reduced)


def system_prefers_reduced_motion() -> bool:
    """Whether Windows' "Animation effects" setting is off."""
    if not win32.IS_WINDOWS:
        return False
    enabled = ctypes.c_int(1)
    spi_getclientareaanimation = 0x1042
    try:
        ok = ctypes.windll.user32.SystemParametersInfoW(
            spi_getclientareaanimation, 0, ctypes.byref(enabled), 0
        )
    except (AttributeError, OSError):
        return False
    return bool(ok) and not enabled.value


_motion: _Motion | None = None


def settings() -> _Motion:
    global _motion
    if _motion is None:
        _motion = _Motion()
    return _motion


def reduced() -> bool:
    return settings().reduced


def ms(duration: int) -> int:
    return 0 if reduced() else duration


def has_effect_above(widget: QWidget) -> bool:
    """Whether an ancestor already renders through a graphics effect (they must not nest)."""
    parent = widget.parentWidget()
    while parent is not None:
        if parent.graphicsEffect() is not None:
            return True
        parent = parent.parentWidget()
    return False


class Tweened(QObject):
    """A float that animates toward targets and calls back on every step; restarts cleanly."""

    def __init__(self, owner: QObject, value: float, on_change: Callable[[float], None]) -> None:
        super().__init__(owner)
        self.value = value
        self._on_change = on_change
        self._animation = QVariantAnimation(self)
        self._animation.valueChanged.connect(self._step)

    def to(self, target: float, duration: int, easing: QEasingCurve = theme.EASE_OUT, delay: int = 0) -> None:
        self._animation.stop()
        duration = ms(duration)
        if duration <= 0 or abs(target - self.value) < 1e-4:
            self._step(target)
            return
        self._animation.setStartValue(float(self.value))
        self._animation.setEndValue(float(target))
        self._animation.setDuration(duration)
        self._animation.setEasingCurve(easing)
        if delay and not reduced():
            QTimer.singleShot(delay, self._animation, self._animation.start)
        else:
            self._animation.start()

    def snap(self, target: float) -> None:
        self._animation.stop()
        self._step(target)

    @property
    def running(self) -> bool:
        return self._animation.state() == QAbstractAnimation.State.Running

    def _step(self, value: object) -> None:
        self.value = float(value)
        self._on_change(self.value)


class Loop(QObject):
    """A repeating 0..1 phase for pulses and spinners. Stops with reduced motion."""

    def __init__(
        self, owner: QObject, period: int, on_change: Callable[[float], None], always: bool = False
    ) -> None:
        super().__init__(owner)
        self._animation = QVariantAnimation(self)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.setDuration(period)
        self._animation.setLoopCount(-1)
        self._animation.valueChanged.connect(lambda value: on_change(float(value)))
        self._always = always  # spinners keep turning (slowly) even with reduced motion
        self._period = period
        self._wanted = False
        # A bound slot, so Qt disconnects it when this object is destroyed.
        settings().changed.connect(self._on_motion_changed)

    def set_running(self, running: bool) -> None:
        self._wanted = running
        self._apply()

    @property
    def running(self) -> bool:
        return self._animation.state() == QAbstractAnimation.State.Running

    @Slot(bool)
    def _on_motion_changed(self, _reduced: bool) -> None:
        self._apply()

    def _apply(self) -> None:
        if self._always:
            self._animation.setDuration(2000 if reduced() else self._period)
        run = self._wanted and (self._always or not reduced())
        if run and not self.running:
            self._animation.start()
        elif not run and self.running:
            self._animation.stop()


def _settle_layout(widget: QWidget) -> None:
    """Re-applies the parent layout so a widget sits exactly where its layout wants it."""
    parent = widget.parentWidget()
    layout = parent.layout() if parent is not None else None
    if layout is not None:
        layout.invalidate()
        layout.activate()


def rise_in(widget: QWidget, duration: int = theme.DUR_2, rise: int = 4, delay: int = 0) -> None:
    """Reveals a widget with a fade and a short rise. Skipped inside another effect."""
    if reduced() or has_effect_above(widget) or not widget.isVisible():
        return
    previous = getattr(widget, "_reveal", None)
    widget._reveal = None
    if previous is not None and isValid(previous):
        previous.stop()
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(0.0)
    widget.setGraphicsEffect(effect)

    def start() -> None:
        if not isValid(widget) or widget.graphicsEffect() is not effect:
            return
        _settle_layout(widget)
        final = widget.pos()
        group = QParallelAnimationGroup(widget)
        fade = QPropertyAnimation(effect, b"opacity", group)
        fade.setDuration(duration)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(theme.EASE_OUT)
        group.addAnimation(fade)
        if rise:
            slide = QPropertyAnimation(widget, b"pos", group)
            slide.setDuration(duration)
            slide.setStartValue(final + QPoint(0, rise))
            slide.setEndValue(final)
            slide.setEasingCurve(theme.EASE_OUT)
            group.addAnimation(slide)

        def done() -> None:
            if getattr(widget, "_reveal", None) is group:
                widget._reveal = None
            if widget.graphicsEffect() is effect:
                widget.setGraphicsEffect(None)
            _settle_layout(widget)

        group.finished.connect(done)
        widget._reveal = group
        group.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    if delay:
        QTimer.singleShot(delay, widget, start)
    else:
        start()


def stagger(widgets: list[QWidget], step: int = 40) -> None:
    """The welcome entrance: each element rises 4 px, 40 ms after the previous one."""
    for index, widget in enumerate(widgets):
        rise_in(widget, theme.DUR_3, 4, delay=index * step)


def fade(widget: QWidget, show: bool, on_done: Callable[[], None] | None = None) -> None:
    """Fades a floating layer in (250 ms) or out (140 ms), showing or hiding it."""

    def finish() -> None:
        if isValid(widget):
            widget.setGraphicsEffect(None)
            widget.setVisible(show)
        if on_done:
            on_done()

    duration = ms(theme.DUR_3 if show else theme.DUR_EXIT)
    if duration <= 0:
        finish()
        return
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(0.0 if show else 1.0)
    widget.setGraphicsEffect(effect)
    widget.show()
    animation = QPropertyAnimation(effect, b"opacity", widget)
    animation.setDuration(duration)
    animation.setStartValue(effect.opacity())
    animation.setEndValue(1.0 if show else 0.0)
    animation.setEasingCurve(theme.EASE_OUT if show else theme.EASE_IN)
    animation.finished.connect(finish)
    animation.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)


class AnimatedStack(QStackedWidget):
    """A stacked widget whose incoming page fades in from 8 px in the direction of travel.

    The index changes immediately; only the incoming page's appearance is animated.
    """

    def __init__(self, distance: int = 8, duration: int = theme.DUR_3) -> None:
        super().__init__()
        self._distance = distance
        self._duration = duration
        self._group: QParallelAnimationGroup | None = None
        self._animated: QWidget | None = None

    def setCurrentIndex(self, index: int) -> None:  # noqa: N802 - Qt override
        previous = self.currentIndex()
        if index == previous:
            return
        self._finish()
        super().setCurrentIndex(index)
        if previous < 0 or reduced() or not self.isVisible() or has_effect_above(self):
            return
        self._play(self.currentWidget(), 1 if index > previous else -1)

    def jump(self, index: int) -> None:
        """Changes the page without animating."""
        self._finish()
        super().setCurrentIndex(index)

    @property
    def animating(self) -> bool:
        return self._group is not None

    def _play(self, page: QWidget, direction: int) -> None:
        final = page.pos()
        effect = QGraphicsOpacityEffect(page)
        effect.setOpacity(0.0)
        page.setGraphicsEffect(effect)
        group = QParallelAnimationGroup(self)
        fade_anim = QPropertyAnimation(effect, b"opacity", group)
        fade_anim.setDuration(self._duration)
        fade_anim.setStartValue(0.0)
        fade_anim.setEndValue(1.0)
        fade_anim.setEasingCurve(theme.EASE_OUT)
        slide = QPropertyAnimation(page, b"pos", group)
        slide.setDuration(self._duration)
        slide.setStartValue(final + QPoint(direction * self._distance, 0))
        slide.setEndValue(final)
        slide.setEasingCurve(theme.EASE_OUT)
        group.addAnimation(fade_anim)
        group.addAnimation(slide)
        group.finished.connect(self._finish)
        self._group, self._animated = group, page
        group.start()

    def _finish(self) -> None:
        group, page = self._group, self._animated
        self._group = self._animated = None
        if group is not None:
            group.blockSignals(True)
            group.stop()
            group.deleteLater()
        if page is not None and isValid(page):
            page.setGraphicsEffect(None)
            page.setGeometry(self.contentsRect())
