"""Settings: display and scan area, detection, actions and safety, and the template collection."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QKeySequenceEdit,
    QListWidget,
    QListWidgetItem,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from loop import __version__
from loop.capture import Region
from loop.config import COOLDOWN_S_RANGE, INTERVAL_MS_RANGE, THRESHOLD_RANGE, Settings, TemplateEntry
from loop.matcher import TemplateError
from loop.screens import Screen
from loop.templates import PROFILE_FILE, TemplateLibrary
from loop.ui import theme
from loop.ui.setup_view import fill_monitors
from loop.ui.widgets import IconButton, Notice, Panel, Switch, button, label, row, section

log = logging.getLogger(__name__)

SLIDER_STEPS = 100


class SettingsView(QWidget):
    threshold_changed = Signal(float)
    interval_changed = Signal(int)
    cooldown_changed = Signal(float)
    actions_changed = Signal(object)  # set[Screen]
    demo_clicks_toggled = Signal(bool)
    hotkey_submitted = Signal(str)
    monitor_changed = Signal()
    clear_region_requested = Signal()
    setup_requested = Signal()
    templates_changed = Signal()

    def __init__(self, settings: Settings, library: TemplateLibrary) -> None:
        super().__init__()
        self.setObjectName("View")
        self._settings = settings
        self._library = library
        self._current_hotkey = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(8)
        sections = (
            ("Recognition profile", self._build_profile()),
            ("Detection", self._build_detection()),
            ("Actions & safety", self._build_safety()),
            ("Templates & profile", self._build_templates()),
        )
        for index, (title, panel) in enumerate(sections):
            if index:
                layout.addSpacing(8)
            layout.addWidget(section(title))
            layout.addWidget(panel)
        layout.addLayout(self._template_tools())
        self.result = Notice()
        self.result.hide()
        layout.addWidget(self.result)

        layout.addSpacing(8)
        layout.addWidget(
            label(
                f"LOOP {__version__} · Settings are saved in %APPDATA%\\LOOP. "
                "Live Interaction is never restored at startup.",
                "Help",
                wrap=True,
            )
        )
        layout.addStretch(1)

    def _build_profile(self) -> Panel:
        panel = Panel()
        self.calibration_row = panel.add_row(
            "Calibration",
            "Capture and test button templates.",
            button("Calibrate", self.setup_requested, size="sm", icon="target"),
        )
        self.monitor = QComboBox()
        self.monitor.setMaximumWidth(160)
        self.monitor.currentIndexChanged.connect(self._on_monitor_changed)
        panel.add_row("Display", "For Monitor and Interact.", self.monitor)
        self.clear_region = button("Clear", self.clear_region_requested, "ghost", "sm")
        self.region_row = panel.add_row("Scan area", "", self.clear_region)
        return panel

    def _build_detection(self) -> Panel:
        panel = Panel()
        self.interval = QSpinBox()
        self.interval.setRange(*INTERVAL_MS_RANGE)
        self.interval.setSingleStep(50)
        self.interval.setSuffix(" ms")
        self.interval.setFixedWidth(88)
        self.interval.valueChanged.connect(self.interval_changed)
        panel.add_row("Scan interval", "How often LOOP looks at the screen.", self.interval)
        low, high = THRESHOLD_RANGE
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(round(low * SLIDER_STEPS), round(high * SLIDER_STEPS))
        self.slider.setFixedWidth(96)
        self.slider.valueChanged.connect(self._on_slider)
        self.threshold = QDoubleSpinBox()
        self.threshold.setRange(low, high)
        self.threshold.setSingleStep(0.01)
        self.threshold.setDecimals(2)
        self.threshold.setFixedWidth(52)
        self.threshold.setAccessibleName("Match threshold")
        self.threshold.valueChanged.connect(self._on_threshold)
        threshold = QWidget()
        threshold.setLayout(row(self.slider, self.threshold))
        panel.add_row("Match threshold", "Higher is stricter. 0.85 suits most setups.", threshold)
        return panel

    def _build_safety(self) -> Panel:
        panel = Panel()
        self.hotkey = QKeySequenceEdit()
        self.hotkey.setObjectName("Kbd")
        self.hotkey.setMaximumSequenceLength(1)
        self.hotkey.setFixedWidth(118)
        self.hotkey.setAccessibleName("Emergency stop shortcut")
        self.hotkey.editingFinished.connect(self._submit_hotkey)
        change = button("Change", self._change_hotkey, size="sm")
        hotkey = QWidget()
        hotkey.setLayout(row(self.hotkey, change, spacing=6))
        self.hotkey_row = panel.add_row("Emergency stop", "", hotkey)
        self.press_play = Switch()
        self.press_again = Switch()
        for switch in (self.press_play, self.press_again):
            switch.toggled.connect(self._emit_actions)
        panel.add_row("Press Play / Ready", "In the lobby, in Demo and Interact.", self.press_play)
        panel.add_row("Press Play Again", "On the results screen.", self.press_again)
        self.cooldown = QDoubleSpinBox()
        self.cooldown.setRange(*COOLDOWN_S_RANGE)
        self.cooldown.setSingleStep(0.5)
        self.cooldown.setDecimals(1)
        self.cooldown.setSuffix(" s")
        self.cooldown.setFixedWidth(88)
        self.cooldown.valueChanged.connect(self.cooldown_changed)
        panel.add_row("Cooldown between actions", "Minimum wait after any click.", self.cooldown)
        self.demo_clicks = Switch()
        self.demo_clicks.toggled.connect(self.demo_clicks_toggled)
        panel.add_row(
            "Allow clicks in the demo window",
            "Demo only. Moves your mouse briefly for each click.",
            self.demo_clicks,
        )
        return panel

    def _build_templates(self) -> Panel:
        panel = Panel()
        self.templates = QListWidget()
        self.templates.setAccessibleName("Templates")
        self.templates.setIconSize(QSize(14, 14))
        self.templates.itemSelectionChanged.connect(self._update_buttons)
        panel.body.setContentsMargins(0, 0, 0, 0)
        panel.body.addWidget(self.templates)
        return panel

    def _template_tools(self) -> QHBoxLayout:
        self.remove = IconButton("trash", "Remove the selected template", self._remove_selected)
        self.export = button("Export…", self._export, "ghost", "sm", "download")
        self.export.setToolTip("Export all templates as a profile folder")
        return row(
            button("Add template", self.setup_requested, size="sm", icon="plus"),
            button("Import…", self._import, "ghost", "sm", "upload"),
            self.export,
            None,
            self.remove,
            spacing=4,
        )

    def load(self) -> None:
        s = self._settings
        widgets = (
            self.interval,
            self.threshold,
            self.slider,
            self.cooldown,
            self.press_play,
            self.press_again,
        )
        for widget in widgets:
            widget.blockSignals(True)
        self.interval.setValue(s.scan_interval_ms)
        self.threshold.setValue(s.threshold)
        self.slider.setValue(round(s.threshold * SLIDER_STEPS))
        self.cooldown.setValue(s.cooldown_s)
        self.press_play.setChecked(Screen.LOBBY in s.actions)
        self.press_again.setChecked(Screen.RESULTS in s.actions)
        for widget in widgets:
            widget.blockSignals(False)
        self.set_demo_clicks(s.demo_clicks_enabled)
        self.refresh_monitors()
        self.refresh_templates()

    def set_demo_clicks(self, enabled: bool) -> None:
        self.demo_clicks.blockSignals(True)
        self.demo_clicks.setChecked(enabled)
        self.demo_clicks.blockSignals(False)

    def set_editable(self, editable: bool) -> None:
        """Session settings are fixed when a session starts, so lock them while one is active."""
        for widget in (
            self.interval,
            self.slider,
            self.threshold,
            self.cooldown,
            self.press_play,
            self.press_again,
            self.demo_clicks,
            self.monitor,
            self.clear_region,
        ):
            widget.setEnabled(editable)

    def refresh_monitors(self) -> None:
        fill_monitors(self.monitor, self._settings)

    def show_region(self, region: Region | None, valid: bool) -> None:
        if region is None:
            text = "Whole display. Set a region in Setup to make scans faster."
        elif not valid:
            text = f"{region.describe()} is outside the connected displays."
        else:
            text = region.describe()
        self.region_row.help.setText(text)
        self.region_row.help.show()
        self.region_row.set_error("" if valid else "Clear it or set a new one in Setup.")
        self.clear_region.setVisible(region is not None)

    def show_profile(self, summary: str) -> None:
        self.calibration_row.help.setText(summary)

    def show_hotkey(self, text: str, active: bool, message: str) -> None:
        if active or not self._current_hotkey:
            self._current_hotkey = text
        self.hotkey.blockSignals(True)
        self.hotkey.setKeySequence(QKeySequence.fromString(text, QKeySequence.SequenceFormat.PortableText))
        self.hotkey.blockSignals(False)
        self.hotkey_row.help.setText(message if active else "")
        self.hotkey_row.help.setVisible(active)
        self.hotkey_row.set_error("" if active else message)

    def refresh_templates(self) -> None:
        self.templates.clear()
        for entry in self._library.entries:
            usable, status = self._library.status(entry)
            text = f"{entry.label}  ·  {Path(entry.path).stem}"
            item = QListWidgetItem(f"{text}  ·  {status}" if usable else f"{text}  ·  missing")
            item.setData(Qt.ItemDataRole.UserRole, entry)
            item.setToolTip(entry.path if usable else status)
            if not usable:
                item.setForeground(QColor(theme.ERR))
            self.templates.addItem(item)
        if not self._library.entries:
            item = QListWidgetItem("No templates yet. Add one in Setup.")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.templates.addItem(item)
        rows = max(1, len(self._library.entries))
        self.templates.setFixedHeight(min(rows, 6) * 30 + 2)
        self._update_buttons()

    def import_path(self, path: Path) -> None:
        try:
            added, problems = self._library.import_profile(path)
        except (TemplateError, OSError) as exc:
            self._report(str(exc), ok=False)
            log.error("Import failed: %s", exc)
            return
        for problem in problems:
            log.warning("Profile import: %s", problem)
        for entry in added:
            log.info("Imported '%s' template '%s'", entry.label, Path(entry.path).stem)
        self.templates_changed.emit()
        skipped = f" {len(problems)} skipped; see Activity." if problems else ""
        self._report(f"Imported {len(added)} template(s).{skipped}", ok=bool(added) and not problems)

    def export_to(self, folder: Path) -> None:
        try:
            count = self._library.export_profile(folder)
        except (TemplateError, OSError) as exc:
            self._report(f"Export failed: {exc}", ok=False)
            log.error("Profile export failed: %s", exc)
            return
        log.info("Exported %d template(s) to %s", count, folder)
        self._report(f"Exported {count} template(s) to {folder}.", ok=True)

    def _report(self, text: str, ok: bool) -> None:
        self.result.show_message(text, "ok" if ok else "warn")

    def _on_monitor_changed(self, index: int) -> None:
        self._settings.monitor = index + 1
        self.monitor_changed.emit()

    def _on_slider(self, value: int) -> None:
        self.threshold.setValue(value / SLIDER_STEPS)

    def _on_threshold(self, value: float) -> None:
        self.slider.blockSignals(True)
        self.slider.setValue(round(value * SLIDER_STEPS))
        self.slider.blockSignals(False)
        self.threshold_changed.emit(value)

    def _emit_actions(self) -> None:
        actions = {Screen.LOBBY} if self.press_play.isChecked() else set()
        if self.press_again.isChecked():
            actions.add(Screen.RESULTS)
        self.actions_changed.emit(actions)

    def _change_hotkey(self) -> None:
        self.hotkey.clear()
        self.hotkey.setFocus()
        self.hotkey_row.help.setText("Press the new key combination…")
        self.hotkey_row.help.show()

    def _submit_hotkey(self) -> None:
        text = self.hotkey.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
        if text:
            self.hotkey_submitted.emit(text)
        else:
            self.show_hotkey(self._current_hotkey, True, "Unchanged.")

    def _update_buttons(self) -> None:
        self.remove.setEnabled(bool(self.templates.selectedItems()))
        self.export.setEnabled(bool(self._library.entries))

    def _import(self) -> None:
        file, _ = QFileDialog.getOpenFileName(
            self, "Import a LOOP profile", "", f"LOOP profile ({PROFILE_FILE})"
        )
        if file:
            self.import_path(Path(file))

    def _export(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Export templates to an empty folder")
        if folder:
            self.export_to(Path(folder))

    def _remove_selected(self) -> None:
        for item in self.templates.selectedItems():
            entry: TemplateEntry = item.data(Qt.ItemDataRole.UserRole)
            name = Path(entry.path).name
            try:
                self._library.remove(entry)
            except OSError as exc:
                self._report(f"Could not delete '{name}': {exc.strerror}", ok=False)
            else:
                log.info("Removed template '%s'", name)
        self.templates_changed.emit()
