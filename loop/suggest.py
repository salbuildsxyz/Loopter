"""Finds likely primary buttons in a screenshot, so setup can start from a suggestion.

Primary buttons in game menus are usually solid, saturated, button-shaped rectangles
(a yellow Play button, for example). Outlined, gradient, pale, or gray buttons are skipped.
"""

from __future__ import annotations

import cv2
import numpy as np

from loop.capture import Region

WORK_HEIGHT = 540
MIN_SATURATION = 100
MIN_VALUE = 140
HUE_STEP = 10  # OpenCV hue runs 0-179
HUE_TOLERANCE = 8
# Button shape limits, relative to the screenshot height.
MIN_HEIGHT, MAX_HEIGHT = 0.025, 0.16
MIN_ASPECT, MAX_ASPECT = 1.6, 10.0
MIN_RECTANGULARITY = 0.85  # outline area / bounding box area
MIN_FILL = 0.5  # share of the box in the button color; text and icons take the rest
MAX_SUGGESTIONS = 5


def find_buttons(frame_bgr: np.ndarray) -> list[Region]:
    """Likely buttons in frame coordinates, largest first."""
    scale = min(1.0, WORK_HEIGHT / frame_bgr.shape[0])
    if scale < 1.0:
        frame_bgr = cv2.resize(frame_bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    hue = hsv[..., 0].astype(np.int16)
    vivid = (hsv[..., 1] >= MIN_SATURATION) & (hsv[..., 2] >= MIN_VALUE)
    found: list[tuple[float, Region]] = []
    for center in range(0, 180, HUE_STEP):
        distance = np.abs(hue - center)
        mask = vivid & (np.minimum(distance, 180 - distance) <= HUE_TOLERANCE)
        for box, fill in _button_shapes(mask.astype(np.uint8)):
            if all(_iou(box, other) < 0.5 for _, other in found):
                found.append((box.width * box.height * fill, box))
    found.sort(key=lambda item: item[0], reverse=True)
    return [_scale_box(box, 1 / scale) for _, box in found[:MAX_SUGGESTIONS]]


def _button_shapes(mask: np.ndarray) -> list[tuple[Region, float]]:
    frame_h, frame_w = mask.shape
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    shapes = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if not MIN_HEIGHT * frame_h <= h <= MAX_HEIGHT * frame_h:
            continue
        if not MIN_ASPECT <= w / h <= MAX_ASPECT or w > frame_w * 0.6:
            continue
        if cv2.contourArea(contour) < MIN_RECTANGULARITY * w * h:
            continue
        fill = float(mask[y : y + h, x : x + w].mean())
        if fill >= MIN_FILL:
            shapes.append((Region(x, y, w, h), fill))
    return shapes


def _scale_box(box: Region, factor: float) -> Region:
    if factor == 1.0:
        return box
    return Region(
        round(box.left * factor),
        round(box.top * factor),
        max(1, round(box.width * factor)),
        max(1, round(box.height * factor)),
    )


def _iou(a: Region, b: Region) -> float:
    width = min(a.right, b.right) - max(a.left, b.left)
    height = min(a.bottom, b.bottom) - max(a.top, b.top)
    if width <= 0 or height <= 0:
        return 0.0
    inter = width * height
    return inter / (a.width * a.height + b.width * b.height - inter)
