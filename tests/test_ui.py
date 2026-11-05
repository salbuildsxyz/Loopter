"""Main window flows driven through real widgets (offscreen, with fake screen and mouse)."""

import json

import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import QLabel

from loop import controller
from loop.capture import Region
from loop.config import Mode, Settings, TemplateEntry, load_settings, save_settings, settings_path
from loop.demo import SCREEN_SIZE, TEMPLATE_FILES, TEMPLATES_DIR
from loop.demo.scenario import DemoScenario
from loop.hotkey import GlobalHotkey
from loop.logging_setup import LogBridge
from loop.policy import Event, EventKind
from loop.screens import Button, Screen, buttons_for
from loop.state import SessionState
from loop.ui import activity_view, main_window, setup_view, theme
from loop.ui.interaction_dialog import InteractionDialog
from loop.ui.main_window import MainWindow
from tests.conftest import GAME_HWND, FakeDesktop

FAKE_MONITOR = Region(0, 0, *SCREEN_SIZE)


class FrameCapture:
    """A screen showing the demo scenario, whatever region is requested."""

    def __init__(self, scenario: DemoScenario) -> None:
        self.scenario = scenario

    def monitors(self):
        return [FAKE_MONITOR]

    def grab(self, region: Region) -> np.ndarray:
        frame = self.scenario.render()
        x, y = max(0, region.left - FAKE_MONITOR.left), max(0, region.top - FAKE_MONITOR.top)
        return frame[y : y + region.height, x : x + region.width].copy()

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


@pytest.fixture
def screen(scenario, monkeypatch):
    """Replaces every real screen access in the window with the demo scenario."""
    monkeypatch.setattr(setup_view, "ScreenCapture", lambda: FrameCapture(scenario))
    for module in (setup_view, main_window, controller):
        monkeypatch.setattr(module, "list_monitors", lambda: [FAKE_MONITOR])
    return FrameCapture(scenario)


def make_window(qtbot, screen, settings):
    win = MainWindow(settings, LogBridge(), QIcon())
    win.controller._capture_factory = lambda: screen
    win.guard._click = lambda x, y: pytest.fail(f"unexpected click at ({x}, {y})")
    win.guard._desktop = FakeDesktop(window=GAME_HWND, foreground=GAME_HWND)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    return win


@pytest.fixture
def window(qtbot, screen):
    win = make_window(qtbot, screen, Settings())
    yield win
    win.close()


def click(qtbot, widget):
    qtbot.mouseClick(widget, Qt.MouseButton.LeftButton)


def choose_mode(qtbot, window, mode):
    click(qtbot, window.session.modes.buttons[mode])


def add_user_template(window, tmp_path, screen=Screen.LOBBY):
    """Adds the demo's templates for a screen (Play and Ready for the lobby) as the user's own."""
    for (_, file), button in zip(TEMPLATE_FILES[screen], buttons_for(screen) or [None], strict=False):
        path = tmp_path / file
        path.write_bytes((TEMPLATES_DIR / file).read_bytes())
        window.settings.templates.append(TemplateEntry(str(path), screen, SCREEN_SIZE[1], button))
    window._templates_changed()


def test_compact_main_screen(window):
    s = window.session
    assert (window.width(), window.height()) == (theme.WINDOW_WIDTH, theme.WINDOW_HEIGHT)
    assert s.minimumSizeHint().height() <= window.stack.height()  # fits without scrolling
    assert s.start_button.isVisible() and s.start_button.isEnabled()
    assert not any(b.isVisible() for b in (s.pause_button, s.resume_button, s.stop_button))
    assert [b.text() for b in s.modes.buttons.values()] == ["Demo", "Monitor", "Interact"]
    assert s.modes.value() is Mode.DEMO and s.tag.text() == "Demo"
    assert s.pill.text() == "Idle" and s.timer.text() == "00:00:00"
    assert not window.guard.armed


def test_navigation_between_views(qtbot, window):
    click(qtbot, window.settings_button)
    assert window.stack.currentIndex() == 2 and window.tabs.value() == "settings"
    click(qtbot, window.tabs.buttons["activity"])
    assert window.settings_pages.currentWidget() is window.activity
    qtbot.keyClick(window, Qt.Key.Key_Escape)
    assert window.stack.currentIndex() == 0
    click(qtbot, window.session.profile)
    assert window.stack.currentIndex() == 1
    window.setup.done.emit()
    assert window.stack.currentIndex() == 0
    window.settings_view.setup_requested.emit()
    assert window.stack.currentIndex() == 1


