"""Recognition of every screen, and of the look-alikes beside each button, in synthetic screenshots."""

import random

import cv2
import numpy as np
import pytest

from loop.capture import Region
from loop.demo import SCREEN_SIZE, SCREENS_DIR, demo_template_path
from loop.demo.scenario import DEMO_SCREENS, DemoScenario
from loop.matcher import load_template, read_image
from loop.recognizer import MAX_WORK_HEIGHT, Recognizer
from loop.screens import Screen

THRESHOLD = 0.85


def all_screens(seed: int = 3):
    """One synthetic screenshot per demo screen, with buttons at random positions."""
    scenario = DemoScenario(random.Random(seed))
    for _ in DEMO_SCREENS:
        yield scenario.screen.state, scenario.render(), scenario.button_box
        scenario.advance()


def resized(frame: np.ndarray, scale: float) -> np.ndarray:
    return cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)


def paste(frame: np.ndarray, image: np.ndarray, x: int, y: int) -> np.ndarray:
    frame = frame.copy()
    h, w = image.shape[:2]
    frame[y : y + h, x : x + w] = image
    return frame


def recognize(templates, frame, threshold=THRESHOLD):
    return Recognizer(templates, threshold, SCREEN_SIZE[1]).observe(frame)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_every_screen_is_recognized(templates, seed):
    recognizer = Recognizer(templates, THRESHOLD, SCREEN_SIZE[1])
    for expected, frame, button in all_screens(seed):
        observation = recognizer.observe(frame)
        assert observation.screen is expected
        assert observation.ambiguous is None
        assert not observation.lookalikes
        if button is not None:
            assert observation.match.box == button


@pytest.mark.parametrize("scale", [0.75, 1.33, 1.5, 2.0])
def test_templates_follow_display_resolution(templates, scale):
    """Templates captured on a 540 px 'display' still work on larger and smaller ones."""
    recognizer = Recognizer(templates, THRESHOLD, round(SCREEN_SIZE[1] * scale))
    for expected, frame, button in all_screens():
        observation = recognizer.observe(resized(frame, scale))
        assert observation.screen is expected, (scale, expected, observation.scores)
        if button is not None:
            cx, cy = observation.match.box.center
            assert abs(cx - button.center[0] * scale) <= 6 * scale
            assert abs(cy - button.center[1] * scale) <= 6 * scale


def test_large_frames_are_matched_at_reduced_size(templates):
    scale = 3.0  # 1620 px tall, above MAX_WORK_HEIGHT
    assert SCREEN_SIZE[1] * scale > MAX_WORK_HEIGHT
    scenario = DemoScenario(random.Random(5))
    observation = Recognizer(templates, THRESHOLD, round(540 * scale)).observe(
        resized(scenario.render(), scale)
    )
    assert observation.screen is Screen.LOBBY
    box = observation.match.box
    expected = scenario.button_box
    assert abs(box.left - expected.left * scale) <= 8
    assert abs(box.width - expected.width * scale) <= 8


def test_buttons_are_found_wherever_the_layout_puts_them(templates):
    """Nothing depends on fixed coordinates: a button is found anywhere in the scanned area."""
    play = read_image(demo_template_path(Screen.LOBBY))
    again = read_image(demo_template_path(Screen.RESULTS))
    background = read_image(SCREENS_DIR / "match.png")
    rng = random.Random(11)
    for image, screen in [(play, Screen.LOBBY), (again, Screen.RESULTS)] * 4:
        h, w = image.shape[:2]
        x, y = rng.randint(0, SCREEN_SIZE[0] - w), rng.randint(110, SCREEN_SIZE[1] - h)
        observation = recognize(templates, paste(background, image, x, y))
        assert observation.screen is screen
        assert observation.match.box == Region(x, y, w, h)


