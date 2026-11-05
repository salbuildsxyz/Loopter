"""Template loading and OpenCV template matching."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from pathlib import Path

import cv2
import numpy as np

from loop.capture import Region

# Small scale sweep so templates still match when the UI is slightly larger or smaller.
SCALES = (1.0, 0.9, 1.1, 0.8, 1.25)
# Below this pixel standard deviation a template is effectively a flat color and matches anywhere.
MIN_TEMPLATE_DETAIL = 4.0
# Peaks examined per template and scale when a check rejects the strongest ones.
MAX_PEAKS = 3
# Templates at least twice this size are searched at half size first, then refined
# within this many pixels of each candidate.
MIN_COARSE_SIDE = 12
REFINE_MARGIN = 6
# Color validation, in OpenCV's 8-bit CIELAB scale. Shape matching ignores brightness and
# contrast, so a button that glows or is highlighted (blended toward white) still matches;
# the color check must tolerate the same changes. It compares hue and how colorful the
# area is, and rejects areas much darker than the template, such as a button behind an overlay.
MIN_CHROMA = 20.0  # below this a color counts as gray
MIN_CHROMA_RATIO = 0.4
MAX_HUE_SHIFT_DEGREES = 25.0
MAX_DARKENING = 45.0
# Two templates this similar show the same thing.
SAME_TEMPLATE_SIMILARITY = 0.9


class TemplateError(Exception):
    pass


@dataclass(frozen=True)
class Template:
    name: str
    image: np.ndarray  # grayscale
    source_height: int | None = None  # height of the display it was captured on, if known
    color: tuple[float, float, float] | None = None  # mean CIELAB color of the original image

    @property
    def size(self) -> tuple[int, int]:
        h, w = self.image.shape[:2]
        return w, h

    def scaled(self, factor: float) -> Template:
        if factor == 1.0:
            return self
        return Template(self.name, _resize(self.image, factor), self.source_height, self.color)


@dataclass(frozen=True)
class Match:
    template: str
    confidence: float
    box: Region  # relative to the searched image
    rejected: bool = False  # the shape matched but the `accept` check refused every peak
    lookalike: Match | None = None  # a stronger peak that the `accept` check refused


def read_image(path: Path) -> np.ndarray:
    """Reads a BGR image. Uses imdecode because cv2.imread fails on non-ASCII Windows paths."""
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
    except OSError as exc:
        raise TemplateError(f"Template '{path.name}' could not be read: {exc.strerror}") from exc
    image = cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None
    if image is None:
        raise TemplateError(f"Template '{path.name}' is not a readable image")
    return image


def write_image(path: Path, image: np.ndarray) -> None:
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise TemplateError(f"Could not encode image for '{path.name}'")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded.tofile(str(path))


def to_gray(image_bgr: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)


def template_from_image(name: str, image_bgr: np.ndarray, source_height: int | None = None) -> Template:
    gray = to_gray(image_bgr)
    if float(gray.std()) < MIN_TEMPLATE_DETAIL:
        raise TemplateError(
            f"Template '{name}' is almost a single flat color. Select an area with visible detail."
        )
    return Template(name, gray, source_height, mean_lab(image_bgr))


def colors_match(expected: tuple[float, float, float], actual: tuple[float, float, float]) -> bool:
    """Whether `actual` (a mean CIELAB color) could be the template color `expected`, lit differently."""
    l_expected, *ab_expected = expected
    l_actual, *ab_actual = actual
    if l_actual < l_expected - MAX_DARKENING:
        return False
    chroma_expected = math.hypot(ab_expected[0] - 128, ab_expected[1] - 128)
    chroma_actual = math.hypot(ab_actual[0] - 128, ab_actual[1] - 128)
    if chroma_expected < MIN_CHROMA:
        return chroma_actual < 2 * MIN_CHROMA
    if chroma_actual < max(MIN_CHROMA, MIN_CHROMA_RATIO * chroma_expected):
        return False
    hue_expected = math.atan2(ab_expected[1] - 128, ab_expected[0] - 128)
    hue_actual = math.atan2(ab_actual[1] - 128, ab_actual[0] - 128)
    shift = abs(math.degrees(hue_actual - hue_expected)) % 360
    return min(shift, 360 - shift) <= MAX_HUE_SHIFT_DEGREES


def mean_lab(image_bgr: np.ndarray) -> tuple[float, float, float]:
    """Mean color in OpenCV's 8-bit CIELAB scale."""
    lab = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2LAB)
    lightness, a, b = cv2.mean(lab)[:3]
    return lightness, a, b


def load_template(path: Path, source_height: int | None = None) -> Template:
    if not path.exists():
        raise TemplateError(f"Template '{path.name}' is missing. Re-import it or remove it from the list.")
    return template_from_image(path.stem, read_image(path), source_height)


