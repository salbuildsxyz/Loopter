"""Controller state handling and plan building."""

import logging

import numpy as np
import pytest

from loop.capture import CaptureError, Region
from loop.config import Mode, Settings, TemplateEntry
from loop.controller import SessionController, SetupError, build_plan, describe_event
from loop.input_guard import ClickTarget, InputGuard
from loop.policy import Event, EventKind
from loop.screens import ACTIONABLE, Screen
from loop.state import SessionState
from loop.worker import ScanPlan
from tests.conftest import DEMO_ORIGIN, ScenarioCapture
from tests.simulation import demo_template_path

MONITORS = [Region(0, 0, 1920, 1080), Region(1920, 0, 2560, 1440)]


class BrokenCapture:
    def grab(self, region: Region) -> np.ndarray:
        raise CaptureError("Screen capture failed (test)")

    def close(self) -> None:
        pass


def observe_plan(templates, guard):
    return ScanPlan(
        templates=templates,
        threshold=0.85,
        interval_s=0.02,
        region=lambda: guard.target.region,
        display_height=DEMO_ORIGIN.height,
    )


@pytest.fixture
def controller(scenario, demo_guard, templates):
    plan = observe_plan(templates, demo_guard)
    c = SessionController(demo_guard, lambda: plan, lambda: ScenarioCapture(scenario))
    yield c
    c.shutdown()


def test_lifecycle_and_signals(qtbot, controller):
    states, scans = [], []
    controller.state_changed.connect(states.append)
    controller.observed.connect(scans.append)
    controller.start()
    qtbot.waitUntil(lambda: len(scans) >= 2, timeout=3000)
    controller.pause()
    paused_scans = len(scans)
    qtbot.wait(150)
    assert len(scans) == paused_scans
    controller.resume()
    qtbot.waitUntil(lambda: len(scans) > paused_scans, timeout=3000)
    controller.stop()
    assert states == [SessionState.RUNNING, SessionState.PAUSED, SessionState.RUNNING, SessionState.STOPPED]
    assert controller.stats.detections == 1  # one lobby, seen on many scans


def test_commands_in_wrong_state_are_ignored(controller):
    controller.pause()
    controller.resume()
    controller.stop()
    assert controller.state is SessionState.IDLE


def test_stats_reset_on_new_session(qtbot, controller):
    controller.start()
    qtbot.waitUntil(lambda: controller.stats.detections >= 1, timeout=3000)
    controller.stop()
    controller.start()
    assert controller.stats.detections == 0
    controller.stop()


def test_stale_worker_signals_are_ignored(qtbot, controller):
    scans = []
    controller.observed.connect(scans.append)
    controller.start()
    qtbot.waitUntil(lambda: bool(scans), timeout=3000)
    controller.stop()
    count = len(scans)
    qtbot.wait(200)
    assert len(scans) == count


def test_setup_error_moves_to_error_state():
    def fail():
        raise SetupError("No buttons are set up yet")

    controller = SessionController(InputGuard(click=lambda x, y: None), fail)
    controller.start()
    assert controller.state is SessionState.ERROR
    assert controller.last_error == "No buttons are set up yet"


def test_repeated_capture_failures_end_in_error(qtbot, demo_guard, templates):
    controller = SessionController(demo_guard, lambda: observe_plan(templates, demo_guard), BrokenCapture)
    controller.start()
    qtbot.waitUntil(lambda: controller.state is SessionState.ERROR, timeout=3000)
    assert controller.stats.errors == 5
    assert "consecutive failures" in controller.last_error
    controller.shutdown()


def test_emergency_stop_disarms_and_stops(controller, demo_guard):
    controller.start()
    demo_guard.arm()
    controller.emergency_stop()
    assert controller.state is SessionState.STOPPED
    assert not demo_guard.armed


def test_observe_only_session_never_arms(qtbot, controller, demo_guard):
    controller.start()
    assert not demo_guard.armed
    controller.resume()
    assert not demo_guard.armed


# Plan building


@pytest.fixture
def user_templates(tmp_path):
    entries = []
    for screen in (Screen.LOBBY, Screen.MATCHMAKING):
        path = tmp_path / f"{screen.value}.png"
        path.write_bytes(demo_template_path(screen).read_bytes())
        entries.append(TemplateEntry(str(path), screen, 540))
    return entries


