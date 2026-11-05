"""Button suggestions for setup."""

import random

import cv2
import numpy as np
import pytest

from loop.capture import Region
from loop.suggest import find_buttons
from tests.simulation.scenario import DemoScenario


def close_to(found: Region, expected: Region, tolerance: int) -> bool:
    return all(
        abs(a - b) <= tolerance
        for a, b in zip(
            (found.left, found.top, found.right, found.bottom),
            (expected.left, expected.top, expected.right, expected.bottom),
            strict=True,
        )
    )


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_suggests_play_in_the_lobby(seed):
    scenario = DemoScenario(random.Random(seed))
    found = find_buttons(scenario.render())
    assert len(found) == 1  # not the Play tab, the cosmetic button, or the mode selector
    assert close_to(found[0], scenario.button_box, 3)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_suggests_play_again_before_the_smaller_yellow_promotion(seed):
    scenario = DemoScenario(random.Random(seed))
    scenario.show("results")
    found = find_buttons(scenario.render())
    assert close_to(found[0], scenario.button_box, 3)
    assert close_to(found[1], Region(60, 446, 260, 36), 3)  # Get Battle Pass, offered second
    assert len(found) == 2


@pytest.mark.parametrize("name", ["matchmaking", "loading", "match", "finding"])
def test_waiting_screens_have_no_suggestions(name):
    scenario = DemoScenario(random.Random(1))
    scenario.show(name)
    assert find_buttons(scenario.render()) == []


@pytest.mark.parametrize("scale", [1.5, 2.0, 4.0])
def test_suggestions_are_in_full_resolution_coordinates(scale):
    scenario = DemoScenario(random.Random(4))
    frame = cv2.resize(scenario.render(), None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
    b = scenario.button_box
    expected = Region(
        round(b.left * scale), round(b.top * scale), round(b.width * scale), round(b.height * scale)
    )
    assert close_to(find_buttons(frame)[0], expected, round(4 * scale))


def test_large_colored_areas_and_outlines_are_not_buttons():
    frame = np.full((540, 960, 3), (40, 30, 30), np.uint8)
    frame[:, :] = (200, 60, 70)  # a saturated background filling the screen
    cv2.rectangle(frame, (100, 100), (400, 160), (40, 230, 240), 3)  # yellow outline only
    cv2.rectangle(frame, (500, 100), (900, 400), (40, 230, 240), -1)  # a yellow panel, too tall
    assert find_buttons(frame) == []
