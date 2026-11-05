"""Settings: display, motion, recognition, actions and safety, and advanced tools."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QWidget

from loop.config import Settings
from loop.screens import Screen
from loop.ui.controls import Button, HotkeyButton, Select, StopSlider, Switch
from loop.ui.model import ViewState
from loop.ui.screenshot import Display
from loop.ui.widgets import Disclosure, Page, Row, Rows, Tag, field, row, text

STRICTNESS = (("Relaxed", 0.80), ("Balanced", 0.85), ("Strict", 0.90))
INTERVALS_MS = (500, 750, 1000, 2000)
COOLDOWNS_S = (1.0, 2.0, 5.0)


def seconds_label(seconds: float) -> str:
    return "1 second" if seconds == 1 else f"{seconds:g} seconds"


def nearest_strictness(threshold: float) -> int:
    return min(range(len(STRICTNESS)), key=lambda i: abs(STRICTNESS[i][1] - threshold))


def _choices(presets: tuple[float, ...], current: float, to_seconds: float) -> list[tuple[str, float]]:
    """Preset choices, plus the saved value if it is not one of them."""
    values = sorted({*presets, current})
    return [(seconds_label(v / to_seconds), v) for v in values]


class SettingsPage(Page):
    display_changed = Signal(int)
    reduce_motion_changed = Signal(bool)
    threshold_changed = Signal(float)
    interval_changed = Signal(int)
    actions_changed = Signal(object)  # set[Screen]
    cooldown_changed = Signal(float)
    hotkey_recorded = Signal(str)
    import_requested = Signal()
    export_requested = Signal()
    data_folder_requested = Signal()
    onboarding_requested = Signal()
    message = Signal(str, str)

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings = settings
        self.heading("Settings")

        general = Rows()
        self.display = Select("Game display")
        self.display.currentIndexChanged.connect(
            lambda _i: self.display_changed.emit(self.display.currentData())
        )
        self._row(general, "Game display", "The screen your game runs on.", self.display)
        self.reduce_motion = Switch("Reduce motion")
        self.reduce_motion.toggled.connect(self.reduce_motion_changed)
        self._row(
            general, "Reduce motion", "Turns off transitions and the live indicator.", self.reduce_motion
        )
        self.group("General", general)

        recognition = Rows()
        strict = Row(control=True)
        strict.body.setDirection(QHBoxLayout.Direction.TopToBottom)
        strict.body.setSpacing(8)
        box, _title, _help = field("Match strictness", "Stricter means fewer false matches.")
        self.strict_value = Tag("Balanced")
        strict.body.addLayout(row(box, self.strict_value, spacing=8))
        self.strictness = StopSlider(len(STRICTNESS), "Match strictness")
        self.strictness.valueChanged.connect(self._on_strictness)
        strict.body.addWidget(self.strictness)
        relaxed, balanced, stricter = (text(name, "stat-label") for name, _ in STRICTNESS)
        strict.body.addLayout(row(relaxed, None, balanced, None, stricter, spacing=0))
        recognition.add(strict)
        self.interval = Select("Check every")
        self.interval.currentIndexChanged.connect(
            lambda _i: self.interval_changed.emit(int(self.interval.currentData()))
        )
        self._row(recognition, "Check every", "How often Loopter looks at the screen.", self.interval)
        self.group("Recognition", recognition)

        safety = Rows()
        self.click_play = Switch("Click Play / Ready")
        self.click_again = Switch("Click Play Again")
        for switch in (self.click_play, self.click_again):
            switch.toggled.connect(self._emit_actions)
        self._row(safety, "Click Play / Ready", "In Auto click, on the lobby screen.", self.click_play)
        self._row(safety, "Click Play Again", "In Auto click, on the results screen.", self.click_again)
        self.cooldown = Select("Pause between clicks")
        self.cooldown.currentIndexChanged.connect(
            lambda _i: self.cooldown_changed.emit(float(self.cooldown.currentData()))
        )
        self._row(safety, "Pause between clicks", "Minimum wait after any click.", self.cooldown)
        self.hotkey = HotkeyButton()
        self.hotkey.recorded.connect(self.hotkey_recorded)
        self.hotkey.rejected.connect(lambda reason: self.message.emit(reason, "warn"))
        _row, _title, self.hotkey_help = self._row(
            safety,
            "Emergency stop",
            "Works even when Loopter is in the background. Stops everything instantly.",
            self.hotkey,
        )
        self.group("Actions & safety", safety)

        advanced = Rows()
        profile = QWidget()
        profile.setLayout(
            row(
                Button("Import", self.import_requested.emit, "secondary", "sm", "upload"),
                Button("Export", self.export_requested.emit, "secondary", "sm", "download"),
            )
        )
        self._row(advanced, "Button profile", "Back up or share your saved buttons.", profile)
        self._row(
            advanced,
            "Data folder",
            "Settings, saved buttons, and log files.",
            Button("Open", self.data_folder_requested.emit, "secondary", "sm"),
        )
        self._row(
            advanced,
            "First-time setup",
            "Walk through setup again.",
            Button("Run again", self.onboarding_requested.emit, "secondary", "sm"),
        )
        self.advanced = Disclosure("Advanced", advanced)
        self.content.addWidget(self.advanced)
        self.content.addWidget(
            text("Auto click is never turned on by itself when Loopter starts.", "caption", wrap=True)
        )
        self.content.addStretch(1)

    @staticmethod
    def _row(rows: Rows, title: str, help_text: str, control: QWidget):
        widget = Row(control=True)
        box, title_label, help_label = field(title, help_text)
        widget.body.addWidget(box, 1)
        widget.body.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
        rows.add(widget)
        return widget, title_label, help_label

    def load(self, displays: list[Display]) -> None:
        """Shows the saved values without emitting changes."""
        s = self._settings
        self.set_displays(displays)
        self.reduce_motion.set_checked_quietly(s.reduce_motion)
        self.strictness.blockSignals(True)
        self.strictness.setValue(nearest_strictness(s.threshold))
        self.strictness.blockSignals(False)
        self._show_strictness()
        self.interval.set_items(_choices(INTERVALS_MS, s.scan_interval_ms, 1000), s.scan_interval_ms)
        self.cooldown.set_items(_choices(COOLDOWNS_S, s.cooldown_s, 1), s.cooldown_s)
        self.click_play.set_checked_quietly(Screen.LOBBY in s.actions)
        self.click_again.set_checked_quietly(Screen.RESULTS in s.actions)
        self.hotkey.set_shortcut(s.emergency_hotkey)

    def set_displays(self, displays: list[Display]) -> None:
        items = [(f"{d.name} · Primary" if d.primary else d.name, d.number) for d in displays]
        self.display.set_items(items, self._settings.monitor)

    def render(self, view: ViewState) -> None:
        # Session settings are fixed when a session starts.
        for widget in (self.display, self.click_play, self.click_again, self.cooldown):
            widget.setEnabled(not view.active)
        self.hotkey.set_shortcut(view.hotkey)

    def show_hotkey_problem(self, message: str) -> None:
        self.hotkey_help.setText(
            message or "Works even when Loopter is in the background. Stops everything instantly."
        )
        self.hotkey_help.setProperty("tone", "warn" if message else None)
        self.hotkey_help.style().polish(self.hotkey_help)

    def _on_strictness(self, index: int) -> None:
        self._show_strictness()
        self.threshold_changed.emit(STRICTNESS[index][1])

    def _show_strictness(self) -> None:
        name = STRICTNESS[self.strictness.value()][0]
        self.strict_value.setText(name)
        self.strictness.setAccessibleDescription(name)

    def _emit_actions(self) -> None:
        actions = {Screen.LOBBY} if self.click_play.isChecked() else set()
        if self.click_again.isChecked():
            actions.add(Screen.RESULTS)
        self.actions_changed.emit(actions)
