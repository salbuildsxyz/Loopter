"""Action decisions, cooldowns, and verification with a fake clock."""

import pytest

from loop.capture import Region
from loop.matcher import Match
from loop.policy import CONFIRM_SCANS, HOLD_MARGIN, MAX_ATTEMPTS, STABLE_SCANS, ActionPolicy, EventKind
from loop.recognizer import Observation
from loop.screens import ACTIONABLE, Screen

THRESHOLD = 0.85
BOX = Region(100, 100, 120, 40)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def seen(screen: Screen, box: Region = BOX, confidence: float = 0.95) -> Observation:
    if screen is Screen.UNKNOWN:
        return Observation(Screen.UNKNOWN, scores={Screen.LOBBY: 0.3})
    return Observation(screen, Match(screen.value, confidence, box), {screen: confidence})


@pytest.fixture
def clock():
    return Clock()


def make(clock, actions=frozenset(ACTIONABLE), cooldown=2.0, verify=5.0):
    return ActionPolicy(actions, THRESHOLD, cooldown, verify, now=clock)


def kinds(step):
    return [e.kind for e in step.events]


def confirm(policy, screen):
    """Shows a screen long enough for the policy to accept it; returns the last step."""
    for _ in range(CONFIRM_SCANS):
        step = policy.update(seen(screen))
    return step


def test_screen_changes_are_reported_once(clock):
    policy = make(clock, actions=frozenset())
    assert kinds(policy.update(seen(Screen.LOBBY))) == []
    first = policy.update(seen(Screen.LOBBY))
    assert kinds(first) == [EventKind.SCREEN_CHANGED]
    assert first.events[0].other is Screen.UNKNOWN
    assert kinds(policy.update(seen(Screen.LOBBY))) == []
    change = confirm(policy, Screen.LOADING)
    assert change.events[0].screen is Screen.LOADING
    assert change.events[0].other is Screen.LOBBY


def test_waits_for_stable_screen_before_acting(clock):
    policy = make(clock)
    steps = [policy.update(seen(Screen.LOBBY)) for _ in range(STABLE_SCANS)]
    assert all(s.click is None for s in steps[:-1])
    assert steps[-1].click == BOX


def test_observe_only_never_clicks(clock):
    policy = make(clock, actions=frozenset())
    for _ in range(10):
        clock.now += 3
        assert policy.update(seen(Screen.LOBBY)).click is None


def test_disabled_action_is_not_clicked(clock):
    policy = make(clock, actions=frozenset({Screen.RESULTS}))
    for _ in range(5):
        assert policy.update(seen(Screen.LOBBY)).click is None


def test_loading_and_unknown_are_never_clicked(clock):
    policy = make(clock)
    for screen in (Screen.LOADING, Screen.UNKNOWN):
        for _ in range(4):
            assert policy.update(seen(screen)).click is None


def test_screen_change_after_click_verifies(clock):
    policy = make(clock)
    policy.update(seen(Screen.LOBBY))
    assert policy.update(seen(Screen.LOBBY)).click == BOX
    clock.now += 1
    assert kinds(policy.update(seen(Screen.LOADING))) == []  # not yet confirmed
    step = policy.update(seen(Screen.LOADING))
    assert EventKind.VERIFIED in kinds(step)
    verified = next(e for e in step.events if e.kind is EventKind.VERIFIED)
    assert (verified.screen, verified.other) == (Screen.LOBBY, Screen.LOADING)


def test_button_moving_counts_as_change(clock):
    policy = make(clock)
    policy.update(seen(Screen.LOBBY))
    policy.update(seen(Screen.LOBBY))
    step = policy.update(seen(Screen.LOBBY, box=BOX.offset(200, 0)))
    assert EventKind.VERIFIED in kinds(step)


def test_no_second_click_while_awaiting_verification(clock):
    policy = make(clock, cooldown=0.5)
    policy.update(seen(Screen.LOBBY))
    assert policy.update(seen(Screen.LOBBY)).click is not None
    for _ in range(3):
        clock.now += 1
        assert policy.update(seen(Screen.LOBBY)).click is None


def test_slow_scans_get_enough_scans_to_verify(clock):
    """With a long scan interval the timeout passes before a change could be confirmed."""
    policy = make(clock, verify=5.0)
    policy.update(seen(Screen.LOBBY))
    assert policy.update(seen(Screen.LOBBY)).click == BOX
    clock.now += 10
    assert kinds(policy.update(seen(Screen.LOADING))) == []
    clock.now += 10
    assert EventKind.VERIFIED in kinds(policy.update(seen(Screen.LOADING)))


