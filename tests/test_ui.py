"""The interface, driven like a user would, against the simulated game.

The screen is the simulation and every click goes to a fake mouse, so nothing here
touches the real desktop or sends real input.
"""

import json
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication, QScrollArea

from loop import controller
from loop.capture import Region
from loop.config import Mode, Settings, TemplateEntry, load_settings, save_settings, settings_path
from loop.hotkey import GlobalHotkey
from loop.logging_setup import LogBridge
from loop.policy import Event, EventKind
from loop.screens import Button, Screen, buttons_for
from loop.state import SessionState
from loop.ui import motion, screenshot, theme
from loop.ui.capture_card import box_problem
from loop.ui.controls import Switch
from loop.ui.home import home_status
from loop.ui.main_window import ACTIVITY, HOME, SETTINGS, SETUP, MainWindow
from loop.ui.model import FILTERS, Check, Target, ViewState, classify, make_entry
from loop.ui.onboarding import BUTTONS, CHECK, DISPLAY, DONE, WELCOME
from loop.ui.screenshot import Display
from loop.ui.widgets import CountLabel
from tests.conftest import GAME_HWND, FakeDesktop
from tests.simulation import SCREEN_SIZE, TEMPLATE_FILES, TEMPLATES_DIR
from tests.simulation.scenario import DemoScenario

FAKE_MONITOR = Region(0, 0, *SCREEN_SIZE)
FAKE_DISPLAY = Display(1, FAKE_MONITOR)


class FrameCapture:
    """A screen showing the simulation, whatever region is requested."""

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


@pytest.fixture(autouse=True)
def full_motion():
    """Each test starts with animations on (unless Windows turns them off) and leaves them that way."""
    motion.settings().set_user_preference(False)
    yield
    motion.settings().set_user_preference(False)


@pytest.fixture
def screen(scenario, monkeypatch):
    """Replaces every real screen access in the window with the simulation."""
    monkeypatch.setattr(screenshot, "ScreenCapture", lambda: FrameCapture(scenario))
    for module in (screenshot, controller):
        monkeypatch.setattr(module, "list_monitors", lambda: [FAKE_MONITOR])
    return FrameCapture(scenario)


def make_window(qtbot, screen, settings):
    win = MainWindow(settings, LogBridge(), QIcon())
    win.controller._capture_factory = lambda: screen
    win.guard._click = lambda x, y: pytest.fail(f"unexpected click at ({x}, {y})")
    win.guard._desktop = FakeDesktop(window=GAME_HWND, foreground=GAME_HWND)
    # The simulated screen is not where the real window is, so don't mask the window out of it.
    win._own_windows = lambda: None
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    return win


@pytest.fixture
def window(qtbot, screen):
    """A returning user's window: first-time setup is done, no buttons saved yet."""
    win = make_window(qtbot, screen, Settings(onboarding_done=True))
    yield win
    win.close()


@pytest.fixture
def fresh(qtbot, screen):
    """A first launch."""
    win = make_window(qtbot, screen, Settings())
    yield win
    win.close()


def click(qtbot, widget):
    qtbot.mouseClick(widget, Qt.MouseButton.LeftButton)


def add_user_template(window, tmp_path, screen=Screen.LOBBY):
    """Adds the simulation's templates for a screen (Play and Ready for the lobby) as the user's own."""
    for (_, file), button in zip(TEMPLATE_FILES[screen], buttons_for(screen) or [None], strict=False):
        path = tmp_path / file
        path.write_bytes((TEMPLATES_DIR / file).read_bytes())
        window.settings.templates.append(TemplateEntry(str(path), screen, SCREEN_SIZE[1], button))
    window._templates_changed()


def show_screenshot(card, scenario, name):
    """What the capture card receives after hiding the window and taking a screenshot."""
    scenario.show(name)
    card._captured(FrameCapture(scenario).grab(FAKE_MONITOR), "", FAKE_DISPLAY)


def check_screen(card, scenario, name):
    scenario.show(name)
    card._evaluate(FrameCapture(scenario).grab(FAKE_MONITOR), "", FAKE_DISPLAY)


def drag(qtbot, widget, start, end):
    qtbot.mousePress(widget, Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseMove(widget, end)
    qtbot.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=end)


def texts(widget) -> str:
    from PySide6.QtWidgets import QAbstractButton, QLabel

    found = [w.text() for w in widget.findChildren(QLabel)]
    found += [w.text() for w in widget.findChildren(QAbstractButton)]
    found += [w.accessibleName() for w in widget.findChildren(QAbstractButton)]
    return " ".join(found)


# First launch and first-time setup


def test_first_launch_opens_setup_at_welcome(fresh):
    o = fresh.onboarding
    assert fresh.onboarding_open and o.step == WELCOME
    assert o.start_button.isVisible() and not o.footer.isVisible()
    assert o.step_label.text() == "Step 1 of 5 · Welcome"
    available = fresh.screen().availableGeometry().height() - 48
    expected = max(theme.MIN_HEIGHT, min(theme.WINDOW_HEIGHT, available))  # small screens get less
    assert fresh.centralWidget().width() == theme.WINDOW_WIDTH
    assert abs(fresh.centralWidget().height() - expected) <= 6  # the native frame rounds at some scales
    assert fresh.windowTitle() == "Loopter"


