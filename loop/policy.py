"""Decides which screen is showing, when to act on it, and whether the action worked.

Pure logic with an injectable clock, so every rule here is testable without timing.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto

from loop.capture import Region
from loop.recognizer import Observation
from loop.screens import Screen, is_expected

# A different screen must be seen on this many consecutive scans before LOOP accepts it,
# so one odd frame (mid-transition, an animation, a notification) never changes the state.
CONFIRM_SCANS = 2
# The confirmed screen, with its button, must be seen on this many consecutive scans
# before LOOP acts on it.
STABLE_SCANS = 2
MAX_ATTEMPTS = 3
# Scores this far below the threshold are reported once, as a hint that a template is outdated.
NEAR_MISS_MARGIN = 0.10
# The confirmed screen is kept, though not acted on, while its button scores within this
# margin below the threshold or looks right in shape but not in color.
HOLD_MARGIN = 0.05


class EventKind(Enum):
    SCREEN_CHANGED = auto()
    AMBIGUOUS = auto()
    LOOKALIKE = auto()
    NEAR_MISS = auto()
    CLICKED = auto()
    VERIFIED = auto()
    UNVERIFIED = auto()


@dataclass(frozen=True)
class Event:
    kind: EventKind
    screen: Screen
    other: Screen | None = None  # previous screen, competing screen, or screen after an action
    confidence: float = 0.0
    unexpected: bool = False
    attempt: int = 0
    point: tuple[int, int] | None = None
    target: str = ""  # the template that was clicked


@dataclass(frozen=True)
class Step:
    events: tuple[Event, ...] = ()
    click: Region | None = None  # box to click, in captured-frame coordinates
    give_up: str = ""


@dataclass
class _Pending:
    screen: Screen
    box: Region
    clicked_at: float
    scans: int = 0  # scans seen since the click


class ActionPolicy:
    def __init__(
        self,
        actions: frozenset[Screen],
        threshold: float,
        cooldown_s: float,
        verify_timeout_s: float,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._actions = actions
        self._threshold = threshold
        self._cooldown_s = cooldown_s
        self._verify_timeout_s = verify_timeout_s
        self._now = now
        self.screen = Screen.UNKNOWN  # the confirmed screen
        self._stable_scans = 0
        self._candidate = Screen.UNKNOWN
        self._candidate_scans = 0
        self._pending: _Pending | None = None
        self._attempts = 0
        self._last_action_at = -math.inf
        self._ambiguous: tuple[Screen, Screen] | None = None
        self._lookalikes: set[Screen] = set()
        self._near_misses: set[Screen] = set()

    def update(self, obs: Observation) -> Step:
        events: list[Event] = []
        self._note_ambiguity(obs, events)
        self._note_lookalikes(obs, events)
        self._note_near_misses(obs, events)
        self._track_screen(obs, events)
        if self._pending is not None:
            give_up = self._check_pending(obs, events)
            if give_up or self._pending is not None:
                return Step(tuple(events), give_up=give_up)
        return Step(tuple(events), self._choose_click(obs))

    def cancel_pending(self) -> None:
        """Forget a click that was proposed but not performed. The cooldown still applies."""
        self._pending = None

    def _track_screen(self, obs: Observation, events: list[Event]) -> None:
        if obs.screen is self.screen:
            self._candidate_scans = 0
            self._stable_scans += 1
            return
        self._stable_scans = 0
        if self._holds(obs):
            self._candidate_scans = 0
            return
        if obs.screen is self._candidate and self._candidate_scans:
            self._candidate_scans += 1
        else:
            self._candidate, self._candidate_scans = obs.screen, 1
        if self._candidate_scans < CONFIRM_SCANS:
            return
        events.append(
            Event(
                EventKind.SCREEN_CHANGED,
                obs.screen,
                other=self.screen,
                confidence=obs.confidence,
                unexpected=not is_expected(self.screen, obs.screen),
            )
        )
        self.screen = obs.screen
        self._stable_scans = self._candidate_scans
        self._candidate_scans = 0

    def _holds(self, obs: Observation) -> bool:
        """Whether an unrecognized frame is just the confirmed screen's button looking uncertain."""
        if self.screen is Screen.UNKNOWN or obs.screen is not Screen.UNKNOWN or obs.ambiguous:
            return False
        near = obs.scores.get(self.screen, 0.0) >= self._threshold - HOLD_MARGIN
        return near or self.screen in obs.lookalikes

    def _check_pending(self, obs: Observation, events: list[Event]) -> str:
        pending = self._pending
        assert pending is not None
        pending.scans += 1
        moved = obs.screen is pending.screen and obs.match is not None and _moved(obs.match.box, pending.box)
        if self.screen is not pending.screen or moved:
            events.append(Event(EventKind.VERIFIED, pending.screen, other=self.screen))
            self._pending = None
            self._attempts = 0
            return ""
        # A change needs CONFIRM_SCANS scans to be accepted, so slow scans get more time.
        if self._now() - pending.clicked_at < self._verify_timeout_s or pending.scans <= CONFIRM_SCANS:
            return ""
        self._pending = None
        self._attempts += 1
        events.append(Event(EventKind.UNVERIFIED, pending.screen, attempt=self._attempts))
        if self._attempts >= MAX_ATTEMPTS:
            return (
                f"Pressing '{pending.screen.label}' did not change the screen after {MAX_ATTEMPTS} attempts"
            )
        return ""

    def _choose_click(self, obs: Observation) -> Region | None:
        if obs.screen not in self._actions or obs.screen is not self.screen or obs.match is None:
            return None
        if self._stable_scans < STABLE_SCANS:
            return None
        now = self._now()
        if now - self._last_action_at < self._cooldown_s:
            return None
        self._pending = _Pending(obs.screen, obs.match.box, now)
        self._last_action_at = now
        return obs.match.box

    def _note_ambiguity(self, obs: Observation, events: list[Event]) -> None:
        if obs.ambiguous and obs.ambiguous != self._ambiguous:
            first, second = obs.ambiguous
            events.append(Event(EventKind.AMBIGUOUS, first, other=second, confidence=obs.scores[first]))
        self._ambiguous = obs.ambiguous

    def _note_lookalikes(self, obs: Observation, events: list[Event]) -> None:
        for screen, confidence in obs.lookalikes.items():
            if screen not in self._lookalikes:
                events.append(Event(EventKind.LOOKALIKE, screen, confidence=confidence))
        self._lookalikes = set(obs.lookalikes)

    def _note_near_misses(self, obs: Observation, events: list[Event]) -> None:
        for screen, score in obs.scores.items():
            near = self._threshold - NEAR_MISS_MARGIN <= score < self._threshold
            if near and screen not in self._near_misses:
                self._near_misses.add(screen)
                events.append(Event(EventKind.NEAR_MISS, screen, confidence=score))


def _moved(a: Region, b: Region) -> bool:
    (ax, ay), (bx, by) = a.center, b.center
    return math.hypot(ax - bx, ay - by) > max(8, min(b.width, b.height) / 2)
