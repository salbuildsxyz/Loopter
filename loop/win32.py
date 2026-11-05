"""Minimal Win32 helpers via ctypes. Coordinates are physical pixels (the app is per-monitor DPI aware)."""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes

from loop.capture import Region

IS_WINDOWS = sys.platform == "win32"
GA_ROOT = 2


class _LastInputInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def client_rect(hwnd: int) -> Region:
    """Screen rectangle of a window's client area."""
    user32 = ctypes.windll.user32
    rect = wintypes.RECT()
    if not user32.GetClientRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
        raise OSError(ctypes.get_last_error(), "GetClientRect failed")
    origin = wintypes.POINT(0, 0)
    user32.ClientToScreen(wintypes.HWND(hwnd), ctypes.byref(origin))
    return Region(origin.x, origin.y, max(1, rect.right - rect.left), max(1, rect.bottom - rect.top))


def visible_window_rect(hwnd: int) -> Region | None:
    """Screen rectangle of a window, or None while it is hidden or minimized."""
    user32 = ctypes.windll.user32
    if not user32.IsWindowVisible(wintypes.HWND(hwnd)) or user32.IsIconic(wintypes.HWND(hwnd)):
        return None
    rect = wintypes.RECT()
    if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
        return None
    width, height = rect.right - rect.left, rect.bottom - rect.top
    return Region(rect.left, rect.top, width, height) if width > 0 and height > 0 else None


class Win32Desktop:
    """What the input guard needs to know about the desktop before clicking."""

    def __init__(self) -> None:
        user32 = ctypes.windll.user32
        user32.WindowFromPoint.restype = wintypes.HWND
        user32.WindowFromPoint.argtypes = [wintypes.POINT]
        user32.GetAncestor.restype = wintypes.HWND
        user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetForegroundWindow.restype = wintypes.HWND
        self._user32 = user32

    def window_at(self, x: int, y: int) -> int:
        """Top-level window under a screen point, or 0."""
        hwnd = self._user32.WindowFromPoint(wintypes.POINT(x, y))
        return (self._user32.GetAncestor(hwnd, GA_ROOT) or 0) if hwnd else 0

    def foreground_window(self) -> int:
        return self._user32.GetForegroundWindow() or 0

    def is_own_window(self, hwnd: int) -> bool:
        pid = wintypes.DWORD()
        self._user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
        return pid.value == os.getpid()

    def idle_seconds(self) -> float:
        """Time since the last mouse or keyboard input on this session."""
        info = _LastInputInfo(ctypes.sizeof(_LastInputInfo), 0)
        if not self._user32.GetLastInputInfo(ctypes.byref(info)):
            raise OSError(ctypes.get_last_error(), "GetLastInputInfo failed")
        elapsed_ms = (ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF
        return elapsed_ms / 1000
