"""User preferences: defaults, validation, and JSON persistence."""

from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from loop.capture import Region
from loop.screens import ACTIONABLE, RECOGNIZABLE, Button, Screen, buttons_for

log = logging.getLogger(__name__)

THRESHOLD_RANGE = (0.50, 0.99)
INTERVAL_MS_RANGE = (100, 10_000)
COOLDOWN_S_RANGE = (0.5, 30.0)
DEFAULT_HOTKEY = "Ctrl+Shift+F12"


class Mode(Enum):
    LIVE = "live"
    INTERACTION = "interaction"

    @property
    def label(self) -> str:
        return _MODE_LABELS[self]


_MODE_LABELS = {Mode.LIVE: "Watch only", Mode.INTERACTION: "Auto click"}
ONBOARDING_STEPS = 5


@dataclass(frozen=True)
class TemplateEntry:
    path: str
    screen: Screen
    source_height: int | None = None  # height of the display the template was captured on
    button: Button | None = None  # the button it shows, for Lobby and Results templates

    def __post_init__(self) -> None:
        if self.screen not in RECOGNIZABLE:
            raise ValueError(f"Templates cannot belong to the {self.screen.label} screen")
        if self.screen in ACTIONABLE and self.button is None:
            # Entries saved before Ready existed name only the screen.
            object.__setattr__(self, "button", buttons_for(self.screen)[0])
        if self.button is not None and self.button.screen is not self.screen:
            raise ValueError(f"The {self.button.label} button is not on the {self.screen.label} screen")

    @property
    def label(self) -> str:
        """What the template shows, as named in the UI and the log."""
        return self.button.label if self.button else self.screen.label

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "screen": self.screen.value,
            "source_height": self.source_height,
            "button": self.button.value if self.button else None,
        }

    @classmethod
    def from_dict(cls, data: Any) -> TemplateEntry:
        if not isinstance(data["path"], str):
            raise ValueError("invalid template path")
        height = data.get("source_height")
        if height is not None and (not isinstance(height, int) or isinstance(height, bool) or height <= 0):
            raise ValueError("invalid source height")
        button = Button(data["button"]) if data.get("button") is not None else None
        return cls(data["path"], Screen(data["screen"]), height, button)


@dataclass
class Settings:
    mode: Mode = Mode.LIVE
    threshold: float = 0.85
    scan_interval_ms: int = 750
    cooldown_s: float = 2.0
    region: Region | None = None
    monitor: int = 1
    templates: list[TemplateEntry] = field(default_factory=list)
    actions: set[Screen] = field(default_factory=lambda: set(ACTIONABLE))
    emergency_hotkey: str = DEFAULT_HOTKEY
    window_geometry: str = ""
    onboarding_done: bool = False
    onboarding_step: int = 0  # the first-launch step to reopen while setup is unfinished
    reduce_motion: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["mode"] = self.mode.value
        data["region"] = self.region.to_dict() if self.region else None
        data["templates"] = [t.to_dict() for t in self.templates]
        data["actions"] = sorted(s.value for s in self.actions)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Settings:
        """Builds settings from untrusted JSON, falling back to defaults field by field."""
        s = cls()
        s.mode = _parse_mode(data.get("mode"))
        s.threshold = _clamp_number(data.get("threshold"), s.threshold, *THRESHOLD_RANGE, float)
        s.scan_interval_ms = _clamp_number(
            data.get("scan_interval_ms"), s.scan_interval_ms, *INTERVAL_MS_RANGE, int
        )
        s.cooldown_s = _clamp_number(data.get("cooldown_s"), s.cooldown_s, *COOLDOWN_S_RANGE, float)
        s.region = _parse_region(data.get("region"))
        monitor = data.get("monitor")
        if isinstance(monitor, int) and not isinstance(monitor, bool) and monitor >= 1:
            s.monitor = monitor
        s.templates = _parse_templates(data.get("templates"))
        actions = data.get("actions")
        if isinstance(actions, list):
            allowed = {x.value for x in ACTIONABLE}
            s.actions = {Screen(a) for a in actions if isinstance(a, str) and a in allowed}
        step = data.get("onboarding_step")
        if isinstance(step, int) and not isinstance(step, bool):
            s.onboarding_step = min(max(step, 0), ONBOARDING_STEPS - 1)
        for name in ("onboarding_done", "reduce_motion"):
            if isinstance(data.get(name), bool):
                setattr(s, name, data[name])
        for name in ("emergency_hotkey", "window_geometry"):
            if isinstance(data.get(name), str):
                setattr(s, name, data[name])
        if not s.emergency_hotkey.strip():
            s.emergency_hotkey = DEFAULT_HOTKEY
        return s


def _parse_mode(value: Any) -> Mode:
    # Auto click must be chosen explicitly every time, so it is never restored. Older versions
    # could also save "demo", an internal test mode that no longer exists.
    if value not in (None, "live", "interaction", "demo"):
        log.warning("Unknown mode %r in settings; using Watch only", value)
    return Mode.LIVE


def _parse_templates(value: Any) -> list[TemplateEntry]:
    if not isinstance(value, list):
        return []
    entries = []
    for item in value:
        try:
            entries.append(TemplateEntry.from_dict(item))
        except (TypeError, ValueError, KeyError):
            # Includes templates for screens older versions recognized (Continue, Skip, ...).
            log.warning("Ignoring a template entry Loopter cannot use: %r", item)
    return entries


def _clamp_number(value: Any, default: float, low: float, high: float, kind: type) -> Any:
    # json.loads accepts NaN and Infinity, which would slip through min() and max().
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return default
    return kind(min(max(value, low), high))


def _parse_region(value: Any) -> Region | None:
    if value is None:
        return None
    try:
        return Region.from_dict(value)
    except (TypeError, ValueError, KeyError):
        log.warning("Ignoring invalid saved scan region: %r", value)
        return None


def app_data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "LOOP"


def settings_path() -> Path:
    return app_data_dir() / "settings.json"


def templates_dir() -> Path:
    return app_data_dir() / "templates"


def logs_dir() -> Path:
    return app_data_dir() / "logs"


def load_settings(path: Path | None = None) -> Settings:
    path = path or settings_path()
    if not path.exists():
        return Settings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("top-level value is not an object")
    except (OSError, ValueError) as exc:
        backup = path.with_suffix(".json.bak")
        log.warning(
            "Settings file could not be read (%s). Using defaults; the old file was kept as %s",
            exc,
            backup.name,
        )
        try:
            path.replace(backup)
        except OSError:
            log.exception("Could not back up the unreadable settings file")
        return Settings()
    return Settings.from_dict(data)


def save_settings(settings: Settings, path: Path | None = None) -> None:
    path = path or settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(settings.to_dict(), indent=2), encoding="utf-8")
    tmp.replace(path)
