"""The full recognize → click → verify loop, simulated end to end.

A real worker thread, controller, recognizer, policy, and input guard run against
a synthetic screen (the demo scenario). Only the mouse and desktop are fakes.
"""

import logging
import re
import time
from dataclasses import replace

import pytest
from PySide6.QtCore import QTimer

from loop.capture import Region
from loop.controller import SessionController
from loop.input_guard import ClickTarget, InputGuard
from loop.screens import ACTIONABLE, Screen
from loop.state import SessionState
from loop.worker import ScanPlan
from tests.conftest import DEMO_ORIGIN, GAME_HWND, LOOP_HWND, FakeDesktop, ScenarioCapture
from tests.simulation.scenario import BUTTON_AREAS

# Lobby → Matchmaking → Loading → Match → Results → Finding Next Match → the next match.
WORKFLOW = [
    Screen.LOBBY,
    Screen.MATCHMAKING,
    Screen.LOADING,
    Screen.UNKNOWN,
    Screen.RESULTS,
    Screen.FINDING_MATCH,
    Screen.LOADING,
    Screen.UNKNOWN,
    Screen.RESULTS,
]


def make_plan(templates, actions=frozenset(ACTIONABLE), verify=1.0, cooldown=0.0, click_target=None):
    return ScanPlan(
        templates=templates,
        threshold=0.85,
        interval_s=0.01,
        region=lambda: DEMO_ORIGIN,
        display_height=DEMO_ORIGIN.height,
        actions=actions,
        cooldown_s=cooldown,
        verify_timeout_s=verify,
        click_target=click_target,
    )


class Session:
    """A controller plus a record of every distinct screen it reported."""

    def __init__(self, plan, guard, scenario, capture=None):
        self.controller = SessionController(guard, lambda: plan, lambda: capture or ScenarioCapture(scenario))
        self.screens: list[Screen] = []
        self.controller.observed.connect(self._observed)

    def _observed(self, observation):
        if not self.screens or self.screens[-1] is not observation.screen:
            self.screens.append(observation.screen)

    @property
    def stats(self):
        return self.controller.stats

    def __enter__(self):
        self.controller.start()
        return self

    def __exit__(self, *_):
        self.controller.stop()
        self.controller.shutdown()


def contains_in_order(sequence, expected):
    it = iter(sequence)
    return all(item in it for item in expected)


def test_scenario_buttons_stay_inside_their_areas(scenario):
    for _ in range(40):
        if scenario.button_box:
            assert BUTTON_AREAS[scenario.screen.state].contains(scenario.button_box)
        scenario.advance()


def test_press_only_advances_on_button(scenario):
    assert scenario.screen.state is Screen.LOBBY
    assert not scenario.press(5, 5)
    x, y = scenario.button_box.center
    assert scenario.press(x, y)
    assert scenario.screen.state is Screen.MATCHMAKING
    assert scenario.button_box is None


def test_scenario_follows_the_real_flow(scenario):
    states = [scenario.screen.state]
    for _ in range(len(WORKFLOW) - 1):
        scenario.advance()
        states.append(scenario.screen.state)
    assert states == WORKFLOW
    assert scenario.matches == 2


def test_full_workflow_presses_only_play_and_play_again(
    qtbot, caplog, scenario, demo_guard, mouse, templates
):
    caplog.set_level(logging.INFO)
    with Session(make_plan(templates), demo_guard, scenario) as session:
        qtbot.waitUntil(
            lambda: contains_in_order(session.screens, WORKFLOW) and session.stats.interactions >= 3,
            timeout=15_000,
        )
    assert scenario.matches >= 2
    assert mouse.pressed[:3] == ["lobby", "results", "results"]
    assert "" not in mouse.pressed  # every click landed on a button; waiting screens were left alone
    assert session.stats.interactions >= 3
    assert session.stats.errors == 0
    assert re.search(r"Clicked '(Play|Ready)' at", caplog.text)
    assert "Clicked 'Play Again' at" in caplog.text
    assert "Unexpected" not in caplog.text


def test_disabled_action_is_never_pressed(qtbot, scenario, demo_guard, mouse, templates):
    plan = make_plan(templates, actions=frozenset({Screen.LOBBY}))
    with Session(plan, demo_guard, scenario) as session:
        qtbot.waitUntil(lambda: scenario.screen.state is Screen.RESULTS, timeout=10_000)
        qtbot.wait(300)
        assert scenario.screen.state is Screen.RESULTS  # waits on the results, never presses Play Again
    assert mouse.pressed == ["lobby"]
    assert session.stats.errors == 0


