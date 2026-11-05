"""The main window: tabs for Home, Setup, Activity, and Settings, plus first-time setup.

The window owns the real session controller, template library, and emergency stop. It
mirrors their state into a ViewState that every page renders, so the interface only ever
shows what the application actually knows.
"""

from __future__ import annotations

import ctypes
import logging
from pathlib import Path

from PySide6.QtCore import QByteArray, QEvent, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QCloseEvent,
    QDesktopServices,
    QGuiApplication,
    QIcon,
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import QFileDialog, QMainWindow, QVBoxLayout, QWidget

from loop import DISPLAY_NAME, win32
from loop.capture import Region
from loop.config import Mode, Settings, app_data_dir, logs_dir, save_settings, templates_dir
from loop.controller import SessionController, build_plan
from loop.hotkey import GlobalHotkey, HotkeyError
from loop.input_guard import InputGuard
from loop.logging_setup import LogBridge
from loop.matcher import TemplateError
from loop.recognizer import Observation
from loop.screens import Screen
from loop.state import SessionState, SessionStats
from loop.templates import PROFILE_FILE, TemplateLibrary
from loop.ui import motion, screenshot, theme
from loop.ui.activity import ActivityPage
from loop.ui.capture_card import CaptureCard
from loop.ui.check_card import CheckCard
from loop.ui.home import HomePage
from loop.ui.model import Check, CheckOutcome, Target, ViewState, saved_targets, short_clock
from loop.ui.onboarding import BUTTONS, DISPLAY, Onboarding
from loop.ui.overlay import AutoClickDialog, ToastHost
from loop.ui.screenshot import Display
from loop.ui.settings_page import SettingsPage
from loop.ui.setup_page import SetupPage
from loop.ui.tabs import TabBar

log = logging.getLogger(__name__)

SAVE_DELAY_MS = 400
FLASH_MS = 2400
PAGES = ("home", "setup", "activity", "settings")
HOME, SETUP, ACTIVITY, SETTINGS = range(len(PAGES))


