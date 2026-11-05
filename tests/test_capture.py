import pytest

from loop.capture import CaptureError, Region, ScreenCapture, display_for

MONITORS = [Region(0, 0, 1920, 1080), Region(-2560, 0, 2560, 1440)]


def test_display_for_returns_containing_monitor():
    assert display_for(Region(-1000, 100, 400, 300), MONITORS) == MONITORS[1]
    assert display_for(Region(10, 10, 400, 300), MONITORS) == MONITORS[0]


def test_region_too_small():
    with pytest.raises(CaptureError, match="too small"):
        display_for(Region(10, 10, 8, 200), MONITORS)


def test_region_outside_displays():
    with pytest.raises(CaptureError, match="not fully inside a connected display"):
        display_for(Region(1800, 900, 400, 400), MONITORS)


def test_region_after_display_removed():
    with pytest.raises(CaptureError):
        display_for(Region(-1000, 100, 400, 300), MONITORS[:1])


@pytest.mark.parametrize(
    "data",
    [
        {"left": 0, "top": 0, "width": 0, "height": 10},
        {"left": "0", "top": 0, "width": 10, "height": 10},
        {"left": 0, "top": 0, "width": True, "height": 10},
        {"left": 0, "top": 0},
    ],
)
def test_region_from_dict_rejects_bad_data(data):
    with pytest.raises((TypeError, ValueError, KeyError)):
        Region.from_dict(data)


def test_region_geometry():
    r = Region(10, 20, 100, 50)
    assert r.center == (60, 45)
    assert r.contains_point(10, 20) and not r.contains_point(110, 20)
    assert r.offset(-10, 5) == Region(0, 25, 100, 50)


@pytest.mark.desktop
def test_real_capture_of_primary_display():
    with ScreenCapture() as capture:
        monitor = capture.monitors()[0]
        frame = capture.grab(Region(monitor.left, monitor.top, 64, 48))
    assert frame.shape == (48, 64, 3)
    assert frame.flags["C_CONTIGUOUS"]