def test_profile_line_shows_what_is_missing(window, tmp_path):
    assert "No button templates" in window.session.profile.text_label.full_text()
    add_user_template(window, tmp_path)
    assert window.session.profile.text_label.full_text().startswith("Play / Ready ready · Play Again")
    add_user_template(window, tmp_path, Screen.RESULTS)
    assert window.session.profile.text_label.full_text().startswith("Profile ready")
    chips = [chip.text() for chip in window.setup._chips.values()]
    assert chips == ["✓  Play", "✓  Ready", "✓  Play Again"]


def test_live_monitor_without_templates_reports_error(qtbot, window):
    choose_mode(qtbot, window, Mode.LIVE)
    assert window.session.tag.text() == "Read-only"
    assert window.session.actions.text() == "–"
    click(qtbot, window.session.start_button)
    assert window.controller.state is SessionState.ERROR
    assert window.session.pill.text() == "Error"
    assert "No usable templates" in window.session.detail.full_text()
    assert window.session.view_log.isVisible()
    assert window.settings_button.badge == theme.ERR
    click(qtbot, window.session.view_log)
    assert window.settings_pages.currentWidget() is window.activity
    assert window.settings_button.badge == ""


def test_live_monitor_runs_without_a_play_again_template(qtbot, window, tmp_path):
    add_user_template(window, tmp_path)  # lobby only
    choose_mode(qtbot, window, Mode.LIVE)
    click(qtbot, window.session.start_button)
    assert window.controller.state is SessionState.RUNNING
    qtbot.waitUntil(lambda: window.controller.stats.detections >= 1, timeout=5000)
    assert window.session.detections.text() == "1"
    click(qtbot, window.session.stop_button)
    assert window.controller.state is SessionState.STOPPED


def test_live_interaction_requires_confirmation(qtbot, monkeypatch, window):
    asked = []
    monkeypatch.setattr(
        main_window, "confirm_live_interaction", lambda parent, key: asked.append(key) or False
    )
    choose_mode(qtbot, window, Mode.INTERACTION)
    assert asked == ["Ctrl+Shift+F12"]
    assert window.settings.mode is Mode.DEMO
    assert window.session.modes.value() is Mode.DEMO

    monkeypatch.setattr(main_window, "confirm_live_interaction", lambda parent, key: True)
    choose_mode(qtbot, window, Mode.INTERACTION)
    assert window.settings.mode is Mode.INTERACTION
    assert window.session.tag.text() == "Real clicks"
    assert not window.guard.armed  # enabling the mode alone never arms clicks


def test_interaction_dialog_needs_the_risk_accepted(qtbot):
    dialog = InteractionDialog(None, "Ctrl+Alt+F9")
    qtbot.addWidget(dialog)
    assert not dialog.confirm.isEnabled()
    dialog.accept_risk.setChecked(True)
    assert dialog.confirm.isEnabled()
    texts = " ".join(label.text() for label in dialog.findChildren(QLabel))
    assert "Ctrl+Alt+F9 stops everything" in texts


def test_live_interaction_is_not_restored_at_startup(qtbot, screen):
    save_settings(Settings(mode=Mode.INTERACTION))
    win = MainWindow(load_settings(), LogBridge(), QIcon())
    qtbot.addWidget(win)
    assert win.settings.mode is Mode.LIVE
    assert win.session.modes.value() is Mode.LIVE
    win.close()


def test_demo_session_through_buttons(qtbot, window):
    s = window.session
    click(qtbot, s.start_button)
    qtbot.waitUntil(lambda: window.controller.state is SessionState.RUNNING, timeout=3000)
    qtbot.waitUntil(lambda: window.controller.stats.detections >= 1, timeout=5000)
    assert s.pill.text() == "Running"
    qtbot.waitUntil(
        lambda: "Lobby" in s.detail.full_text() or "Matchmaking" in s.detail.full_text(), timeout=3000
    )
    qtbot.waitUntil(lambda: s.timer.text() != "00:00:00", timeout=3000)
    assert not s.start_button.isVisible() and s.pause_button.isVisible() and s.stop_button.isVisible()
    assert not s.modes.isEnabled()
    assert not window.settings_view.cooldown.isEnabled()

    click(qtbot, s.pause_button)
    assert window.controller.state is SessionState.PAUSED
    assert s.pill.text() == "Paused" and s.resume_button.isVisible() and not s.pause_button.isVisible()
    paused_at = s.timer.text()
    qtbot.wait(1200)
    assert s.timer.text() == paused_at
    click(qtbot, s.resume_button)
    assert window.controller.state is SessionState.RUNNING
    click(qtbot, s.stop_button)
    assert window.controller.state is SessionState.STOPPED
    assert s.pill.text() == "Stopped" and s.start_button.isVisible()
    assert window.settings_view.cooldown.isEnabled() and s.modes.isEnabled()
    assert not window.guard.armed


