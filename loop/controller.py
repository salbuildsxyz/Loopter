"""Session controller: owns the state machine, the scan worker, and session statistics."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace

from PySide6.QtCore import QObject, Signal, Slot

from loop.capture import CaptureError, Region, ScreenCapture, display_for, list_monitors
from loop.config import Mode, Settings, templates_dir
from loop.demo import SCREEN_SIZE, demo_templates
from loop.input_guard import ClickTarget, InputGuard
from loop.policy import MAX_ATTEMPTS, Event, EventKind
from loop.recognizer import Observation
from loop.screens import ACTION_LABELS, Screen
from loop.state import Command, SessionClock, SessionMachine, SessionState, SessionStats
from loop.templates import TemplateLibrary
from loop.worker import Capture, ScanPlan, ScanWorker

log = logging.getLogger(__name__)


class SetupError(Exception):
    pass


def build_plan(
    settings: Settings,
    guard: InputGuard,
    monitors: list[Region] | None = None,
    own_windows: Callable[[], list[Region]] | None = None,
) -> ScanPlan:
    """Turns settings into a scan plan, or raises SetupError with a message for the user.

    Without a scan region, live modes scan the whole selected display. `own_windows`
    lists LOOP's windows, which are blanked out of every capture so LOOP never
    recognizes its own screenshot preview.
    """
    common = {
        "threshold": settings.threshold,
        "interval_s": settings.scan_interval_ms / 1000,
        "cooldown_s": settings.cooldown_s,
    }
    if settings.mode is Mode.DEMO:
        if guard.target is None:
            raise SetupError("The demo target window is not open")
        actions = frozenset(settings.actions) if settings.demo_clicks_enabled else frozenset()
        return ScanPlan(
            templates=demo_templates(),
            region=lambda: target.region if (target := guard.target) else None,
            display_height=SCREEN_SIZE[1],
            actions=actions,
            **common,
        )

    try:
        monitors = monitors if monitors is not None else list_monitors()
        region = settings.region or _whole_display(settings.monitor, monitors)
        display = display_for(region, monitors)
    except CaptureError as exc:
        raise SetupError(str(exc)) from exc
    templates = _load_user_templates(settings)
    common |= {"region": lambda: region, "display_height": display.height, "masked": own_windows}
    if settings.mode is Mode.LIVE:
        # Live Monitor never interacts, regardless of any other setting.
        return ScanPlan(templates=templates, **common)

    actions = frozenset(settings.actions)
    if not actions & templates.keys():
        raise SetupError(
            "Live Interaction has nothing it could press. Save a Play or Ready template (Lobby) or a "
            "Play Again template (Results) in Setup, and enable it in Settings."
        )
    for screen in sorted(actions - templates.keys(), key=lambda s: s.value):
        log.warning("No usable template for '%s'; that action cannot trigger", ACTION_LABELS[screen])
    return ScanPlan(
        templates=templates,
        actions=actions,
        click_target=ClickTarget(region, require_user_idle=True),
        **common,
    )


def _whole_display(number: int, monitors: list[Region]) -> Region:
    if not monitors:
        raise CaptureError("No display is connected")
    return monitors[min(max(number, 1), len(monitors)) - 1]


def _load_user_templates(settings: Settings) -> dict[Screen, tuple]:
    library = TemplateLibrary(templates_dir(), settings.templates)
    groups, problems = library.load()
    for problem in problems:
        log.warning("Skipping template: %s", problem)
    if not groups:
        raise SetupError(
            "No usable templates. Open Setup, capture the lobby or the results screen, "
            "and save the button LOOP finds."
        )
    conflicts = library.conflicts()
    if conflicts:
        # Contradictory templates could report the wrong screen with high confidence.
        raise SetupError(" ".join(conflicts))
    return {screen: tuple(group) for screen, group in groups.items()}


class SessionController(QObject):
    state_changed = Signal(object)  # SessionState
    stats_changed = Signal(object)  # SessionStats
    observed = Signal(object)  # Observation

    def __init__(
        self,
        guard: InputGuard,
        plan_builder: Callable[[], ScanPlan],
        capture_factory: Callable[[], Capture] = ScreenCapture,
    ) -> None:
        super().__init__()
        self._guard = guard
        self._plan_builder = plan_builder
        self._capture_factory = capture_factory
        self._machine = SessionMachine()
        self._clock = SessionClock()
        self._stats = SessionStats()
        self._plan: ScanPlan | None = None
        self._worker: ScanWorker | None = None
        self._retired: list[ScanWorker] = []
        self.last_error = ""

    @property
    def state(self) -> SessionState:
        return self._machine.state

    @property
    def stats(self) -> SessionStats:
        return replace(self._stats)

    def elapsed(self) -> float:
        return self._clock.elapsed()

    def start(self) -> None:
        if not self._machine.can(Command.START):
            return
        try:
            plan = self._plan_builder()
        except SetupError as exc:
            self._fail(str(exc))
            return
        self._stats = SessionStats()
        self.stats_changed.emit(self.stats)
        self.last_error = ""
        self._plan = plan
        if plan.click_target is not None:
            self._guard.set_target(plan.click_target)
        worker = ScanWorker(plan, self._guard, self._capture_factory)
        worker.observed.connect(self._on_observed)
        worker.event.connect(self._on_event)
        worker.note.connect(self._on_note)
        worker.problem.connect(self._on_problem)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(self._on_finished)
        self._worker = worker
        self._clock.start()
        self._transition(Command.START)
        self._set_armed(True)
        worker.start()
        log.info(
            "Session started: %d screen(s) with templates, threshold %.2f, interval %d ms, clicks %s",
            len(plan.templates),
            plan.threshold,
            round(plan.interval_s * 1000),
            _describe_actions(plan.actions),
        )

    def pause(self) -> None:
        if self._worker and self._machine.can(Command.PAUSE):
            self._set_armed(False)
            self._worker.set_paused(True)
            self._clock.pause()
            self._transition(Command.PAUSE)
            log.info("Session paused")

    def resume(self) -> None:
        if self._worker and self._machine.can(Command.RESUME):
            self._worker.set_paused(False)
            self._clock.resume()
            self._transition(Command.RESUME)
            self._set_armed(True)
            log.info("Session resumed")

    def stop(self) -> None:
        if not self._machine.can(Command.STOP):
            return
        self._end_session()
        self._transition(Command.STOP)
        log.info("Session stopped after %s", format_duration(self._clock.elapsed()))

    def emergency_stop(self) -> None:
        self._guard.disarm()
        was_active = self._machine.state in (SessionState.RUNNING, SessionState.PAUSED)
        self.stop()
        log.warning("Emergency stop: %sclicks disabled", "session stopped and " if was_active else "")

    def shutdown(self) -> None:
        self._end_session()
        for worker in self._retired:
            worker.wait(3000)

    def _set_armed(self, armed: bool) -> None:
        if armed and self._plan is not None and self._plan.interacts:
            self._guard.arm()
        else:
            self._guard.disarm()

    def _end_session(self) -> None:
        self._guard.disarm()
        if self._plan is not None and self._plan.click_target is not None:
            self._guard.set_target(None)
        self._plan = None
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.request_stop()
            self._retired.append(worker)
        self._clock.stop()

    @Slot()
    def _on_finished(self) -> None:
        worker = self.sender()
        # `finished` can arrive just before the thread fully exits; dropping the last
        # reference to a running QThread aborts the process, so wait first.
        worker.wait()
        if worker in self._retired:
            self._retired.remove(worker)

    def _fail(self, message: str) -> None:
        self.last_error = message
        self._end_session()
        self._transition(Command.FAIL)
        log.error(message)

    def _transition(self, command: Command) -> None:
        self.state_changed.emit(self._machine.apply(command))

    def _counts(self) -> bool:
        # Signals from a stopped worker can still be queued, and a scan already in
        # flight when Pause is pressed should not change the numbers.
        sender = self.sender()
        return sender is not None and sender is self._worker and self._machine.state is SessionState.RUNNING

    @Slot(object)
    def _on_observed(self, observation: Observation) -> None:
        if self._counts():
            self.observed.emit(observation)

    @Slot(object)
    def _on_event(self, event: Event) -> None:
        if not self._counts():
            return
        if event.kind is EventKind.SCREEN_CHANGED and event.screen is not Screen.UNKNOWN:
            self._stats.detections += 1
        elif event.kind is EventKind.VERIFIED:
            self._stats.interactions += 1
        elif event.kind is EventKind.UNVERIFIED:
            self._stats.errors += 1
        self.stats_changed.emit(self.stats)
        level, message = describe_event(event)
        log.log(level, message)

    @Slot(str)
    def _on_note(self, message: str) -> None:
        if self._counts():
            log.info(message)

    @Slot(str)
    def _on_problem(self, message: str) -> None:
        if self._counts():
            self._stats.errors += 1
            self.stats_changed.emit(self.stats)
            log.warning(message)

    @Slot(str)
    def _on_failed(self, message: str) -> None:
        if self.sender() is self._worker:
            self._fail(message)


def describe_event(event: Event) -> tuple[int, str]:
    """Log level and message for a session event."""
    screen = event.screen.label
    other = event.other.label if event.other else ""
    match event.kind:
        case EventKind.SCREEN_CHANGED:
            # An unknown screen has no confidence of its own; the best other score would mislead.
            score = f" ({event.confidence:.3f})" if event.screen is not Screen.UNKNOWN else ""
            if event.unexpected:
                return logging.WARNING, f"Unexpected screen change: {other} → {screen}{score}"
            return logging.INFO, f"Screen: {other} → {screen}{score}"
        case EventKind.AMBIGUOUS:
            return logging.WARNING, (
                f"'{screen}' and '{other}' templates match the same area ({event.confidence:.3f}); "
                "no action taken. Make the templates more distinctive."
            )
        case EventKind.LOOKALIKE:
            return logging.INFO, (
                f"Something shaped like the '{screen}' template ({event.confidence:.3f}) has the wrong "
                "colors, so it is ignored. It may be dimmed, covered, or a different button."
            )
        case EventKind.NEAR_MISS:
            return logging.INFO, (
                f"'{screen}' scored {event.confidence:.3f}, just below the threshold. "
                "Its template may be outdated, or the threshold too strict."
            )
        case EventKind.CLICKED:
            x, y = event.point or (0, 0)
            return logging.INFO, f"Clicked '{event.target or ACTION_LABELS[event.screen]}' at ({x}, {y})"
        case EventKind.VERIFIED:
            return logging.INFO, f"Action verified: {screen} → {other}"
        case EventKind.UNVERIFIED:
            return logging.WARNING, (
                f"Clicked '{ACTION_LABELS[event.screen]}' but the screen did not change "
                f"(attempt {event.attempt} of {MAX_ATTEMPTS})"
            )
    raise ValueError(f"Unhandled event {event.kind}")


def _describe_actions(actions: frozenset[Screen]) -> str:
    if not actions:
        return "off"
    return ", ".join(ACTION_LABELS[s] for s in ACTION_LABELS if s in actions)


def format_duration(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"
