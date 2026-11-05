"""Recognition of the user's own button crops on their own game screenshots.

These images are game artwork, so they are kept out of the repository and the build
(assests/LOOP_button_templates, plus the original screenshots in LOOP_SCREENSHOTS or
Pictures\\Screenshots). The tests are skipped where the images are not present.
"""

import os
from functools import cache
from pathlib import Path

import cv2
import numpy as np
import pytest

from loop.capture import Region
from loop.matcher import TemplateError, find_best, read_image, to_gray
from loop.policy import ActionPolicy, EventKind
from loop.recognizer import Recognizer
from loop.screens import ACTIONABLE, Screen
from loop.templates import PROFILE_FILE, TemplateLibrary

ASSETS = Path(__file__).parents[1] / "assests" / "LOOP_button_templates"
SCREENSHOTS = Path(os.environ.get("LOOP_SCREENSHOTS", Path.home() / "Pictures" / "Screenshots"))
THRESHOLD = 0.85

if not (ASSETS / PROFILE_FILE).exists():
    pytest.skip("the private button crops are not present", allow_module_level=True)

# Screenshot time stamp → what it shows. Button areas are in 1080p screenshot pixels.
SHOTS = {
    "162224": Screen.UNKNOWN,  # matchmaking, CANCEL where PLAY was
    "162230": Screen.LOBBY,  # lobby while the background loads
    "162234": Screen.LOBBY,
    "162431": Screen.UNKNOWN,  # matchmaking
    "162446": Screen.UNKNOWN,  # matchmaking
    "162509": Screen.UNKNOWN,  # loading
    "162520": Screen.UNKNOWN,  # warm-up island
    "162612": Screen.UNKNOWN,  # battle bus
    "162652": Screen.UNKNOWN,  # skydiving
    "162909": Screen.UNKNOWN,  # eliminated
    "162933": Screen.RESULTS,  # also shows EQUIP A SPRITE, RETURN TO LOBBY, GET BATTLE PASS
    "163032": Screen.UNKNOWN,  # finding next match, small CANCEL
}
BUTTON_AREAS = {Screen.LOBBY: Region(94, 873, 330, 80), Screen.RESULTS: Region(1340, 480, 482, 88)}
# Buttons that must never be pressed, plus the optional Return to Lobby button.
NEGATIVES = [*sorted((ASSETS / "negative_examples").glob("*.png")), *(ASSETS / "optional").glob("*.png")]


@cache
def screenshot(stamp: str) -> np.ndarray:
    path = SCREENSHOTS / f"Screenshot 2026-11-03 {stamp}.png"
    if not path.exists():
        pytest.skip(f"screenshot {path.name} is not present")
    return read_image(path)


@pytest.fixture(scope="module")
def templates(tmp_path_factory):
    library = TemplateLibrary(tmp_path_factory.mktemp("templates"), [])
    added, problems = library.import_profile(ASSETS / PROFILE_FILE)
    assert problems == [] and library.conflicts() == []
    assert [e.label for e in added] == ["Play", "Play", "Play Again"]
    return library.load()[0]


@pytest.fixture(scope="module")
def recognizer(templates):
    return Recognizer(templates, THRESHOLD, 1080)


def resized(frame, height):
    scale = height / frame.shape[0]
    interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
    return cv2.resize(frame, None, fx=scale, fy=scale, interpolation=interpolation)


def with_button(stamp, change):
    """The screenshot with its button area replaced by `change(button)`."""
    frame = screenshot(stamp).copy()
    area = BUTTON_AREAS[SHOTS[stamp]]
    patch = frame[area.top : area.bottom, area.left : area.right].astype(np.float32)
    frame[area.top : area.bottom, area.left : area.right] = np.clip(change(patch), 0, 255).astype(np.uint8)
    return frame


@pytest.mark.parametrize("height", [720, 1080, 1440])
@pytest.mark.parametrize("stamp", SHOTS)
def test_each_screenshot_is_recognized_at_common_resolutions(templates, stamp, height):
    observation = Recognizer(templates, THRESHOLD, height).observe(resized(screenshot(stamp), height))
    expected = SHOTS[stamp]
    assert observation.screen is expected
    assert not observation.lookalikes and observation.ambiguous is None
    if expected in ACTIONABLE:
        area = BUTTON_AREAS[expected]
        x, y = observation.match.box.center
        assert area.contains_point(round(x * 1080 / height), round(y * 1080 / height))
        assert observation.confidence >= 0.95


def test_play_and_play_again_do_not_match_each_other(templates):
    def best(screen, stamp):
        return find_best(to_gray(screenshot(stamp)), templates[screen]).confidence

    assert best(Screen.LOBBY, "162933") < 0.6  # Play templates on the results screen
    assert best(Screen.RESULTS, "162234") < 0.6  # Play Again on the lobby
    assert (
        Recognizer({Screen.LOBBY: templates[Screen.LOBBY]}, THRESHOLD, 1080)
        .observe(screenshot("162933"))
        .screen
        is Screen.UNKNOWN
    )