def test_unverified_click_retries_then_gives_up(clock):
    policy = make(clock, cooldown=1.0, verify=5.0)
    policy.update(seen(Screen.LOBBY))
    clicks, failures, give_up = 0, 0, ""
    for _ in range(60):
        step = policy.update(seen(Screen.LOBBY))
        clicks += step.click is not None
        failures += kinds(step).count(EventKind.UNVERIFIED)
        if step.give_up:
            give_up = step.give_up
            break
        clock.now += 1
    assert clicks == MAX_ATTEMPTS
    assert failures == MAX_ATTEMPTS
    assert "did not change the screen" in give_up


def test_success_resets_attempts(clock):
    policy = make(clock, cooldown=0.0, verify=2.0)
    policy.update(seen(Screen.LOBBY))
    policy.update(seen(Screen.LOBBY))  # click 1
    clock.now += 3
    for _ in range(CONFIRM_SCANS):  # the screen had time and scans to change
        assert kinds(policy.update(seen(Screen.LOBBY))) == []
    assert kinds(policy.update(seen(Screen.LOBBY))) == [EventKind.UNVERIFIED]
    clock.now += 1
    policy.update(seen(Screen.LOBBY))  # click 2
    assert EventKind.VERIFIED in kinds(confirm(policy, Screen.LOADING))
    confirm(policy, Screen.UNKNOWN)
    for _ in range(MAX_ATTEMPTS - 1):
        policy.update(seen(Screen.LOBBY))
        clock.now += 3
        step = policy.update(seen(Screen.LOBBY))
        assert not step.give_up


def test_cooldown_spaces_actions(clock):
    policy = make(clock, cooldown=10.0, verify=1.0)
    policy.update(seen(Screen.LOBBY))
    assert policy.update(seen(Screen.LOBBY)).click is not None
    confirm(policy, Screen.LOADING)  # verified quickly
    policy.update(seen(Screen.RESULTS))
    clock.now += 2
    assert policy.update(seen(Screen.RESULTS)).click is None  # still cooling down
    clock.now += 9
    assert policy.update(seen(Screen.RESULTS)).click is not None


def test_cancelled_click_is_retried_after_cooldown(clock):
    policy = make(clock, cooldown=2.0)
    policy.update(seen(Screen.LOBBY))
    assert policy.update(seen(Screen.LOBBY)).click is not None
    policy.cancel_pending()
    assert policy.update(seen(Screen.LOBBY)).click is None
    clock.now += 2.5
    assert policy.update(seen(Screen.LOBBY)).click is not None


def test_unexpected_transition_is_flagged(clock):
    policy = make(clock, actions=frozenset())
    confirm(policy, Screen.LOBBY)
    assert confirm(policy, Screen.RESULTS).events[0].unexpected
    assert not confirm(policy, Screen.FINDING_MATCH).events[0].unexpected


def test_unexpected_change_while_verifying_still_verifies(clock):
    policy = make(clock)
    policy.update(seen(Screen.LOBBY))
    policy.update(seen(Screen.LOBBY))
    step = confirm(policy, Screen.RESULTS)
    assert EventKind.VERIFIED in kinds(step)
    assert any(e.unexpected for e in step.events if e.kind is EventKind.SCREEN_CHANGED)


def test_ambiguity_reported_once_per_episode(clock):
    policy = make(clock)
    ambiguous = Observation(
        Screen.UNKNOWN,
        scores={Screen.LOBBY: 0.92, Screen.RESULTS: 0.91},
        ambiguous=(Screen.LOBBY, Screen.RESULTS),
    )
    assert kinds(policy.update(ambiguous)) == [EventKind.AMBIGUOUS]
    assert kinds(policy.update(ambiguous)) == []
    assert policy.update(ambiguous).click is None
    policy.update(seen(Screen.UNKNOWN))
    assert EventKind.AMBIGUOUS in kinds(policy.update(ambiguous))


