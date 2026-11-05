"""The connected displays, and screenshots taken while Loopter steps out of the way."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget

from loop.capture import CaptureError, Region, ScreenCapture, list_monitors

log = logging.getLogger(__name__)

# Time for the window to disappear before the screenshot is taken.
HIDE_DELAY_MS = 300


@dataclass(frozen=True)
class Display:
    number: int  # from 1, in the order Windows reports them
    region: Region

    @property
    def name(self) -> str:
        return f"Display {self.number}"

    @property
    def primary(self) -> bool:
        return (self.region.left, self.region.top) == (0, 0)

    @property
    def size(self) -> str:
        return f"{self.region.width} × {self.region.height}"


def list_displays() -> list[Display]:
    try:
        monitors = list_monitors()
    except CaptureError as exc:
        log.error("Could not list displays: %s", exc)
        return []
    return [Display(number, region) for number, region in enumerate(monitors, start=1)]


def display_for(number: int, displays: list[Display]) -> Display | None:
    """The chosen display, or the closest one if it is no longer connected."""
    if not displays:
        return None
    return displays[min(max(number, 1), len(displays)) - 1]


def default_display(displays: list[Display]) -> Display | None:
    return next((d for d in displays if d.primary), displays[0] if displays else None)


def grab_hidden(widget: QWidget, region: Region, done: Callable[[np.ndarray | None, str], None]) -> None:
    """Hides the window, captures `region`, shows the window again, then calls done(frame, error)."""
    window = widget.window()
    window.hide()

    def finish() -> None:
        frame, error = None, ""
        try:
            with ScreenCapture() as capture:
                frame = capture.grab(region)
        except CaptureError as exc:
            error = str(exc)
        finally:
            window.show()
            window.raise_()
            window.activateWindow()
        done(frame, error)

    QTimer.singleShot(HIDE_DELAY_MS, finish)