def test_onboarding_end_to_end(qtbot, fresh, scenario):
    o = fresh.onboarding
    click(qtbot, o.start_button)
    assert o.step == DISPLAY and o.stepper.step == 1
    assert [c.display.number for c in o.display_cards] == [1] and o.display_cards[0].isChecked()
    click(qtbot, o.next_button)

    assert o.step == BUTTONS
    assert not o.next_button.isEnabled() and o.note.text() == "Save Play to continue"
    capture = o.capture
    assert capture.target is Target.PLAY and capture.phase == "prepare"
    show_screenshot(capture, scenario, "lobby")
    assert capture.phase == "confirm" and capture.shot.box is not None  # a suggestion is boxed
    assert capture.shot.tag == "Suggested" and capture.save_button.isEnabled()
    click(qtbot, capture.save_button)
    assert capture.phase == "saved" and capture.shot.mode == "saved"
    assert o.chips[Target.PLAY].done and o.next_button.isEnabled()
    assert o.note.text() == "Play Again can wait"
    assert capture.next_panel.isVisible() and capture.next_panel.button.text() == "Capture Play Again"
    assert fresh.view.checks[Target.PLAY] is Check.UNCHECKED  # saved is not the same as working

    click(qtbot, capture.next_panel.button)
    assert capture.target is Target.AGAIN and capture.phase == "prepare"
    show_screenshot(capture, scenario, "results")
    click(qtbot, capture.save_button)
    assert {e.button for e in fresh.settings.templates} >= {Button.PLAY_AGAIN}
    click(qtbot, o.next_button)

    assert o.step == CHECK
    check = o.check
    assert [r.state.label for r in check.rows.values()] == ["Not checked", "Not checked"]
    assert o.skip_button.isVisible() and not o.next_button.isEnabled()
    check_screen(check, scenario, "results")
    assert fresh.view.checks[Target.AGAIN] is Check.WORKING
    assert fresh.view.checks[Target.PLAY] is Check.UNCHECKED  # not on screen, so not claimed
    assert "Play Again works" in check.notice.message.text()
    assert o.next_button.isEnabled() and not o.skip_button.isVisible()
    click(qtbot, o.next_button)

    assert o.step == DONE and o.next_button.text() == "Open dashboard"
    assert o.summary_values["Play Again"].label == "Working"
    assert o.summary_values["Play / Ready"].label == "Not checked"
    assert "Not checked" in o.finish_lede.text()
    click(qtbot, o.next_button)
    assert not fresh.onboarding_open and fresh.page == HOME
    assert fresh.settings.onboarding_done
    assert fresh.toasts.messages()[-1] == "Loopter is ready"
    qtbot.waitUntil(lambda: settings_path().exists(), timeout=3000)
    assert json.loads(settings_path().read_text())["onboarding_done"] is True


def test_capture_hides_the_window_while_taking_the_screenshot(qtbot, fresh, scenario):
    o = fresh.onboarding
    o.show_step(BUTTONS)
    scenario.show("lobby")
    click(qtbot, o.capture.capture_button)
    assert o.capture.phase == "loading"
    qtbot.waitUntil(lambda: not fresh.isVisible(), timeout=1000)
    qtbot.waitUntil(lambda: fresh.isVisible() and o.capture.frame is not None, timeout=3000)
    assert o.capture.phase == "confirm" and o.capture.shot.box is not None


def test_a_failed_screenshot_explains_and_offers_retry(qtbot, fresh):
    o = fresh.onboarding
    o.show_step(BUTTONS)
    o.capture._captured(None, "Screen capture failed. The desktop may be locked.", FAKE_DISPLAY)
    assert o.capture.phase == "failed" and o.capture.failed.isVisible()
    assert "desktop may be locked" in o.capture.failed.message.text()
    buttons = [o.capture.failed.actions.itemAt(i).widget() for i in range(o.capture.failed.actions.count())]
    choose = next(b for b in buttons if b is not None and b.text() == "Choose another display")
    click(qtbot, choose)
    assert o.step == DISPLAY


def test_onboarding_progress_is_saved_and_reopened(qtbot, screen):
    win = make_window(qtbot, screen, Settings())
    click(qtbot, win.onboarding.start_button)
    click(qtbot, win.onboarding.next_button)
    assert win.settings.onboarding_step == BUTTONS
    win.close()

    again = make_window(qtbot, screen, load_settings())
    assert again.onboarding_open and again.onboarding.step == BUTTONS
    again.close()


def test_finish_later_goes_home_and_setup_can_continue(qtbot, fresh):
    click(qtbot, fresh.onboarding.later_button)
    qtbot.waitUntil(lambda: not fresh.onboarding.isVisible(), timeout=2000)
    assert fresh.page == HOME and not fresh.settings.onboarding_done
    h = fresh.home
    assert h.title.text() == "Needs setup" and h.start_button.text() == "Finish setup"
    assert fresh.toasts.messages()[-1] == "Setup saved · finish any time from Home"
    click(qtbot, h.start_button)
    assert fresh.onboarding_open and fresh.onboarding.step == BUTTONS