def test_observe_only_never_arms_or_clicks(qtbot, scenario, demo_guard, mouse, templates):
    with Session(make_plan(templates, actions=frozenset()), demo_guard, scenario) as session:
        qtbot.waitUntil(lambda: len(session.screens) >= 1, timeout=3000)
        qtbot.wait(200)
        assert not demo_guard.armed
    assert mouse.clicks == []
    assert session.stats.detections == 1


def test_click_without_effect_gives_up(qtbot, scenario, desktop, templates):
    guard = InputGuard(click=lambda x, y: None, desktop=desktop)
    guard.set_target(ClickTarget(DEMO_ORIGIN, window=desktop.window))
    session = Session(make_plan(templates, verify=0.05), guard, scenario)
    session.controller.start()
    qtbot.waitUntil(lambda: session.controller.state is SessionState.ERROR, timeout=5000)
    assert "did not change the screen" in session.controller.last_error
    assert session.stats.errors == 3
    assert not guard.armed
    session.controller.shutdown()


class FailSafeException(Exception):
    """Stands in for pyautogui's exception when the cursor is pushed into a screen corner."""


def test_mouse_failure_ends_the_session(qtbot, scenario, desktop, templates):
    attempts = []

    def failing_mouse(x, y):
        attempts.append((x, y))
        raise FailSafeException

    guard = InputGuard(click=failing_mouse, desktop=desktop)
    guard.set_target(ClickTarget(DEMO_ORIGIN, window=desktop.window))
    session = Session(make_plan(templates), guard, scenario)
    session.controller.start()
    # The session must not keep reporting Running while clicks are silently disabled.
    qtbot.waitUntil(lambda: session.controller.state is SessionState.ERROR, timeout=3000)
    assert "Mouse input failed (FailSafeException)" in session.controller.last_error
    assert len(attempts) == 1
    assert not guard.armed
    session.controller.shutdown()


def test_recovers_after_error(qtbot, scenario, desktop, mouse, templates):
    clicks_work = []
    guard = InputGuard(click=lambda x, y: mouse(x, y) if clicks_work else None, desktop=desktop)
    guard.set_target(ClickTarget(DEMO_ORIGIN, window=desktop.window))
    session = Session(make_plan(templates, verify=0.05), guard, scenario)
    session.controller.start()
    qtbot.waitUntil(lambda: session.controller.state is SessionState.ERROR, timeout=5000)
    clicks_work.append(True)
    session.controller.start()
    qtbot.waitUntil(lambda: session.stats.interactions >= 1, timeout=5000)
    assert session.controller.state is SessionState.RUNNING
    session.controller.stop()
    session.controller.shutdown()


def test_unexpected_screen_change_is_logged(qtbot, caplog, scenario, demo_guard, templates):
    caplog.set_level(logging.INFO)
    with Session(make_plan(templates, actions=frozenset()), demo_guard, scenario) as session:
        qtbot.waitUntil(lambda: Screen.LOBBY in session.screens, timeout=3000)
        scenario.show("results")  # straight from the lobby to the results, skipping the match
        qtbot.waitUntil(lambda: Screen.RESULTS in session.screens, timeout=3000)
    assert "Unexpected screen change: Lobby → Results" in caplog.text


def test_masked_areas_are_never_recognized(qtbot, scenario, demo_guard, mouse, templates):
    """LOOP blanks its own window out of each capture, so its screenshot preview is never acted on."""
    button = scenario.button_box.offset(DEMO_ORIGIN.left, DEMO_ORIGIN.top)
    plan = replace(make_plan(templates), masked=lambda: [Region(button.left - 5, button.top - 5, 400, 120)])
    with Session(plan, demo_guard, scenario) as session:
        qtbot.waitUntil(lambda: len(session.screens) >= 1, timeout=3000)
        qtbot.wait(300)
    assert session.screens == [Screen.UNKNOWN]
    assert mouse.clicks == []


def test_ambiguous_templates_never_click(qtbot, caplog, scenario, demo_guard, mouse, templates):
    caplog.set_level(logging.INFO)
    lobby = templates[Screen.LOBBY]
    plan = make_plan({Screen.LOBBY: lobby, Screen.RESULTS: lobby})
    with Session(plan, demo_guard, scenario):
        qtbot.waitUntil(lambda: "match the same area" in caplog.text, timeout=3000)
        qtbot.wait(200)
    assert mouse.clicks == []


def test_pause_blocks_clicks_and_resume_continues(qtbot, scenario, demo_guard, mouse, templates):
    with Session(make_plan(templates), demo_guard, scenario) as session:
        session.controller.pause()
        assert not demo_guard.armed
        qtbot.wait(300)
        assert mouse.clicks == []
        session.controller.resume()
        assert demo_guard.armed
        qtbot.waitUntil(lambda: session.stats.interactions >= 2, timeout=5000)
    assert session.stats.errors == 0