class Root(QWidget):
    """The window background; it keeps its floating layers the same size as itself."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Root")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.layers: list[QWidget] = []

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        for layer in self.layers:
            layer.setGeometry(self.rect())


class MainWindow(QMainWindow):
    emergency_triggered = Signal()  # emitted from the hotkey thread

    def __init__(self, settings: Settings, bridge: LogBridge, icon: QIcon) -> None:
        super().__init__()
        self.setWindowTitle(DISPLAY_NAME)
        self.setWindowIcon(icon)
        self.settings = settings
        motion.settings().set_user_preference(settings.reduce_motion)
        self.view = ViewState(mode=Mode.LIVE, hotkey=settings.emergency_hotkey)
        self.guard = InputGuard()
        self.controller = SessionController(
            self.guard, lambda: build_plan(self.settings, own_windows=self._own_windows())
        )
        self.library = TemplateLibrary(templates_dir(), settings.templates)
        self.hotkey = GlobalHotkey(self._on_hotkey_pressed)
        self.displays: list[Display] = screenshot.list_displays()
        if not settings.onboarding_done and settings.onboarding_step == 0:
            # A first launch starts on the primary display.
            primary = screenshot.default_display(self.displays)
            if primary is not None:
                settings.monitor = primary.number
        self._log_templates()

        self._save_timer = QTimer(self, singleShot=True, interval=SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self._save)
        self._display_timer = QTimer(self, singleShot=True, interval=500)
        self._display_timer.timeout.connect(self._on_displays_changed)
        self._elapsed_timer = QTimer(self, interval=250)
        self._elapsed_timer.timeout.connect(self._tick)
        self._flash_timer = QTimer(self, singleShot=True, interval=FLASH_MS)
        self._flash_timer.timeout.connect(self._clear_flash)

        self._onboarding_open = False
        self._build()
        self._connect(bridge)
        self._load_state()

    # Construction

    def _cards(self, primary: bool) -> tuple[CaptureCard, CheckCard]:
        capture = CaptureCard(self.library, self.display, self.saved_targets)
        check = CheckCard(
            self.settings, self.library, self.view.checks, self.display, self.saved_targets, primary=primary
        )
        return capture, check

    def saved_targets(self) -> set[Target]:
        return self.view.saved

    def _build(self) -> None:
        self.root = Root()
        layout = QVBoxLayout(self.root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.tabs = TabBar([name.title() for name in PAGES])
        self.tabs.picked.connect(self.go)
        layout.addWidget(self.tabs)

        self.home = HomePage()
        setup_capture, setup_check = self._cards(primary=False)
        self.setup = SetupPage(self.settings, self.library, setup_capture, setup_check)
        self.activity = ActivityPage()
        self.settings_page = SettingsPage(self.settings)
        self.stack = motion.AnimatedStack()
        for page in (self.home, self.setup, self.activity, self.settings_page):
            self.stack.addWidget(page)
        layout.addWidget(self.stack, 1)
        self.shell = [self.tabs, self.stack]

        onboarding_capture, onboarding_check = self._cards(primary=True)
        self.onboarding = Onboarding(onboarding_capture, onboarding_check)
        self.onboarding.setParent(self.root)
        self.onboarding.hide()
        self.dialog = AutoClickDialog(self.root)
        self.toasts = ToastHost(self.root)
        self.root.layers = [self.onboarding, self.dialog, self.toasts]
        self.setCentralWidget(self.root)
        self.captures = (setup_capture, onboarding_capture)
        self.checks = (setup_check, onboarding_check)

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self._escape)
        for number in range(1, len(PAGES) + 1):
            QShortcut(QKeySequence(f"Ctrl+{number}"), self, lambda n=number - 1: self._shortcut(n))

    def _connect(self, bridge: LogBridge) -> None:
        for entry in bridge.history:
            self.activity.append(*entry)
        bridge.record.connect(self._on_record)

        c = self.controller
        c.state_changed.connect(self._on_state)
        c.stats_changed.connect(self._on_stats)
        c.observed.connect(self._on_observed)

        h = self.home
        h.start_requested.connect(self.start_session)
        h.pause_requested.connect(c.pause)
        h.resume_requested.connect(c.resume)
        h.stop_requested.connect(self.stop_session)
        h.mode_picked.connect(self.pick_mode)
        h.open_requested.connect(self.open)

        self.dialog.accepted.connect(self._auto_click_confirmed)
        self.dialog.rejected.connect(self._auto_click_declined)

        for capture in self.captures:
            capture.saved.connect(lambda target, card=capture: self._on_saved(target, card))
        self.captures[0].display_requested.connect(lambda: self.go(SETTINGS))
        self.captures[1].display_requested.connect(lambda: self.onboarding.show_step(DISPLAY))
        for check in self.checks:
            check.checked.connect(self._on_checked)
        self.checks[0].recapture.connect(self.open_setup_for)
        self.checks[1].recapture.connect(self._recapture_in_onboarding)

        s = self.setup
        s.region_selected.connect(self._set_region)
        s.templates_changed.connect(self._templates_changed)
        s.onboarding_requested.connect(lambda: self.show_onboarding(0))
        s.message.connect(self.toast)

        a = self.activity
        a.home_requested.connect(lambda: self.go(HOME))
        a.open_folder_requested.connect(lambda: _open_folder(logs_dir()))
        a.message.connect(self.toast)

        v = self.settings_page
        v.display_changed.connect(self._pick_display)
        v.reduce_motion_changed.connect(self._set_reduce_motion)
        v.threshold_changed.connect(lambda value: self._update(threshold=value))
        v.interval_changed.connect(lambda value: self._update(scan_interval_ms=value))
        v.actions_changed.connect(lambda value: self._update(actions=value))
        v.cooldown_changed.connect(lambda value: self._update(cooldown_s=value))
        v.hotkey_recorded.connect(self.apply_hotkey)
        v.import_requested.connect(self._import_profile)
        v.export_requested.connect(self._export_profile)
        v.data_folder_requested.connect(lambda: _open_folder(app_data_dir()))
        v.onboarding_requested.connect(lambda: self.show_onboarding(0))
        v.message.connect(self.toast)

        o = self.onboarding
        o.finished.connect(self._finish_onboarding)
        o.deferred.connect(self._defer_onboarding)
        o.step_changed.connect(self._onboarding_step)
        o.display_picked.connect(self._pick_display)

        self.emergency_triggered.connect(self._on_emergency)
        app = QGuiApplication.instance()
        app.screenAdded.connect(self._watch_screen)
        app.screenRemoved.connect(lambda _s: self._display_timer.start())
        for screen in app.screens():
            self._watch_screen(screen, announce=False)

    def _load_state(self) -> None:
        s = self.settings
        self.setMinimumSize(theme.MIN_WIDTH, theme.MIN_HEIGHT)
        if s.window_geometry:
            # Keep the position the window had; it always opens at its regular size.
            self.restoreGeometry(QByteArray.fromBase64(s.window_geometry.encode()))
            self.setWindowState(Qt.WindowState.WindowNoState)
        height = theme.WINDOW_HEIGHT
        if (screen := self.screen()) is not None:
            height = max(theme.MIN_HEIGHT, min(height, screen.availableGeometry().height() - 48))
        self.resize(theme.WINDOW_WIDTH, height)
        self.settings_page.load(self.displays)
        self.settings_page.set_displays(self.displays)
        self.onboarding.set_displays(self.displays, s.monitor)
        self._register_hotkey(s.emergency_hotkey)
        self._refresh_saved()
        self.go(HOME, animate=False)
        if self.needs_onboarding():
            self.show_onboarding(s.onboarding_step, animate=False)

    def needs_onboarding(self) -> bool:
        return not self.settings.onboarding_done and not self.library.usable_buttons()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        _tint_title_bar(int(self.winId()))

    def changeEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.type() == QEvent.Type.WindowStateChange:
            self.home.set_ambient_allowed(not self.isMinimized())
        super().changeEvent(event)

    # Rendering

    def render(self) -> None:
        view = self.view
        view.checks.sync(view.saved)
        self.home.render(view)
        self.setup.render(view)
        self.settings_page.render(view)
        self.onboarding.render(view)
        for capture in self.captures:
            if capture.phase not in ("loading", "confirm"):
                capture.render()
        for check in self.checks:
            check.refresh()
        self.tabs.set_flag(SETUP, "warn" if self._setup_needs_attention() else "")
        self._update_title()

    def _setup_needs_attention(self) -> bool:
        return Target.PLAY not in self.view.saved or any(
            c is Check.ADJUST for c in self.view.checks.statuses.values()
        )

    def _update_title(self) -> None:
        view = self.view
        if view.active:
            state = (
                "Paused"
                if view.session is SessionState.PAUSED
                else "Auto clicking"
                if view.mode is Mode.INTERACTION
                else "Watching"
            )
            title = f"{DISPLAY_NAME} · {state} · {short_clock(view.elapsed)}"
        else:
            title = DISPLAY_NAME
        if self.windowTitle() != title:
            self.setWindowTitle(title)

    def _refresh_saved(self) -> None:
        """Re-reads which buttons have a usable picture (this loads the files, so not on every frame)."""
        self.view.saved = saved_targets(self.library.usable_buttons())
        self.render()

    def toast(self, message: str, kind: str = "info") -> None:
        self.toasts.show_message(message, kind)

    # Navigation

    @property
    def page(self) -> int:
        return -1 if self.onboarding_open else self.stack.currentIndex()

    @property
    def onboarding_open(self) -> bool:
        return self._onboarding_open

    def go(self, page: int, animate: bool = True) -> None:
        if self.onboarding_open:
            self._close_onboarding()
        if animate:
            self.stack.setCurrentIndex(page)
        else:
            self.stack.jump(page)
        self.tabs.set_current(page, animate)
        if page == ACTIVITY:
            self.tabs.set_flag(ACTIVITY, "")

    def open(self, name: str) -> None:
        """Follows a link from Home: a page, the check, or a button to capture."""
        if name in (t.value for t in Target):
            self.open_setup_for(Target(name))
        elif name == "again":
            self.open_setup_for(Target.AGAIN)
        elif name == "check":
            self.go(SETUP)
            self.setup.show_check()
        else:
            self.go({"setup": SETUP, "settings": SETTINGS, "activity": ACTIVITY}.get(name, HOME))

    def open_setup_for(self, target: Target) -> None:
        if target is Target.PLAY and Target.PLAY not in self.view.saved and self.page == HOME:
            self.show_onboarding(BUTTONS)
            return
        self.go(SETUP)
        self.setup.capture_target(target)

    def show_onboarding(self, step: int = 0, animate: bool = True) -> None:
        if self.view.active:
            self.toast("Stop the session before running setup.", "info")
            return
        self._onboarding_open = True
        self.onboarding.setGeometry(self.root.rect())
        self.onboarding.raise_()
        self.toasts.raise_()
        for widget in self.shell:
            widget.setEnabled(False)
        self.toasts.set_bottom(72)
        self.onboarding.start(step)
        if animate:
            motion.fade(self.onboarding, True)
        else:
            self.onboarding.show()

    def _close_onboarding(self) -> None:
        self._onboarding_open = False
        for widget in self.shell:
            widget.setEnabled(True)
        self.toasts.set_bottom(16)
        motion.fade(self.onboarding, False)

    def _escape(self) -> None:
        if self.dialog.is_open:
            self.dialog.cancel()
        elif not self.onboarding_open and self.page != HOME:
            self.go(HOME)

    def _shortcut(self, page: int) -> None:
        if not self.onboarding_open and not self.dialog.is_open:
            self.go(page)

    # First-time setup

    def _finish_onboarding(self) -> None:
        self.settings.onboarding_done = True
        self.settings.onboarding_step = 0
        self._schedule_save()
        log.info("First-time setup finished")
        self.go(HOME)
        ready = (
            "Loopter is ready"
            if Target.AGAIN in self.view.saved
            else "Loopter is ready · add Play Again any time"
        )
        self.toast(ready, "ok")
        self.home.focus_start()

    def _defer_onboarding(self) -> None:
        self._schedule_save()
        self.go(HOME)
        self.toast("Setup saved · finish any time from Home", "info")
        self.home.focus_start()

    def _onboarding_step(self, step: int) -> None:
        self.settings.onboarding_step = step
        self._schedule_save()

    def _recapture_in_onboarding(self, target: Target) -> None:
        self.captures[1].reset(target)
        self.onboarding.show_step(BUTTONS)

    # Session

    def _own_windows(self):
        """Loopter's window, so scans ignore it. Called on the GUI thread; the result runs on the worker."""
        if QGuiApplication.platformName() != "windows":
            return None
        hwnd = int(self.winId())
        return lambda: [rect] if (rect := win32.visible_window_rect(hwnd)) else []

    def start_session(self) -> None:
        if Target.PLAY not in self.view.saved:
            self.show_onboarding(max(self.settings.onboarding_step, BUTTONS))
            return
        self.controller.start()
        if self.controller.state is SessionState.RUNNING:
            auto = self.view.mode is Mode.INTERACTION
            self.toast("Auto click started" if auto else "Watching started", "ok")

    def stop_session(self) -> None:
        total = self.controller.elapsed()
        self.controller.stop()
        self.toast(f"Session ended · {short_clock(total)}", "info")

    def _on_state(self, state: SessionState) -> None:
        view = self.view
        view.session = state
        view.error = self.controller.last_error if state is SessionState.ERROR else ""
        if state is SessionState.RUNNING:
            view.emergency = False
            self._elapsed_timer.start()
        else:
            self._elapsed_timer.stop()
        if not view.active:
            view.screen = ""
            view.flash = ""
        view.elapsed = self.controller.elapsed()
        if state is SessionState.ERROR and self.page != ACTIVITY:
            self.tabs.set_flag(ACTIVITY, "error")
        self.render()

    def _on_stats(self, stats: SessionStats) -> None:
        self.view.stats = stats
        self.home.render(self.view)

    def _tick(self) -> None:
        self.view.elapsed = self.controller.elapsed()
        self.home.render(self.view)
        self._update_title()

    def _on_observed(self, observation: Observation) -> None:
        screen = observation.screen
        name = screen.label if screen is not Screen.UNKNOWN else ""
        if name == self.view.screen:
            return
        self.view.screen = name
        target = {Screen.LOBBY: Target.PLAY, Screen.RESULTS: Target.AGAIN}.get(screen)
        if target is not None and observation.match is not None:
            if self.view.mode is Mode.INTERACTION:
                self.view.flash = f"{target.label} is on screen. Clicking once it's safe."
            else:
                self.view.flash = f"{target.label} is on screen. Nothing is clicked."
            self._flash_timer.start()
            self.home.dot.blip()
        self.home.render(self.view)

    def _clear_flash(self) -> None:
        self.view.flash = ""
        self.home.render(self.view)

    def _on_record(self, timestamp: str, level: str, message: str) -> None:
        entry = self.activity.append(timestamp, level, message)
        if entry.kind in ("warn", "error") and self.page != ACTIVITY and self.tabs.flag(ACTIVITY) != "error":
            self.tabs.set_flag(ACTIVITY, entry.kind)
        if entry.kind == "click":
            self.home.dot.blip()

    # Modes

    def pick_mode(self, mode: Mode) -> None:
        if mode is self.view.mode or self.view.active:
            return
        if mode is Mode.INTERACTION:
            self.dialog.open(self.settings.emergency_hotkey)
            return
        self._set_mode(Mode.LIVE)
        self.toast("Watch only · nothing will be clicked", "info")

    def _auto_click_confirmed(self) -> None:
        self.view.emergency = False
        self._set_mode(Mode.INTERACTION)
        self.toast(f"Auto click is on · {self.settings.emergency_hotkey} stops it", "warn")
        self.home.modes.option(Mode.INTERACTION).setFocus(Qt.FocusReason.OtherFocusReason)

    def _auto_click_declined(self) -> None:
        log.info("Auto click was not turned on")
        self.home.modes.option(self.view.mode).setFocus(Qt.FocusReason.OtherFocusReason)

    def _set_mode(self, mode: Mode) -> None:
        self.settings.mode = mode
        self.view.mode = mode
        level = logging.WARNING if mode is Mode.INTERACTION else logging.INFO
        suffix = " (confirmed)" if mode is Mode.INTERACTION else ""
        log.log(level, "Mode set to %s%s", mode.label, suffix)
        self._schedule_save()
        self.render()

    # Buttons and checks

    def display(self) -> Display | None:
        return screenshot.display_for(self.settings.monitor, self.displays)

    def _on_saved(self, target: Target | Screen, card: CaptureCard) -> None:
        if isinstance(target, Target):
            self.view.checks.reset(target)  # a new picture has not been recognized yet
        self._templates_changed()
        if card is self.captures[0]:
            label = target.label if isinstance(target, Target) else f"{target.label} screen"
            self.toast(f"{label} saved", "ok")

    def _on_checked(self, outcome: CheckOutcome) -> None:
        for target, verdict in outcome.results.items():
            if target in self.view.saved:
                self.view.checks.statuses[target] = verdict
        self.render()

    def _templates_changed(self) -> None:
        self._schedule_save()
        self._refresh_saved()

    def _log_templates(self) -> None:
        groups, problems = self.library.load()
        for problem in problems:
            log.warning(problem)
        names = [f"{screen.label} · {t.name}" for screen, group in groups.items() for t in group]
        log.info("Loaded %d saved button(s): %s", len(names), ", ".join(names) or "none")

    # Settings

    def _update(self, **changes: object) -> None:
        for name, value in changes.items():
            setattr(self.settings, name, value)
        self._schedule_save()

    def _pick_display(self, number: int) -> None:
        if number == self.settings.monitor or self.view.active:
            return
        self.settings.monitor = number
        self._schedule_save()
        self.settings_page.set_displays(self.displays)
        self.onboarding.set_displays(self.displays, number)
        if not self.onboarding_open:
            self.toast(f"Using Display {number}", "ok")
        self.render()

    def _set_reduce_motion(self, reduced: bool) -> None:
        self.settings.reduce_motion = reduced
        motion.settings().set_user_preference(reduced)
        self._schedule_save()
        self.toast("Reduced motion on" if reduced else "Reduced motion off", "info")

    def _set_region(self, region: Region | None) -> None:
        self.settings.region = region
        log.info("Scan area %s", f"set to {region.describe()}" if region else "cleared")
        self.toast("Scan area set" if region else "Scanning the whole display", "ok")
        self._schedule_save()
        self.render()

    def _import_profile(self) -> None:
        file, _ = QFileDialog.getOpenFileName(
            self, "Import a button profile", "", f"Loopter profile ({PROFILE_FILE})"
        )
        if file:
            self.import_profile(Path(file))

    def import_profile(self, path: Path) -> None:
        try:
            added, problems = self.library.import_profile(path)
        except (TemplateError, OSError) as exc:
            log.error("Import failed: %s", exc)
            self.toast(f"Couldn't import: {exc}", "err")
            return
        for problem in problems:
            log.warning("Profile import: %s", problem)
        for entry in added:
            log.info("Imported the '%s' picture (%s)", entry.label, Path(entry.path).stem)
            if entry.button is not None:
                for target in Target:
                    if entry.button in target.buttons:
                        self.view.checks.reset(target)
        self._templates_changed()
        skipped = f" · {len(problems)} skipped" if problems else ""
        self.toast(f"Imported {len(added)} button(s){skipped}", "ok" if added and not problems else "warn")

    def _export_profile(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Export your buttons to an empty folder")
        if folder:
            self.export_profile(Path(folder))

    def export_profile(self, folder: Path) -> None:
        try:
            count = self.library.export_profile(folder)
        except (TemplateError, OSError) as exc:
            log.error("Profile export failed: %s", exc)
            self.toast(f"Export failed: {exc}", "err")
            return
        log.info("Exported %d button(s) to %s", count, folder)
        self.toast(f"Exported {count} button(s)", "ok")

    def _schedule_save(self) -> None:
        self._save_timer.start()

    def _save(self) -> None:
        try:
            save_settings(self.settings)
        except OSError as exc:
            log.error("Settings could not be saved: %s", exc)

    # Emergency stop

    def _register_hotkey(self, text: str) -> str:
        """Registers the shortcut and returns an error message, or "" on success."""
        try:
            self.hotkey.register(text)
        except HotkeyError as exc:
            log.error("Emergency stop shortcut unavailable: %s", exc)
            self.settings_page.show_hotkey_problem(str(exc))
            return str(exc)
        self.settings_page.show_hotkey_problem("")
        return ""

    def apply_hotkey(self, text: str) -> None:
        previous = self.settings.emergency_hotkey
        if text == previous:
            return
        error = self._register_hotkey(text)
        if not error:
            self._update(emergency_hotkey=text)
            self.view.hotkey = text
            log.info("Emergency stop shortcut set to %s", text)
            self.toast(f"Emergency stop is now {text}", "ok")
        else:
            self._register_hotkey(previous)
            self.settings_page.show_hotkey_problem(f"{error} Still using {previous}.")
            self.toast(f"{text} is unavailable · still using {previous}", "warn")
        self.render()

    def _on_hotkey_pressed(self) -> None:
        # Runs on the hotkey thread: disarm first so no click can slip through
        # before the UI thread handles the rest.
        self.guard.disarm()
        self.emergency_triggered.emit()

    def _on_emergency(self) -> None:
        was_active = self.view.active
        self.controller.emergency_stop()
        self.view.emergency = True
        if self.view.mode is Mode.INTERACTION:
            self._set_mode(Mode.LIVE)
        self.render()
        if was_active:
            self.toast("Emergency stop · clicks are off", "err")
        else:
            self.toast("Emergency stop · nothing was running", "info")

    # Displays

    def _watch_screen(self, screen, announce: bool = True) -> None:
        screen.geometryChanged.connect(lambda _g: self._display_timer.start())
        if announce:
            self._display_timer.start()

    def _on_displays_changed(self) -> None:
        log.info("Display configuration changed")
        self.displays = screenshot.list_displays()
        self.settings_page.set_displays(self.displays)
        self.onboarding.set_displays(self.displays, self.settings.monitor)
        self.render()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt override
        self.controller.shutdown()
        self.hotkey.unregister()
        self.settings.window_geometry = bytes(self.saveGeometry().toBase64()).decode()
        self._save_timer.stop()
        self._save()
        super().closeEvent(event)


def _tint_title_bar(hwnd: int) -> None:
    """Gives the native Windows 11 title bar the window's dark color (ignored elsewhere)."""
    if not win32.IS_WINDOWS or QGuiApplication.platformName() != "windows":
        return
    dark_mode, border_color, caption_color, text_color = 20, 34, 35, 36  # DWMWINDOWATTRIBUTE values

    def colorref(hex_color: str) -> ctypes.c_uint:
        r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
        return ctypes.c_uint(r | g << 8 | b << 16)

    try:
        dwm = ctypes.windll.dwmapi
        values = (
            (dark_mode, ctypes.c_uint(1)),
            (border_color, colorref(theme.BORDER)),
            (caption_color, colorref(theme.BG)),
            (text_color, colorref(theme.TEXT)),
        )
        for attribute, value in values:
            dwm.DwmSetWindowAttribute(
                ctypes.c_void_p(hwnd), attribute, ctypes.byref(value), ctypes.sizeof(value)
            )
    except (AttributeError, OSError):
        pass


def _open_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
