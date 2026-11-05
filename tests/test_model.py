"""What the interface claims about buttons comes only from real recognition results."""

from loop.capture import Region
from loop.matcher import Match
from loop.recognizer import Observation
from loop.screens import Screen
from loop.ui.model import ButtonChecks, Check, Target, evaluate, format_clock, short_clock

THRESHOLD = 0.85
BOTH = {Target.PLAY, Target.AGAIN}


def match(confidence: float) -> Match:
    return Match("Play", confidence, Region(10, 10, 40, 20))


def test_a_recognized_lobby_makes_play_work_and_leaves_play_again_alone():
    seen = Observation(Screen.LOBBY, match(0.95), scores={Screen.LOBBY: 0.95, Screen.RESULTS: 0.80})
    outcome = evaluate(seen, BOTH, THRESHOLD)
    assert outcome.screen is Screen.LOBBY
    assert outcome.results == {Target.PLAY: Check.WORKING}  # a near score elsewhere is not a verdict


def test_a_near_miss_needs_adjustment():
    seen = Observation(Screen.UNKNOWN, scores={Screen.LOBBY: 0.79})
    outcome = evaluate(seen, BOTH, THRESHOLD)
    assert outcome.results == {Target.PLAY: Check.ADJUST}
    assert outcome.screen is Screen.LOBBY


def test_a_look_alike_needs_adjustment():
    seen = Observation(Screen.UNKNOWN, scores={Screen.RESULTS: 0.4}, lookalikes={Screen.RESULTS: 0.9})
    assert evaluate(seen, BOTH, THRESHOLD).results == {Target.AGAIN: Check.ADJUST}


def test_nothing_on_screen_changes_nothing():
    seen = Observation(Screen.UNKNOWN, scores={Screen.LOBBY: 0.3, Screen.RESULTS: 0.2})
    outcome = evaluate(seen, BOTH, THRESHOLD)
    assert outcome.screen is None and outcome.results == {}


def test_unsaved_buttons_get_no_verdict():
    seen = Observation(Screen.RESULTS, match(0.97), scores={Screen.RESULTS: 0.97})
    outcome = evaluate(seen, {Target.PLAY}, THRESHOLD)
    assert outcome.screen is Screen.RESULTS and outcome.results == {}


def test_saved_buttons_start_not_checked_and_saving_resets_them():
    checks = ButtonChecks()
    assert checks[Target.PLAY] is Check.NONE
    checks.sync({Target.PLAY})
    assert checks[Target.PLAY] is Check.UNCHECKED and checks[Target.AGAIN] is Check.NONE
    checks.statuses[Target.PLAY] = Check.WORKING
    checks.sync({Target.PLAY})
    assert checks[Target.PLAY] is Check.WORKING  # syncing keeps real results
    checks.reset(Target.PLAY)
    assert checks[Target.PLAY] is Check.UNCHECKED
    checks.sync(set())
    assert checks[Target.PLAY] is Check.NONE


def test_clock_formats():
    assert format_clock(0) == "00:00:00" and format_clock(3725.9) == "01:02:05"
    assert short_clock(65) == "01:05" and short_clock(3600) == "01:00:00"
