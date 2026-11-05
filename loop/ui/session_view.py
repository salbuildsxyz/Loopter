"""The main screen: session status, timer, counts, mode, and the start and stop controls."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from loop.config import Mode
from loop.controller import format_duration
from loop.recognizer import Observation
from loop.screens import Button
from loop.state import SessionState, SessionStats
from loop.ui import icons, theme
from loop.ui.widgets import ElidedLabel, SegmentedControl, StatusPill, button, label, set_style_property

MODE_NAMES = {Mode.DEMO: "Demo", Mode.LIVE: "Monitor", Mode.INTERACTION: "Interact"}
MODE_ICONS = {Mode.DEMO: "demo", Mode.LIVE: "eye", Mode.INTERACTION: "alert"}
MODE_TAGS = {
    Mode.DEMO: ("Demo", "", "Scans LOOP's own simulated demo window"),
    Mode.LIVE: ("Read-only", "", "Live Monitor recognizes screens and never sends input"),
    Mode.INTERACTION: ("Real clicks", "warn", "Live Interaction may send real mouse clicks"),
}
IDLE_DETAILS = {
    Mode.DEMO: "Practice run in the demo window",
    Mode.LIVE: "Watches the screen. Never clicks.",
    Mode.INTERACTION: "Presses Play and Play Again for real",
}
STATE_KEYS = {
    SessionState.IDLE: "idle",
    SessionState.RUNNING: "running",
    SessionState.PAUSED: "paused",
    SessionState.STOPPED: "stopped",
    SessionState.ERROR: "error",
}


class SessionView(QWidget):
    start_requested = Signal()
    pause_requested = Signal()
    resume_requested = Signal()
    stop_requested = Signal()
    mode_selected = Signal(object)  # Mode
    setup_requested = Signal()
    activity_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("View")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(0)

        self.pill = StatusPill()
        self.detail = ElidedLabel("Caption")
        self.view_log = button("View log", self.activity_requested, variant="link")
        self.view_log.hide()
        self.tag = label("", "Tag")
        status = QHBoxLayout()
        status.setSpacing(8)
        status.addWidget(self.pill)
        status.addWidget(self.detail, 1)
        status.addWidget(self.view_log)
        status.addWidget(self.tag)
        layout.addLayout(status)

        layout.addSpacing(20)
        self.timer = label(format_duration(0), "Timer")
        self.timer.setAccessibleName("Session time")
        layout.addWidget(self.timer)

        layout.addSpacing(12)
        self.detections = label("0", "Numeral")
        self.actions = label("0", "Numeral")
        self.actions_caption = label("Successful actions", "Caption")
        stats = QHBoxLayout()
        stats.setSpacing(16)
        stats.addLayout(_stat(self.detections, label("Detections", "Caption")), 1)
        stats.addLayout(_stat(self.actions, self.actions_caption), 1)
        layout.addLayout(stats)

        layout.addSpacing(24)
        self.modes = SegmentedControl(
            ((m, MODE_NAMES[m], MODE_ICONS[m]) for m in Mode), risky=[Mode.INTERACTION]
        )
        self.modes.setAccessibleName("Mode")
        self.modes.selected.connect(self.mode_selected)
        layout.addWidget(self.modes)

        layout.addSpacing(12)
        self.start_button = button(
            "Start session", self.start_requested, "primary", "lg", "play", theme.ACCENT_INK
        )
        self.pause_button = button("Pause", self.pause_requested, size="lg", icon="pause")
        self.resume_button = button(
            "Resume", self.resume_requested, "primary", "lg", "play", theme.ACCENT_INK
        )
        self.stop_button = button("Stop", self.stop_requested, "danger", "lg", "stop", theme.ERR)
        controls = QHBoxLayout()
        controls.setSpacing(8)
        for widget in (self.start_button, self.pause_button, self.resume_button, self.stop_button):
            controls.addWidget(widget, 1)
        layout.addLayout(controls)

        layout.addSpacing(12)
        self.profile = ProfileLine()
        self.profile.clicked.connect(self.setup_requested)
        layout.addWidget(self.profile)
        layout.addStretch(1)

        self._mode = Mode.DEMO
        self._state = SessionState.IDLE

    def set_mode(self, mode: Mode) -> None:
        self._mode = mode
        self.modes.set_value(mode)
        text, kind, tip = MODE_TAGS[mode]
        self.tag.setText(text)
        self.tag.setToolTip(tip)
        set_style_property(self.tag, "kind", kind)
        if mode is Mode.LIVE:
            self.actions.setText("–")
            self.actions_caption.setText("Actions · off in Monitor")
        else:
            self.actions_caption.setText("Successful actions")
        if self._state is SessionState.IDLE:
            self.detail.setText(IDLE_DETAILS[mode])

    def set_state(self, state: SessionState, error: str = "", emergency: bool = False) -> None:
        self._state = state
        active = state in (SessionState.RUNNING, SessionState.PAUSED)
        self.start_button.setVisible(not active)
        self.pause_button.setVisible(state is SessionState.RUNNING)
        self.resume_button.setVisible(state is SessionState.PAUSED)
        self.stop_button.setVisible(active)
        self.modes.setEnabled(not active)
        self.pill.set_state(STATE_KEYS[state], state.value)
        set_style_property(self.timer, "dim", state is SessionState.IDLE)
        self.view_log.setVisible(state is SessionState.ERROR)
        if state is SessionState.ERROR:
            self.detail.setText(error or "The session stopped. See the activity log.")
        elif state is SessionState.IDLE:
            self.detail.setText(IDLE_DETAILS[self._mode])
        elif state is SessionState.PAUSED:
            self.detail.setText("Scans paused · clicks disarmed")
        elif state is SessionState.STOPPED:
            self.detail.setText("Emergency stop · clicks disarmed" if emergency else "Session ended")
        elif state is SessionState.RUNNING:
            self.detail.setText("Looking for a known screen…")

    def set_stats(self, stats: SessionStats) -> None:
        self.detections.setText(str(stats.detections))
        # Live Monitor never clicks, so a count there would be meaningless.
        self.actions.setText("–" if self._mode is Mode.LIVE else str(stats.interactions))

    def set_elapsed(self, seconds: float) -> None:
        self.timer.setText(format_duration(seconds))

    def set_observation(self, observation: Observation | None) -> None:
        if observation is None or self._state is not SessionState.RUNNING:
            return
        text = observation.screen.label
        if observation.match is not None:
            text += f" · {observation.confidence:.2f}"
        if observation.ambiguous:
            text += " · ambiguous, no action"
        elif observation.lookalikes:
            text += " · look-alike ignored"
        self.detail.setText(text)

    def set_profile(self, buttons: set[Button], region_set: bool) -> None:
        self.profile.show_status(buttons, region_set)


def _stat(value: QLabel, caption: QLabel) -> QVBoxLayout:
    column = QVBoxLayout()
    column.setSpacing(0)
    column.addWidget(value)
    column.addWidget(caption)
    return column


class ProfileLine(QPushButton):
    """One line saying whether the recognition profile can press both buttons; opens Setup."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("ProfileLine")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 6, 0)
        layout.setSpacing(6)
        self._icon = QLabel()
        self._icon.setFixedSize(QSize(14, 14))
        self.text_label = ElidedLabel()
        self.text_label.setStyleSheet(f"background: transparent; color: {theme.FG_2};")
        chevron = QLabel()
        chevron.setPixmap(icons.pixmap("chevron", theme.FG_3, 14))
        for widget in (self._icon, self.text_label, chevron):
            widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self._icon)
        layout.addWidget(self.text_label, 1)
        layout.addWidget(chevron)

    def show_status(self, buttons: set[Button], region_set: bool) -> None:
        area = "scan region" if region_set else "whole display"
        lobby = [b.label for b in (Button.PLAY, Button.READY) if b in buttons]
        if lobby and Button.PLAY_AGAIN in buttons:
            ok, text = True, f"Profile ready · {' / '.join(lobby)} · Play Again · {area}"
        elif lobby:
            ok, text = False, f"{' / '.join(lobby)} ready · Play Again template missing"
        elif Button.PLAY_AGAIN in buttons:
            ok, text = False, "Play Again ready · Play template missing"
        else:
            ok, text = False, "No button templates yet · Set up"
        self._icon.setPixmap(icons.pixmap("check" if ok else "alert", theme.OK if ok else theme.WARN, 14))
        self.text_label.setText(text)
        self.setAccessibleName(f"Recognition profile: {text}. Opens setup.")
        self.setToolTip("Open Setup")
