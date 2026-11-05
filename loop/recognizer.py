"""Classifies a screenshot as one of the known screens."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace

import cv2
import numpy as np

from loop.capture import Region
from loop.matcher import Match, Template, colors_match, find_best, to_gray
from loop.screens import Screen

# Two screens whose best matches overlap and are this close in confidence cannot be told apart.
AMBIGUITY_MARGIN = 0.03
MIN_OVERLAP_FOR_AMBIGUITY = 0.3
# Large captures are matched at reduced size; buttons stay recognizable and scans stay fast.
MAX_WORK_HEIGHT = 720


@dataclass(frozen=True)
class Observation:
    screen: Screen
    match: Match | None = None  # match for `screen`, in captured-frame coordinates
    scores: Mapping[Screen, float] = field(default_factory=dict)  # best confidence per screen
    ambiguous: tuple[Screen, Screen] | None = None
    lookalikes: Mapping[Screen, float] = field(default_factory=dict)  # shape matched, colors did not
    matches: Mapping[Screen, Match] = field(default_factory=dict)  # best per screen, frame coordinates

    @property
    def confidence(self) -> float:
        if self.match is not None:
            return self.match.confidence
        return max(self.scores.values(), default=0.0)


class Recognizer:
    """Matches every screen's templates against a frame and picks the screen shown.

    Templates captured on a display of known height are rescaled to `display_height`,
    so a template made at 1080p still matches at 1440p or 4K.
    """

    def __init__(
        self,
        templates: Mapping[Screen, Sequence[Template]],
        threshold: float,
        display_height: int,
    ) -> None:
        self._templates = {
            screen: [_fit_to_display(t, display_height) for t in group]
            for screen, group in templates.items()
            if group
        }
        self._threshold = threshold
        self._prepared: dict[float, dict[Screen, list[Template]]] = {}

    def observe(self, frame_bgr: np.ndarray) -> Observation:
        work_scale = min(1.0, MAX_WORK_HEIGHT / frame_bgr.shape[0])
        if work_scale < 1.0:
            frame_bgr = cv2.resize(
                frame_bgr, None, fx=work_scale, fy=work_scale, interpolation=cv2.INTER_AREA
            )
        gray = to_gray(frame_bgr)
        lab = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2LAB)

        def accept(template: Template, box: Region) -> bool:
            # Shape matching ignores color, so a gray tab or a cream Cancel button with similar
            # text can score well against a yellow Play button.
            return template.color is None or colors_match(template.color, _mean(lab, box))

        found = {
            screen: find_best(gray, group, accept) for screen, group in self._templates_at(work_scale).items()
        }
        matches = {screen: _to_frame(m, work_scale) for screen, m in found.items()}
        scores = {screen: m.confidence for screen, m in matches.items()}
        hits = sorted(
            ((s, m) for s, m in matches.items() if not m.rejected and m.confidence >= self._threshold),
            key=lambda hit: hit[1].confidence,
            reverse=True,
        )
        recognized = {s for s, _ in hits}
        lookalikes = {
            s: refused.confidence
            for s, m in matches.items()
            if (refused := _refused(m)) and refused.confidence >= self._threshold and s not in recognized
        }
        result = {"scores": scores, "lookalikes": lookalikes, "matches": matches}
        if not hits:
            return Observation(Screen.UNKNOWN, **result)
        screen, best = hits[0]
        for other, match in hits[1:]:
            close = best.confidence - match.confidence < AMBIGUITY_MARGIN
            if close and _overlap(best.box, match.box) >= MIN_OVERLAP_FOR_AMBIGUITY:
                return Observation(Screen.UNKNOWN, ambiguous=(screen, other), **result)
        return Observation(screen, best, **result)

    def _templates_at(self, work_scale: float) -> dict[Screen, list[Template]]:
        if work_scale not in self._prepared:
            self._prepared[work_scale] = {
                screen: [t.scaled(work_scale) for t in group] for screen, group in self._templates.items()
            }
        return self._prepared[work_scale]


def _fit_to_display(template: Template, display_height: int) -> Template:
    if not template.source_height:
        return template
    return template.scaled(display_height / template.source_height)


def _mean(image: np.ndarray, box: Region) -> tuple[float, float, float]:
    lightness, a, b = cv2.mean(image[box.top : box.bottom, box.left : box.right])[:3]
    return lightness, a, b


def _refused(match: Match) -> Match | None:
    """The strongest location whose shape matched but whose colors did not, if any."""
    return match if match.rejected else match.lookalike


def _to_frame(match: Match, work_scale: float) -> Match:
    if work_scale == 1.0:
        return match
    b = match.box
    box = Region(
        round(b.left / work_scale),
        round(b.top / work_scale),
        max(1, round(b.width / work_scale)),
        max(1, round(b.height / work_scale)),
    )
    lookalike = _to_frame(match.lookalike, work_scale) if match.lookalike else None
    return replace(match, box=box, lookalike=lookalike)


def _overlap(a: Region, b: Region) -> float:
    """Intersection area as a share of the smaller box."""
    width = min(a.right, b.right) - max(a.left, b.left)
    height = min(a.bottom, b.bottom) - max(a.top, b.top)
    if width <= 0 or height <= 0:
        return 0.0
    return width * height / min(a.width * a.height, b.width * b.height)