def test_skip_check_goes_to_the_summary(qtbot, fresh, tmp_path):
    add_user_template(fresh, tmp_path)
    o = fresh.onboarding
    o.show_step(CHECK)
    assert o.note.text() == "Check now, or skip it"
    click(qtbot, o.skip_button)
    assert o.step == DONE
    assert o.summary_values["Play / Ready"].label == "Not checked"
    assert o.summary_values["Play Again"].label == "Add later in Setup"


def test_returning_users_with_buttons_skip_onboarding(qtbot, screen, tmp_path):
    path = tmp_path / "play.png"
    path.write_bytes((TEMPLATES_DIR / "play.png").read_bytes())
    settings = Settings(templates=[TemplateEntry(str(path), Screen.LOBBY, SCREEN_SIZE[1], Button.PLAY)])
    win = make_window(qtbot, screen, settings)
    assert win.page == HOME and not win.onboarding_open
    assert win.view.checks[Target.PLAY] is Check.UNCHECKED  # never "Working" until checked again
    win.close()


def test_setup_can_be_reopened(qtbot, window):
    window.go(SETUP)
    window.setup.onboarding_requested.emit()
    assert window.onboarding_open and window.onboarding.step == WELCOME
    window.onboarding.deferred.emit()
    window.go(SETTINGS)
    window.settings_page.onboarding_requested.emit()
    assert window.onboarding_open


# No demo or sample content


def test_no_demo_or_sample_content(fresh):
    assert [o.value for o in fresh.home.modes.options] == [Mode.LIVE, Mode.INTERACTION]
    assert [o.text() for o in fresh.home.modes.options] == ["Watch only", "Auto click"]
    for widget in (fresh, fresh.onboarding):
        content = texts(widget).lower()
        assert "demo" not in content and "simulat" not in content
    h = fresh.home
    assert (h.duration.text(), h.actions.text(), h.screens.text()) == ("00:00:00", "0", "0")
    assert fresh.activity.items == []
    assert "Working" not in texts(fresh)


def test_a_saved_demo_mode_opens_as_watch_only(qtbot, screen):
    save_settings(Settings(onboarding_done=True))
    data = json.loads(settings_path().read_text())
    data["mode"] = "demo"
    settings_path().write_text(json.dumps(data))
    win = make_window(qtbot, screen, load_settings())
    assert win.settings.mode is Mode.LIVE and win.home.modes.value() is Mode.LIVE
    win.close()


# Home and navigation


def test_home_essentials(window):
    h = window.home
    assert window.page == HOME
    assert h.start_button.isVisible() and not h.stop_button.isVisible()
    assert h.modes.value() is Mode.LIVE and h.mode_tag.text() == "Watch only"
    assert h.dot.tone == "setup" and h.title.text() == "Needs setup"
    assert h.mode_help.text() == "Recognizes your buttons. Never clicks."
    assert [r.state.label for r in h.button_rows.values()] == ["Not set up", "Not set up"]
    assert h.hotkey_caps.accessibleName() == "Ctrl+Shift+F12"
    assert window.tabs.flag(SETUP) == "warn"
    assert not window.guard.armed


def test_navigation_between_pages(qtbot, window):
    tabs = window.tabs
    click(qtbot, tabs.tabs[SETTINGS])
    assert window.page == SETTINGS and tabs.current == SETTINGS
    click(qtbot, tabs.tabs[ACTIVITY])
    assert window.page == ACTIVITY
    qtbot.keyClick(window, Qt.Key.Key_Escape)
    assert window.page == HOME and tabs.current == HOME
    click(qtbot, window.home.manage)
    assert window.page == SETUP
    qtbot.keyClick(window, Qt.Key.Key_4, Qt.KeyboardModifier.ControlModifier)
    assert window.page == SETTINGS
    tabs.tabs[SETTINGS].setFocus()
    qtbot.keyClick(tabs.tabs[SETTINGS], Qt.Key.Key_Home)
    assert window.page == HOME
    qtbot.keyClick(QApplication.focusWidget(), Qt.Key.Key_Right)
    assert window.page == SETUP


def test_tab_underline_slides_to_the_selected_tab(qtbot, window):
    if motion.reduced():
        pytest.skip("Windows animation effects are turned off on this machine")
    tabs = window.tabs
    window.go(SETTINGS)
    assert tabs._travel.running
    target = tabs._indicator_for(SETTINGS)
    qtbot.waitUntil(lambda: tabs._indicator() == target, timeout=2000)


def test_page_transitions_animate_and_clean_up(qtbot, window):
    if motion.reduced():
        pytest.skip("Windows animation effects are turned off on this machine")
    window.go(SETTINGS)
    page = window.stack.currentWidget()
    assert page.graphicsEffect() is not None  # fading in
    qtbot.waitUntil(lambda: page.graphicsEffect() is None, timeout=2000)
    assert page.pos() == QPoint(0, 0)


def test_reduce_motion_setting(qtbot, window):
    window.go(SETTINGS, animate=False)
    v = window.settings_page
    click(qtbot, v.reduce_motion)
    assert window.settings.reduce_motion and motion.reduced()
    window.go(ACTIVITY)
    assert window.stack.currentWidget().graphicsEffect() is None  # no transition
    count = CountLabel()
    count.set_value(7)
    assert count.text() == "7"  # no counting animation
    dot = window.home.dot
    dot.set_tone("watch")
    assert not dot.pulsing  # looping effects stop
    click(qtbot, v.reduce_motion)
    assert not window.settings.reduce_motion


