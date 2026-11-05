"""What the interface shows, derived only from real application data.

Nothing here invents a result: a button reads "Working" only after a recognition check
recognized it, and every Activity entry is a real log line.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from loop.capture import Region
from loop.config import DEFAULT_HOTKEY, Mode
from loop.recognizer import Observation
from loop.screens import Button, Screen
from loop.state import SessionState, SessionStats

NEAR_MISS_MARGIN = 0.10


class Target(Enum):
    """The two buttons the interface asks for. Play / Ready covers both lobby buttons."""

    PLAY = "play"
    AGAIN = "again"

    @property
    def label(self) -> str:
        return "Play / Ready" if self is Target.PLAY else "Play Again"

    @property
    def short(self) -> str:
        return "Play" if self is Target.PLAY else "Play Again"

    @property
    def screen(self) -> Screen:
        return Screen.LOBBY if self is Target.PLAY else Screen.RESULTS

    @property
    def button(self) -> Button:
        """The button a new capture is saved as."""
        return Button.PLAY if self is Target.PLAY else Button.PLAY_AGAIN

    @property
    def buttons(self) -> set[Button]:
        """Saved buttons that count as this target."""
        return {Button.PLAY, Button.READY} if self is Target.PLAY else {Button.PLAY_AGAIN}

    @property
    def place(self) -> str:
        return "lobby" if self is Target.PLAY else "results screen"

    @property
    def other(self) -> Target:
        return Target.AGAIN if self is Target.PLAY else Target.PLAY


TARGETS = (Target.PLAY, Target.AGAIN)


class Check(Enum):
    NONE = "Not set up"
    UNCHECKED = "Not checked"
    WORKING = "Working"
    ADJUST = "Needs adjustment"

    @property
    def tone(self) -> str:
        return {Check.NONE: "none", Check.UNCHECKED: "info", Check.WORKING: "ok", Check.ADJUST: "warn"}[self]


def saved_targets(buttons: set[Button]) -> set[Target]:
    return {t for t in TARGETS if t.buttons & buttons}


@dataclass
class ButtonChecks:
    """Each target's check status. Saving or replacing a button resets it to Not checked."""

    statuses: dict[Target, Check] = field(default_factory=lambda: dict.fromkeys(TARGETS, Check.NONE))

    def sync(self, saved: set[Target]) -> None:
        for target in TARGETS:
            if target not in saved:
                self.statuses[target] = Check.NONE
            elif self.statuses[target] is Check.NONE:
                self.statuses[target] = Check.UNCHECKED

    def reset(self, target: Target) -> None:
        self.statuses[target] = Check.UNCHECKED

    def __getitem__(self, target: Target) -> Check:
        return self.statuses[target]


@dataclass
class ViewState:
    """Everything the pages render, mirrored from the controller, settings, and checks."""

    session: SessionState = SessionState.IDLE
    error: str = ""
    mode: Mode = Mode.LIVE
    emergency: bool = False  # the emergency stop was used since the last start
    saved: set[Target] = field(default_factory=set)
    checks: ButtonChecks = field(default_factory=ButtonChecks)
    stats: SessionStats = field(default_factory=SessionStats)
    elapsed: float = 0.0
    screen: str = ""  # the recognized screen while a session runs; "" while searching
    flash: str = ""  # a brief note about what is on screen right now
    hotkey: str = DEFAULT_HOTKEY

    @property
    def active(self) -> bool:
        return self.session in (SessionState.RUNNING, SessionState.PAUSED)


@dataclass(frozen=True)
class CheckOutcome:
    """One recognition check: the screen it looks like, and a verdict per saved target."""

    screen: Screen | None
    results: dict[Target, Check]


def evaluate(observation: Observation, saved: set[Target], threshold: float) -> CheckOutcome:
    """Turns one recognition of the current screen into button verdicts. Never clicks."""
    results: dict[Target, Check] = {}
    for target in TARGETS:
        if target not in saved:
            continue
        screen = target.screen
        if observation.screen is screen and observation.match is not None:
            results[target] = Check.WORKING
        elif observation.screen is Screen.UNKNOWN and (
            (observation.ambiguous and screen in observation.ambiguous)
            or screen in observation.lookalikes
            or observation.scores.get(screen, 0.0) >= threshold - NEAR_MISS_MARGIN
        ):
            results[target] = Check.ADJUST
    if observation.screen in (Screen.LOBBY, Screen.RESULTS):
        shown: Screen | None = observation.screen
    else:
        shown = next((t.screen for t, r in results.items() if r is Check.ADJUST), None)
    return CheckOutcome(shown, results)


def describe_check(observation: Observation, threshold: float) -> str:
    """The technical description of a check, for the log."""
    screen, scores = observation.screen, observation.scores
    others = ", ".join(f"{s.label} {score:.2f}" for s, score in scores.items() if s is not screen)
    if observation.ambiguous:
        first, second = observation.ambiguous
        head = f"Ambiguous: '{first.label}' and '{second.label}' templates match the same area."
    elif screen is Screen.UNKNOWN:
        head = f"No screen recognized above the {threshold:.2f} threshold."
    else:
        head = f"Recognized '{screen.label}' at {scores[screen]:.3f}."
    if observation.lookalikes:
        names = ", ".join(f"'{s.label}'" for s in observation.lookalikes)
        head += f" Ignored a look-alike for {names}: the shape matches but the colors do not."
    return f"{head} Scores: {others}." if others else head


def region_in(region: Region | None, origin: Region) -> Region | None:
    """`region` in the coordinates of a screenshot of `origin`, if it lies inside it."""
    if region is None or not origin.contains(region):
        return None
    return region.offset(-origin.left, -origin.top)


# Activity: log lines → readable entries


@dataclass(frozen=True)
class Entry:
    time: str
    level: str
    message: str
    kind: str  # detect, click, ok, warn, error, info
    title: str


def _first_sentence(message: str) -> str:
    index = message.find(". ")
    return message[: index + 1] if index > 0 else message


def classify(level: str, message: str) -> tuple[str, str]:
    """The kind of a log line and a short, plain title for it."""
    if level in ("ERROR", "CRITICAL"):
        return "error", _first_sentence(message)
    if m := re.match(r"Clicked '([^']+)'", message):
        return "click", f"Clicked {m[1]}"
    if m := re.match(r"Action verified: .+? → (.+)$", message):
        return "ok", f"Click confirmed · now on {m[1]}"
    if level == "WARNING":
        return "warn", _first_sentence(message)
    if m := re.match(r"Screen: (.+?) → (.+?)(?: \(\d\.\d+\))?$", message):
        if m[2] == "Unknown":
            return "info", f"Left the {m[1]} screen"
        return "detect", f"Recognized the {m[2]} screen"
    if message.startswith("Saved the "):
        return "ok", _first_sentence(message)
    return "info", _first_sentence(message)


def make_entry(time: str, level: str, message: str) -> Entry:
    kind, title = classify(level, message)
    return Entry(time, level, message, kind, title)


FILTERS = {
    "all": lambda e: True,
    "click": lambda e: e.kind == "click" or (e.kind == "ok" and e.title.startswith("Click")),
    "warn": lambda e: e.kind == "warn",
    "error": lambda e: e.kind == "error",
}


def format_clock(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"


def short_clock(seconds: float) -> str:
    total = int(seconds)
    return format_clock(total) if total >= 3600 else f"{total // 60:02d}:{total % 60:02d}"
