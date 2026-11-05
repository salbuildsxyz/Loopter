"""Setup: a guided way to capture, select, save, and test button templates."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from loop.capture import CaptureError, Region, ScreenCapture, list_monitors
from loop.config import Settings, TemplateEntry
from loop.matcher import TemplateError
from loop.recognizer import Observation, Recognizer
from loop.screens import ACTIONABLE, RECOGNIZABLE, Button, Screen, buttons_for
from loop.suggest import find_buttons
from loop.templates import TemplateLibrary
from loop.ui import icons, theme
from loop.ui.canvas import ImageCanvas
from loop.ui.widgets import (
    FieldRow,
    Notice,
    SegmentedControl,
    Switch,
    bgr_to_qimage,
    button,
    label,
    row,
    set_style_property,
)

log = logging.getLogger(__name__)

# Time for the main window to disappear before the screenshot is taken.
HIDE_DELAY_MS = 300
WAITING_SCREENS = [s for s in RECOGNIZABLE if s not in ACTIONABLE]


@dataclass(frozen=True)
class Step:
    name: str
    lede: str


STEPS = [
    Step("Select display", "Pick the display the game runs on."),
    Step(
        "Capture screenshot",
        "Open the lobby or the results screen, then capture it. LOOP hides itself for a moment.",
    ),
    Step(
        "Find the button",
        "LOOP selects the most likely button. Press Find again for the next one, "
        "or drag around the button yourself.",
    ),
    Step("Check the selection", "The box should cover the whole button and nothing else."),
    Step("Confirm the button", "Play and Ready are different buttons. Choose the one the selection shows."),
    Step("Save the template", "Saved templates are loaded every time LOOP starts."),
    Step("Test recognition", "Recognizes this screenshot with all your templates."),
]


def fill_monitors(combo: QComboBox, settings: Settings) -> None:
    """Lists the connected displays and selects the one in the settings."""
    try:
        monitors = list_monitors()
    except CaptureError as exc:
        log.error("Could not list displays: %s", exc)
        monitors = []
    combo.blockSignals(True)
    combo.clear()
    for i, m in enumerate(monitors, start=1):
        combo.addItem(f"Display {i} · {m.width}×{m.height}", m)
        combo.setItemData(i - 1, f"Position ({m.left}, {m.top})", Qt.ItemDataRole.ToolTipRole)
    combo.setCurrentIndex(max(min(settings.monitor, len(monitors)) - 1, 0))
    combo.blockSignals(False)


class SetupView(QWidget):
    region_selected = Signal(object)  # Region | None
    templates_changed = Signal()
    monitor_changed = Signal()
    done = Signal()

    def __init__(self, settings: Settings, library: TemplateLibrary) -> None:
        super().__init__()
        self.setObjectName("View")
        self._settings = settings
        self._library = library
        self._frame: np.ndarray | None = None
        self._origin: Region | None = None  # display the frame was captured from
        self._suggestions: list[Region] = []
        self._suggestion = -1
        self._saved = False
        self._step = 0

        body = QWidget()
        body.setObjectName("View")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(10)

        self._chips = {b: label("", "Chip") for b in Button}
        layout.addLayout(row(*self._chips.values(), None, spacing=6))

        self._track = StepTrack(len(STEPS))
        layout.addWidget(self._track)
        self._step_name = label("", "Title")
        self._step_count = label("", "Caption")
        layout.addLayout(row(self._step_name, None, self._step_count))
        self._lede = label("", "Secondary", wrap=True)
        layout.addWidget(self._lede)

        self._pages = QStackedWidget()
        for page in self._build_pages():
            self._pages.addWidget(page)
        layout.addWidget(self._pages)

        self.canvas = ImageCanvas()
        self.canvas.setMinimumHeight(190)
        self.canvas.selection_changed.connect(self._on_selection)
        layout.addWidget(self.canvas, 1)
        self.selection_text = label("", "Caption")
        layout.addWidget(self.selection_text)
        self.result = Notice()
        self.result.hide()
        layout.addWidget(self.result)

        layout.addWidget(self._build_advanced())

        scroll = QScrollArea()
        scroll.setWidget(body)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.back_button = button("Back", lambda: self.show_step(self._step - 1))
        self.next_button = button("Next", self._next, "primary")
        footer = QWidget()
        footer.setObjectName("TitleStrip")
        footer.setLayout(row(self.back_button, self.next_button, margins=(16, 10, 16, 10)))
        footer.setStyleSheet(
            f"QWidget#TitleStrip {{ border-bottom: none; border-top: 1px solid {theme.LINE}; }}"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(scroll, 1)
        outer.addWidget(footer)

        self.refresh_monitors()
        self.refresh_templates()
        self.show_step(0)

    # Pages

    def _build_pages(self) -> list[QWidget]:
        self.monitor = QComboBox()
        self.monitor.setAccessibleName("Display to capture")
        self.monitor.currentIndexChanged.connect(self._on_monitor_changed)

        self.capture_button = button(
            "Capture screenshot", self._capture, "primary", icon="camera", icon_color=theme.ACCENT_INK
        )
        self.find_button = button("Find button", self._find_buttons, icon="search")
        self.manual_hint = label("Drag around the button on the screenshot.", "Caption", wrap=True)
        self.manual_hint.hide()

        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(64)
        self.preview.setStyleSheet(
            f"background: {theme.BG_0}; border: 1px solid {theme.LINE}; border-radius: 6px;"
        )

        self.kind = SegmentedControl([(b, b.label, "") for b in Button])
        self.kind.setAccessibleName("Button shown in the selection")
        self.kind.selected.connect(self._on_kind_selected)

        self.save_button = button("Save template", self._save_selection_as_template, "primary")
        self.test_button = button("Test recognition", self._test_recognition, icon="target")
        self.meter = ConfidenceMeter()
        self.meter.hide()
        another = button("Add another button", lambda: self.show_step(1), "ghost", "sm", "plus")

        contents = [
            [self.monitor],
            [self.capture_button],
            [self.find_button, self.manual_hint],
            [self.preview],
            [self.kind],
            [self.save_button],
            [self.test_button, self.meter, another],
        ]
        pages = []
        for widgets in contents:
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(8)
            for widget in widgets:
                layout.addWidget(widget)
            pages.append(page)
        return pages

    def _build_advanced(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(0)
        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setObjectName("IconButton")
        self.advanced_toggle.setText("Advanced calibration")
        self.advanced_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setIconSize(QSize(14, 14))
        self.advanced_toggle.setStyleSheet(f"color: {theme.FG_2}; padding: 4px 6px;")
        self.advanced_toggle.toggled.connect(self._show_advanced)
        layout.addWidget(self.advanced_toggle, 0, Qt.AlignmentFlag.AlignLeft)

        self.advanced = QWidget()
        rows = QVBoxLayout(self.advanced)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(0)
        self.manual = Switch()
        self.manual.toggled.connect(self._on_manual)
        rows.addWidget(
            FieldRow(
                "Manual selection",
                "Drag around the button yourself instead of using suggestions.",
                self.manual,
            )
        )
        self.use_region_button = button("Use selection", self._use_selection_as_region, size="sm")
        self.clear_region_button = button("Clear", lambda: self.region_selected.emit(None), "ghost", "sm")
        region_controls = QWidget()
        region_controls.setLayout(row(self.use_region_button, self.clear_region_button, spacing=4))
        self.region_row = FieldRow("Scan region", "", region_controls)
        rows.addWidget(self.region_row)
        self.waiting = QComboBox()
        self.waiting.addItem("None", None)
        for screen in WAITING_SCREENS:
            self.waiting.addItem(screen.label, screen)
        self.waiting.currentIndexChanged.connect(self._on_waiting_selected)
        rows.addWidget(
            FieldRow(
                "Waiting screen", "Optional: save the selection as a screen LOOP only logs.", self.waiting
            )
        )
        rows.addWidget(
            FieldRow(
                "Import image",
                "Adds a PNG, JPG, or BMP as the chosen kind. Matched at its own size.",
                button("Import…", self._import, size="sm", icon="upload"),
            )
        )
        layout.addWidget(self.advanced)
        self._show_advanced(False)
        return box

    # State

    @property
    def selected_target(self) -> tuple[Screen, Button | None] | None:
        """The screen and button the next saved template shows, if one is chosen."""
        if (waiting := self.waiting.currentData()) is not None:
            return waiting, None
        if (chosen := self.kind.value()) is not None:
            return chosen.screen, chosen
        return None

    def select_target(self, screen: Screen, button: Button | None = None) -> None:
        button = button or next(iter(buttons_for(screen)), None)
        if button is None:
            self.waiting.setCurrentIndex(self.waiting.findData(screen))
        else:
            self.waiting.setCurrentIndex(0)
            self.kind.set_value(button)
        self._update_buttons()

    def show_step(self, index: int) -> None:
        self._step = max(0, min(index, len(STEPS) - 1))
        step = STEPS[self._step]
        self._pages.setCurrentIndex(self._step)
        self._fit_page(self._step)
        self._track.set_step(self._step)
        self._step_name.setText(step.name)
        self._step_count.setText(f"Step {self._step + 1} of {len(STEPS)}")
        self._lede.setText(step.lede)
        self.result.hide()
        if self._step == 3:
            self._show_preview()
        self._update_buttons()

    def _fit_page(self, index: int) -> None:
        """Sizes the step area to the current page instead of the tallest one."""
        for i in range(self._pages.count()):
            policy = QSizePolicy.Policy.Preferred if i == index else QSizePolicy.Policy.Ignored
            self._pages.widget(i).setSizePolicy(policy, policy)
        self._pages.adjustSize()

    @property
    def step(self) -> int:
        return self._step

    def refresh_monitors(self) -> None:
        fill_monitors(self.monitor, self._settings)

    def refresh_templates(self) -> None:
        have = self._library.usable_buttons()
        for b, chip in self._chips.items():
            done = b in have
            chip.setText(f"{'✓' if done else '○'}  {b.label}")
            chip.setToolTip(f"{b.label}: {'template saved' if done else 'no template yet'}")
            set_style_property(chip, "done", done)
        self._update_buttons()

    def refresh_overlay(self) -> None:
        self.canvas.set_outline(self._region_in_frame())
        region = self._settings.region
        self.region_row.help.setText(
            f"Scanning {region.describe()}." if region else "Whole display. A region makes scans faster."
        )
        self.region_row.help.show()
        self.clear_region_button.setEnabled(region is not None)

    def _region_in_frame(self) -> Region | None:
        region = self._settings.region
        if region is None or self._origin is None or not self._origin.contains(region):
            return None
        return region.offset(-self._origin.left, -self._origin.top)

    def _update_buttons(self) -> None:
        has_frame = self._frame is not None
        has_selection = self.canvas.selection is not None
        self.canvas.setVisible(has_frame and self._step > 0)
        self.selection_text.setVisible(has_frame and self._step > 0)
        self.find_button.setEnabled(has_frame)
        self.use_region_button.setEnabled(has_selection)
        self.save_button.setEnabled(has_selection and self.selected_target is not None)
        self.test_button.setEnabled(has_frame and bool(self._library.entries))
        ready = [
            True,
            has_frame,
            has_selection,
            has_selection,
            self.selected_target is not None,
            self._saved or bool(self._library.entries),
            True,
        ]
        self.back_button.setEnabled(self._step > 0)
        self.next_button.setEnabled(ready[self._step])
        self.next_button.setText("Done" if self._step == len(STEPS) - 1 else "Next")

    def _next(self) -> None:
        if self._step == len(STEPS) - 1:
            self.done.emit()
        else:
            self.show_step(self._step + 1)

    def _show_advanced(self, shown: bool) -> None:
        self.advanced.setVisible(shown)
        self.advanced_toggle.setIcon(icons.icon("down" if shown else "chevron", theme.FG_3))

    def _on_manual(self, manual: bool) -> None:
        self.find_button.setVisible(not manual)
        self.manual_hint.setVisible(manual)

    def _on_monitor_changed(self, index: int) -> None:
        self._settings.monitor = index + 1
        self.monitor_changed.emit()

    def _on_kind_selected(self, _button: Button) -> None:
        self.waiting.blockSignals(True)
        self.waiting.setCurrentIndex(0)
        self.waiting.blockSignals(False)
        self._update_buttons()

    def _on_waiting_selected(self, index: int) -> None:
        if index > 0:
            self.kind.set_value(None)
        self._update_buttons()

    # Capture and selection

    def _capture(self) -> None:
        monitor = self.monitor.currentData()
        if monitor is None:
            self._report("No display is available to capture.", ok=False)
            return
        self.window().hide()
        QTimer.singleShot(HIDE_DELAY_MS, lambda: self._finish_capture(monitor))

    def _finish_capture(self, monitor: Region) -> None:
        try:
            with ScreenCapture() as capture:
                frame = capture.grab(monitor)
        except CaptureError as exc:
            self._report(str(exc), ok=False)
            log.error("Calibration capture failed: %s", exc)
            return
        finally:
            window = self.window()
            window.show()
            window.raise_()
            window.activateWindow()
        self._frame, self._origin = frame, monitor
        self._suggestions, self._suggestion = [], -1
        self._saved = False
        self.canvas.set_image(bgr_to_qimage(frame))
        self.meter.hide()
        self.refresh_overlay()
        self.show_step(2)
        if not self.manual.isChecked():
            self._find_buttons()

    def _find_buttons(self) -> None:
        if self._frame is None:
            return
        if self._suggestion < 0:
            self._suggestions = find_buttons(self._frame)
            missing = [s for s in ACTIONABLE if s not in {e.screen for e in self._library.entries}]
            if missing:
                self.select_target(missing[0])
        if not self._suggestions:
            self._report(
                "No solid, colored buttons found. Drag around the button to select it yourself.", ok=False
            )
            return
        self._suggestion = (self._suggestion + 1) % len(self._suggestions)
        box = self._suggestions[self._suggestion]
        self.canvas.set_marks(
            [
                (b, str(i + 1), theme.ACCENT if b == box else theme.FG_3)
                for i, b in enumerate(self._suggestions)
            ]
        )
        self.canvas.select(box)
        count = len(self._suggestions)
        more = " Press Find again for the next one." if count > 1 else ""
        self._report(f"Suggestion {self._suggestion + 1} of {count} selected.{more}", ok=True)

    def _on_selection(self, selection: Region | None) -> None:
        if self._frame is None:
            self.selection_text.setText("")
        elif selection is None:
            self.selection_text.setText("Drag on the screenshot to select an area.")
        else:
            self.selection_text.setText(f"Selection {selection.width} × {selection.height} px")
        self._saved = False
        self._update_buttons()

    def _show_preview(self) -> None:
        selection = self.canvas.selection
        if selection is None or self._frame is None:
            self.preview.clear()
            return
        image = QPixmap.fromImage(bgr_to_qimage(self._crop(selection)))
        width = max(self.preview.width() - 16, 120)
        self.preview.setPixmap(
            image.scaled(
                width, 96, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
        )

    def _crop(self, region: Region) -> np.ndarray:
        return self._frame[region.top : region.bottom, region.left : region.right].copy()

    def _use_selection_as_region(self) -> None:
        selection = self.canvas.selection
        if selection is None or self._origin is None:
            return
        region = selection.offset(self._origin.left, self._origin.top)
        self.region_selected.emit(region)
        self._report(f"Scan region set to {region.describe()}.", ok=True)

    # Templates

    def _save_selection_as_template(self) -> None:
        selection, target = self.canvas.selection, self.selected_target
        if selection is None or self._origin is None or target is None:
            return
        screen, chosen = target
        try:
            entry = self._library.add_image(self._crop(selection), screen, self._origin.height, chosen)
        except (TemplateError, OSError) as exc:
            self._report(str(exc), ok=False)
            return
        self._saved = True
        self._template_added(entry, f"{selection.width} × {selection.height}")

    def _import(self) -> None:
        file, _ = QFileDialog.getOpenFileName(
            self, "Import a template image", "", "Images (*.png *.jpg *.jpeg *.bmp)"
        )
        if file:
            self.import_path(Path(file))

    def import_path(self, path: Path) -> None:
        target = self.selected_target
        if target is None:
            self._report("Choose which button the image shows first (step 5).", ok=False)
            return
        try:
            entry = self._library.import_file(path, *target)
        except (TemplateError, OSError) as exc:
            self._report(str(exc), ok=False)
            log.error("Import failed: %s", exc)
            return
        self._template_added(entry, "imported")

    def _template_added(self, entry: TemplateEntry, detail: str) -> None:
        name = Path(entry.path).stem
        log.info("Added '%s' template '%s' (%s)", entry.label, name, detail)
        self.templates_changed.emit()
        self._report(f"Saved '{entry.label}' template '{name}' for the {entry.screen.label} screen.", ok=True)

    def _test_recognition(self) -> None:
        if self._frame is None or self._origin is None:
            return
        groups, problems = self._library.load()
        if not groups:
            self._report(" ".join(problems) or "No templates to test.", ok=False)
            return
        area = self._region_in_frame()
        image = self._crop(area) if area else self._frame
        threshold = self._settings.threshold
        try:
            observation = Recognizer(groups, threshold, self._origin.height).observe(image)
        except TemplateError as exc:
            self._report(str(exc), ok=False)
            return
        offset = (area.left, area.top) if area else (0, 0)
        self.canvas.set_marks(_marks(observation, threshold, offset))
        self.meter.show_observation(observation, threshold)
        message = describe_test(observation, threshold)
        message += " (scan region)" if area else " (whole screenshot)"
        if problems:
            message += " Skipped: " + " ".join(problems)
        self._report(message, ok=observation.match is not None)
        log.info(message)

    def _report(self, text: str, ok: bool) -> None:
        self.result.show_message(text, "ok" if ok else "warn")


class StepTrack(QWidget):
    """A row of short bars, one per step, filled up to the current one."""

    def __init__(self, count: int) -> None:
        super().__init__()
        self._count = count
        self._current = 0
        self.setFixedHeight(4)

    def set_step(self, index: int) -> None:
        self._current = index
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        gap = 4
        width = (self.width() - gap * (self._count - 1)) / self._count
        for i in range(self._count):
            painter.setBrush(QColor(theme.ACCENT if i <= self._current else theme.LINE_2))
            painter.drawRoundedRect(QRectF(i * (width + gap), 0, width, 4), 2, 2)


class ConfidenceMeter(QWidget):
    """The test result's confidence as a bar, with the threshold marked."""

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.heading = label("", "FieldLabel")
        self.value = label("", "Mono")
        layout.addLayout(row(self.heading, None, self.value))
        self._bar = _MeterBar()
        layout.addWidget(self._bar)
        self.threshold_text = label("", "Caption")
        layout.addLayout(row(label("0", "Caption"), None, self.threshold_text, None, label("1", "Caption")))

    def show_observation(self, observation: Observation, threshold: float) -> None:
        confidence = observation.confidence
        if observation.match is not None:
            name = observation.match.template
            heading, color = f"Recognized · {observation.screen.label} ({name})", theme.OK
        elif observation.ambiguous:
            heading, color = "Ambiguous · no action", theme.ERR
        else:
            heading, color = "Not recognized", theme.WARN
        self.heading.setText(heading)
        self.value.setText(f"{confidence:.2f}")
        self.threshold_text.setText(f"threshold {threshold:.2f}")
        self._bar.set_values(confidence, threshold, color)
        self.show()