def test_buttons_and_callouts_follow_what_is_saved(window, tmp_path):
    add_user_template(window, tmp_path)
    h = window.home
    assert h.title.text() == "Ready" and h.dot.tone == "ready"
    assert h.button_rows[Target.PLAY].state.label == "Not checked"
    assert not h.button_rows[Target.PLAY].action.isVisible()
    assert h.callout.isVisible() and h.callout.action.text() == "Add Play Again"
    add_user_template(window, tmp_path, Screen.RESULTS)
    assert h.callout.action.text() == "Check now"
    assert window.tabs.flag(SETUP) == ""


def test_problems_explain_themselves_and_offer_a_fix(qtbot, window, tmp_path):
    add_user_template(window, tmp_path)
    window.settings.region = Region(10**6, 0, 200, 200)  # a display that went away
    click(qtbot, window.home.start_button)
    h = window.home
    assert window.controller.state is SessionState.ERROR
    assert h.title.text() == "Needs attention" and h.dot.tone == "error"
    assert "not fully inside a connected display" in h.description.text()
    assert h.callout.action.text() == "Open Settings"
    assert window.tabs.flag(ACTIVITY) == "error"
    click(qtbot, h.callout.action)
    assert window.page == SETTINGS
    click(qtbot, window.tabs.tabs[ACTIVITY])
    assert window.tabs.flag(ACTIVITY) == ""


def test_watch_only_session(qtbot, window, tmp_path, scenario):
    add_user_template(window, tmp_path)  # lobby only
    h = window.home
    assert h.start_button.text() == "Start watching"
    click(qtbot, h.start_button)
    assert window.controller.state is SessionState.RUNNING
    assert h.title.text() == "Watching" and h.dot.tone == "watch"
    assert window.toasts.messages()[-1] == "Watching started"
    qtbot.waitUntil(lambda: window.controller.stats.detections >= 1, timeout=5000)
    qtbot.waitUntil(lambda: h.screens.text() == "1", timeout=2000)  # counts up from real stats
    qtbot.waitUntil(lambda: h.screen_name.text() == "Lobby", timeout=3000)
    assert "is on screen. Nothing is clicked." in h.description.text()
    assert h.actions.text() == "0"  # Watch only never clicks
    assert not h.start_button.isVisible() and h.pause_button.isVisible() and h.stop_button.isVisible()
    assert not h.modes.options[0].isEnabled() and h.mode_help.text() == "Stop the session to change mode."
    assert not window.settings_page.cooldown.isEnabled()
    assert window.windowTitle().startswith("Loopter · Watching · ")

    click(qtbot, h.pause_button)
    assert window.controller.state is SessionState.PAUSED and h.title.text() == "Paused"
    paused_at = h.duration.text()
    qtbot.wait(1200)
    assert h.duration.text() == paused_at
    assert h.pause_button.text() == "Resume"
    click(qtbot, h.pause_button)
    assert window.controller.state is SessionState.RUNNING
    click(qtbot, h.stop_button)
    assert window.controller.state is SessionState.STOPPED
    assert h.title.text() == "Ready" and window.toasts.messages()[-1].startswith("Session ended · ")
    assert h.start_button.isVisible() and h.modes.options[1].isEnabled()
    assert window.settings_page.cooldown.isEnabled() and not window.guard.armed


def test_auto_click_requires_confirmation(qtbot, window):
    h = window.home
    click(qtbot, h.modes.option(Mode.INTERACTION))
    dialog = window.dialog
    assert dialog.is_open and window.settings.mode is Mode.LIVE
    assert dialog.cancel_button.hasFocus() and not dialog.confirm_button.isEnabled()
    assert dialog.keys.accessibleName() == "Ctrl+Shift+F12"
    click(qtbot, dialog.confirm_button)  # disabled until the risk is accepted
    assert window.settings.mode is Mode.LIVE
    qtbot.keyClick(dialog.cancel_button, Qt.Key.Key_Escape)
    assert not dialog.is_open and window.settings.mode is Mode.LIVE and h.modes.value() is Mode.LIVE

    click(qtbot, h.modes.option(Mode.INTERACTION))
    click(qtbot, dialog.accept_box)
    assert dialog.confirm_button.isEnabled()
    click(qtbot, dialog.confirm_button)
    assert window.settings.mode is Mode.INTERACTION and h.mode_tag.text() == "Auto click"
    assert window.toasts.messages()[-1].startswith("Auto click is on")
    assert not window.guard.armed  # choosing the mode alone never arms clicks


def test_auto_click_dialog_keeps_focus_inside(qtbot, window):
    dialog = window.dialog
    dialog.open("Ctrl+Shift+F12")
    reached = set()
    for _ in range(6):
        qtbot.keyClick(QApplication.focusWidget(), Qt.Key.Key_Tab)
        reached.add(QApplication.focusWidget())
    assert reached <= {dialog.accept_box, dialog.cancel_button, dialog.confirm_button}
    qtbot.mouseClick(dialog, Qt.MouseButton.LeftButton, pos=QPoint(2, 2))  # the scrim cancels
    assert not dialog.is_open


