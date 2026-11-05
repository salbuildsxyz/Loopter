"""Checking saved buttons against the screen. It looks once and never clicks.

A button reads "Working" only after this check recognized it on screen.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QHBoxLayout, QWidget

from loop.config import Settings
from loop.matcher import TemplateError
from loop.recognizer import Recognizer
from loop.screens import Screen
from loop.templates import TemplateLibrary
from loop.ui import screenshot, theme
from loop.ui.controls import Button
from loop.ui.model import (
    TARGETS,
    ButtonChecks,
    Check,
    CheckOutcome,
    Target,
    describe_check,
    evaluate,
    region_in,
)
from loop.ui.screenshot import Display
from loop.ui.widgets import Notice, ScanBar, StateText, column, field, text

log = logging.getLogger(__name__)

HELP = {
    Check.WORKING: {
        Target.PLAY: "Recognized on the lobby screen.",
        Target.AGAIN: "Recognized on the results screen.",
    },
    Check.ADJUST: {t: "Your saved picture didn't match. Capture it again." for t in TARGETS},
    Check.UNCHECKED: {
        Target.PLAY: "Show the lobby, then check.",
        Target.AGAIN: "Show a results screen, then check.",
    },
    Check.NONE: {Target.PLAY: "Needed to start matches.", Target.AGAIN: "Optional. Add it later in Setup."},
}


class _CheckRow(QWidget):
    def __init__(self, target: Target, on_recapture: Callable[[Target], None]) -> None:
        super().__init__()
        self.target = target
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 10)
        layout.setSpacing(12)
        box, _title, self.help = field(target.label, " ")
        layout.addWidget(box, 1)
        self.recapture = Button("Recapture", lambda: on_recapture(target), "secondary", "sm")
        layout.addWidget(self.recapture)
        self.state = StateText()
        layout.addWidget(self.state, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_check(self, check: Check) -> None:
        self.help.setText(HELP[check][self.target])
        self.recapture.setVisible(check is Check.ADJUST)
        self.state.set_state(check.value, check.tone)
        self.setAccessibleName(f"{self.target.label}: {check.value}")


class CheckCard(QWidget):
    checked = Signal(object)  # CheckOutcome
    recapture = Signal(object)  # Target

    def __init__(
        self,
        settings: Settings,
        library: TemplateLibrary,
        checks: ButtonChecks,
        display: Callable[[], Display | None],
        saved_targets: Callable[[], set[Target]],
        primary: bool = False,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._library = library
        self._checks = checks
        self._display = display
        self._saved_targets = saved_targets
        self.phase = "idle"  # idle, scanning, done
        self.result: tuple[str, Target | None, str] | None = None  # kind, target, place

        layout = column(12)
        self.setLayout(layout)
        rows = column(0)
        self.rows = {t: _CheckRow(t, self.recapture.emit) for t in TARGETS}
        for widget in self.rows.values():
            rows.addWidget(widget)
        layout.addLayout(rows)
        self.scanbar = ScanBar()
        layout.addWidget(self.scanbar)
        self.notice = Notice()
        layout.addWidget(self.notice)
        self.run_button = Button(
            "Check my screen", self.run, "primary" if primary else "secondary", "sm", "scan"
        )
        self.caption = text("", "caption")
        foot = QHBoxLayout()
        foot.setSpacing(12)
        foot.addWidget(self.run_button)
        foot.addWidget(self.caption, 1)
        layout.addLayout(foot)
        self.refresh()

    @property
    def has_run(self) -> bool:
        return self.phase == "done"

    def run(self) -> None:
        display = self._display()
        if display is None:
            self.notice.show_message("err", "No display is available to check. Is your monitor connected?")
            return
        self.phase = "scanning"
        self.refresh()
        screenshot.grab_hidden(
            self, display.region, lambda frame, error: self._evaluate(frame, error, display)
        )

    def _evaluate(self, frame: np.ndarray | None, error: str, display: Display) -> None:
        self.phase = "done"
        if frame is None:
            self.result = ("failed", None, error)
            log.warning("Recognition check couldn't see the screen: %s", error)
            self.refresh()
            return
        groups, problems = self._library.load()
        for problem in problems:
            log.warning(problem)
        area = region_in(self._settings.region, display.region)
        image = frame[area.top : area.bottom, area.left : area.right] if area else frame
        threshold = self._settings.threshold
        try:
            if not groups:
                raise TemplateError("no saved picture could be loaded")
            observation = Recognizer(groups, threshold, display.region.height).observe(image)
        except TemplateError as exc:
            self.result = ("unavailable", None, "")
            log.info("Recognition check couldn't run: %s", exc)
            self.refresh()
            return
        log.info("Recognition check: %s", describe_check(observation, threshold))
        outcome = evaluate(observation, self._saved_targets(), threshold)
        self.checked.emit(outcome)  # the owner records the verdicts in the shared checks
        self.result = self._describe(outcome)
        self.refresh()
        self.run_button.setFocus(Qt.FocusReason.OtherFocusReason)

    def _describe(self, outcome: CheckOutcome) -> tuple[str, Target | None, str]:
        target = {Screen.LOBBY: Target.PLAY, Screen.RESULTS: Target.AGAIN}.get(outcome.screen)
        if target is None:
            return ("none", None, "")
        if target not in self._saved_targets():
            return ("unsaved", target, target.place)
        verdict = self._checks[target]
        kind = {Check.WORKING: "working", Check.ADJUST: "adjust"}.get(verdict, "none")
        return (kind, target, target.place)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setPen(QColor(theme.BORDER_SUBTLE))
        y = self.rows[Target.AGAIN].geometry().top()
        painter.drawLine(0, y, self.width(), y)

    def refresh(self) -> None:
        saved = self._saved_targets()
        for target, widget in self.rows.items():
            widget.set_check(self._checks[target])
        self.scanbar.setVisible(self.phase == "scanning")
        self._show_notice(bool(saved))
        scanning = self.phase == "scanning"
        self.run_button.set_busy(scanning)
        self.run_button.setText(
            "Checking…" if scanning else "Check again" if self.phase == "done" else "Check my screen"
        )
        self.run_button.set_icon("refresh" if self.phase == "done" else "scan")
        self.run_button.setEnabled(bool(saved) and not scanning)
        display = self._display()
        name = display.name if display else "your display"
        self.caption.setText(f"Looking at {name} once…" if scanning else "Watch only — no clicks are sent.")

    def _show_notice(self, any_saved: bool) -> None:
        if self.phase == "done" and self.result is not None:
            kind, target, detail = self.result
            if kind == "working" and target is not None:
                self.notice.show_message("ok", f"<b>Recognized your {detail}.</b> {target.label} works.")
            elif kind == "adjust" and target is not None:
                self.notice.show_message(
                    "warn",
                    f"<b>Almost.</b> Something like {target.label} is on screen, "
                    "but your saved picture doesn't "
                    "match it well.",
                    [
                        Button(
                            f"Recapture {target.short}",
                            lambda: self.recapture.emit(target),
                            "secondary",
                            "sm",
                        )
                    ],
                )
            elif kind == "unsaved" and target is not None:
                self.notice.show_message(
                    "info",
                    f"This looks like the {detail}, but {target.label} isn't saved yet.",
                    [
                        Button(
                            f"Capture {target.short}", lambda: self.recapture.emit(target), "secondary", "sm"
                        )
                    ],
                )
            elif kind == "unavailable":
                self.notice.show_message(
                    "info",
                    "Recognition isn't available right now. "
                    "Your buttons stay “Not checked” until a check can run.",
                )
            elif kind == "failed":
                self.notice.show_message("err", f"<b>Couldn't see your screen.</b> {detail}")
            else:
                self.notice.show_message(
                    "info",
                    "None of your saved buttons are on screen. Open your game's lobby or results screen, "
                    "then check again.",
                )
        elif not any_saved:
            self.notice.show_message("info", "Save a button first, then check it here.")
        else:
            self.notice.hide()