def test_stop_disarms_and_halts(qtbot, scenario, demo_guard, mouse, templates):
    with Session(make_plan(templates), demo_guard, scenario) as session:
        qtbot.waitUntil(lambda: session.stats.interactions >= 1, timeout=5000)
    assert not demo_guard.armed
    clicks = len(mouse.clicks)
    qtbot.wait(300)
    assert len(mouse.clicks) == clicks


def test_demo_window_closing_ends_in_error(qtbot, scenario, demo_guard, templates):
    plan = replace(
        make_plan(templates, actions=frozenset()),
        region=lambda: t.region if (t := demo_guard.target) else None,
    )
    session = Session(plan, demo_guard, scenario)
    session.controller.start()
    qtbot.waitUntil(lambda: session.stats.detections >= 1, timeout=3000)
    demo_guard.set_target(None)
    qtbot.waitUntil(lambda: session.controller.state is SessionState.ERROR, timeout=3000)
    assert "no longer available" in session.controller.last_error
    session.controller.shutdown()


class TestLiveInteraction:
    """Live Interaction against a simulated game window."""

    @pytest.fixture
    def game(self):
        return FakeDesktop(window=GAME_HWND, foreground=GAME_HWND, idle=60.0)

    @pytest.fixture
    def guard(self, game, mouse):
        return InputGuard(click=mouse, desktop=game)

    def live_plan(self, templates):
        return make_plan(templates, click_target=ClickTarget(DEMO_ORIGIN, require_user_idle=True))

    def test_controller_installs_and_removes_click_target(self, qtbot, scenario, guard, templates):
        assert guard.target is None
        with Session(self.live_plan(templates), guard, scenario) as session:
            assert guard.target.require_user_idle
            qtbot.waitUntil(lambda: session.stats.interactions >= 2, timeout=10_000)
        assert guard.target is None
        assert not guard.armed

    def test_waits_while_loop_is_in_front(self, qtbot, caplog, scenario, game, guard, mouse, templates):
        caplog.set_level(logging.INFO)
        game.foreground = LOOP_HWND
        with Session(self.live_plan(templates), guard, scenario) as session:
            qtbot.waitUntil(lambda: "Loopter is in the foreground" in caplog.text, timeout=3000)
            qtbot.wait(200)
            assert mouse.clicks == []
            assert session.stats.errors == 0
            game.foreground = GAME_HWND
            qtbot.waitUntil(lambda: session.stats.interactions >= 1, timeout=5000)
        assert caplog.text.count("Loopter is in the foreground") == 1  # reported once, not every scan

    def test_waits_while_user_is_active(self, qtbot, caplog, scenario, game, guard, mouse, templates):
        caplog.set_level(logging.INFO)
        game.idle = 0.1
        with Session(self.live_plan(templates), guard, scenario) as session:
            qtbot.waitUntil(lambda: "click postponed" in caplog.text, timeout=3000)
            assert mouse.clicks == []
            game.idle = 60.0
            qtbot.waitUntil(lambda: session.stats.interactions >= 1, timeout=5000)
        assert session.stats.errors == 0

    def test_never_clicks_a_background_window(self, qtbot, scenario, game, guard, mouse, templates):
        game.foreground = 0x777  # something else is in front of the game
        with Session(self.live_plan(templates), guard, scenario):
            qtbot.wait(400)
        assert mouse.clicks == []

    def test_emergency_stop_mid_session(self, qtbot, scenario, guard, mouse, templates):
        with Session(self.live_plan(templates), guard, scenario) as session:
            qtbot.waitUntil(lambda: session.stats.interactions >= 1, timeout=5000)
            session.controller.emergency_stop()
            assert not guard.armed
            assert guard.target is None
            clicks = len(mouse.clicks)
            qtbot.wait(300)
            assert len(mouse.clicks) == clicks
            assert session.controller.state is SessionState.STOPPED


class SlowCapture(ScenarioCapture):
    def grab(self, region: Region):
        time.sleep(0.3)
        return super().grab(region)


def test_slow_capture_never_blocks_the_ui(qtbot, scenario, demo_guard, templates):
    ticks = []
    timer = QTimer(interval=20)
    timer.timeout.connect(lambda: ticks.append(time.monotonic()))
    timer.start()
    session = Session(make_plan(templates), demo_guard, scenario, capture=SlowCapture(scenario))
    session.controller.start()
    qtbot.wait(1000)
    started = time.monotonic()
    session.controller.stop()
    stop_duration = time.monotonic() - started
    timer.stop()
    session.controller.shutdown()
    gaps = [b - a for a, b in zip(ticks, ticks[1:], strict=False)]
    assert len(ticks) >= 25
    assert max(gaps) < 0.25
    assert stop_duration < 0.05