def test_unrecognized_frames_are_unknown(templates):
    rng = np.random.default_rng(0)
    frames = [
        np.zeros((540, 960, 3), np.uint8),
        rng.integers(0, 255, (540, 960, 3), dtype=np.uint8),
        read_image(SCREENS_DIR / "match.png"),
        read_image(SCREENS_DIR / "lobby.png"),  # only the small Play tab and a cosmetic button
        read_image(SCREENS_DIR / "results.png"),  # only Get Battle Pass, Return to Lobby, Equip
    ]
    for frame in frames:
        observation = recognize(templates, frame)
        assert observation.screen is Screen.UNKNOWN
        assert observation.match is None
        assert max(observation.scores.values()) < THRESHOLD


class TestLookalikes:
    """Buttons that share a color, a word, or a shape with Play or Play Again are never taken for them."""

    def test_cancel_during_matchmaking_is_not_play(self, templates):
        observation = recognize(templates, read_image(SCREENS_DIR / "matchmaking.png"))
        assert observation.screen is Screen.MATCHMAKING
        assert observation.scores[Screen.LOBBY] < THRESHOLD

    def test_play_inside_play_again_is_not_the_lobby(self, templates):
        scenario = DemoScenario(random.Random(2))
        scenario.show("results")
        observation = recognize(templates, scenario.render())
        assert observation.screen is Screen.RESULTS
        assert observation.scores[Screen.LOBBY] < THRESHOLD

    def test_gray_play_button_of_the_same_size_is_rejected_by_color(self, templates):
        """A worst case for shape matching: the Play button itself, but gray like the Play tab."""
        play = read_image(demo_template_path(Screen.LOBBY))
        gray = cv2.cvtColor(cv2.cvtColor(play, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
        observation = recognize(templates, paste(read_image(SCREENS_DIR / "lobby.png"), gray, 60, 420))
        assert observation.screen is Screen.UNKNOWN
        assert list(observation.lookalikes) == [Screen.LOBBY]
        assert observation.lookalikes[Screen.LOBBY] >= THRESHOLD  # the shape alone would have matched

    def test_real_button_is_found_beside_a_stronger_gray_copy(self, templates):
        scenario = DemoScenario(random.Random(1))
        play = read_image(demo_template_path(Screen.LOBBY))
        gray = cv2.cvtColor(cv2.cvtColor(play, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
        # The copy sits above the real button, so it is the first peak the matcher finds.
        observation = recognize(templates, paste(scenario.render(), gray, 400, 300))
        assert observation.screen is Screen.LOBBY
        assert observation.match.box == scenario.button_box
        assert not observation.lookalikes  # recognized screens are not reported as look-alikes

    @pytest.mark.parametrize(
        "source, box",
        [
            ("results", Region(60, 446, 260, 36)),  # Get Battle Pass: same yellow, other text
            ("results", Region(600, 120, 320, 44)),  # Equip: yellow rim, gradient fill
            ("results", Region(600, 176, 320, 44)),  # Return to Lobby
            ("lobby", Region(40, 16, 70, 30)),  # the small Play tab
        ],
    )
    def test_other_buttons_stretched_to_button_size_are_not_actions(self, templates, source, box):
        frame = read_image(SCREENS_DIR / f"{source}.png")
        decoy = frame[box.top : box.bottom, box.left : box.right]
        for size in [(300, 64), (236, 60)]:
            stretched = cv2.resize(decoy, size, interpolation=cv2.INTER_LINEAR)
            observation = recognize(
                templates, paste(read_image(SCREENS_DIR / "match.png"), stretched, 330, 380)
            )
            assert observation.screen is Screen.UNKNOWN, (source, box, size, observation.scores)


def test_slightly_dimmed_button_still_matches(templates):
    scenario = DemoScenario(random.Random(1))
    frame = scenario.render()
    b = scenario.button_box
    frame[b.top : b.bottom, b.left : b.right] = (frame[b.top : b.bottom, b.left : b.right] * 0.85).astype(
        np.uint8
    )
    assert recognize(templates, frame).screen is Screen.LOBBY


def test_button_darkened_by_an_overlay_is_not_pressed(templates):
    """A menu or dialog darkening the screen also covers the button, so LOOP leaves it alone."""
    scenario = DemoScenario(random.Random(1))
    frame = scenario.render() // 3
    observation = recognize(templates, frame)
    assert observation.screen is Screen.UNKNOWN
    assert list(observation.lookalikes) == [Screen.LOBBY]


def test_mostly_covered_button_is_a_low_confidence_match(templates):
    scenario = DemoScenario(random.Random(1))
    frame = scenario.render()
    b = scenario.button_box
    # A notification drawn over two thirds of the button.
    frame[b.top : b.bottom, b.left : b.left + b.width * 2 // 3] = (60, 60, 64)
    observation = recognize(templates, frame)
    assert observation.screen is Screen.UNKNOWN
    assert observation.scores[Screen.LOBBY] < THRESHOLD


def test_identical_templates_for_two_screens_are_ambiguous():
    play = load_template(demo_template_path(Screen.LOBBY))
    observation = recognize(
        {Screen.LOBBY: [play], Screen.RESULTS: [play]}, DemoScenario(random.Random(1)).render()
    )
    assert observation.screen is Screen.UNKNOWN
    assert set(observation.ambiguous) == {Screen.LOBBY, Screen.RESULTS}


def test_two_buttons_in_different_places_are_not_ambiguous(templates):
    again = read_image(demo_template_path(Screen.RESULTS))
    frame = paste(DemoScenario(random.Random(1)).render(), again, 600, 440)
    observation = recognize(templates, frame)
    assert observation.ambiguous is None
    assert observation.screen in (Screen.LOBBY, Screen.RESULTS)


def test_screens_without_templates_are_never_reported(templates):
    only_lobby = {Screen.LOBBY: templates[Screen.LOBBY]}
    recognizer = Recognizer(only_lobby, THRESHOLD, SCREEN_SIZE[1])
    for expected, frame, _ in all_screens():
        observation = recognizer.observe(frame)
        assert observation.screen is (Screen.LOBBY if expected is Screen.LOBBY else Screen.UNKNOWN)
        assert set(observation.scores) == {Screen.LOBBY}


def test_match_is_in_frame_coordinates_for_sub_regions(templates):
    scenario = DemoScenario(random.Random(4))
    frame = scenario.render()
    sub = Region(20, 100, 640, 420)
    crop = frame[sub.top : sub.bottom, sub.left : sub.right]
    observation = recognize(templates, crop)
    assert observation.match.box == scenario.button_box.offset(-sub.left, -sub.top)
    assert observation.matches[Screen.LOBBY] == observation.match


def test_play_and_ready_are_told_apart(templates):
    lobby = templates[Screen.LOBBY]
    play_only = {Screen.LOBBY: tuple(t for t in lobby if t.name == "Play")}
    for name in ("Play", "Ready"):
        scenario = DemoScenario(random.Random(0))
        while scenario.button_name != name:
            scenario.show("lobby")
        frame = scenario.render()
        observation = recognize(templates, frame)
        assert observation.screen is Screen.LOBBY
        assert observation.match.template == name
        play_score = recognize(play_only, frame).scores[Screen.LOBBY]
        assert (play_score >= THRESHOLD) is (name == "Play")


@pytest.mark.parametrize("glow", [0.3, 0.5])
def test_glowing_button_is_still_recognized(templates, glow):
    """The reported flicker: a highlighted button failed the old color check now and then."""
    scenario = DemoScenario(random.Random(1))
    frame = scenario.render()
    b = scenario.button_box
    patch = frame[b.top : b.bottom, b.left : b.right].astype(np.float32)
    frame[b.top : b.bottom, b.left : b.right] = (patch * (1 - glow) + 255 * glow).astype(np.uint8)
    observation = recognize(templates, frame)
    assert observation.screen is Screen.LOBBY
    assert not observation.lookalikes