@pytest.mark.parametrize("negative", NEGATIVES, ids=lambda p: p.stem)
@pytest.mark.parametrize("stamp", ["162234", "162933"])
def test_other_buttons_in_place_of_the_real_one_are_not_actions(recognizer, negative, stamp):
    image = read_image(negative).astype(np.float32)

    def replace_button(patch):
        patch[:] = 30
        height, width = min(image.shape[0], patch.shape[0]), min(image.shape[1], patch.shape[1])
        patch[:height, :width] = image[:height, :width]
        return patch

    observation = recognizer.observe(with_button(stamp, replace_button))
    assert observation.screen is Screen.UNKNOWN
    assert observation.confidence < 0.7


@pytest.mark.parametrize(
    "change",
    [
        lambda b: b * 0.7 + 255 * 0.3,  # glow
        lambda b: b * 0.5 + 255 * 0.5,  # strong glow
        lambda b: b * 1.1,
        lambda b: b * 0.85,  # slightly dimmed
        lambda b: cv2.GaussianBlur(b, (3, 3), 0),
        lambda b: b + np.random.default_rng(0).normal(0, 6, b.shape),
    ],
    ids=["glow", "strong-glow", "brighter", "dimmed", "blurred", "noisy"],
)
@pytest.mark.parametrize("stamp", ["162234", "162933"])
def test_buttons_are_recognized_when_they_glow_or_change_slightly(recognizer, stamp, change):
    observation = recognizer.observe(with_button(stamp, change))
    assert observation.screen is SHOTS[stamp]
    assert observation.confidence >= 0.9


@pytest.mark.parametrize("stamp", ["162234", "162933"])
def test_a_darkened_button_is_a_lookalike_not_an_action(recognizer, stamp):
    """A button dimmed behind a menu or overlay keeps its shape but cannot be pressed."""
    observation = recognizer.observe(with_button(stamp, lambda b: b * 0.5))
    assert observation.screen is Screen.UNKNOWN
    assert SHOTS[stamp] in observation.lookalikes


@pytest.mark.parametrize("stamp", ["162234", "162933"])
def test_a_partly_covered_button_is_not_recognized(recognizer, stamp):
    def cover_half(patch):
        patch[:, patch.shape[1] // 2 :] = 40
        return patch

    assert recognizer.observe(with_button(stamp, cover_half)).screen is Screen.UNKNOWN


def test_a_template_saved_for_the_wrong_screen_is_refused_or_ambiguous(templates, tmp_path):
    library = TemplateLibrary(tmp_path, [])
    library.import_profile(ASSETS / PROFILE_FILE)
    with pytest.raises(TemplateError, match="looks the same"):
        library.import_file(ASSETS / "buttons" / "play_btn.png", Screen.RESULTS)

    mislabeled = {**templates, Screen.RESULTS: templates[Screen.LOBBY]}
    observation = Recognizer(mislabeled, THRESHOLD, 1080).observe(screenshot("162234"))
    assert observation.screen is Screen.UNKNOWN and observation.ambiguous


# The recorded session, with each click taking the game to the next screenshot.
FIRST_MATCH = ["162234", "162446", "162509", "162520", "162612", "162652", "162909", "162933"]
NEXT_MATCH = ["163032", "162509", "162520", "162612", "162652", "162909", "162933"]


def play_session(recognizer, sequence, press_works=True, scans_per_waiting_screen=4):
    now = 0.0
    policy = ActionPolicy(frozenset(ACTIONABLE), THRESHOLD, 2.0, 5.0, now=lambda: now)
    observe = cache(lambda stamp: recognizer.observe(screenshot(stamp)))
    index = scans_here = 0
    events, clicks, give_up = [], [], ""
    for _ in range(200):
        if index == len(sequence) or give_up:
            break
        now += 0.75
        stamp = sequence[index]
        step = policy.update(observe(stamp))
        events.extend(step.events)
        give_up = step.give_up
        scans_here += 1
        if step.click is not None:
            clicks.append(stamp)
            assert BUTTON_AREAS[SHOTS[stamp]].contains_point(*step.click.center)
            if press_works:
                index, scans_here = index + 1, 0
        elif SHOTS[stamp] is Screen.UNKNOWN and scans_here >= scans_per_waiting_screen:
            index, scans_here = index + 1, 0
    return events, clicks, give_up


def kinds(events, kind):
    return [e for e in events if e.kind is kind]


def test_recorded_session_presses_each_button_once(recognizer):
    events, clicks, give_up = play_session(recognizer, FIRST_MATCH + NEXT_MATCH)
    assert clicks == ["162234", "162933", "162933"]
    confirmed = [e.screen for e in kinds(events, EventKind.SCREEN_CHANGED)]
    assert confirmed == [Screen.LOBBY, Screen.UNKNOWN, Screen.RESULTS, Screen.UNKNOWN, Screen.RESULTS]
    assert len(kinds(events, EventKind.VERIFIED)) == 2  # the last click has no next screen yet
    assert not kinds(events, EventKind.UNVERIFIED) and not give_up
    assert not kinds(events, EventKind.LOOKALIKE) and not kinds(events, EventKind.AMBIGUOUS)


def test_recorded_session_gives_up_when_a_press_does_nothing(recognizer):
    events, clicks, give_up = play_session(recognizer, FIRST_MATCH, press_works=False)
    assert clicks == ["162234"] * 3
    assert len(kinds(events, EventKind.UNVERIFIED)) == 3
    assert "did not change the screen" in give_up
