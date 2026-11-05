"""Background scan loop: capture, recognize, decide, and (when allowed) click."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Protocol

import numpy as np
from PySide6.QtCore import QThread, Signal

from loop.capture import CaptureError, Region, ScreenCapture
from loop.input_guard import ClickTarget, InputBlocked, InputDeferred, InputFailed, InputGuard
from loop.matcher import Template, TemplateError
from loop.policy import ActionPolicy, Event, EventKind
from loop.recognizer import Observation, Recognizer
from loop.screens import Screen

log = logging.getLogger(__name__)

MAX_CONSECUTIVE_FAILURES = 5


class Capture(Protocol):
    def grab(self, region: Region) -> np.ndarray: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class ScanPlan:
    templates: Mapping[Screen, tuple[Template, ...]]
    threshold: float
    interval_s: float
    region: Callable[[], Region | None]
    display_height: int
    actions: frozenset[Screen] = frozenset()  # empty: observe only
    cooldown_s: float = 2.0
    verify_timeout_s: float = 5.0
    click_target: ClickTarget | None = None  # installed by the controller for live interaction
    masked: Callable[[], Sequence[Region]] | None = None  # screen areas to blank out of each capture

    @property
    def interacts(self) -> bool:
        return bool(self.actions)


class SessionAborted(Exception):
    pass


class ScanWorker(QThread):
    observed = Signal(object)  # Observation
    event = Signal(object)  # Event
    note = Signal(str)
    problem = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        plan: ScanPlan,
        guard: InputGuard,
        capture_factory: Callable[[], Capture] = ScreenCapture,
    ) -> None:
        super().__init__()
        self._plan = plan
        self._guard = guard
        self._capture_factory = capture_factory
        self._recognizer = Recognizer(plan.templates, plan.threshold, plan.display_height)
        self._policy = ActionPolicy(plan.actions, plan.threshold, plan.cooldown_s, plan.verify_timeout_s)
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._resumed = threading.Event()
        self._last_note = ""

    def request_stop(self) -> None:
        self._stop.set()

    def set_paused(self, paused: bool) -> None:
        if paused:
            self._paused.set()
        else:
            self._paused.clear()
            self._resumed.set()

    def run(self) -> None:
        try:
            capture = self._capture_factory()
        except Exception as exc:
            log.exception("Screen capture could not be initialised")
            self.failed.emit(f"Screen capture could not be initialised: {exc}")
            return
        try:
            self._loop(capture)
        finally:
            capture.close()

    def _loop(self, capture: Capture) -> None:
        failures = 0
        while not self._stop.is_set():
            if self._paused.is_set():
                self._stop.wait(0.05)
                continue
            if self._resumed.is_set():
                # Time spent paused must not count against a click awaiting verification.
                self._resumed.clear()
                self._policy.cancel_pending()
            started = time.monotonic()
            try:
                self._scan_once(capture)
                failures = 0
            except (SessionAborted, InputFailed) as exc:
                # A failed click leaves the guard disarmed, so carrying on would only pretend to run.
                self.failed.emit(str(exc))
                return
            except (CaptureError, TemplateError, InputBlocked) as exc:
                failures += 1
                self.problem.emit(str(exc))
                if failures >= MAX_CONSECUTIVE_FAILURES:
                    self.failed.emit(f"Stopped after {failures} consecutive failures. Last: {exc}")
                    return
            except Exception as exc:
                log.exception("Unexpected error in scan loop")
                self.failed.emit(f"Unexpected error: {exc}")
                return
            remaining = self._plan.interval_s - (time.monotonic() - started)
            if remaining > 0:
                self._stop.wait(remaining)

    def _scan_once(self, capture: Capture) -> None:
        region = self._plan.region()
        if region is None:
            raise CaptureError("The scan target is no longer available")
        frame = capture.grab(region)
        if self._plan.masked is not None:
            for area in self._plan.masked():
                _blank(frame, area.offset(-region.left, -region.top))
        observation = self._recognizer.observe(frame)
        step = self._policy.update(observation)
        self.observed.emit(_as_confirmed(observation, self._policy.screen))
        for event in step.events:
            self.event.emit(event)
        if step.give_up:
            raise SessionAborted(step.give_up)
        if step.click is not None:
            target = observation.match.template if observation.match else ""
            self._click(step.click.offset(region.left, region.top), observation.screen, target)

    def _click(self, box: Region, screen: Screen, target: str) -> None:
        if not self._guard.armed or self._paused.is_set() or self._stop.is_set():
            self._policy.cancel_pending()
            return
        x, y = box.center
        try:
            self._guard.click(x, y)
        except InputDeferred as exc:
            self._policy.cancel_pending()
            self._note(str(exc))
            return
        except InputBlocked:
            self._policy.cancel_pending()
            raise
        self._last_note = ""
        self.event.emit(Event(EventKind.CLICKED, screen, point=(x, y), target=target))

    def _note(self, message: str) -> None:
        if message != self._last_note:
            self._last_note = message
            self.note.emit(message)


def _blank(frame: np.ndarray, area: Region) -> None:
    """Fills `area` (frame coordinates, possibly partly outside the frame) with black."""
    h, w = frame.shape[:2]
    left, top = max(area.left, 0), max(area.top, 0)
    right, bottom = min(area.right, w), min(area.bottom, h)
    if left < right and top < bottom:
        frame[top:bottom, left:right] = 0


def _as_confirmed(observation: Observation, screen: Screen) -> Observation:
    """The observation as the UI should show it: the confirmed screen, with its match if seen now."""
    if observation.screen is screen:
        return observation
    return replace(observation, screen=screen, match=None)
