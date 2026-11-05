from dataclasses import replace

import cv2
import numpy as np
import pytest

from loop.capture import Region
from loop.demo import SCREENS_DIR, demo_template_path
from loop.matcher import (
    TemplateError,
    colors_match,
    find_best,
    load_template,
    look_alike,
    mean_lab,
    read_image,
    template_from_image,
    to_gray,
    write_image,
)
from loop.screens import Screen


def compose(screen: str, button: Screen, x: int, y: int) -> np.ndarray:
    frame = read_image(SCREENS_DIR / f"{screen}.png")
    sprite = read_image(demo_template_path(button))
    h, w = sprite.shape[:2]
    frame[y : y + h, x : x + w] = sprite
    return frame


def play_template():
    return load_template(demo_template_path(Screen.LOBBY))


def test_finds_button_at_its_position():
    match = find_best(to_gray(compose("lobby", Screen.LOBBY, 233, 301)), [play_template()])
    assert match.confidence > 0.97
    assert (match.box.left, match.box.top) == (233, 301)


def test_tolerates_small_scale_differences():
    frame = compose("lobby", Screen.LOBBY, 200, 250)
    scaled = cv2.resize(frame, None, fx=1.1, fy=1.1, interpolation=cv2.INTER_LINEAR)
    match = find_best(to_gray(scaled), [play_template()])
    assert match.confidence > 0.85
    assert abs(match.box.left - 220) <= 3 and abs(match.box.top - 275) <= 3


def test_no_templates_returns_none():
    assert find_best(np.zeros((50, 50), np.uint8), []) is None


def test_template_larger_than_region_raises():
    with pytest.raises(TemplateError, match="larger than the scanned area"):
        find_best(np.zeros((30, 30), np.uint8), [play_template()])


def test_flat_template_is_rejected():
    with pytest.raises(TemplateError, match="flat color"):
        template_from_image("flat", np.full((20, 20, 3), 128, np.uint8))


def test_missing_and_unreadable_templates(tmp_path):
    with pytest.raises(TemplateError, match="missing"):
        load_template(tmp_path / "gone.png")
    junk = tmp_path / "junk.png"
    junk.write_bytes(b"not an image")
    with pytest.raises(TemplateError, match="not a readable image"):
        load_template(junk)


def test_non_ascii_paths_round_trip(tmp_path):
    image = read_image(demo_template_path(Screen.LOBBY))
    path = tmp_path / "plantillas ñ" / "botón.png"
    write_image(path, image)
    template = load_template(path, source_height=1080)
    assert template.name == "botón"
    assert template.size == (image.shape[1], image.shape[0])
    assert template.source_height == 1080


def test_scaled_template_keeps_metadata():
    template = load_template(demo_template_path(Screen.LOBBY), source_height=540)
    doubled = template.scaled(2.0)
    assert doubled.size == (template.size[0] * 2, template.size[1] * 2)
    assert doubled.source_height == 540
    assert template.scaled(1.0) is template


def test_rejected_peak_gives_way_to_the_next_best_location():
    """A check that refuses the strongest peak lets a weaker, acceptable one win."""
    frame = to_gray(compose("lobby", Screen.LOBBY, 233, 301))
    template = play_template()
    best = find_best(frame, [template])
    refused = best.box
    match = find_best(frame, [template], accept=lambda _t, box: box != refused)
    assert match.box != refused and not match.rejected
    assert match.confidence < best.confidence
    assert match.lookalike == replace(best, rejected=True)  # kept for reporting


def test_every_peak_rejected_returns_the_strongest_marked_rejected():
    frame = to_gray(compose("lobby", Screen.LOBBY, 233, 301))
    match = find_best(frame, [play_template()], accept=lambda _t, _box: False)
    assert match.rejected
    assert match.box == Region(233, 301, *play_template().size)


def test_templates_record_their_color():
    template = play_template()
    lightness, a, b = template.color
    assert lightness > 180 and b > 160  # bright yellow in 8-bit CIELAB
    assert template.scaled(0.5).color == template.color


def lab(bgr):
    return mean_lab(np.full((4, 4, 3), bgr, np.uint8))


YELLOW = (58, 234, 244)


@pytest.mark.parametrize("glow", [0.0, 0.25, 0.5, 0.6])
def test_highlighted_colors_still_match(glow):
    """A glow or hover blends a button toward white; shape matching ignores that, so must color."""
    lit = tuple(round(c * (1 - glow) + 255 * glow) for c in YELLOW)
    assert colors_match(lab(YELLOW), lab(lit))


@pytest.mark.parametrize(
    "other",
    [
        (224, 218, 217),  # gray tab
        (217, 243, 251),  # cream Cancel
        (247, 211, 217),  # lavender
        (40, 40, 200),  # red
        tuple(c // 3 for c in YELLOW),  # the same button behind a dark overlay
    ],
)
def test_other_colors_do_not_match(other):
    assert not colors_match(lab(YELLOW), lab(other))


def test_gray_templates_only_match_gray():
    gray = lab((200, 200, 200))
    assert colors_match(gray, lab((230, 230, 232)))
    assert not colors_match(gray, lab(YELLOW))


def test_look_alike_ignores_capture_size():
    play = play_template()
    bigger = template_from_image("x", cv2.resize(read_image(demo_template_path(Screen.LOBBY)), (354, 90)))
    assert look_alike(play, bigger)
    assert not look_alike(play, load_template(demo_template_path(Screen.RESULTS)))