class _MeterBar(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(10)
        self._value, self._threshold, self._color = 0.0, 0.85, theme.OK

    def set_values(self, value: float, threshold: float, color: str) -> None:
        self._value, self._threshold, self._color = value, threshold, color
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        track = QRectF(0, 3, self.width(), 4)
        painter.setBrush(QColor(theme.BG_3))
        painter.drawRoundedRect(track, 2, 2)
        painter.setBrush(QColor(self._color))
        painter.drawRoundedRect(QRectF(0, 3, self.width() * max(0.0, min(self._value, 1.0)), 4), 2, 2)
        x = self.width() * self._threshold
        painter.setPen(QPen(QColor(theme.FG_1), 1.5))
        painter.drawLine(int(x), 0, int(x), self.height())


def _marks(
    observation: Observation, threshold: float, offset: tuple[int, int]
) -> list[tuple[Region, str, str]]:
    """The recognized screen in green, look-alikes in amber, and near misses in gray."""
    marks = []
    for screen, match in observation.matches.items():
        if screen in observation.lookalikes:
            shown = match.lookalike or match
            caption = f"{screen.label} look-alike  {shown.confidence:.2f}  colors differ"
            marks.append((shown.box.offset(*offset), caption, theme.WARN))
        if match.rejected:
            continue
        caption = f"{screen.label}  {match.confidence:.2f}"
        if screen is observation.screen:
            marks.append((match.box.offset(*offset), caption, theme.OK))
        elif match.confidence >= threshold - 0.10:
            marks.append((match.box.offset(*offset), caption, theme.FG_3))
    return marks


def describe_test(observation: Observation, threshold: float) -> str:
    screen, scores = observation.screen, observation.scores
    others = ", ".join(f"{s.label} {score:.2f}" for s, score in scores.items() if s is not screen)
    if observation.ambiguous:
        first, second = observation.ambiguous
        head = f"Ambiguous: '{first.label}' and '{second.label}' templates match the same area."
    elif screen is Screen.UNKNOWN:
        head = f"No screen recognized above the {threshold:.2f} threshold."
    else:
        head = f"Recognized '{screen.label}' at {scores[screen]:.3f}."
    if observation.lookalikes:
        names = ", ".join(f"'{s.label}'" for s in observation.lookalikes)
        head += f" Ignored a look-alike for {names}: the shape matches but the colors do not."
    return f"{head} Scores: {others}." if others else head
