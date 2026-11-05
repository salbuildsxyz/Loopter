"""Main window: a compact session screen with Setup, Settings, and Activity behind it."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QCloseEvent, QDesktopServices, QGuiApplication, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import QFrame, QLabel, QMainWindow, QScrollArea, QStackedWidget, QVBoxLayout, QWidget

from loop import win32
from loop.capture import CaptureError, Region, display_for, list_monitors
from loop.config import Mode, Settings, app_data_dir, save_settings, templates_dir
from loop.controller import SessionController, build_plan
from loop.demo import SCREEN_SIZE
from loop.demo.target_window import DemoTargetWindow
from loop.hotkey import GlobalHotkey, HotkeyError
from loop.input_guard import InputGuard
from loop.logging_setup import LogBridge
from loop.screens import Button
from loop.state import SessionState
from loop.templates import TemplateLibrary
from loop.ui import icons, theme
from loop.ui.activity_view import ActivityView
from loop.ui.interaction_dialog import confirm_live_interaction
from loop.ui.session_view import SessionView
from loop.ui.settings_view import SettingsView
from loop.ui.setup_view import SetupView
from loop.ui.widgets import IconButton, SegmentedControl, label, row

log = logging.getLogger(__name__)

SAVE_DELAY_MS = 400
DEMO_START_DELAY_MS = 200
ATTENTION_LEVELS = {"WARNING": theme.WARN, "ERROR": theme.ERR, "CRITICAL": theme.ERR}


class MainWindow(QMainWindow):
    emergency_triggered = Signal()  # emitted from the hotkey thread

    def __init__(self, settings: Settings, bridge: LogBridge, icon: QIcon) -> None:
        super().__init__()
        self.setWindowTitle("LOOP")
        self.setWindowIcon(icon)
        self.settings = settings
        self.guard = InputGuard()
        self.controller = SessionController(
            self.guard, lambda: build_plan(self.settings, self.guard, own_windows=self._own_windows())
        )
        self.library = TemplateLibrary(templates_dir(), settings.templates)
        self._log_templates()
        self.hotkey = GlobalHotkey(self._on_hotkey_pressed)
        self.demo_window: DemoTargetWindow | None = None
        self._emergency = False

        self._save_timer = QTimer(self, singleShot=True, interval=SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self._save)
        self._display_timer = QTimer(self, singleShot=True, interval=500)
        self._display_timer.timeout.connect(self._on_displays_changed)
        self._elapsed_timer = QTimer(self, interval=250)
        self._elapsed_timer.timeout.connect(lambda: self.session.set_elapsed(self.controller.elapsed()))

        self._build()
        self._connect(bridge)
        self._load_state()

    def _build(self) -> None:
        self.settings_button = IconButton("gear", "Settings and activity", self.show_settings)
        brand = QLabel()
        brand.setPixmap(icons.brand(20))
        title = QWidget()
        title.setObjectName("TitleStrip")
        title.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        title.setLayout(
            row(brand, label("LOOP", "Wordmark"), None, self.settings_button, margins=(14, 8, 10, 8))
        )

        self.session = SessionView()
        self.setup = SetupView(self.settings, self.library)
        self.settings_view = SettingsView(self.settings, self.library)
        self.activity = ActivityView()

        self.tabs = SegmentedControl([("settings", "Settings", ""), ("activity", "Activity", "")])
        self.tabs.setAccessibleName("Settings sections")
        self.tabs.selected.connect(self._show_tab)
        self.settings_pages = QStackedWidget()
        self.settings_pages.addWidget(_scrolling(self.settings_view))
        self.settings_pages.addWidget(self.activity)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.session)
        self.stack.addWidget(_page(self._back_button(), label("Setup", "Title"), body=self.setup))
        self.stack.addWidget(_page(self._back_button(), self.tabs, body=self.settings_pages))

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(title)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(root)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self.show_main)

    def _back_button(self) -> IconButton:
        return IconButton("back", "Back to session", self.show_main)

    def _connect(self, bridge: LogBridge) -> None:
        for entry in bridge.history:
            self.activity.append(*entry)
        bridge.record.connect(self._on_record)

        c = self.controller
        c.state_changed.connect(self._on_state)
        c.stats_changed.connect(self.session.set_stats)
        c.observed.connect(self.session.set_observation)

        s = self.session
        s.start_requested.connect(self._start)
        s.pause_requested.connect(c.pause)
        s.resume_requested.connect(c.resume)
        s.stop_requested.connect(c.stop)
        s.mode_selected.connect(self._select_mode)
        s.setup_requested.connect(self.show_setup)
        s.activity_requested.connect(self.show_activity)

        v = self.settings_view
        v.threshold_changed.connect(lambda value: self._update(threshold=value))
        v.interval_changed.connect(lambda value: self._update(scan_interval_ms=value))
        v.cooldown_changed.connect(lambda value: self._update(cooldown_s=value))
        v.actions_changed.connect(lambda value: self._update(actions=value))
        v.demo_clicks_toggled.connect(self._set_demo_clicks)
        v.hotkey_submitted.connect(self._apply_hotkey)
        v.monitor_changed.connect(lambda: self._monitor_changed(self.setup))
        v.clear_region_requested.connect(lambda: self._set_region(None))
        v.setup_requested.connect(self.show_setup)
        v.templates_changed.connect(self._templates_changed)

        self.setup.region_selected.connect(self._set_region)
        self.setup.templates_changed.connect(self._templates_changed)
        self.setup.monitor_changed.connect(lambda: self._monitor_changed(self.settings_view))
        self.setup.done.connect(self.show_main)

        self.activity.open_folder_requested.connect(lambda: _open_folder(app_data_dir()))

        self.emergency_triggered.connect(self._on_emergency)
        app = QGuiApplication.instance()
        app.screenAdded.connect(self._watch_screen)
        app.screenRemoved.connect(lambda _s: self._display_timer.start())
        for screen in app.screens():
            self._watch_screen(screen, announce=False)

    def _load_state(self) -> None:
        s = self.settings
        self.setMinimumSize(theme.WINDOW_WIDTH, theme.WINDOW_HEIGHT)
        if s.window_geometry:
            # Keep the position the window had; it always opens at its compact size.
            self.restoreGeometry(QByteArray.fromBase64(s.window_geometry.encode()))
            self.setWindowState(Qt.WindowState.WindowNoState)
        self.resize(theme.WINDOW_WIDTH, theme.WINDOW_HEIGHT)
        self.settings_view.load()
        self._set_mode(s.mode, announce=False)
        self._on_state(self.controller.state)
        self._refresh_profile()
        self._register_hotkey(s.emergency_hotkey)

    # Navigation

    def show_main(self) -> None:
        self.stack.setCurrentIndex(0)

    def show_setup(self) -> None:
        self.setup.refresh_monitors()
        self.stack.setCurrentIndex(1)

    def show_settings(self) -> None:
        self.stack.setCurrentIndex(2)
        self._show_tab(self.tabs.value() or "settings")

    def show_activity(self) -> None:
        self.stack.setCurrentIndex(2)
        self._show_tab("activity")

    def _show_tab(self, tab: str) -> None:
        self.tabs.set_value(tab)
        self.settings_pages.setCurrentIndex(0 if tab == "settings" else 1)
        if tab == "activity":
            self.settings_button.set_badge("")

    def _on_record(self, timestamp: str, level: str, message: str) -> None:
        self.activity.append(timestamp, level, message)
        color = ATTENTION_LEVELS.get(level)
        if color and not self._viewing_activity() and self.settings_button.badge != theme.ERR:
            self.settings_button.set_badge(color)

    def _viewing_activity(self) -> bool:
        return self.stack.currentIndex() == 2 and self.settings_pages.currentWidget() is self.activity

    # Session

    def _own_windows(self) -> Callable[[], list[Region]] | None:
        """LOOP's window, so scans ignore it. Called on the GUI thread; the result runs on the worker."""
        if QGuiApplication.platformName() != "windows":
            return None
        hwnd = int(self.winId())
        return lambda: [rect] if (rect := win32.visible_window_rect(hwnd)) else []

    def _start(self) -> None:
        self._emergency = False
        if self.settings.mode is Mode.DEMO and not (self.demo_window and self.demo_window.isVisible()):
            self._show_demo_target()
            # Let the new window settle at its final position before the first scan.
            QTimer.singleShot(DEMO_START_DELAY_MS, self.controller.start)
            return
        self.controller.start()

    def _on_state(self, state: SessionState) -> None:
        error = self.controller.last_error if state is SessionState.ERROR else ""
        active = state in (SessionState.RUNNING, SessionState.PAUSED)
        self.session.set_state(state, error, self._emergency)
        if state is SessionState.ERROR and not self._viewing_activity():
            self.settings_button.set_badge(theme.ERR)
        self.settings_view.set_editable(not active)
        self.session.set_elapsed(self.controller.elapsed())
        if state is SessionState.RUNNING:
            self._elapsed_timer.start()
        else:
            self._elapsed_timer.stop()

    # Modes and settings

    def _select_mode(self, mode: Mode) -> None:
        if mode is self.settings.mode:
            return
        if mode is Mode.INTERACTION and not confirm_live_interaction(self, self.settings.emergency_hotkey):
            self.session.set_mode(self.settings.mode)
            log.info("Live Interaction was not enabled")
            return
        self._set_mode(mode)

    def _set_mode(self, mode: Mode, announce: bool = True) -> None:
        self.settings.mode = mode
        if mode is not Mode.DEMO and self.demo_window is not None:
            self.demo_window.hide()
        self.session.set_mode(mode)
        self.session.set_stats(self.controller.stats)
        self._refresh_region()
        if announce:
            level = logging.WARNING if mode is Mode.INTERACTION else logging.INFO
            log.log(level, "Mode set to %s", mode.label)
            self._schedule_save()

    def _update(self, **changes: object) -> None:
        for name, value in changes.items():
            setattr(self.settings, name, value)
        self._schedule_save()

    def _set_region(self, region: Region | None) -> None:
        self.settings.region = region
        self._refresh_region()
        log.info("Scan region %s", f"set to {region.describe()}" if region else "cleared")
        self._schedule_save()

    def _refresh_region(self) -> None:
        region = self.settings.region
        valid = True
        if region is not None:
            try:
                display_for(region, list_monitors())
            except CaptureError:
                valid = False
        self.settings_view.show_region(region, valid)
        self.setup.refresh_overlay()
        self._refresh_profile()

    def _monitor_changed(self, other: SetupView | SettingsView) -> None:
        other.refresh_monitors()
        self._schedule_save()

    def _templates_changed(self) -> None:
        self.setup.refresh_templates()
        self.settings_view.refresh_templates()
        self._refresh_profile()
        self._schedule_save()

    def _refresh_profile(self) -> None:
        buttons = self.library.usable_buttons()
        self.session.set_profile(buttons, self.settings.region is not None)
        missing = [b.label for b in Button if b not in buttons]
        count = len(self.library.entries)
        summary = f"{count} template(s). " + (
            f"No {', '.join(missing)} template." if missing else "All buttons set up."
        )
        self.settings_view.show_profile(summary)

    def _set_demo_clicks(self, enabled: bool) -> None:
        self.settings.demo_clicks_enabled = enabled
        log.info("Demo clicks %s", "allowed" if enabled else "off")
        self._schedule_save()

    def _schedule_save(self) -> None:
        self._save_timer.start()

    def _save(self) -> None:
        try:
            save_settings(self.settings)
        except OSError as exc:
            log.error("Settings could not be saved: %s", exc)

    def _log_templates(self) -> None:
        groups, problems = self.library.load()
        for problem in problems:
            log.warning(problem)
        names = [f"{screen.label} · {t.name}" for screen, group in groups.items() for t in group]
        log.info("Loaded %d template(s): %s", len(names), ", ".join(names) or "none")

    # Emergency stop

    def _register_hotkey(self, text: str) -> str:
        """Registers the shortcut and returns an error message, or "" on success."""
        try:
            self.hotkey.register(text)
        except HotkeyError as exc:
            self.settings_view.show_hotkey(text, False, str(exc))
            log.error("Emergency stop shortcut unavailable: %s", exc)
            return str(exc)
        self.settings_view.show_hotkey(
            text, True, "Works while LOOP is in the background. Stops and disarms all."
        )
        return ""

    def _apply_hotkey(self, text: str) -> None:
        previous = self.settings.emergency_hotkey
        error = self._register_hotkey(text)
        if not error:
            self._update(emergency_hotkey=text)
            log.info("Emergency stop shortcut set to %s", text)
        elif previous != text and not self._register_hotkey(previous):
            self.settings_view.show_hotkey(previous, True, f"{error} Still using {previous}.")

    def _on_hotkey_pressed(self) -> None:
        # Runs on the hotkey thread: disarm first so no click can slip through
        # before the UI thread handles the rest.
        self.guard.disarm()
        self.emergency_triggered.emit()

    def _on_emergency(self) -> None:
        self._emergency = True
        self.controller.emergency_stop()
        self.settings.demo_clicks_enabled = False
        self.settings_view.set_demo_clicks(False)
        if self.settings.mode is Mode.INTERACTION:
            self._set_mode(Mode.LIVE)
        self.session.set_state(self.controller.state, emergency=True)
        self._schedule_save()

    # Demo target

    def _show_demo_target(self) -> None:
        if self.demo_window is None:
            self.demo_window = DemoTargetWindow(self.guard)
            self.demo_window.setWindowIcon(self.windowIcon())
            available = self.screen().availableGeometry()
            width = SCREEN_SIZE[0] / self.devicePixelRatioF()
            self.demo_window.move(round(available.right() - width - 40), available.top() + 60)
        self.demo_window.show()
        self.demo_window.raise_()

    # Displays

    def _watch_screen(self, screen, announce: bool = True) -> None:
        screen.geometryChanged.connect(lambda _g: self._display_timer.start())
        if announce:
            self._display_timer.start()

    def _on_displays_changed(self) -> None:
        log.info("Display configuration changed")
        self.setup.refresh_monitors()
        self.settings_view.refresh_monitors()
        self._refresh_region()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt override
        self.controller.shutdown()
        self.hotkey.unregister()
        if self.demo_window is not None:
            self.demo_window.close()
        self.settings.window_geometry = bytes(self.saveGeometry().toBase64()).decode()
        self._save_timer.stop()
        self._save()
        super().closeEvent(event)


def _page(back: QWidget, heading: QWidget, body: QWidget) -> QWidget:
    """A secondary view: a back button and heading above the view's own content."""
    head = QWidget()
    head.setObjectName("ViewHead")
    head.setLayout(row(back, heading, None, margins=(8, 8, 16, 8)))
    line = QFrame()
    line.setFixedHeight(1)
    line.setStyleSheet(f"background: {theme.LINE};")
    page = QWidget()
    page.setObjectName("View")
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    layout.addWidget(head)
    layout.addWidget(line)
    layout.addWidget(body, 1)
    return page


def _scrolling(widget: QWidget) -> QScrollArea:
    scroll = QScrollArea()
    scroll.setWidget(widget)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    return scroll


def _open_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
