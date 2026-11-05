"""The full Lobby → … → next match sequence, recognized and decided offline.

The real recognizer and policy run on generated screenshots with a fake clock. There is
no mouse at all: a proposed click is applied to the scenario directly, or not at all.
"""

import random
from dataclasses import dataclass, field

import cv2
import numpy as np
import pytest

from loop.policy import ActionPolicy, EventKind
from loop.recognizer import Recognizer
from loop.screens import ACTIONABLE, Screen
from tests.simulation import SCREEN_SIZE
from tests.simulation.scenario import DemoScenario

THRESHOLD = 0.85
SCANS_PER_TIMED_SCREEN = 4
WORKFLOW = [
    Screen.LOBBY,
    Screen.MATCHMAKING,
    Screen.LOADING,
    Screen.UNKNOWN,  # the match
    Screen.RESULTS,
    Screen.FINDING_MATCH,
    Screen.LOADING,
    Screen.UNKNOWN,
    Screen.RESULTS,
]


@dataclass
class Run:
    """What happened during a simulated session."""

    confirmed: list[Screen] = field(default_factory=list)
    clicks: list[str] = field(default_factory=list)  # demo screen each click was proposed on
    events: list = field(default_factory=list)
    give_up: str = ""


class Simulation:
    def __init__(self, templates, seed=1, actions=frozenset(ACTIONABLE), press_works=True):
        self.scenario = DemoScenario(random.Random(seed))
        self.recognizer = Recognizer(templates, THRESHOLD, SCREEN_SIZE[1])
        self.now = 0.0
        self.policy = ActionPolicy(actions, THRESHOLD, 2.0, 5.0, now=lambda: self.now)
        self.press_works = press_works
        self.run = Run()
        self._scans_here = 0

    def scan(self, frame=None):
        self.now += 0.75
        observation = self.recognizer.observe(self.scenario.render() if frame is None else frame)
        step = self.policy.update(observation)
        self.run.events.extend(step.events)
        for event in step.events:
            if event.kind is EventKind.SCREEN_CHANGED:
                self.run.confirmed.append(event.screen)
        if step.give_up:
            self.run.give_up = step.give_up
        if step.click is not None:
            self.run.clicks.append(self.scenario.screen.name)
            if self.press_works:
                assert self.scenario.press(*step.click.center), "a click missed its button"
                self._scans_here = 0
        return step

    def play(self, scans):
        for _ in range(scans):
            index = self.scenario.index
            self.scan()
            if self.scenario.index != index:
                self._scans_here = 0
            elif self.scenario.screen.auto_advance_ms:
                self._scans_here += 1
                if self._scans_here >= SCANS_PER_TIMED_SCREEN:
                    self.scenario.advance()
                    self._scans_here = 0
            if self.run.give_up:
                break
        return self.run


def kinds(run, kind):
    return [e for e in run.events if e.kind is kind]


@pytest.mark.parametrize("seed", [1, 2, 3, 4])
def test_full_sequence_is_recognized_in_order_with_one_click_per_button(templates, seed):
    run = Simulation(templates, seed).play(60)
    assert run.confirmed[: len(WORKFLOW)] == WORKFLOW
    # One click per appearance of the lobby or results, never on waiting or unknown screens.
    appearances = [s for s in run.confirmed if s in ACTIONABLE]
    assert run.clicks == [{Screen.LOBBY: "lobby", Screen.RESULTS: "results"}[s] for s in appearances]
    assert len(kinds(run, EventKind.VERIFIED)) == len(run.clicks)
    assert not kinds(run, EventKind.UNVERIFIED) and not run.give_up
    assert not any(e.unexpected for e in kinds(run, EventKind.SCREEN_CHANGED))


def test_recognition_alone_follows_the_sequence_without_clicking(templates):
    """With no actions, the lobby is never left; the rest of the sequence is walked by hand."""
    sim = Simulation(templates, actions=frozenset())
    confirmed = []
    for _ in WORKFLOW:
        for _ in range(3):
            sim.scan()
        confirmed.append(sim.policy.screen)
        sim.scenario.advance()
    assert confirmed == WORKFLOW
    assert sim.run.clicks == []


def test_unknown_and_waiting_screens_never_click(templates):
    sim = Simulation(templates)
    rng = np.random.default_rng(3)
    for name in ("matchmaking", "loading", "match", "finding"):
        sim.scenario.show(name)
        for _ in range(8):
            sim.scan()
    for _ in range(8):
        sim.scan(rng.integers(0, 255, (*SCREEN_SIZE[::-1], 3), dtype=np.uint8))
    assert sim.run.clicks == []


def test_unchanged_screen_is_pressed_once_until_verification_fails(templates):
    """If the press does nothing, LOOP waits for verification before trying again, then gives up."""
    sim = Simulation(templates, press_works=False)
    run = sim.play(60)
    assert run.clicks == ["lobby"] * 3
    assert len(kinds(run, EventKind.UNVERIFIED)) == 3
    assert "did not change the screen" in run.give_up
    # Clicks were at least the verification timeout apart.
    clicked = [e for e in run.events if e.kind is EventKind.UNVERIFIED]
    assert len(clicked) == 3


def test_recovers_on_a_new_session_after_giving_up(templates):
    failed = Simulation(templates, press_works=False)
    failed.play(60)
    assert failed.run.give_up
    retry = Simulation(templates)
    retry.scenario = failed.scenario
    run = retry.play(30)
    assert run.clicks[0] == "lobby" and not run.give_up
    assert kinds(run, EventKind.VERIFIED)


def test_glowing_button_and_stray_frames_do_not_flicker_the_state(templates):
    """Reproduces the reported Lobby ↔ Unknown flicker: a pulsing highlight and odd frames."""
    sim = Simulation(templates, actions=frozenset())
    b = sim.scenario.button_box
    for i in range(30):
        frame = sim.scenario.render()
        if i % 3 == 1:  # highlight pulse: the button blends toward white
            patch = frame[b.top : b.bottom, b.left : b.right].astype(np.float32)
            frame[b.top : b.bottom, b.left : b.right] = (patch * 0.5 + 255 * 0.5).astype(np.uint8)
        if i % 7 == 3:  # a single unrelated frame, e.g. a notification sliding in
            frame = cv2.GaussianBlur(frame, (31, 31), 0)
        sim.scan(frame)
    assert sim.run.confirmed == [Screen.LOBBY]


def test_stale_template_never_acts(templates):
    """After a game update the button looks different: LOOP reports a near miss and does nothing."""
    sim = Simulation(templates)
    b = sim.scenario.button_box
    for _ in range(10):
        frame = sim.scenario.render()
        # The new button style: same place and color, redrawn text.
        frame[b.top + 12 : b.bottom - 12, b.left + 40 : b.right - 40] = (60, 230, 245)
        sim.scan(frame)
    assert sim.run.clicks == []
    assert Screen.LOBBY not in sim.run.confirmed


def test_wrongly_labeled_template_is_ambiguous_not_acted_on(templates):
    """A Play template saved as Results matches the lobby button as strongly as the real one."""
    mislabeled = {**templates, Screen.RESULTS: templates[Screen.LOBBY]}
    sim = Simulation(mislabeled)
    run = sim.play(10)
    assert run.clicks == []
    assert kinds(run, EventKind.AMBIGUOUS)
