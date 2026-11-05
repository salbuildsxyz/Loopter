import ctypes
import sys
import threading

import pytest

from loop.hotkey import (
    MOD_ALT,
    MOD_CONTROL,
    MOD_SHIFT,
    MOD_WIN,
    GlobalHotkey,
    HotkeyError,
    parse_hotkey,
)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Ctrl+Shift+F12", (MOD_CONTROL | MOD_SHIFT, 0x7B)),
        ("Alt+Q", (MOD_ALT, ord("Q"))),
        ("Meta+End", (MOD_WIN, 0x23)),
        ("Pause", (0, 0x13)),
        ("Ctrl+7", (MOD_CONTROL, ord("7"))),
    ],
)
def test_parse_hotkey(text, expected):
    assert parse_hotkey(text) == expected


@pytest.mark.parametrize("text", ["", "Ctrl+", "Hyper+A", "Ctrl+Shift+F99", "Ctrl+Volume Up"])
def test_parse_hotkey_rejects(text):
    with pytest.raises(HotkeyError):
        parse_hotkey(text)


@pytest.mark.desktop
@pytest.mark.skipif(sys.platform != "win32", reason="Win32 global hotkeys")
def test_registered_hotkey_fires_on_real_key_events():
    fired = threading.Event()
    hotkey = GlobalHotkey(fired.set)
    hotkey.register("Ctrl+Alt+Shift+F23")  # practically never bound by other software
    try:
        keybd_event = ctypes.windll.user32.keybd_event
        keys = [0x11, 0x12, 0x10, 0x86]  # Ctrl, Alt, Shift, F23
        for vk in keys:
            keybd_event(vk, 0, 0, 0)
        for vk in reversed(keys):
            keybd_event(vk, 0, 2, 0)  # KEYEVENTF_KEYUP
        assert fired.wait(2.0)
    finally:
        hotkey.unregister()


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 global hotkeys")
def test_conflicting_registration_reports_error():
    first, second = GlobalHotkey(lambda: None), GlobalHotkey(lambda: None)
    first.register("Ctrl+Alt+Shift+F22")
    try:
        with pytest.raises(HotkeyError, match="could not be registered"):
            second.register("Ctrl+Alt+Shift+F22")
    finally:
        first.unregister()
        second.unregister()