def test_auto_click_is_not_restored_at_startup(qtbot, screen):
    save_settings(Settings(mode=Mode.INTERACTION, onboarding_done=True))
    win = make_window(qtbot, screen, load_settings())
    assert win.settings.mode is Mode.LIVE and win.home.modes.value() is Mode.LIVE
    win.close()


def test_auto_click_session_and_emergency_stop(qtbot, tmp_path, window, scenario):
    clicks = []
    window.guard._click = lambda x, y: clicks.append((x, y)) or scenario.press(x, y)
    add_user_template(window, tmp_path)
    window.settings.region = FAKE_MONITOR
    window.dialog.accepted.emit()  # what confirming the dialog does
    h = window.home
    assert h.start_button.text() == "Start auto click" and h.start_button.variant == "accent"
    click(qtbot, h.start_button)
    assert window.controller.state is SessionState.RUNNING and window.guard.armed
    assert h.title.text() == "Auto clicking" and h.dot.tone == "auto"
    qtbot.waitUntil(lambda: window.controller.stats.interactions >= 1, timeout=5000)
    assert clicks
    qtbot.waitUntil(lambda: h.actions.text() == str(window.controller.stats.interactions), timeout=2000)

    window._on_hotkey_pressed()  # what the hotkey thread calls
    assert not window.guard.armed
    qtbot.waitUntil(lambda: window.controller.state is SessionState.STOPPED, timeout=2000)
    assert window.settings.mode is Mode.LIVE  # must be confirmed again
    assert window.guard.target is None
    assert h.title.text() == "Stopped" and "Emergency stop pressed" in h.description.text()
    assert window.toasts.messages()[-1] == "Emergency stop · clicks are off"


def test_emergency_stop_with_nothing_running(qtbot, window):
    window._on_hotkey_pressed()
    qtbot.waitUntil(lambda: bool(window.toasts.messages()), timeout=2000)
    assert window.toasts.messages()[-1] == "Emergency stop · nothing was running"
    assert not window.guard.armed


def test_closing_during_a_session_stops_it(qtbot, screen, tmp_path):
    win = make_window(qtbot, screen, Settings(onboarding_done=True))
    add_user_template(win, tmp_path)
    click(qtbot, win.home.start_button)
    qtbot.waitUntil(lambda: win.controller.state is SessionState.RUNNING, timeout=3000)
    win.close()
    assert not win.guard.armed
    assert win.controller._worker is None  # stopped and waited for


def test_live_dot_motion_runs_only_while_watching(qtbot, window, tmp_path):
    if motion.reduced():
        pytest.skip("Windows animation effects are turned off on this machine")
    add_user_template(window, tmp_path)
    dot = window.home.dot
    assert not dot.pulsing  # nothing moves while idle
    click(qtbot, window.home.start_button)
    assert dot.pulsing and not dot.orbiting
    window.home.set_ambient_allowed(False)  # minimized
    assert not dot.pulsing
    window.home.set_ambient_allowed(True)
    assert dot.pulsing
    click(qtbot, window.home.stop_button)
    assert not dot.pulsing


def test_keyboard_reaches_the_main_controls(qtbot, window, tmp_path):
    add_user_template(window, tmp_path)
    h = window.home
    h.modes.option(Mode.LIVE).setFocus()
    reached = set()
    for _ in range(30):
        qtbot.keyClick(QApplication.focusWidget(), Qt.Key.Key_Tab)
        reached.add(QApplication.focusWidget())
    assert {h.start_button, h.manage} <= reached
    h.start_button.setFocus()
    qtbot.keyClick(h.start_button, Qt.Key.Key_Space)
    assert window.controller.state is SessionState.RUNNING
    window.controller.stop()


@pytest.mark.desktop  # needs real fonts; the offscreen platform has none
def test_every_page_fits_the_minimum_window_width(qtbot, window, tmp_path):
    add_user_template(window, tmp_path)
    window.resize(theme.MIN_WIDTH, theme.MIN_HEIGHT)
    for index in range(4):
        window.go(index, animate=False)
        qtbot.wait(20)
        page = window.stack.currentWidget()
        assert isinstance(page, QScrollArea)
        assert page.widget().minimumSizeHint().width() <= page.viewport().width()
        assert page.horizontalScrollBar().maximum() == 0


# Settings


def test_settings_are_persisted(qtbot, window):
    v = window.settings_page
    v.strictness.setValue(2)
    v.interval.setCurrentIndex(v.interval.findData(1000))
    v.cooldown.setCurrentIndex(v.cooldown.findData(5.0))
    click(qtbot, v.click_again)
    qtbot.waitUntil(lambda: settings_path().exists(), timeout=3000)
    qtbot.wait(500)
    data = json.loads(settings_path().read_text())
    assert data["threshold"] == pytest.approx(0.9)
    assert v.strict_value.text() == "Strict"
    assert data["scan_interval_ms"] == 1000
    assert data["cooldown_s"] == 5.0
    assert data["actions"] == ["lobby"]


