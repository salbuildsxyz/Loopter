import pytest

from loop.capture import Region
from loop.input_guard import USER_IDLE_S, ClickTarget, InputBlocked, InputDeferred, InputGuard
from tests.conftest import GAME_HWND, LOOP_HWND, FakeDesktop

AREA = Region(100, 100, 400, 300)
DEMO = 42


def make(target: ClickTarget, desktop: FakeDesktop):
    clicks = []
    guard = InputGuard(click=lambda x, y: clicks.append((x, y)), desktop=desktop)
    guard.set_target(target)
    return guard, clicks


def demo_guard(window_at=DEMO):
    return make(ClickTarget(AREA, window=DEMO), FakeDesktop(window=window_at, foreground=window_at))


def live_guard(**desktop):
    defaults = {"window": GAME_HWND, "foreground": GAME_HWND, "idle": 60.0}
    return make(ClickTarget(AREA, require_user_idle=True), FakeDesktop(**(defaults | desktop)))


def test_disarmed_by_default():
    guard, clicks = demo_guard()
    with pytest.raises(InputBlocked, match="disabled"):
        guard.click(200, 200)
    assert clicks == []


def test_demo_click_inside_target():
    guard, clicks = demo_guard()
    guard.arm()
    guard.click(200, 200)
    assert clicks == [(200, 200)]


def test_refuses_points_outside_target():
    guard, clicks = demo_guard()
    guard.arm()
    for point in [(99, 200), (500, 200), (200, 400), (0, 0)]:
        with pytest.raises(InputBlocked, match="outside"):
            guard.click(*point)
    assert clicks == []


def test_refuses_without_target():
    guard, _ = demo_guard()
    guard.arm()
    guard.set_target(None)
    with pytest.raises(InputBlocked, match="No click target"):
        guard.click(200, 200)


def test_covered_demo_target_postpones():
    guard, clicks = demo_guard(window_at=999)
    guard.arm()
    with pytest.raises(InputDeferred, match="covering"):
        guard.click(200, 200)
    assert clicks == []


def test_live_click_in_foreground_window():
    guard, clicks = live_guard()
    guard.arm()
    guard.click(300, 250)
    assert clicks == [(300, 250)]


def test_live_never_clicks_loop_itself():
    guard, clicks = live_guard(window=LOOP_HWND, foreground=LOOP_HWND)
    guard.arm()
    with pytest.raises(InputDeferred, match="Loopter is in the foreground"):
        guard.click(300, 250)
    assert clicks == []


def test_live_never_clicks_background_windows():
    guard, clicks = live_guard(window=GAME_HWND, foreground=0x777)
    guard.arm()
    with pytest.raises(InputDeferred, match="not in the foreground"):
        guard.click(300, 250)
    assert clicks == []


def test_live_waits_for_user_to_be_idle():
    guard, clicks = live_guard(idle=USER_IDLE_S / 2)
    guard.arm()
    with pytest.raises(InputDeferred, match="click postponed"):
        guard.click(300, 250)
    assert clicks == []


def test_deferral_is_not_an_error_but_is_a_block():
    assert issubclass(InputDeferred, InputBlocked)


def test_disarm_takes_effect_immediately():
    guard, clicks = demo_guard()
    guard.arm()
    guard.click(150, 150)
    guard.disarm()
    with pytest.raises(InputBlocked):
        guard.click(150, 150)
    assert clicks == [(150, 150)]


def test_disarm_during_checks_prevents_click():
    clicks = []

    class SlowDesktop(FakeDesktop):
        def idle_seconds(self) -> float:
            guard.disarm()  # the emergency stop fires while the guard is checking
            return 60.0

    guard = InputGuard(click=lambda x, y: clicks.append((x, y)), desktop=SlowDesktop(GAME_HWND, GAME_HWND))
    guard.set_target(ClickTarget(AREA, require_user_idle=True))
    guard.arm()
    with pytest.raises(InputBlocked, match="disabled"):
        guard.click(200, 200)
    assert clicks == []


def test_failing_mouse_input_disarms():
    def explode(x, y):
        raise RuntimeError("fail-safe")

    guard = InputGuard(click=explode, desktop=FakeDesktop(DEMO, DEMO))
    guard.set_target(ClickTarget(AREA, window=DEMO))
    guard.arm()
    with pytest.raises(InputBlocked, match="Clicks were disabled"):
        guard.click(200, 200)
    assert not guard.armed
