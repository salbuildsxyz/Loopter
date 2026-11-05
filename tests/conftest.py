"""Shared fixtures.

By default the suite never touches the real desktop: Qt runs offscreen, real mouse
input is replaced by a function that fails the test, and tests that capture the
screen, show real windows, or send key events are skipped. Set LOOP_DESKTOP_TESTS=1
to run those too.
"""

from __future__ import annotations

import os
import random

import numpy as np
import pytest

DESKTOP_TESTS = os.environ.get("LOOP_DESKTOP_TESTS") == "1"
if not DESKTOP_TESTS:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from loop import input_guard  # noqa: E402 - must follow the platform choice above
from loop.capture import Region  # noqa: E402
from loop.input_guard import ClickTarget, InputGuard  # noqa: E402
from tests.simulation import SCREEN_SIZE, demo_templates  # noqa: E402
from tests.simulation.scenario import DemoScenario  # noqa: E402

DEMO_ORIGIN = Region(200, 150, *SCREEN_SIZE)
DEMO_HWND = 0xBEEF
GAME_HWND = 0xCAFE
LOOP_HWND = 0x1001


def pytest_collection_modifyitems(config, items):
    if DESKTOP_TESTS:
        return
    skip = pytest.mark.skip(reason="touches the real desktop; set LOOP_DESKTOP_TESTS=1 to run")
    for item in items:
        if "desktop" in item.keywords:
            item.add_marker(skip)


class FakeDesktop:
    """Answers the input guard's questions about windows and user activity."""

    def __init__(self, window: int = DEMO_HWND, foreground: int = DEMO_HWND, idle: float = 60.0) -> None:
        self.window = window
        self.foreground = foreground
        self.idle = idle

    def window_at(self, x: int, y: int) -> int:
        return self.window

    def foreground_window(self) -> int:
        return self.foreground

    def is_own_window(self, hwnd: int) -> bool:
        return hwnd == LOOP_HWND

    def idle_seconds(self) -> float:
        return self.idle


class ScenarioCapture:
    """Stands in for the screen: the demo scenario drawn at DEMO_ORIGIN.

    Screens that advance on a timer in the real demo window advance here after a
    few captures, so whole matches run without real time passing.
    """

    def __init__(self, scenario: DemoScenario, captures_per_timed_screen: int = 3) -> None:
        self.scenario = scenario
        self._captures_per_timed_screen = captures_per_timed_screen
        self._captures_here = 0
        self._index = scenario.index

    def grab(self, region: Region) -> np.ndarray:
        if self.scenario.index != self._index:
            self._index, self._captures_here = self.scenario.index, 0
        if self.scenario.screen.auto_advance_ms:
            self._captures_here += 1
            if self._captures_here > self._captures_per_timed_screen:
                self.scenario.advance()
        frame = self.scenario.render()
        x, y = region.left - DEMO_ORIGIN.left, region.top - DEMO_ORIGIN.top
        return frame[y : y + region.height, x : x + region.width].copy()

    def close(self) -> None:
        pass


class ScenarioMouse:
    """A mouse whose clicks press the scenario's button instead of moving the real cursor."""

    def __init__(self, scenario: DemoScenario) -> None:
        self.scenario = scenario
        self.clicks: list[tuple[int, int]] = []
        self.pressed: list[str] = []  # demo screen whose button each click hit, or "" for a miss

    def __call__(self, x: int, y: int) -> None:
        self.clicks.append((x, y))
        name = self.scenario.screen.name
        hit = self.scenario.press(x - DEMO_ORIGIN.left, y - DEMO_ORIGIN.top)
        self.pressed.append(name if hit else "")


@pytest.fixture(autouse=True)
def no_real_mouse(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(x: int, y: int) -> None:
        raise AssertionError(f"a test attempted a real mouse click at ({x}, {y})")

    monkeypatch.setattr(input_guard, "pyautogui_click", refuse)


@pytest.fixture(scope="session", autouse=True)
def qt_application_first(qapp):
    """Create the QApplication before any mss handle, as the app does, so Qt sets DPI awareness."""
    return qapp


@pytest.fixture(autouse=True)
def isolated_app_data(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Keeps tests away from the real %APPDATA%\\LOOP folder."""
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    return tmp_path / "appdata" / "LOOP"


@pytest.fixture
def scenario() -> DemoScenario:
    return DemoScenario(random.Random(7))


@pytest.fixture
def desktop() -> FakeDesktop:
    return FakeDesktop()


@pytest.fixture
def mouse(scenario: DemoScenario) -> ScenarioMouse:
    return ScenarioMouse(scenario)


@pytest.fixture
def demo_guard(mouse: ScenarioMouse, desktop: FakeDesktop) -> InputGuard:
    guard = InputGuard(click=mouse, desktop=desktop)
    guard.set_target(ClickTarget(DEMO_ORIGIN, window=DEMO_HWND))
    return guard


@pytest.fixture(scope="session")
def templates():
    return demo_templates()
