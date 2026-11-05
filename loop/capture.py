"""Screen regions and screenshot capture."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import mss
import numpy as np
from mss.exception import ScreenShotError

MIN_REGION_SIZE = 16


class CaptureError(Exception):
    pass


@dataclass(frozen=True)
class Region:
    """A rectangle in physical desktop pixels (the coordinate space used by mss and Win32)."""

    left: int
    top: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Region width and height must be positive")

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    @property
    def center(self) -> tuple[int, int]:
        return self.left + self.width // 2, self.top + self.height // 2

    def contains_point(self, x: int, y: int) -> bool:
        return self.left <= x < self.right and self.top <= y < self.bottom

    def contains(self, other: Region) -> bool:
        return (
            self.left <= other.left
            and self.top <= other.top
            and other.right <= self.right
            and other.bottom <= self.bottom
        )

    def offset(self, dx: int, dy: int) -> Region:
        return Region(self.left + dx, self.top + dy, self.width, self.height)

    def describe(self) -> str:
        return f"{self.width} × {self.height} at ({self.left}, {self.top})"

    def to_dict(self) -> dict[str, int]:
        return {"left": self.left, "top": self.top, "width": self.width, "height": self.height}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Region:
        values = [data[k] for k in ("left", "top", "width", "height")]
        if not all(isinstance(v, int) and not isinstance(v, bool) for v in values):
            raise TypeError("Region values must be integers")
        return cls(*values)


def display_for(region: Region, monitors: list[Region]) -> Region:
    """The display that fully contains the region. Raises CaptureError if the region is unusable."""
    if region.width < MIN_REGION_SIZE or region.height < MIN_REGION_SIZE:
        raise CaptureError(
            f"Scan region is too small ({region.width} × {region.height}). "
            f"Select at least {MIN_REGION_SIZE} × {MIN_REGION_SIZE} pixels."
        )
    for monitor in monitors:
        if monitor.contains(region):
            return monitor
    raise CaptureError(
        "Scan region is not fully inside a connected display. "
        "A display may have been disconnected or rearranged; reselect the region."
    )


class ScreenCapture:
    """Owns one mss handle. mss handles are per-thread, so create this in the thread that uses it."""

    def __init__(self) -> None:
        self._sct = mss.MSS()

    def monitors(self) -> list[Region]:
        """Connected displays in mss order; list index 0 is display 1."""
        return [Region(m["left"], m["top"], m["width"], m["height"]) for m in self._sct.monitors[1:]]

    def grab(self, region: Region) -> np.ndarray:
        """Returns a BGR image of the region."""
        display_for(region, self.monitors())
        try:
            shot = self._sct.grab(region.to_dict())
        except ScreenShotError as exc:
            raise CaptureError(
                "Screen capture failed. The desktop may be locked, or a secure prompt "
                f"(such as UAC) may be on screen. Details: {exc}"
            ) from exc
        return np.ascontiguousarray(np.asarray(shot)[:, :, :3])

    def close(self) -> None:
        self._sct.close()

    def __enter__(self) -> ScreenCapture:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def list_monitors() -> list[Region]:
    try:
        with ScreenCapture() as capture:
            return capture.monitors()
    except ScreenShotError as exc:
        raise CaptureError(f"Connected displays could not be listed: {exc}") from exc