def find_best(
    gray: np.ndarray,
    templates: list[Template],
    accept: Callable[[Template, Region], bool] | None = None,
) -> Match | None:
    """Best match across all templates and scales, regardless of threshold.

    `accept` can refuse a location, for example one with the wrong colors; the next
    strongest peaks are tried instead. A refused peak stronger than the result is kept
    as its `lookalike`. When every peak is refused, the strongest one is returned
    marked as rejected.

    Returns None only when no template is given. Raises TemplateError when every
    template is larger than the image, which means the scan region is too small.
    """
    if not templates:
        return None
    img_h, img_w = gray.shape
    coarse = cv2.resize(gray, (img_w // 2, img_h // 2), interpolation=cv2.INTER_AREA)
    best: Match | None = None
    best_rejected: Match | None = None
    for template in templates:
        for scale in SCALES:
            scaled = _resize(template.image, scale)
            t_h, t_w = scaled.shape
            if t_w > img_w or t_h > img_h:
                continue
            for confidence, x, y in _peaks(gray, coarse, scaled):
                if best is not None and confidence <= best.confidence:
                    continue
                box = Region(x, y, t_w, t_h)
                if accept is None or accept(template, box):
                    best = Match(template.name, confidence, box)
                    break
                if best_rejected is None or confidence > best_rejected.confidence:
                    best_rejected = Match(template.name, confidence, box, rejected=True)
    if best is None and best_rejected is None:
        raise TemplateError(
            f"Every template is larger than the scanned area ({img_w} × {img_h}). "
            "Select a larger scan region."
        )
    if best is None:
        return best_rejected
    if best_rejected is not None and best_rejected.confidence > best.confidence:
        return replace(best, lookalike=best_rejected)
    return best


def look_alike(a: Template, b: Template) -> bool:
    """Whether two templates show the same thing, allowing for different capture sizes."""
    (a_w, a_h), (b_w, b_h) = a.size, b.size
    if abs(a_w / a_h - b_w / b_h) > 0.15 * (a_w / a_h):
        return False
    resized = cv2.resize(b.image, (a_w, a_h), interpolation=cv2.INTER_AREA)
    similarity = float(cv2.matchTemplate(a.image, resized, cv2.TM_CCOEFF_NORMED)[0, 0])
    colors = a.color is None or b.color is None or colors_match(a.color, b.color)
    return similarity >= SAME_TEMPLATE_SIMILARITY and colors


def _peaks(gray: np.ndarray, coarse: np.ndarray, template: np.ndarray) -> Iterator[tuple[float, int, int]]:
    """The strongest match locations, best first: (confidence, x, y).

    Large templates are located on a half-size image and then refined at full size
    around each candidate, which is several times faster than a full-size search.
    """
    t_h, t_w = template.shape
    if min(t_h, t_w) < 2 * MIN_COARSE_SIDE:
        result = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
        for _ in range(MAX_PEAKS):
            _, confidence, _, (x, y) = cv2.minMaxLoc(result)
            if not np.isfinite(confidence):
                return
            yield float(confidence), x, y
            _suppress(result, x, y, t_w, t_h)
        return
    small = cv2.resize(template, (t_w // 2, t_h // 2), interpolation=cv2.INTER_AREA)
    if small.shape[0] > coarse.shape[0] or small.shape[1] > coarse.shape[1]:
        return
    result = cv2.matchTemplate(coarse, small, cv2.TM_CCOEFF_NORMED)
    img_h, img_w = gray.shape
    for _ in range(MAX_PEAKS):
        _, coarse_confidence, _, (cx, cy) = cv2.minMaxLoc(result)
        if not np.isfinite(coarse_confidence):
            return
        _suppress(result, cx, cy, t_w // 2, t_h // 2)
        left, top = max(0, 2 * cx - REFINE_MARGIN), max(0, 2 * cy - REFINE_MARGIN)
        right, bottom = min(img_w, 2 * cx + t_w + REFINE_MARGIN), min(img_h, 2 * cy + t_h + REFINE_MARGIN)
        if right - left < t_w or bottom - top < t_h:
            continue
        fine = cv2.matchTemplate(gray[top:bottom, left:right], template, cv2.TM_CCOEFF_NORMED)
        _, confidence, _, (x, y) = cv2.minMaxLoc(fine)
        if np.isfinite(confidence):
            yield float(confidence), left + x, top + y


def _suppress(result: np.ndarray, x: int, y: int, width: int, height: int) -> None:
    """Removes a peak and its neighborhood from a match result so the next peak can be found."""
    result[max(0, y - height // 2) : y + height // 2 + 1, max(0, x - width // 2) : x + width // 2 + 1] = -1.0


def _resize(image: np.ndarray, scale: float) -> np.ndarray:
    if scale == 1.0:
        return image
    h, w = image.shape[:2]
    size = (max(1, round(w * scale)), max(1, round(h * scale)))
    interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
    return cv2.resize(image, size, interpolation=interpolation)