def test_live_interaction_session_and_emergency_stop(qtbot, monkeypatch, tmp_path, window, scenario):
    clicks = []
    window.guard._click = lambda x, y: clicks.append((x, y)) or scenario.press(x, y)
    monkeypatch.setattr(main_window, "confirm_live_interaction", lambda parent, key: True)
    add_user_template(window, tmp_path)
    window.settings.region = FAKE_MONITOR
    choose_mode(qtbot, window, Mode.INTERACTION)
    click(qtbot, window.session.start_button)
    assert window.controller.state is SessionState.RUNNING
    assert window.guard.armed
    qtbot.waitUntil(lambda: window.controller.stats.interactions >= 1, timeout=5000)
    assert clicks
    assert window.session.actions.text() == str(window.controller.stats.interactions)

    window._on_hotkey_pressed()  # what the hotkey thread calls
    assert not window.guard.armed
    qtbot.waitUntil(lambda: window.controller.state is SessionState.STOPPED, timeout=2000)
    assert window.settings.mode is Mode.LIVE  # must be confirmed again
    assert window.guard.target is None
    assert "Emergency stop" in window.session.detail.full_text()


def test_closing_during_a_session_stops_it(qtbot, screen):
    win = make_window(qtbot, screen, Settings())
    click(qtbot, win.session.start_button)
    qtbot.waitUntil(lambda: win.controller.state is SessionState.RUNNING, timeout=3000)
    win.close()
    assert not win.guard.armed
    assert win.controller._worker is None  # stopped and waited for


def test_settings_are_persisted(qtbot, window):
    v = window.settings_view
    v.threshold.setValue(0.9)
    v.interval.setValue(1500)
    v.cooldown.setValue(5.5)
    click(qtbot, v.press_again)
    click(qtbot, v.demo_clicks)
    qtbot.waitUntil(lambda: settings_path().exists(), timeout=3000)
    qtbot.wait(500)
    data = json.loads(settings_path().read_text())
    assert data["threshold"] == pytest.approx(0.9)
    assert v.slider.value() == 90
    assert data["scan_interval_ms"] == 1500
    assert data["cooldown_s"] == 5.5
    assert data["actions"] == ["lobby"]
    assert data["demo_clicks_enabled"] is True


def test_saved_settings_are_shown_and_not_reset(qtbot, screen):
    saved = Settings(threshold=0.92, scan_interval_ms=2000, cooldown_s=4.0, actions={Screen.RESULTS})
    win = make_window(qtbot, screen, saved)
    v = win.settings_view
    assert (v.threshold.value(), v.slider.value(), v.interval.value(), v.cooldown.value()) == (
        0.92,
        92,
        2000,
        4.0,
    )
    assert not v.press_play.isChecked() and v.press_again.isChecked()
    assert (saved.threshold, saved.scan_interval_ms, saved.cooldown_s) == (0.92, 2000, 4.0)
    assert saved.actions == {Screen.RESULTS}
    win.close()


def drag(qtbot, canvas, start, end):
    qtbot.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseMove(canvas, end)
    qtbot.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)


def test_manual_selection_save_and_test(qtbot, window, scenario):
    setup = window.setup
    window.show_setup()
    click(qtbot, setup.manual)  # select by hand instead of using suggestions
    setup._finish_capture(FAKE_MONITOR)
    assert setup.step == 2 and setup.canvas.selection is None and not setup.find_button.isVisible()

    canvas = setup.canvas
    button = scenario.button_box
    start = canvas._to_widget(Region(button.left, button.top, 1, 1)).topLeft().toPoint()
    end = canvas._to_widget(Region(button.right, button.bottom, 1, 1)).topLeft().toPoint()
    drag(qtbot, canvas, start, end)
    assert abs(canvas.selection.width - button.width) <= 3

    click(qtbot, setup.next_button)
    assert setup.step == 3 and not setup.preview.pixmap().isNull()
    click(qtbot, setup.next_button)
    setup.select_target(Screen.LOBBY, Button(scenario.button_name.lower()))
    click(qtbot, setup.next_button)
    click(qtbot, setup.save_button)
    assert len(window.settings.templates) == 1
    entry = window.settings.templates[0]
    assert (entry.screen, entry.source_height) == (Screen.LOBBY, FAKE_MONITOR.height)
    assert window.settings_view.templates.count() == 1

    click(qtbot, setup.next_button)
    click(qtbot, setup.test_button)
    assert "Recognized 'Lobby'" in setup.result.text.text()
    assert setup.meter.heading.text().startswith("Recognized · Lobby")

    outside = QPoint(start.x() - 30, start.y() - 30), QPoint(end.x() + 30, end.y() + 30)
    drag(qtbot, canvas, *outside)
    click(qtbot, setup.use_region_button)
    assert window.settings.region.contains(button)
    assert not window.settings_view.clear_region.isHidden()
    click(qtbot, setup.next_button)  # Done
    assert window.stack.currentIndex() == 0


