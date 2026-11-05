"""Local demonstration environment built from bundled, generated screenshot fixtures."""

from dataclasses import replace
from pathlib import Path

from loop import ASSETS_DIR
from loop.matcher import Template, load_template
from loop.screens import Screen

DEMO_ASSETS = ASSETS_DIR / "demo"
SCREENS_DIR = DEMO_ASSETS / "screens"
TEMPLATES_DIR = DEMO_ASSETS / "templates"
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
