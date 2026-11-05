"""A synthetic game used by the tests: generated menu screens and their button templates.

Nothing here ships with the app. The images are drawn by scripts/generate_assets.py.
"""

from dataclasses import replace
from pathlib import Path

from loop.matcher import Template, load_template
from loop.screens import Screen

IMAGES = Path(__file__).resolve().parent / "images"
SCREENS_DIR = IMAGES / "screens"
TEMPLATES_DIR = IMAGES / "templates"
SCREEN_SIZE = (960, 540)

# Each screen's templates as (name in the log, file). The lobby shows Play, or Ready in a party.
TEMPLATE_FILES = {
    Screen.LOBBY: (("Play", "play.png"), ("Ready", "ready.png")),
    Screen.MATCHMAKING: (("Matchmaking", "matchmaking.png"),),
    Screen.LOADING: (("Loading", "loading.png"),),
    Screen.RESULTS: (("Play Again", "play_again.png"),),
    Screen.FINDING_MATCH: (("Finding next match", "finding.png"),),
}


def demo_template_path(screen: Screen) -> Path:
    """The first template of a screen."""
    return TEMPLATES_DIR / TEMPLATE_FILES[screen][0][1]


def demo_templates() -> dict[Screen, tuple[Template, ...]]:
    """The bundled templates, recorded as captured on a display as tall as the demo screen."""
    height = SCREEN_SIZE[1]
    groups: dict[Screen, tuple[Template, ...]] = {}
    for screen, names in TEMPLATE_FILES.items():
        groups[screen] = tuple(
            replace(load_template(TEMPLATES_DIR / file, height), name=label) for label, file in names
        )
    return groups
