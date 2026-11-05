"""System-wide emergency stop hotkey using Win32 RegisterHotKey."""

from __future__ import annotations

import ctypes
import logging
import threading
from collections.abc import Callable
from ctypes import wintypes

log = logging.getLogger(__name__)

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012
HOTKEY_ID = 0x4C50

_MODIFIERS = {"ctrl": MOD_CONTROL, "alt": MOD_ALT, "shift": MOD_SHIFT, "meta": MOD_WIN, "win": MOD_WIN}
_NAMED_KEYS = {
    "esc": 0x1B,
    "space": 0x20,
    "pgup": 0x21,
    "pgdown": 0x22,
    "end": 0x23,
    "home": 0x24,
    "ins": 0x2D,
    "del": 0x2E,
    "pause": 0x13,
    "backspace": 0x08,
    "tab": 0x09,
    "return": 0x0D,
}


class HotkeyError(Exception):
    pass


def parse_hotkey(text: str) -> tuple[int, int]:
    """Parses Qt portable key text such as 'Ctrl+Shift+F12' into (modifiers, virtual key)."""
    parts = [p.strip().lower() for p in text.split("+") if p.strip()]
    if not parts:
        raise HotkeyError("Shortcut is empty")
    *mods, key = parts
    modifiers = 0
    for mod in mods:
        if mod not in _MODIFIERS:
            raise HotkeyError(f"Unknown modifier '{mod}'")
        modifiers |= _MODIFIERS[mod]
    return modifiers, _virtual_key(key)


def _virtual_key(key: str) -> int:
    if len(key) == 1 and key.isalnum():
        return ord(key.upper())
    if key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        return 0x70 + int(key[1:]) - 1
    if key in _NAMED_KEYS:
        return _NAMED_KEYS[key]
    raise HotkeyError(f"Key '{key}' cannot be used as a global shortcut")


class GlobalHotkey:
    """Runs a Win32 message loop on a daemon thread and calls `on_trigger` from that thread."""

    def __init__(self, on_trigger: Callable[[], None]) -> None:
        self._on_trigger = on_trigger
        self._thread: threading.Thread | None = None
        self._thread_id = 0

    def register(self, text: str) -> None:
        """Replaces the active hotkey. Raises HotkeyError if Windows refuses it."""
        modifiers, vk = parse_hotkey(text)
        self.unregister()
        ready = threading.Event()
        outcome: dict[str, int | bool] = {}
        thread = threading.Thread(
            target=self._run,
            args=(modifiers | MOD_NOREPEAT, vk, ready, outcome),
            name="loop-hotkey",
            daemon=True,
        )
        thread.start()
        if not ready.wait(2.0) or not outcome.get("ok"):
            raise HotkeyError(f"'{text}' could not be registered. Another application may already use it.")
        self._thread = thread

    def unregister(self) -> None:
        if self._thread and self._thread.is_alive():
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            self._thread.join(timeout=2.0)
        self._thread = None

    def _run(self, modifiers: int, vk: int, ready: threading.Event, outcome: dict) -> None:
        user32 = ctypes.windll.user32
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        outcome["ok"] = bool(user32.RegisterHotKey(None, HOTKEY_ID, modifiers, vk))
        ready.set()
        if not outcome["ok"]:
            return
        try:
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                    try:
                        self._on_trigger()
                    except Exception:
                        log.exception("Emergency stop handler failed")
        finally:
            user32.UnregisterHotKey(None, HOTKEY_ID)