def test_near_miss_reported_once_per_screen(clock):
    policy = make(clock)
    near = Observation(Screen.UNKNOWN, scores={Screen.LOBBY: THRESHOLD - 0.05, Screen.RESULTS: 0.2})
    step = policy.update(near)
    assert kinds(step) == [EventKind.NEAR_MISS]
    assert step.events[0].screen is Screen.LOBBY
    assert kinds(policy.update(near)) == []


def test_lookalike_reported_once_per_episode_and_never_clicked(clock):
    policy = make(clock)
    lookalike = Observation(Screen.UNKNOWN, scores={Screen.LOBBY: 0.4}, lookalikes={Screen.LOBBY: 0.97})
    step = policy.update(lookalike)
    assert kinds(step) == [EventKind.LOOKALIKE]
    assert step.events[0].confidence == 0.97
    for _ in range(3):
        step = policy.update(lookalike)
        assert kinds(step) == [] and step.click is None
    policy.update(seen(Screen.UNKNOWN))
    assert EventKind.LOOKALIKE in kinds(policy.update(lookalike))


class TestHysteresis:
    """The confirmed screen changes only on consistent evidence, and uncertainty never clicks."""

    def test_one_odd_frame_does_not_change_the_screen(self, clock):
        policy = make(clock, actions=frozenset())
        confirm(policy, Screen.LOBBY)
        for odd in (Screen.UNKNOWN, Screen.RESULTS, Screen.LOADING):
            assert kinds(policy.update(seen(odd))) == []
            assert kinds(policy.update(seen(Screen.LOBBY))) == []
        assert policy.screen is Screen.LOBBY

    def test_contradictory_frames_never_confirm_or_click(self, clock):
        policy = make(clock, cooldown=0.0)
        for i in range(20):
            clock.now += 1
            step = policy.update(seen(Screen.LOBBY if i % 2 else Screen.RESULTS))
            assert step.click is None and EventKind.SCREEN_CHANGED not in kinds(step)
        assert policy.screen is Screen.UNKNOWN

    def test_glowing_button_keeps_the_lobby_without_clicking(self, clock):
        """The reported flicker: a highlight made the button fail the color check for a few scans."""
        policy = make(clock, cooldown=0.0)
        confirm(policy, Screen.LOBBY)
        policy.cancel_pending()
        glowing = Observation(Screen.UNKNOWN, scores={Screen.LOBBY: 0.6}, lookalikes={Screen.LOBBY: 0.97})
        for _ in range(4):
            clock.now += 1
            step = policy.update(glowing)
            assert step.click is None and EventKind.SCREEN_CHANGED not in kinds(step)
        assert policy.screen is Screen.LOBBY
        assert policy.update(seen(Screen.LOBBY)).click is None  # needs fresh, stable evidence
        assert policy.update(seen(Screen.LOBBY)).click == BOX

    @pytest.mark.parametrize("below, holds", [(HOLD_MARGIN / 2, True), (HOLD_MARGIN * 3, False)])
    def test_scores_just_below_the_threshold_hold_the_screen(self, clock, below, holds):
        policy = make(clock, actions=frozenset())
        confirm(policy, Screen.LOBBY)
        dip = Observation(Screen.UNKNOWN, scores={Screen.LOBBY: THRESHOLD - below})
        policy.update(dip)
        policy.update(dip)
        assert (policy.screen is Screen.LOBBY) is holds

    def test_a_flicker_after_clicking_does_not_count_as_success(self, clock):
        policy = make(clock, verify=5.0)
        policy.update(seen(Screen.LOBBY))
        assert policy.update(seen(Screen.LOBBY)).click == BOX
        clock.now += 1
        assert EventKind.VERIFIED not in kinds(policy.update(seen(Screen.UNKNOWN)))
        assert EventKind.VERIFIED not in kinds(policy.update(seen(Screen.LOBBY)))
        clock.now += 5
        assert EventKind.UNVERIFIED in kinds(policy.update(seen(Screen.LOBBY)))

    def test_ambiguous_frames_do_not_hold_or_click(self, clock):
        policy = make(clock, cooldown=0.0)
        confirm(policy, Screen.LOBBY)
        policy.cancel_pending()
        ambiguous = Observation(
            Screen.UNKNOWN,
            scores={Screen.LOBBY: 0.93, Screen.RESULTS: 0.92},
            ambiguous=(Screen.LOBBY, Screen.RESULTS),
        )
        assert policy.update(ambiguous).click is None
        assert policy.update(ambiguous).click is None
        assert policy.screen is Screen.UNKNOWN
