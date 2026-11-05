"""The screens LOOP can recognize and the order they normally follow.

Two screens have a button to press: the lobby (Play) and the match results (Play Again).
Everything else in a match is a waiting state.
"""

from __future__ import annotations

from enum import Enum


class Screen(Enum):
    LOBBY = "lobby"
    MATCHMAKING = "matchmaking"
    LOADING = "loading"
    RESULTS = "results"
    FINDING_MATCH = "finding_match"
    UNKNOWN = "unknown"

    @property
    def label(self) -> str:
        return _LABELS[self]


_LABELS = {
    Screen.LOBBY: "Lobby",
    Screen.MATCHMAKING: "Matchmaking",
    Screen.LOADING: "Loading",
    Screen.RESULTS: "Results",
    Screen.FINDING_MATCH: "Finding next match",
    Screen.UNKNOWN: "Unknown",
}


class Button(Enum):
    """A button LOOP can press. Play and Ready are different buttons on the same lobby screen."""

    PLAY = "play"
    READY = "ready"
    PLAY_AGAIN = "play_again"

    @property
    def label(self) -> str:
        return _BUTTON_LABELS[self]

    @property
    def screen(self) -> Screen:
        return _BUTTON_SCREENS[self]


_BUTTON_LABELS = {Button.PLAY: "Play", Button.READY: "Ready", Button.PLAY_AGAIN: "Play Again"}
_BUTTON_SCREENS = {Button.PLAY: Screen.LOBBY, Button.READY: Screen.LOBBY, Button.PLAY_AGAIN: Screen.RESULTS}

# Screens with a button LOOP can press, named after their buttons.
ACTION_LABELS = {
    Screen.LOBBY: "Play / Ready",
    Screen.RESULTS: "Play Again",
}
ACTIONABLE = tuple(ACTION_LABELS)


def buttons_for(screen: Screen) -> tuple[Button, ...]:
    return tuple(b for b in Button if b.screen is screen)


RECOGNIZABLE = tuple(s for s in Screen if s is not Screen.UNKNOWN)

# Unknown covers the match itself, so it may follow any screen that leads into one.
_EXPECTED_NEXT = {
    Screen.LOBBY: {Screen.MATCHMAKING, Screen.LOADING, Screen.UNKNOWN},
    Screen.MATCHMAKING: {Screen.LOBBY, Screen.LOADING, Screen.UNKNOWN},
    Screen.LOADING: {Screen.UNKNOWN, Screen.LOBBY},
    Screen.RESULTS: {Screen.FINDING_MATCH, Screen.LOBBY, Screen.LOADING, Screen.UNKNOWN},
    Screen.FINDING_MATCH: {Screen.LOADING, Screen.RESULTS, Screen.LOBBY, Screen.UNKNOWN},
}


def is_expected(previous: Screen, new: Screen) -> bool:
    """Whether `new` normally follows `previous`. Anything may follow an unknown screen."""
    return previous is Screen.UNKNOWN or new in _EXPECTED_NEXT[previous]