def test_saved_settings_are_shown_and_not_reset(qtbot, screen):
    saved = Settings(
        threshold=0.92, scan_interval_ms=1200, cooldown_s=4.0, actions={Screen.RESULTS}, onboarding_done=True
    )
    win = make_window(qtbot, screen, saved)
    v = win.settings_page
    assert v.strict_value.text() == "Strict"  # the nearest named stop
    assert v.interval.currentData() == 1200 and v.interval.currentText() == "1.2 seconds"
    assert v.cooldown.currentData() == 4.0
    assert not v.click_play.isChecked() and v.click_again.isChecked()
    assert (saved.threshold, saved.scan_interval_ms, saved.cooldown_s) == (0.92, 1200, 4.0)
    assert saved.actions == {Screen.RESULTS}
    win.close()


def test_advanced_settings_expand(qtbot, window):
    window.go(SETTINGS, animate=False)
    advanced = window.settings_page.advanced
    assert not advanced.body.isVisible()
    click(qtbot, advanced.head)
    assert advanced.is_open and advanced.body.isVisible()
    qtbot.waitUntil(lambda: advanced.body.maximumHeight() == 16777215, timeout=2000)
    click(qtbot, advanced.head)
    qtbot.waitUntil(lambda: not advanced.body.isVisible(), timeout=2000)


def test_switch_animates_its_knob(qtbot):
    switch = Switch("Test")
    qtbot.addWidget(switch)
    switch.show()
    switch.setChecked(True)
    qtbot.waitUntil(lambda: switch._on.value == 1.0, timeout=1000)
    switch.setChecked(False)
    qtbot.waitUntil(lambda: switch._on.value == 0.0, timeout=1000)


def test_hotkey_is_recorded_from_key_presses(qtbot, window):
    window.go(SETTINGS, animate=False)
    button = window.settings_page.hotkey
    click(qtbot, button)
    assert button.recording
    qtbot.keyClick(button, Qt.Key.Key_K)  # no modifier: refused
    assert button.recording and window.toasts.messages()[-1] == "Use at least one of Ctrl, Alt, or Shift"
    qtbot.keyClick(button, Qt.Key.Key_Escape)
    assert not button.recording and window.settings.emergency_hotkey == "Ctrl+Shift+F12"
    click(qtbot, button)
    ctrl_alt = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
    qtbot.keyClick(button, Qt.Key.Key_F19, ctrl_alt)
    assert window.settings.emergency_hotkey == "Ctrl+Alt+F19"
    assert window.home.hotkey_caps.accessibleName() == "Ctrl+Alt+F19"


def test_rejected_hotkey_keeps_previous(window):
    # Start from a combination nothing else uses (a running copy may hold the default).
    previous = "Ctrl+Alt+Shift+F20"
    window.apply_hotkey(previous)
    blocker = GlobalHotkey(lambda: None)
    blocker.register("Ctrl+Alt+Shift+F21")
    try:
        window.apply_hotkey("Ctrl+Alt+Shift+F21")
    finally:
        blocker.unregister()
    assert window.settings.emergency_hotkey == previous
    status = window.settings_page.hotkey_help.text()
    assert "could not be registered" in status and f"Still using {previous}" in status


def test_profiles_export_and_import(qtbot, window, tmp_path):
    add_user_template(window, tmp_path)
    folder = tmp_path / "profile"
    window.export_profile(folder)
    assert (folder / "profile.json").exists()
    for entry in list(window.library.entries):
        window.library.remove(entry)
    window._templates_changed()
    assert Target.PLAY not in window.view.saved
    window.import_profile(folder / "profile.json")
    assert Target.PLAY in window.view.saved and window.view.checks[Target.PLAY] is Check.UNCHECKED


# Setup page


def test_manual_selection_save_and_check(qtbot, window, scenario):
    window.go(SETUP, animate=False)
    setup = window.setup
    capture = setup.capture
    capture.reset(Target.PLAY)
    show_screenshot(capture, scenario, "lobby")
    capture.shot.set_box(None, animate=False)  # draw it by hand instead
    capture._on_edited()
    assert not capture.save_button.isEnabled()

    shot = capture.shot
    button = scenario.button_box
    as_percent = QRectF(
        button.left / SCREEN_SIZE[0] * 100,
        button.top / SCREEN_SIZE[1] * 100,
        button.width / SCREEN_SIZE[0] * 100,
        button.height / SCREEN_SIZE[1] * 100,
    )
    area = shot._to_widget(as_percent)
    drag(qtbot, shot, area.topLeft().toPoint(), area.bottomRight().toPoint())
    assert shot.tag == "Your box" and capture.save_button.isEnabled()
    saved = capture._box_pixels()
    assert abs(saved.width - button.width) <= 6 and abs(saved.height - button.height) <= 6

    click(qtbot, capture.save_button)
    entry = window.settings.templates[-1]
    assert (entry.screen, entry.button, entry.source_height) == (Screen.LOBBY, Button.PLAY, SCREEN_SIZE[1])
    assert window.toasts.messages()[-1] == "Play / Ready saved"
    assert setup.rows[Target.PLAY].action.text() == "Recapture"

    check_screen(setup.check, scenario, "lobby")
    assert window.view.checks[Target.PLAY] is Check.WORKING
    assert "Recognized your lobby" in setup.check.notice.message.text()
    assert window.home.button_rows[Target.PLAY].state.label == "Working"


