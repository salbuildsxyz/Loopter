"""Capturing a button: take a screenshot, confirm or draw the box, and save it.

Shared by first-time setup and the Setup page. The window hides while the screenshot is
taken. Likely buttons are suggested by loop.suggest; without a suggestion the user draws
the box. Saving a button replaces its earlier picture and resets it to "Not checked".
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import numpy as np
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QWidget

from loop.capture import Region
from loop.matcher import TemplateError
from loop.screens import Screen
from loop.suggest import find_buttons
from loop.templates import TemplateLibrary
from loop.ui import icons, screenshot, theme
from loop.ui.controls import Button, SegmentedControl, surface
from loop.ui.model import TARGETS, Target
from loop.ui.screenshot import Display
from loop.ui.shot_view import ShotView
from loop.ui.widgets import Notice, StateText, bgr_to_qimage, column, field, rich, row, text

log = logging.getLogger(__name__)

MIN_BOX, MAX_BOX_WIDTH, MAX_BOX_HEIGHT = 4.0, 45.0, 35.0  # percent of the screenshot

PREPARE = {
    Target.PLAY: "Open your game and go to the <b>lobby</b>, where the Play (or Ready) button shows.",
    Target.AGAIN: "Finish a match and wait for the <b>results screen</b> with Play Again.",
}
PRESS_CAPTURE = "Press <b>Capture screen</b>. Loopter hides for a moment while it takes the picture."


def box_problem(box: QRectF | None) -> str:
    """Why a box cannot be saved, or "" if it fits a single button."""
    if box is None:
        return "Draw a box around the button."
    if box.width() < MIN_BOX or box.height() < MIN_BOX:
        return "That box is very small. Draw it around the whole button."
    if box.width() > MAX_BOX_WIDTH or box.height() > MAX_BOX_HEIGHT:
        return "That box is too large. It should cover just the button, not the area around it."
    return ""


class _StepNumber(QWidget):
    """An 18 px numbered circle that turns into a green check when its step is done."""

    def __init__(self, number: int) -> None:
        super().__init__()
        self.number = number
        self.done = False
        self.setFixedSize(18, 20)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        circle = QRectF(0.5, 1.5, 17, 17)
        border = theme.line(theme.SUCCESS) if self.done else QColor(theme.BORDER)
        painter.setPen(QPen(border, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(circle)
        if self.done:
            icons.paint(painter, "check", circle.adjusted(3.5, 3.5, -3.5, -3.5), theme.SUCCESS, 2)
        else:
            painter.setFont(theme.font(11, 500))
            painter.setPen(QColor(theme.TEXT))
            painter.drawText(circle, Qt.AlignmentFlag.AlignCenter, str(self.number))


class _Step(QWidget):
    def __init__(self, number: int) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.mark = _StepNumber(number)
        self.label = text("", "body-2", wrap=True, rich_text=True)
        layout.addWidget(self.mark, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.label, 1)

    def set(self, html: str, done: bool) -> None:
        self.label.setText(rich(html))
        self.label.setProperty("tone", "off" if done else None)
        self.label.style().polish(self.label)
        self.mark.done = done
        self.mark.update()


class _NextPanel(QWidget):
    """The suggestion to capture the other button next."""

    def __init__(self) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        box, self.title, self.help = field("", " ")
        layout.addWidget(box, 1)
        self.button = Button("", variant="secondary", size="sm", icon="arrow")
        layout.addWidget(self.button, 0, Qt.AlignmentFlag.AlignVCenter)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        surface(painter, QRectF(self.rect()), theme.BG, theme.BORDER_SUBTLE, theme.R_MD)


class CaptureCard(QWidget):
    saved = Signal(object)  # Target, or the waiting Screen that was saved
    display_requested = Signal()  # the user wants to pick another display

    def __init__(
        self,
        library: TemplateLibrary,
        display: Callable[[], Display | None],
        saved_targets: Callable[[], set[Target]],
    ) -> None:
        super().__init__()
        self._library = library
        self._display = display
        self._saved_targets = saved_targets
        self.target: Target | Screen = Target.PLAY
        self.phase = "prepare"  # prepare, loading, failed, confirm, saved
        self.frame: np.ndarray | None = None
        self.origin: Region | None = None
        self.suggestions: list[QRectF] = []
        self.candidate = -1  # index of the suggestion shown, or -1 for the user's own box
        self.error = ""
        self._was_saved = False

        layout = column(12)
        self.setLayout(layout)
        self.kind = SegmentedControl([(t, t.label, "") for t in TARGETS], size="sm")
        self.kind.setAccessibleName("Button to capture")
        self.kind.picked.connect(lambda value: value != self.target and self.reset(value))
        layout.addLayout(row(text("Button", "label"), self.kind, spacing=12))
        self.waiting_note = text("", "help", wrap=True)
        layout.addWidget(self.waiting_note)

        self.steps = [_Step(1), _Step(2)]
        steps = column(6)
        for step in self.steps:
            steps.addWidget(step)
        self.steps_box = QWidget()
        self.steps_box.setLayout(steps)
        layout.addWidget(self.steps_box)

        question, self.question, self.question_help = field("", " ")
        self.question_box = question
        layout.addWidget(question)

        self.shot = ShotView()
        self.capture_button = Button("Capture screen", self.capture, "primary", "sm", "camera")
        self.shot.empty_actions.addStretch(1)
        self.shot.empty_actions.addWidget(self.capture_button)
        self.shot.empty_actions.addStretch(1)
        self.shot.edited.connect(self._on_edited)
        layout.addWidget(self.shot)

        self.failed = Notice("err")
        layout.addWidget(self.failed)
        self.optional = text("Optional. You can add Play Again later from Setup.", "caption")
        layout.addWidget(self.optional)
        self.fit = Notice("warn")
        layout.addWidget(self.fit)
        self.save_error = Notice("err")
        layout.addWidget(self.save_error)

        self.save_button = Button("Save", self.save, "primary", "sm", "check")
        self.next_button = Button("Try another", self.next_suggestion, "secondary", "sm", "search")
        self.again_button = Button("Capture again", self.capture, "ghost", "sm", "camera")
        self.confirm_actions = QWidget()
        self.confirm_actions.setLayout(row(self.save_button, self.next_button, None, self.again_button))
        layout.addWidget(self.confirm_actions)

        self.saved_state = StateText("", "ok")
        self.redo_button = Button("Wrong button? Redo", self.redo, "ghost", "sm")
        self.saved_actions = QWidget()
        self.saved_actions.setLayout(row(self.saved_state, None, self.redo_button))
        layout.addWidget(self.saved_actions)

        self.next_panel = _NextPanel()
        self.next_panel.button.clicked.connect(self._capture_other)
        layout.addWidget(self.next_panel)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.render()

    # Flow

    def reset(self, target: Target | Screen) -> None:
        """Starts over for `target`: a Play / Play Again button, or a waiting screen."""
        self.target = target
        self.phase = "prepare"
        self.frame = self.origin = None
        self.suggestions, self.candidate, self.error = [], -1, ""
        self.render()

    @property
    def target_name(self) -> str:
        return self.target.short if isinstance(self.target, Target) else f"{self.target.label} screen"

    def capture(self) -> None:
        display = self._display()
        if display is None:
            self._fail("No display is available. Check that your monitor is connected.")
            return
        self.phase = "loading"
        self.render()
        screenshot.grab_hidden(
            self, display.region, lambda frame, error: self._captured(frame, error, display)
        )

    def _captured(self, frame: np.ndarray | None, error: str, display: Display) -> None:
        if frame is None:
            self._fail(error or "Try again.")
            return
        self.frame, self.origin = frame, display.region
        self.suggestions = []
        if isinstance(self.target, Target):
            height, width = frame.shape[:2]
            self.suggestions = [
                QRectF(
                    b.left / width * 100, b.top / height * 100, b.width / width * 100, b.height / height * 100
                )
                for b in find_buttons(frame)
            ]
        self.candidate = 0 if self.suggestions else -1
        self.phase = "confirm"
        self.shot.show_image(bgr_to_qimage(frame), self.suggestions[0] if self.suggestions else None)
        self.render()
        focus = self.save_button if self.save_button.isEnabled() else self.shot
        focus.setFocus(Qt.FocusReason.OtherFocusReason)

    def _fail(self, error: str) -> None:
        self.error = error
        self.phase = "failed"
        log.error("Screenshot failed: %s", error)
        self.render()

    def next_suggestion(self) -> None:
        if len(self.suggestions) < 2:
            return
        self.candidate = (self.candidate + 1) % len(self.suggestions)
        self.shot.set_box(self.suggestions[self.candidate])
        self.render()

    def _on_edited(self) -> None:
        self.candidate = -1
        self.render()

    def redo(self) -> None:
        self.phase = "confirm"
        self.shot.unsave()
        self.render()

    def _capture_other(self) -> None:
        if isinstance(self.target, Target):
            self.reset(self.target.other)
            self.capture_button.setFocus(Qt.FocusReason.OtherFocusReason)

    def selection(self) -> Region | None:
        """The box in desktop coordinates, while a screenshot is being confirmed."""
        if self.phase != "confirm" or self.shot.box is None or self.frame is None or self.origin is None:
            return None
        return self._box_pixels().offset(self.origin.left, self.origin.top)

    def _box_pixels(self) -> Region:
        assert self.frame is not None and self.shot.box is not None
        height, width = self.frame.shape[:2]
        box = self.shot.box
        left = min(max(round(box.x() / 100 * width), 0), width - 1)
        top = min(max(round(box.y() / 100 * height), 0), height - 1)
        right = min(max(round(box.right() / 100 * width), left + 1), width)
        bottom = min(max(round(box.bottom() / 100 * height), top + 1), height)
        return Region(left, top, right - left, bottom - top)

    def save(self) -> None:
        if self.frame is None or self.origin is None or box_problem(self.shot.box):
            return
        box = self._box_pixels()
        crop = self.frame[box.top : box.bottom, box.left : box.right].copy()
        target = self.target
        replacing = isinstance(target, Target) and target in self._saved_targets()
        try:
            if isinstance(target, Target):
                entry = self._library.replace_image(crop, target.button, self.origin.height)
            else:
                entry = self._library.add_image(crop, target, self.origin.height)
        except (TemplateError, OSError) as exc:
            self.save_error.show_message("err", f"<b>Couldn't save it.</b> {exc}")
            return
        what = (
            f"the '{entry.label}' button for the {entry.screen.label} screen"
            if entry.button
            else f"the {entry.screen.label} screen"
        )
        log.info(
            "Saved %s (%s, %d × %d)%s",
            what,
            Path(entry.path).stem,
            box.width,
            box.height,
            " (replaced)" if replacing else "",
        )
        self.phase = "saved"
        self.shot.show_saved()
        self.render()
        self.saved.emit(target)

    def import_path(self, path: Path) -> str:
        """Adds an image file as the current target; returns an error message, or ""."""
        target = self.target
        try:
            if isinstance(target, Target):
                earlier = [e for e in self._library.entries if e.button is target.button]
                entry = self._library.import_file(path, target.screen, target.button)
                for old in earlier:
                    self._library.remove(old)
            else:
                entry = self._library.import_file(path, target)
        except (TemplateError, OSError) as exc:
            log.error("Import failed: %s", exc)
            return str(exc)
        log.info(
            "Saved the '%s' picture for the %s screen (imported from %s)",
            entry.label,
            entry.screen.label,
            path.name,
        )
        self.saved.emit(target)
        return ""

    # Rendering

    def render(self) -> None:
        saved = self._saved_targets()
        target = self.target
        waiting = not isinstance(target, Target)
        self.kind.set_value(None if waiting else target)
        for t in TARGETS:
            self.kind.set_tick(t, t in saved)
        self.waiting_note.setVisible(waiting)
        if waiting:
            self.waiting_note.setText(
                f"Saving a waiting screen: {target.label}. Pick something on it that never changes, "
                "such as its "
                "title. Loopter notes it in Activity and never clicks it."
            )
        phase = self.phase
        preparing = phase in ("prepare", "failed", "loading")
        self.steps_box.setVisible(preparing)
        first = PREPARE[target] if not waiting else f"Open your game's <b>{target.label.lower()}</b> screen."
        for step, html in zip(self.steps, (first, PRESS_CAPTURE), strict=True):
            step.set(html, phase == "loading")

        if phase in ("prepare", "failed"):
            is_saved = not waiting and target in saved
            message = (
                f"{target.label} is saved. A new capture replaces it."
                if is_saved
                else "Your screenshot will appear here"
            )
            if self.shot.mode != "empty" or self.shot.empty_text.text() != message:
                self.shot.show_empty(message)
        elif phase == "loading" and self.shot.mode != "loading":
            self.shot.show_loading()

        self.failed.setVisible(phase == "failed")
        if phase == "failed":
            name = (self._display() or Display(1, Region(0, 0, 1, 1))).name
            self.failed.set(
                "err",
                f"<b>Couldn't take a screenshot.</b> {self.error} "
                f"Make sure {name} is on and not asleep, then try again.",
                [
                    Button("Try again", self.capture, "secondary", "sm"),
                    Button("Choose another display", self.display_requested.emit, "ghost", "sm"),
                ],
            )
        self.optional.setVisible(phase == "prepare" and target is Target.AGAIN and target not in saved)

        confirming = phase == "confirm"
        self.question_box.setVisible(confirming)
        if confirming:
            if self.suggestions:
                self.question.setText(f"Is the box on your {self.target_name} button?")
                self.question_help.setText(
                    "Drag the box to move it, drag its corner to resize, or draw a new one."
                )
            elif waiting:
                self.question.setText(f"Draw a box around something unique on the {target.label} screen.")
                self.question_help.setText(
                    "Drag on the screenshot. You can move or resize the box afterwards."
                )
            else:
                self.question.setText(f"Draw a box around your {self.target_name} button.")
                self.question_help.setText(
                    "Drag on the screenshot. You can move or resize the box afterwards."
                )
        problem = box_problem(self.shot.box) if confirming else ""
        if confirming:
            if self.shot.box is None:
                self.shot.set_label("", "ok")
            elif problem:
                self.shot.set_label("Adjust the box", "bad")
            else:
                self.shot.set_label("Your box" if self.candidate < 0 else "Suggested", "ok")
        elif phase == "saved":
            self.shot.set_label(f"{self.target_name} saved", "saved")
        show_fit = confirming and self.shot.box is not None and bool(problem)
        if show_fit:
            self.fit.show_message("warn", problem)
        else:
            self.fit.hide()
        if not confirming:
            self.save_error.hide()

        self.confirm_actions.setVisible(confirming)
        self.save_button.setText(f"Save {self.target_name}" if not waiting else "Save screen")
        self.save_button.setEnabled(confirming and not problem)
        self.next_button.setVisible(len(self.suggestions) > 1)
        self.saved_actions.setVisible(phase == "saved")
        label = target.label if not waiting else f"{target.label} screen"
        self.saved_state.set_state(f"{label} saved", "ok")
        other = target.other if not waiting else None
        show_next = phase == "saved" and other is not None and other not in saved
        self.next_panel.setVisible(show_next)
        if show_next:
            optional = " · optional" if other is Target.AGAIN else ""
            self.next_panel.title.setText(f"Next: {other.label}{optional}")
            self.next_panel.help.setText(
                "When you reach a results screen, capture Play Again."
                if other is Target.AGAIN
                else "Capture the Play button from the lobby."
            )
            self.next_panel.button.setText(f"Capture {other.short}")
