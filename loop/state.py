"""Session state machine, clock, and counters. Free of Qt so it can be tested directly."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum


class SessionState(Enum):
    IDLE = "Idle"
    RUNNING = "Running"
    PAUSED = "Paused"
    STOPPED = "Stopped"
    ERROR = "Error"


class Command(Enum):
    START = "start"
    PAUSE = "pause"
    RESUME = "resume"
    STOP = "stop"
    FAIL = "fail"


class InvalidTransition(Exception):
    pass


_S = SessionState
_TRANSITIONS: dict[Command, tuple[frozenset[SessionState], SessionState]] = {
    Command.START: (frozenset({_S.IDLE, _S.STOPPED, _S.ERROR}), _S.RUNNING),
    Command.PAUSE: (frozenset({_S.RUNNING}), _S.PAUSED),
    Command.RESUME: (frozenset({_S.PAUSED}), _S.RUNNING),
    Command.STOP: (frozenset({_S.RUNNING, _S.PAUSED}), _S.STOPPED),
    Command.FAIL: (frozenset(SessionState), _S.ERROR),
}


class SessionMachine:
    def __init__(self) -> None:
        self.state = SessionState.IDLE

    def can(self, command: Command) -> bool:
        allowed_from, _ = _TRANSITIONS[command]
        return self.state in allowed_from

    def apply(self, command: Command) -> SessionState:
        allowed_from, target = _TRANSITIONS[command]
        if self.state not in allowed_from:
            raise InvalidTransition(f"Cannot {command.value} while {self.state.value.lower()}")
        self.state = target
        return target


class SessionClock:
    """Measures active session time, excluding paused intervals."""

    def __init__(self, now: Callable[[], float] = time.monotonic) -> None:
        self._now = now
        self._started_at: float | None = None
        self._paused_at: float | None = None
        self._paused_total = 0.0
        self._frozen: float | None = None

    def start(self) -> None:
        self._started_at = self._now()
        self._paused_at = None
        self._paused_total = 0.0
        self._frozen = None

    def pause(self) -> None:
        if self._started_at is not None and self._paused_at is None:
            self._paused_at = self._now()

    def resume(self) -> None:
        if self._paused_at is not None:
            self._paused_total += self._now() - self._paused_at
            self._paused_at = None

    def stop(self) -> None:
        if self._started_at is not None:
            self._frozen = self.elapsed()
            self._started_at = None

    def elapsed(self) -> float:
        if self._frozen is not None:
            return self._frozen
        if self._started_at is None:
            return 0.0
        end = self._paused_at if self._paused_at is not None else self._now()
        return end - self._started_at - self._paused_total


@dataclass
class SessionStats:
    detections: int = 0
    interactions: int = 0
    errors: int = 0
