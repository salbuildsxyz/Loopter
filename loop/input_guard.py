"""The only path through which LOOP sends mouse input.

A click is refused unless the guard is armed and the point lies inside the click
target. For the demo target, that window must be on top at the point. For live
interaction, the point must be in the foreground window (never LOOP itself) and
the user must not have used the mouse or keyboard in the last few seconds.
The emergency stop disarms the guard from any thread, effective immediately.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from loop.capture import Region

ClickFn = Callable[[int, int], None]
USER_IDLE_S = 2.0


class Desktop(Protocol):
    def window_at(self, x: int, y: int) -> int: ...
    def foreground_window(self) -> int: ...
    def is_own_window(self, hwnd: int) -> bool: ...
    def idle_seconds(self) -> float: ...


@dataclass(frozen=True)
class ClickTarget:
    region: Region
    window: int = 0  # a specific window that must be on top; 0 means the foreground window
    require_user_idle: bool = False


class InputBlocked(Exception):
    pass


class InputDeferred(InputBlocked):
    """The click is not safe right now but may be retried later; not an error."""


class InputFailed(InputBlocked):
    """Sending the click failed and the guard disarmed itself; the session cannot continue."""


def pyautogui_click(x: int, y: int) -> None:
    """Clicks at a screen point and puts the cursor back where the user left it."""
    import pyautogui  # Imported lazily: it changes process DPI awareness on import.

    original = pyautogui.position()
    pyautogui.click(x, y)
    pyautogui.moveTo(original.x, original.y)


def _default_desktop() -> Desktop:
    from loop.win32 import Win32Desktop

    return Win32Desktop()


class InputGuard:
    def __init__(self, click: ClickFn | None = None, desktop: Desktop | None = None) -> None:
        self._click = click or pyautogui_click
        self._desktop = desktop or _default_desktop()
        self._armed = threading.Event()
        self._lock = threading.Lock()
        self._target: ClickTarget | None = None

    @property
    def armed(self) -> bool:
        return self._armed.is_set()

    def arm(self) -> None:
        self._armed.set()

    def disarm(self) -> None:
        self._armed.clear()

    def set_target(self, target: ClickTarget | None) -> None:
        with self._lock:
            self._target = target

    @property
    def target(self) -> ClickTarget | None:
        with self._lock:
            return self._target

    def click(self, x: int, y: int) -> None:
        target = self.target
        if not self._armed.is_set():
            raise InputBlocked("Clicks are disabled")
        if target is None:
            raise InputBlocked("No click target is set")
        if not target.region.contains_point(x, y):
            raise InputBlocked(f"Click at ({x}, {y}) is outside the allowed area")
        self._check_window(target, x, y)
        if target.require_user_idle and self._desktop.idle_seconds() < USER_IDLE_S:
            raise InputDeferred(f"Mouse or keyboard used in the last {USER_IDLE_S:g} s; click postponed")
        if not self._armed.is_set():  # the emergency stop may have fired during the checks
            raise InputBlocked("Clicks are disabled")
        try:
            self._click(x, y)
        except Exception as exc:
            # pyautogui raises FailSafeException when the cursor is in a screen corner.
            self.disarm()
            raise InputFailed(f"Mouse input failed ({type(exc).__name__}). Clicks were disabled.") from exc

    def _check_window(self, target: ClickTarget, x: int, y: int) -> None:
        window = self._desktop.window_at(x, y)
        if target.window:
            if window != target.window:
                raise InputDeferred("Another window is covering the demo target; click postponed")
            return
        foreground = self._desktop.foreground_window()
        if foreground and self._desktop.is_own_window(foreground):
            raise InputDeferred("LOOP is in the foreground. Switch to the game window to allow clicks.")
        if not foreground or window != foreground:
            raise InputDeferred("The button is not in the foreground window; click postponed")
