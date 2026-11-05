"""Setup: the saved buttons, capturing a button, checking recognition, and calibration."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import QFileDialog, QMenu

from loop.capture import Region
from loop.config import Settings
from loop.screens import ACTIONABLE, RECOGNIZABLE, Screen
from loop.templates import TemplateLibrary
from loop.ui.capture_card import CaptureCard
from loop.ui.check_card import CheckCard
from loop.ui.controls import Button
from loop.ui.home import ButtonRow
from loop.ui.model import TARGETS, Target, ViewState
from loop.ui.widgets import Card, Disclosure, Page, Row, Rows, field

log = logging.getLogger(__name__)

WAITING_SCREENS = [s for s in RECOGNIZABLE if s not in ACTIONABLE]


class SetupPage(Page):
    region_selected = Signal(object)  # Region | None
    templates_changed = Signal()
    onboarding_requested = Signal()
    message = Signal(str, str)  # text, toast kind

    def __init__(
        self, settings: Settings, library: TemplateLibrary, capture: CaptureCard, check: CheckCard
    ) -> None:
        super().__init__()
        self._settings = settings
        self._library = library
        self.capture = capture
        self.check = check
        self.heading("Setup", "Loopter recognizes your game from small pictures of its buttons.")

        self.rows: dict[Target, ButtonRow] = {}
        buttons = Rows()
        for target in TARGETS:
            action = Button("Capture", lambda t=target: self.capture_target(t), "secondary", "sm", "camera")
            widget = ButtonRow(target, action)
            widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            widget.customContextMenuRequested.connect(lambda pos, t=target: self._button_menu(t, pos))
            self.rows[target] = widget
            buttons.add(widget)
        self.group("Your buttons", buttons)

        self.capture_box = Card()
        self.capture_box.body.addWidget(capture)
        self.group("Capture a button", self.capture_box)
        self.check_box = Card()
        self.check_box.body.addWidget(check)
        self.group("Check recognition", self.check_box)

        calibration = Rows()
        self.set_area = Button("Set area", self._set_area, "secondary", "sm")
        self.area_row, self.area_help = self._control_row(calibration, "Scan area", self.set_area)
        self.clear_area = Button("Clear", lambda: self.region_selected.emit(None), "ghost", "sm")
        self.area_row.body.insertWidget(1, self.clear_area)
        self.waiting_button = Button("Add", self._waiting_menu, "secondary", "sm")
        _row, self.waiting_help = self._control_row(calibration, "Waiting screens", self.waiting_button)
        _row, _help = self._control_row(
            calibration, "Import an image", Button("Import", self._import, "secondary", "sm", "upload")
        )
        _help.setText("A PNG, JPG, or BMP of a single button.")
        self.calibration = Disclosure("Advanced calibration", calibration)
        self.content.addWidget(self.calibration)
        restart = Button("Run first-time setup again", self.onboarding_requested.emit, "link")
        self.content.addWidget(restart, 0, Qt.AlignmentFlag.AlignLeft)
        self.content.addStretch(1)

    @staticmethod
    def _control_row(rows: Rows, title: str, control: Button) -> tuple[Row, object]:
        widget = Row(control=True)
        box, _title, help_label = field(title, " ")
        widget.body.addWidget(box, 1)
        widget.body.addWidget(control)
        rows.add(widget)
        return widget, help_label

    def capture_target(self, target: Target | Screen) -> None:
        """Opens the capture card for a button (or a waiting screen) and scrolls to it."""
        self.capture.reset(target)
        self.scroll_to(self.capture_box)

    def show_check(self) -> None:
        self.scroll_to(self.check_box)

    def render(self, view: ViewState) -> None:
        for target, widget in self.rows.items():
            widget.set_check(view.checks[target])
            widget.action.setText("Recapture" if target in view.saved else "Capture")
        region = self._settings.region
        self.area_help.setText(
            f"Scanning {region.describe()}."
            if region
            else "Whole display. A smaller area makes checks faster."
        )
        self.clear_area.setVisible(region is not None)
        waiting = [e for e in self._library.entries if e.screen in WAITING_SCREENS]
        count = f" {len(waiting)} saved." if waiting else ""
        self.waiting_help.setText(f"Optional. Noted in Activity, never clicked.{count}")
        # The scan area is fixed when a session starts.
        self.set_area.setEnabled(not view.active)
        self.clear_area.setEnabled(not view.active)

    def _set_area(self) -> None:
        region: Region | None = self.capture.selection()
        if region is None:
            self.message.emit(
                "Capture a screenshot above, draw a box around the area to scan, then press Set area.", "info"
            )
            return
        self.region_selected.emit(region)

    def _waiting_menu(self) -> None:
        menu = QMenu(self)
        for screen in WAITING_SCREENS:
            menu.addAction(f"Capture the {screen.label} screen", lambda s=screen: self.capture_target(s))
        waiting = [e for e in self._library.entries if e.screen in WAITING_SCREENS]
        if waiting:
            menu.addSeparator()
            menu.addAction(f"Remove saved waiting screens ({len(waiting)})", self._remove_waiting)
        menu.exec(self.waiting_button.mapToGlobal(QPoint(0, self.waiting_button.height() + 4)))

    def _remove_waiting(self) -> None:
        for entry in [e for e in self._library.entries if e.screen in WAITING_SCREENS]:
            self._remove(entry)
        self.templates_changed.emit()

    def _button_menu(self, target: Target, position: QPoint) -> None:
        entries = [e for e in self._library.entries if e.button in target.buttons]
        if not entries:
            return
        menu = QMenu(self)
        menu.addAction(f"Remove saved {target.label}", lambda: self._remove_target(target))
        menu.exec(self.rows[target].mapToGlobal(position))

    def _remove_target(self, target: Target) -> None:
        for entry in [e for e in self._library.entries if e.button in target.buttons]:
            self._remove(entry)
        self.templates_changed.emit()

    def _remove(self, entry) -> None:
        try:
            self._library.remove(entry)
        except OSError as exc:
            self.message.emit(f"Couldn't delete {Path(entry.path).name}: {exc.strerror}", "err")
            return
        log.info("Removed the '%s' picture (%s)", entry.label, Path(entry.path).name)

    def _import(self) -> None:
        file, _ = QFileDialog.getOpenFileName(
            self, "Import a button image", "", "Images (*.png *.jpg *.jpeg *.bmp)"
        )
        if file:
            self.import_image(Path(file))

    def import_image(self, path: Path) -> None:
        error = self.capture.import_path(path)
        if error:
            self.message.emit(f"Couldn't import it: {error}", "err")