def test_recapturing_replaces_the_saved_picture(qtbot, window, scenario):
    capture = window.setup.capture
    for _ in range(2):
        capture.reset(Target.PLAY)
        show_screenshot(capture, scenario, "lobby")
        click(qtbot, capture.save_button)
    lobby = [e for e in window.settings.templates if e.button is Button.PLAY]
    assert len(lobby) == 1
    assert window.view.checks[Target.PLAY] is Check.UNCHECKED


def test_box_size_rules():
    assert box_problem(None)
    assert "very small" in box_problem(QRectF(10, 10, 3, 10))
    assert "too large" in box_problem(QRectF(10, 10, 50, 10))
    assert "too large" in box_problem(QRectF(10, 10, 20, 40))
    assert box_problem(QRectF(10, 10, 20, 10)) == ""


def test_an_oversized_box_cannot_be_saved(qtbot, window, scenario):
    window.go(SETUP, animate=False)
    capture = window.setup.capture
    show_screenshot(capture, scenario, "lobby")
    capture.shot.set_box(QRectF(0, 0, 80, 60), animate=False)
    capture._on_edited()
    assert capture.shot.tag == "Adjust the box" and capture.shot.tone == "bad"
    assert capture.fit.isVisible() and not capture.save_button.isEnabled()


def test_try_another_cycles_through_suggestions(qtbot, window, scenario):
    window.go(SETUP, animate=False)
    capture = window.setup.capture
    show_screenshot(capture, scenario, "lobby")
    capture.suggestions = [QRectF(10, 10, 10, 6), QRectF(50, 50, 10, 6)]
    capture.candidate = 0
    capture.render()
    assert capture.next_button.isVisible()
    click(qtbot, capture.next_button)
    assert capture.candidate == 1 and capture.shot.box == QRectF(50, 50, 10, 6)


def test_keyboard_nudges_the_box(qtbot, window, scenario):
    capture = window.setup.capture
    show_screenshot(capture, scenario, "lobby")
    before = QRectF(capture.shot.box)
    capture.shot.setFocus()
    qtbot.keyClick(capture.shot, Qt.Key.Key_Right)
    qtbot.keyClick(capture.shot, Qt.Key.Key_Down, Qt.KeyboardModifier.ShiftModifier)
    after = capture.shot.box
    assert after.x() == pytest.approx(before.x() + 0.5) and after.y() == pytest.approx(before.y() + 2)
    assert capture.shot.tag == "Your box"


def test_recognition_check_never_claims_untested_buttons(qtbot, window, tmp_path, scenario):
    add_user_template(window, tmp_path)
    check = window.setup.check
    assert window.view.checks[Target.PLAY] is Check.UNCHECKED
    assert window.view.checks[Target.AGAIN] is Check.NONE
    check_screen(check, scenario, "matchmaking")
    assert window.view.checks[Target.PLAY] is Check.UNCHECKED
    assert "None of your saved buttons" in check.notice.message.text()
    scenario.show("lobby")
    click(qtbot, check.run_button)  # hides the window, looks once, never clicks
    qtbot.waitUntil(lambda: window.view.checks[Target.PLAY] is Check.WORKING, timeout=3000)
    assert check.run_button.text() == "Check again"


def test_check_without_usable_pictures_is_unavailable(qtbot, window, tmp_path, scenario):
    add_user_template(window, tmp_path)
    for entry in window.settings.templates:
        Path(entry.path).unlink()
    check = window.setup.check
    check_screen(check, scenario, "lobby")
    assert "Recognition isn't available" in check.notice.message.text()
    assert window.view.checks[Target.PLAY] is not Check.WORKING


def test_waiting_screens_are_optional(qtbot, window, scenario):
    window.go(SETUP, animate=False)
    setup = window.setup
    setup.capture_target(Screen.MATCHMAKING)
    capture = setup.capture
    assert capture.kind.value() is None and capture.waiting_note.isVisible()
    show_screenshot(capture, scenario, "matchmaking")
    assert capture.shot.box is None  # waiting screens get no button suggestion
    capture.shot.set_box(QRectF(0, 0, 45, 35), animate=False)
    capture._on_edited()
    click(qtbot, capture.save_button)
    assert window.settings.templates, capture.save_error.message.text()
    assert window.settings.templates[-1].screen is Screen.MATCHMAKING
    assert "1 saved" in setup.waiting_help.text()


def test_scan_area_from_a_selection(qtbot, window, scenario):
    window.go(SETUP, animate=False)
    setup = window.setup
    setup._set_area()
    assert window.toasts.messages()[-1].startswith("Capture a screenshot above")
    show_screenshot(setup.capture, scenario, "lobby")
    setup.capture.shot.set_box(QRectF(0, 50, 60, 50), animate=False)
    click(qtbot, setup.set_area)
    assert window.settings.region == Region(0, 270, 576, 270)
    assert not setup.clear_area.isHidden()
    click(qtbot, setup.clear_area)
    assert window.settings.region is None


def test_import_an_image_as_a_button(qtbot, window, tmp_path):
    image = tmp_path / "again.png"
    image.write_bytes((TEMPLATES_DIR / "play_again.png").read_bytes())
    window.setup.capture.reset(Target.AGAIN)
    window.setup.import_image(image)
    assert Target.AGAIN in window.view.saved
    window.setup.import_image(tmp_path / "missing.png")
    assert window.toasts.messages()[-1].startswith("Couldn't import it")


