"""The demo scenario: lobby, matchmaking, loading, match, results, finding the next match, and on.

Only the lobby (Play) and the results (Play Again) have a button to press; every other
screen moves on by itself after a while, like the real thing.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

import numpy as np

from loop.capture import Region
from loop.matcher import read_image
from loop.screens import ACTIONABLE, Screen
from tests.simulation import SCREENS_DIR, TEMPLATE_FILES, TEMPLATES_DIR


@dataclass(frozen=True)
class DemoScreen:
    name: str
    state: Screen
    next: str
    auto_advance_ms: int = 0

    @property
    def has_button(self) -> bool:
        return self.state in ACTIONABLE


DEMO_SCREENS = (
    DemoScreen("lobby", Screen.LOBBY, "matchmaking"),
    DemoScreen("matchmaking", Screen.MATCHMAKING, "loading", auto_advance_ms=1800),
    DemoScreen("loading", Screen.LOADING, "match", auto_advance_ms=1400),
    DemoScreen("match", Screen.UNKNOWN, "results", auto_advance_ms=2400),
    DemoScreen("results", Screen.RESULTS, "finding"),
    DemoScreen("finding", Screen.FINDING_MATCH, "loading", auto_advance_ms=1800),
)
_BY_NAME = {s.name: i for i, s in enumerate(DEMO_SCREENS)}

# Where each button may appear. It moves a little every time, so nothing relies on fixed coordinates.
BUTTON_AREAS = {
    Screen.LOBBY: Region(52, 404, 256, 96),
    Screen.RESULTS: Region(600, 232, 320, 114),
}


class DemoScenario:
    """Pure model of the demo: which screen is shown and where its button is."""

    def __init__(self, rng: random.Random | None = None) -> None:
        self._rng = rng or random.Random()
        self._backgrounds = {s.name: read_image(SCREENS_DIR / f"{s.name}.png") for s in DEMO_SCREENS}
        # Every button a screen can show; the lobby shows Play or, as in a party, Ready.
        self._buttons = {
            s.state: [(name, read_image(TEMPLATES_DIR / file)) for name, file in TEMPLATE_FILES[s.state]]
            for s in DEMO_SCREENS
            if s.has_button
        }
        self.index = 0
        self.matches = 0  # matches played to the end
        self.button_box: Region | None = None
        self.button_name = ""
        self._button_image: np.ndarray | None = None
        self._place_button()

    @property
    def screen(self) -> DemoScreen:
        return DEMO_SCREENS[self.index]

    def advance(self) -> None:
        self.index = _BY_NAME[self.screen.next]
        if self.screen.state is Screen.RESULTS:
            self.matches += 1
        self._place_button()

    def show(self, name: str) -> None:
        """Jumps to a screen, as when the game does something unexpected."""
        self.index = _BY_NAME[name]
        self._place_button()

    def press(self, x: int, y: int) -> bool:
        """Handles a click in image coordinates; returns True if it hit the button."""
        if self.button_box is None or not self.button_box.contains_point(x, y):
            return False
        self.advance()
        return True

    def render(self) -> np.ndarray:
        frame = self._backgrounds[self.screen.name].copy()
        if self.button_box is not None:
            b = self.button_box
            frame[b.top : b.bottom, b.left : b.right] = self._button_image
        return frame

    def _place_button(self) -> None:
        if not self.screen.has_button:
            self.button_box, self.button_name, self._button_image = None, "", None
            return
        area = BUTTON_AREAS[self.screen.state]
        self.button_name, self._button_image = self._rng.choice(self._buttons[self.screen.state])
        h, w = self._button_image.shape[:2]
        x = self._rng.randint(area.left, area.right - w)
        y = self._rng.randint(area.top, area.bottom - h)
        self.button_box = Region(x, y, w, h)