def live(mode=Mode.LIVE, **overrides):
    return Settings(mode=mode, **({"region": Region(100, 100, 800, 600)} | overrides))


def test_live_monitor_never_interacts(user_templates):
    settings = live(templates=user_templates)
    plan = build_plan(settings, MONITORS)
    assert not plan.interacts
    assert plan.click_target is None
    assert plan.display_height == 1080


def test_live_interaction_plan(user_templates):
    settings = live(Mode.INTERACTION, templates=user_templates, region=Region(2000, 100, 800, 600))
    plan = build_plan(settings, MONITORS)
    assert plan.actions == frozenset(ACTIONABLE)
    assert plan.click_target == ClickTarget(Region(2000, 100, 800, 600), require_user_idle=True)
    assert plan.display_height == 1440


def test_live_interaction_warns_about_actions_without_templates(caplog, user_templates):
    caplog.set_level(logging.WARNING)
    build_plan(live(Mode.INTERACTION, templates=user_templates), MONITORS)
    assert "No usable template for 'Play Again'" in caplog.text
    assert "No usable template for 'Play'" not in caplog.text


def test_missing_templates_are_skipped_with_warning(caplog, tmp_path, user_templates):
    caplog.set_level(logging.WARNING)
    entries = [*user_templates, TemplateEntry(str(tmp_path / "gone.png"), Screen.RESULTS)]
    plan = build_plan(live(templates=entries), MONITORS)
    assert set(plan.templates) == {Screen.LOBBY, Screen.MATCHMAKING}
    assert "Skipping template" in caplog.text


@pytest.mark.parametrize(
    "settings, message",
    [
        (Settings(mode=Mode.LIVE), "No buttons are set up yet"),
        (live(), "No buttons are set up yet"),
        (live(templates=[TemplateEntry("C:/nowhere/gone.png", Screen.LOBBY)]), "No buttons are set up yet"),
        (live(region=Region(10**6, 0, 200, 200)), "not fully inside"),
        (live(region=Region(0, 0, 8, 8)), "too small"),
    ],
)
def test_incorrect_configuration_is_reported(settings, message):
    with pytest.raises(SetupError, match=message):
        build_plan(settings, MONITORS)


@pytest.mark.parametrize("monitor, expected", [(1, 0), (2, 1), (9, 1)])
def test_without_a_region_the_whole_selected_display_is_scanned(user_templates, monitor, expected):
    settings = live(Mode.INTERACTION, templates=user_templates, region=None, monitor=monitor)
    plan = build_plan(settings, MONITORS)
    assert plan.region() == MONITORS[expected]
    assert plan.click_target.region == MONITORS[expected]
    assert plan.display_height == MONITORS[expected].height


def test_no_connected_display_is_reported(user_templates):
    with pytest.raises(SetupError, match="No display"):
        build_plan(live(templates=user_templates, region=None), [])


def test_live_plans_mask_loops_own_windows(user_templates):
    own = [Region(0, 0, 10, 10)]
    plan = build_plan(live(templates=user_templates), MONITORS, lambda: own)
    assert plan.masked() == own


@pytest.mark.parametrize("kind", list(EventKind))
def test_every_event_has_a_log_message(kind):
    level, message = describe_event(Event(kind, Screen.LOBBY, other=Screen.LOADING, attempt=1, point=(1, 2)))
    assert message
    assert level in (logging.INFO, logging.WARNING)


def test_templates_saved_for_the_wrong_screen_block_the_session(tmp_path, user_templates):
    path = tmp_path / "mislabeled.png"
    path.write_bytes(demo_template_path(Screen.LOBBY).read_bytes())
    entries = [*user_templates, TemplateEntry(str(path), Screen.RESULTS, 540)]
    with pytest.raises(SetupError, match="saved for the wrong screen"):
        build_plan(live(templates=entries), MONITORS)


def test_live_interaction_needs_something_to_press(tmp_path):
    path = tmp_path / "loading.png"
    path.write_bytes(demo_template_path(Screen.LOADING).read_bytes())
    waiting_only = [TemplateEntry(str(path), Screen.LOADING, 540)]
    with pytest.raises(SetupError, match="nothing it could press"):
        build_plan(live(Mode.INTERACTION, templates=waiting_only), MONITORS)
    assert not build_plan(live(templates=waiting_only), MONITORS).interacts  # monitoring is fine