# Activity


def test_click_filter_matches_controller_messages():
    clicked = Event(EventKind.CLICKED, Screen.LOBBY, point=(10, 20), target="Play")
    verified = Event(EventKind.VERIFIED, Screen.LOBBY, other=Screen.MATCHMAKING)
    changed = Event(EventKind.SCREEN_CHANGED, Screen.LOBBY, other=Screen.UNKNOWN, confidence=0.9)
    clicks = FILTERS["click"]
    assert clicks(make_entry("", "INFO", controller.describe_event(clicked)[1]))
    assert clicks(make_entry("", "INFO", controller.describe_event(verified)[1]))
    assert not clicks(make_entry("", "INFO", controller.describe_event(changed)[1]))


@pytest.mark.parametrize(
    "level, message, kind, title",
    [
        ("INFO", "Screen: Unknown → Lobby (0.980)", "detect", "Recognized the Lobby screen"),
        ("INFO", "Screen: Lobby → Unknown", "info", "Left the Lobby screen"),
        ("INFO", "Clicked 'Play' at (10, 20)", "click", "Clicked Play"),
        ("INFO", "Action verified: Lobby → Matchmaking", "ok", "Click confirmed · now on Matchmaking"),
        ("INFO", "Saved the 'Play' button for the Lobby screen (lobby-1, 120 × 40)", "ok", None),
        (
            "WARNING",
            "Unexpected screen change: Lobby → Results (0.9)",
            "warn",
            "Unexpected screen change: Lobby → Results (0.9)",
        ),
        ("ERROR", "Capture failed. The display went away.", "error", "Capture failed."),
    ],
)
def test_activity_titles_are_readable(level, message, kind, title):
    found_kind, found_title = classify(level, message)
    assert found_kind == kind
    assert found_title == (title or message)


def test_activity_filters_copy_clear_and_details(qtbot, window):
    activity = window.activity
    window.go(ACTIVITY, animate=False)
    activity.clear()
    assert activity.empty.isVisible() and activity.empty.title.text() == "No activity yet"
    activity.append("10:00:00", "INFO", "Screen: Unknown → Lobby (0.980)")
    activity.append("10:00:01", "INFO", "Clicked 'Play' at (10, 20)")
    activity.append("10:00:02", "WARNING", "Unexpected screen change")
    activity.append("10:00:03", "ERROR", "Capture failed")
    assert [e.title for e in activity.visible_entries()][0] == "Capture failed"  # newest first
    activity.set_filter("click")
    assert [e.title for e in activity.visible_entries()] == ["Clicked Play"]
    item = next(i for i in activity.items if not i.isHidden())
    click(qtbot, item.head)
    assert item.expanded and item.detail.text() == "Clicked 'Play' at (10, 20)"
    activity.set_filter("error")
    activity.copy()
    assert QGuiApplication.clipboard().text() == "10:00:03  Capture failed"
    activity.set_filter("warn")
    assert [e.title for e in activity.visible_entries()] == ["Unexpected screen change"]
    activity.set_filter("all")
    activity.clear()
    assert activity.visible_entries() == [] and activity.empty.title.text() == "No activity yet"


def test_empty_filter_offers_to_show_everything(qtbot, window):
    window.go(ACTIVITY, animate=False)
    activity = window.activity
    activity.clear()
    activity.append("10:00:00", "INFO", "fine")
    activity.set_filter("error")
    assert activity.empty.title.text() == "Nothing matches this filter"
    click(qtbot, activity.empty_action)
    assert activity.filter == "all" and len(activity.visible_entries()) == 1


def test_warnings_mark_activity_until_seen(window):
    window.go(HOME, animate=False)
    window._on_record("10:00:00", "INFO", "fine")
    assert window.tabs.flag(ACTIVITY) == ""
    window._on_record("10:00:01", "WARNING", "careful")
    assert window.tabs.flag(ACTIVITY) == "warn"
    window._on_record("10:00:02", "ERROR", "broken")
    window._on_record("10:00:03", "WARNING", "careful again")
    assert window.tabs.flag(ACTIVITY) == "error"  # an error is not downgraded
    window.go(ACTIVITY, animate=False)
    assert window.tabs.flag(ACTIVITY) == ""


def test_toasts_show_at_most_two(qtbot, window):
    for index in range(4):
        window.toast(f"message {index}")
    assert window.toasts.messages() == ["message 2", "message 3"]


# Home status, derived purely from real state


def test_home_status_is_derived_from_state():
    view = ViewState()
    assert home_status(view).title == "Needs setup"
    view.saved = {Target.PLAY}
    view.checks.sync(view.saved)
    status = home_status(view)
    assert (status.title, status.callout.action) == ("Ready", "Add Play Again")
    view.checks.statuses[Target.PLAY] = Check.ADJUST
    assert home_status(view).callout.action == "Fix"
    view.session = SessionState.RUNNING
    assert home_status(view).title == "Watching" and home_status(view).callout is None
    view.mode = Mode.INTERACTION
    assert home_status(view).title == "Auto clicking"
    view.session = SessionState.ERROR
    view.error = "No display is connected"
    assert home_status(view).callout.action == "Open Settings"