def test_guided_setup_finds_both_buttons(qtbot, window, scenario):
    """Capture the lobby and the results, accept each suggestion, and recognition works."""
    setup = window.setup
    assert [chip.property("done") for chip in setup._chips.values()] == [False, False, False]
    for screen in (Screen.LOBBY, Screen.RESULTS):
        scenario.show(screen.value)
        setup._finish_capture(FAKE_MONITOR)  # finds the most likely button straight away
        assert setup.selected_target[0] is screen  # the first screen still missing a template
        selection, button = setup.canvas.selection, scenario.button_box
        assert button.contains(selection) and selection.width >= button.width - 6
        click(qtbot, setup.save_button)

    assert [e.screen for e in window.settings.templates] == [Screen.LOBBY, Screen.RESULTS]
    click(qtbot, setup.test_button)
    assert "Recognized 'Results'" in setup.result.text.text()
    recognized = [box for box, _, color in setup.canvas._marks if color == theme.OK]
    assert len(recognized) == 1 and scenario.button_box.contains(recognized[0])


def test_find_buttons_on_a_waiting_screen_asks_for_a_manual_selection(window, scenario):
    setup = window.setup
    scenario.show("matchmaking")
    setup._finish_capture(FAKE_MONITOR)
    assert setup.canvas.selection is None
    assert "select it yourself" in setup.result.text.text()
    assert not setup.next_button.isEnabled()


def test_waiting_screen_templates_are_optional(qtbot, window, scenario):
    setup = window.setup
    scenario.show("matchmaking")
    setup._finish_capture(FAKE_MONITOR)
    setup.canvas.select(Region(0, 0, SCREEN_SIZE[0], SCREEN_SIZE[1] // 2))
    setup.select_target(Screen.MATCHMAKING)
    assert setup.kind.value() is None
    click(qtbot, setup.save_button)
    assert window.settings.templates, setup.result.text.text()
    assert window.settings.templates[-1].screen is Screen.MATCHMAKING


def test_actions_filter_matches_controller_messages():
    clicked = Event(EventKind.CLICKED, Screen.LOBBY, point=(10, 20), target="Play")
    verified = Event(EventKind.VERIFIED, Screen.LOBBY, other=Screen.MATCHMAKING)
    changed = Event(EventKind.SCREEN_CHANGED, Screen.LOBBY, other=Screen.UNKNOWN, confidence=0.9)
    action = activity_view.FILTERS["action"]
    assert action("INFO", controller.describe_event(clicked)[1])
    assert action("INFO", controller.describe_event(verified)[1])
    assert not action("INFO", controller.describe_event(changed)[1])


def test_activity_filters_copy_and_clear(qtbot, window):
    activity = window.activity
    activity.clear()
    activity.append("10:00:00", "INFO", "Screen: Unknown → Lobby (0.980)")
    activity.append("10:00:01", "INFO", "Clicked 'Play' at (10, 20)")
    activity.append("10:00:02", "WARNING", "Unexpected screen change")
    activity.append("10:00:03", "ERROR", "Capture failed")
    assert len(activity.text().splitlines()) == 4
    click(qtbot, activity.filters.buttons["action"])
    assert activity.text() == "10:00:01  INFO   Clicked 'Play' at (10, 20)"
    assert "Clicked" in activity.view.toPlainText() and "Capture" not in activity.view.toPlainText()
    click(qtbot, activity.filters.buttons["error"])
    activity.copy()
    assert QGuiApplication.clipboard().text() == "10:00:03  ERROR  Capture failed"
    activity.clear()
    assert activity.text() == "" and activity.view.toPlainText() == ""


def test_warnings_mark_the_settings_button_until_seen(window):
    window.show_main()
    window._on_record("10:00:00", "INFO", "fine")
    assert window.settings_button.badge == ""
    window._on_record("10:00:01", "WARNING", "careful")
    assert window.settings_button.badge == theme.WARN
    window.show_activity()
    assert window.settings_button.badge == ""


def test_rejected_hotkey_keeps_previous(window):
    # Start from a combination nothing else uses (a running copy of LOOP may hold the default).
    previous = "Ctrl+Alt+Shift+F20"
    window._apply_hotkey(previous)
    blocker = GlobalHotkey(lambda: None)
    blocker.register("Ctrl+Alt+Shift+F21")
    try:
        window._apply_hotkey("Ctrl+Alt+Shift+F21")
    finally:
        blocker.unregister()
    assert window.settings.emergency_hotkey == previous
    status = window.settings_view.hotkey_row.help.text()
    assert "could not be registered" in status and f"Still using {previous}" in status
