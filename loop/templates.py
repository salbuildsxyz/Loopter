"""The user's template collection: PNG files in the app data folder, listed in settings.

A collection can be exported as a profile (a folder with profile.json and the images)
and imported elsewhere, so templates captured once can be reused and shared.
"""

from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path

import numpy as np

from loop.config import TemplateEntry
from loop.matcher import (
    Template,
    TemplateError,
    load_template,
    look_alike,
    read_image,
    template_from_image,
    write_image,
)
from loop.screens import Button, Screen

PROFILE_FILE = "profile.json"
PROFILE_VERSION = 1


class TemplateLibrary:
    def __init__(self, directory: Path, entries: list[TemplateEntry]) -> None:
        self.directory = directory
        self.entries = entries  # shared with Settings.templates, so edits persist with settings

    def add_image(
        self,
        image_bgr: np.ndarray,
        screen: Screen,
        source_height: int | None,
        button: Button | None = None,
    ) -> TemplateEntry:
        """Saves a cropped screenshot as a new template. Raises TemplateError if it is unusable."""
        entry = TemplateEntry("", screen, source_height, button)
        self._check_new(template_from_image(entry.label, image_bgr, source_height), entry)
        path = self._unique_path(f"{screen.value}-{time.strftime('%Y%m%d-%H%M%S')}")
        write_image(path, image_bgr)
        return self._add(replace(entry, path=str(path)))

    def import_file(self, source: Path, screen: Screen, button: Button | None = None) -> TemplateEntry:
        """Copies an image into the library so later edits to the original do not affect matching.

        The display it came from is unknown, so it is matched at its own size.
        """
        image = read_image(source)
        entry = TemplateEntry("", screen, None, button)
        self._check_new(template_from_image(source.stem, image), entry)
        path = self._unique_path(f"{screen.value}-{source.stem}")
        write_image(path, image)
        return self._add(replace(entry, path=str(path)))

    def remove(self, entry: TemplateEntry) -> None:
        """Removes a template from the list; deletes the file only if LOOP created it."""
        self.entries.remove(entry)
        file = Path(entry.path)
        if file.parent.resolve() == self.directory.resolve():
            file.unlink(missing_ok=True)

    def status(self, entry: TemplateEntry) -> tuple[bool, str]:
        """Whether the template is usable, with its size or the reason it is not."""
        try:
            width, height = load_template(Path(entry.path)).size
        except TemplateError as exc:
            return False, str(exc)
        return True, f"{width} × {height}"

    def usable_buttons(self) -> set[Button]:
        """Buttons with at least one template that can be loaded."""
        return {e.button for e in self.entries if e.button is not None and self.status(e)[0]}

    def load(self) -> tuple[dict[Screen, list[Template]], list[str]]:
        """Usable templates grouped by screen, plus a message for each one that could not be loaded.

        Templates are named after the button or screen they show, as the log reports them.
        """
        groups: dict[Screen, list[Template]] = {}
        problems = []
        for entry, template in self._loaded(problems):
            groups.setdefault(entry.screen, []).append(replace(template, name=entry.label))
        return groups, problems

    def conflicts(self) -> list[str]:
        """Messages for templates of different screens that show the same thing.

        Such a pair means one of them was saved for the wrong screen, and recognition
        could report the wrong screen with high confidence.
        """
        loaded = self._loaded([])
        messages = []
        for i, (entry, template) in enumerate(loaded):
            for other, other_template in loaded[i + 1 :]:
                if entry.screen is not other.screen and look_alike(template, other_template):
                    messages.append(_conflict_message(entry, other))
        return messages

    def export_profile(self, folder: Path) -> int:
        """Writes the usable templates and profile.json to `folder`; returns how many were exported.

        The folder must be empty or new, so an export never overwrites another profile.
        """
        if folder.is_dir() and any(folder.iterdir()):
            raise TemplateError(f"'{folder.name}' is not empty. Choose an empty folder for the export.")
        folder.mkdir(parents=True, exist_ok=True)
        records = []
        for entry, _ in self._loaded([]):
            name = f"{len(records) + 1:02d}-{entry.screen.value}.png"
            write_image(folder / name, read_image(Path(entry.path)))
            records.append(replace(entry, path=name).to_dict())
        data = {"version": PROFILE_VERSION, "templates": records}
        (folder / PROFILE_FILE).write_text(json.dumps(data, indent=2), encoding="utf-8")
        return len(records)

    def import_profile(self, profile: Path) -> tuple[list[TemplateEntry], list[str]]:
        """Adds the templates listed in a profile.json; returns the new entries and any problems."""
        try:
            data = json.loads(profile.read_text(encoding="utf-8"))
            records = data["templates"]
            if not isinstance(records, list):
                raise TypeError("'templates' is not a list")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise TemplateError(f"'{profile.name}' is not a LOOP profile: {exc}") from exc
        added, problems = [], []
        for record in records:
            try:
                entry = TemplateEntry.from_dict(record)
                source = _inside(profile.parent, entry.path)
                image = read_image(source)
                self._check_new(template_from_image(source.stem, image, entry.source_height), entry)
            except (TemplateError, ValueError, KeyError, TypeError) as exc:
                problems.append(f"Skipped {record!r}: {exc}")
                continue
            path = self._unique_path(f"{entry.screen.value}-{source.stem}")
            write_image(path, image)
            added.append(self._add(replace(entry, path=str(path))))
        return added, problems

    def _loaded(self, problems: list[str]) -> list[tuple[TemplateEntry, Template]]:
        loaded = []
        for entry in self.entries:
            try:
                loaded.append((entry, load_template(Path(entry.path), entry.source_height)))
            except TemplateError as exc:
                problems.append(str(exc))
        return loaded

    def _check_new(self, template: Template, entry: TemplateEntry) -> None:
        for other, other_template in self._loaded([]):
            if other.screen is entry.screen and np.array_equal(template.image, other_template.image):
                name = Path(other.path).stem
                raise TemplateError(f"Already saved as your '{other.label}' template '{name}'.")
            if other.screen is not entry.screen and look_alike(template, other_template):
                raise TemplateError(
                    f"This looks the same as your '{other.label}' template '{Path(other.path).stem}', "
                    f"which belongs to the {other.screen.label} screen. Check which screen it shows, "
                    "or remove the other template if that one was saved for the wrong screen."
                )

    def _add(self, entry: TemplateEntry) -> TemplateEntry:
        self.entries.append(entry)
        return entry

    def _unique_path(self, stem: str) -> Path:
        path = self.directory / f"{stem}.png"
        counter = 2
        taken = {e.path for e in self.entries}
        while path.exists() or str(path) in taken:
            path = self.directory / f"{stem}-{counter}.png"
            counter += 1
        return path


def _inside(folder: Path, relative: str) -> Path:
    """The file a profile lists, which must be inside the profile's folder."""
    path = (folder / relative).resolve()
    if not path.is_relative_to(folder.resolve()):
        raise TemplateError(f"'{relative}' is outside the profile folder.")
    return path


def _conflict_message(a: TemplateEntry, b: TemplateEntry) -> str:
    return (
        f"The '{a.label}' template '{Path(a.path).stem}' ({a.screen.label}) and the '{b.label}' template "
        f"'{Path(b.path).stem}' ({b.screen.label}) show the same thing. One of them was saved for the "
        "wrong screen; remove it in Settings."
    )
