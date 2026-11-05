"""Win32 helpers. Tests that open real windows or capture the screen are desktop tests."""

import sys

import pytest

from loop import win32
from loop.capture import Region, ScreenCapture
from loop.input_guard import InputGuard
from loop.recognizer import Recognizer
from loop.screens import Screen
from tests.simulation import SCREEN_SIZE, demo_templates
from tests.simulation.target_window import DemoTargetWindow

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Win32 only")


def test_desktop_queries_are_well_formed():
    desktop = win32.Win32Desktop()
    assert desktop.idle_seconds() >= 0
    assert isinstance(desktop.foreground_window(), int)
    assert not desktop.is_own_window(0)
    assert win32.visible_window_rect(0) is None


@pytest.fixture
def demo_window(qtbot):
    guard = InputGuard(click=lambda x, y: None)
    window = DemoTargetWindow(guard)
    qtbot.addWidget(window)
    window.move(120, 120)
    window.show()
    qtbot.waitExposed(window)
    qtbot.waitUntil(lambda: guard.target is not None, timeout=2000)
    yield window, guard
    window.close()


@pytest.mark.desktop
def test_target_is_published_at_physical_fixture_size(demo_window):
    window, guard = demo_window
    client = win32.client_rect(int(window.winId()))
    assert guard.target.region == Region(client.left, client.top, *SCREEN_SIZE)
    assert guard.target.window == int(window.winId())


@pytest.mark.desktop
def test_window_under_target_center_is_the_demo_window(demo_window):
    window, guard = demo_window
    assert win32.Win32Desktop().window_at(*guard.target.region.center) == int(window.winId())


@pytest.mark.desktop
def test_real_capture_of_demo_window_is_recognized(qtbot, demo_window):
    _, guard = demo_window
    recognizer = Recognizer(demo_templates(), 0.97, SCREEN_SIZE[1])
    screens = []

    def recognized() -> bool:
        # Windows animates new windows in, so early frames are partially transparent.
        with ScreenCapture() as capture:
            screens.append(recognizer.observe(capture.grab(guard.target.region)).screen)
        return screens[-1] is Screen.LOBBY

    qtbot.waitUntil(recognized, timeout=3000)


@pytest.mark.desktop
def test_hiding_window_clears_target(demo_window):
    window, guard = demo_window
    window.hide()
    assert guard.target is None


@pytest.mark.desktop
def test_visible_window_rect_follows_the_window(demo_window):
    window, guard = demo_window
    hwnd = int(window.winId())
    rect = win32.visible_window_rect(hwnd)
    assert rect is not None and rect.contains(guard.target.region)
    window.hide()
    assert win32.visible_window_rect(hwnd) is None
