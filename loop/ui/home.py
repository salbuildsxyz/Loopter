"""Home: the session status, the mode switch, the main controls, statistics, and button readiness."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget

from loop.config import Mode
from loop.state import SessionState
from loop.ui import icons, motion, theme
from loop.ui.controls import Button, KeyCaps, SegmentedControl, surface
from loop.ui.model import TARGETS, Check, Target, ViewState, format_clock
from loop.ui.widgets import (
    CountLabel,
    LiveDot,
    Page,
    Row,
    Rows,
    StateText,
    StatStrip,
    Tag,
    column,
    row,
    swap_text,
    text,
)

FIX_WORDS = (
    (("button", "template", "setup"), "Open Setup", "setup"),
    (("display", "region", "area", "monitor"), "Open Settings", "settings"),
)


@dataclass(frozen=True)
class Callout:
    tone: str  # info, warn, error
    icon: str
    message: str
    action: str
    target: str  # what the action opens: setup, again, check, settings, activity, or a Target value


@dataclass(frozen=True)
class Status:
    tone: str  # the live dot: setup, ready, watch, auto, paused, error
    title: str
    description: str
    callout: Callout | None = None


def home_status(view: ViewState) -> Status:
    """Home's status, derived from the controller's state and the saved buttons; never invented."""
    if view.session is SessionState.ERROR:
        message = view.error or "The session stopped. Activity has the details."
        fix = next((f for f in FIX_WORDS if any(w in message.lower() for w in f[0])), None)
        action, target = (fix[1], fix[2]) if fix else ("View activity", "activity")
        callout = Callout("error", "alert", "Fix the problem, then start again.", action, target)
        return Status("error", "Needs attention", message, callout)
    if view.session is SessionState.PAUSED:
        return Status("paused", "Paused", "Scanning is paused and clicks are off.")
    if view.session is SessionState.RUNNING:
        if view.mode is Mode.INTERACTION:
            default = f"Clicks your buttons when it's safe. {view.hotkey} stops instantly."
            return Status("auto", "Auto clicking", view.flash or default)
        return Status("watch", "Watching", view.flash or "Looking for your buttons. Nothing is clicked.")
    if Target.PLAY not in view.saved:
        return Status("setup", "Needs setup", "Save your Play button so Loopter knows what to look for.")
    if view.emergency:
        status = Status(
            "paused",
            "Stopped",
            "Emergency stop pressed. Clicks are off, and Auto click needs confirming again.",
        )
    elif view.mode is Mode.INTERACTION:
        status = Status(
            "ready", "Ready", "Press Start and Loopter clicks your buttons when you're away from the mouse."
        )
    else:
        status = Status("ready", "Ready", "Press Start and Loopter watches your game. Nothing is clicked.")
    adjust = next((t for t in TARGETS if view.checks[t] is Check.ADJUST), None)
    if adjust is not None:
        callout = Callout(
            "warn", "alert", f"{adjust.label} needs adjustment before it's reliable.", "Fix", adjust.value
        )
    elif Target.AGAIN not in view.saved:
        callout = Callout(
            "info",
            "info",
            "Play Again isn't set up, so Loopter stops after one match.",
            "Add Play Again",
            "again",
        )
    elif any(view.checks[t] is Check.UNCHECKED for t in TARGETS):
        callout = Callout("info", "info", "Some buttons haven't been checked yet.", "Check now", "check")
    else:
        callout = None
    return Status(status.tone, status.title, status.description, callout)


class _OverhangRow(QHBoxLayout):
    """A row that starts left of its parent's padding, so the live dot's pulse has room."""

    def setGeometry(self, rect) -> None:  # noqa: N802 - Qt override
        super().setGeometry(rect.adjusted(-LiveDot.OVERHANG, 0, 0, 0))


class CalloutBox(QWidget):
    """One sentence about what to do next, with one small action."""

    triggered = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 8, 8)
        layout.setSpacing(10)
        self.icon = QLabel()
        self.icon.setFixedSize(16, 16)
        self.message = text("", "help", wrap=True)
        self.action = Button("", variant="secondary", size="sm")
        self.action.clicked.connect(lambda: self.callout and self.triggered.emit(self.callout.target))
        layout.addWidget(self.icon)
        layout.addWidget(self.message, 1)
        layout.addWidget(self.action)
        self.callout: Callout | None = None

    def set_callout(self, callout: Callout) -> None:
        self.callout = callout
        color = {"warn": theme.WARNING, "error": theme.DANGER}.get(callout.tone, theme.TEXT_2)
        self.icon.setPixmap(icons.pixmap(callout.icon, color, 16))
        self.message.setText(callout.message)
        self.action.setText(callout.action)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        tone = self.callout.tone if self.callout else "info"
        border = {"warn": theme.line(theme.WARNING), "error": theme.line(theme.DANGER)}.get(
            tone, theme.BORDER_SUBTLE
        )
        surface(painter, QRectF(self.rect()), theme.SURFACE, border, theme.R_LG)


class ButtonRow(Row):
    """A saved button and its status; on Home, a "Set up" link when it is missing."""

    def __init__(self, target: Target, action: Button) -> None:
        super().__init__()
        self.target = target
        name = text(target.label, "row-title")
        name.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.state = StateText()
        self.action = action
        self.body.addWidget(name, 1)
        self.body.addWidget(self.state)
        self.body.addWidget(action)

    def set_check(self, check: Check) -> None:
        self.state.set_state(check.value, check.tone)
        self.setAccessibleName(f"{self.target.label}: {check.value}")


class HomePage(Page):
    start_requested = Signal()
    pause_requested = Signal()
    resume_requested = Signal()
    stop_requested = Signal()
    mode_picked = Signal(object)  # Mode
    open_requested = Signal(str)  # setup, again, check, settings, activity, or a Target value

    def __init__(self) -> None:
        super().__init__(spacing=16)
        layout = self.content

        # Status: the dot overhangs the left edge so the 10 px dot itself aligns with the text.
        self.dot = LiveDot()
        self.title = text("Needs setup", "status")
        self.mode_tag = Tag("Watch only")
        self.screen_label = text("Screen", "label")
        self.screen_label.setFont(theme.font(10, 500, caps=True))
        self.screen_name = text("", "body")
        self.screen_name.setFont(theme.font(12, 500))
        head = _OverhangRow()
        head.setSpacing(0)
        head.addWidget(self.dot)
        head.addWidget(self.title)
        head.addSpacing(10)
        head.addWidget(self.mode_tag)
        head.addStretch(1)
        head.addWidget(self.screen_label)
        head.addSpacing(6)
        head.addWidget(self.screen_name)
        self.description = text("", "body-2", wrap=True)
        self.description.setMinimumHeight(20)
        self.description.setAccessibleDescription("live")
        self.callout = CalloutBox()
        self.callout.triggered.connect(self.open_requested)
        status = column(6)
        status.addLayout(head)
        status.addWidget(self.description)
        status.addSpacing(4)
        status.addWidget(self.callout)
        layout.addLayout(status)

        # Mode and session controls
        self.modes = SegmentedControl(
            [(Mode.LIVE, "Watch only", "eye"), (Mode.INTERACTION, "Auto click", "pointer")], "lg"
        )
        self.modes.setAccessibleName("Mode")
        self.modes.picked.connect(self.mode_picked)
        self.mode_help = text("", "caption")
        self.mode_help.setContentsMargins(2, 0, 2, 0)
        self.start_button = Button("Start watching", self.start_requested.emit, "primary", "lg", "play")
        self.pause_button = Button("Pause", self._pause_or_resume, "secondary", "lg", "pause")
        self.stop_button = Button("Stop", self.stop_requested.emit, "danger", "lg", "stop")
        for button in (self.start_button, self.pause_button, self.stop_button):
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        controls = column(8)
        controls.addWidget(self.modes)
        controls.addWidget(self.mode_help)
        controls.addLayout(row(self.start_button, self.pause_button, self.stop_button))
        layout.addLayout(controls)

        # Session statistics
        self.duration = text("00:00:00", "stat")
        self.actions = CountLabel()
        self.screens = CountLabel()
        self.stats = StatStrip(
            [
                ("Duration", self.duration),
                ("Successful actions", self.actions),
                ("Recognized screens", self.screens),
            ]
        )
        session = column(8)
        session.addWidget(text("Session", "label"))
        session.addWidget(self.stats)
        layout.addLayout(session)

        # Button readiness
        self.manage = Button("Manage", lambda: self.open_requested.emit("setup"), "link")
        self.rows = Rows()
        self.button_rows: dict[Target, ButtonRow] = {}
        for target in TARGETS:
            link = Button("Set up", lambda t=target: self.open_requested.emit(t.value), "link")
            self.button_rows[target] = ButtonRow(target, link)
            self.rows.add(self.button_rows[target])
        buttons = column(8)
        buttons.addLayout(row(text("Buttons", "label"), None, self.manage))
        buttons.addWidget(self.rows)
        layout.addLayout(buttons)

        shield = QLabel()
        shield.setPixmap(icons.pixmap("shield", theme.TEXT_3, 14))
        self.hotkey_caps = KeyCaps()
        layout.addLayout(row(shield, text("Emergency stop", "caption"), None, self.hotkey_caps))
        layout.addStretch(1)
        self._paused = False

    def _pause_or_resume(self) -> None:
        (self.resume_requested if self._paused else self.pause_requested).emit()

    def render(self, view: ViewState) -> None:
        status = home_status(view)
        self.dot.set_tone(status.tone)
        swap_text(self.title, status.title)
        swap_text(self.description, status.description)
        self.title.setAccessibleName(f"Status: {status.title}")
        auto = view.mode is Mode.INTERACTION
        self.mode_tag.setText("Auto click" if auto else "Watch only")
        self.mode_tag.set_accent(auto)
        for widget in (self.screen_label, self.screen_name):
            widget.setVisible(view.active)
        if view.active:
            swap_text(self.screen_name, view.screen or "Searching…")
        if status.callout is not None:
            was_hidden = self.callout.isHidden()
            self.callout.set_callout(status.callout)
            self.callout.show()
            if was_hidden:
                motion.rise_in(self.callout)
        else:
            self.callout.hide()

        self.modes.set_value(view.mode)
        self.modes.set_risk(auto)
        self.modes.set_options_enabled(not view.active)
        if view.active:
            self.mode_help.setText("Stop the session to change mode.")
        elif auto:
            self.mode_help.setText("Recognizes and clicks your buttons. You confirmed this.")
        else:
            self.mode_help.setText("Recognizes your buttons. Never clicks.")

        needs_setup = Target.PLAY not in view.saved
        self.start_button.setVisible(not view.active)
        self.pause_button.setVisible(view.active)
        self.stop_button.setVisible(view.active)
        self._paused = view.session is SessionState.PAUSED
        self.pause_button.setText("Resume" if self._paused else "Pause")
        self.pause_button.set_icon("play" if self._paused else "pause")
        if needs_setup:
            self.start_button.setText("Finish setup")
            self.start_button.set_icon("arrow")
        else:
            self.start_button.setText("Start auto click" if auto else "Start watching")
            self.start_button.set_icon("play")
        self.start_button.set_variant("accent" if auto and not needs_setup else "primary")

        self.duration.setText(format_clock(view.elapsed))
        self.actions.set_value(view.stats.interactions)
        self.screens.set_value(view.stats.detections)

        for target, widget in self.button_rows.items():
            widget.set_check(view.checks[target])
            widget.action.setVisible(target not in view.saved)
        self.hotkey_caps.set_shortcut(view.hotkey)

    def set_ambient_allowed(self, allowed: bool) -> None:
        self.dot.set_ambient_allowed(allowed)

    def focus_start(self) -> None:
        target = self.start_button if self.start_button.isVisible() else self.pause_button
        target.setFocus(Qt.FocusReason.OtherFocusReason)
