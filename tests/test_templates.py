import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from loop.config import TemplateEntry
from loop.demo import TEMPLATES_DIR, demo_template_path
from loop.matcher import TemplateError, read_image
from loop.screens import Button, Screen
from loop.templates import PROFILE_FILE, TemplateLibrary


@pytest.fixture
def library(tmp_path):
    return TemplateLibrary(tmp_path / "templates", [])


def play_image():
    return read_image(demo_template_path(Screen.LOBBY))


def test_add_image_records_screen_and_display_height(library):
    entry = library.add_image(play_image(), Screen.LOBBY, 1440)
    assert entry.screen is Screen.LOBBY
    assert entry.source_height == 1440
    assert entry.path.endswith(".png") and "lobby-" in entry.path
    assert library.entries == [entry]
    assert library.status(entry) == (True, "236 × 60")


def test_add_image_rejects_flat_selection(library):
    with pytest.raises(TemplateError):
        library.add_image(np.zeros((30, 30, 3), np.uint8), Screen.RESULTS, 1080)
    assert library.entries == []


def test_names_do_not_collide(library):
    first = library.add_image(play_image(), Screen.LOBBY, 1080)
    second = library.add_image(play_image()[1:-1], Screen.LOBBY, 1080)
    assert first.path != second.path


def test_the_same_image_is_not_added_twice(library, tmp_path):
    library.add_image(play_image(), Screen.LOBBY, 1080)
    with pytest.raises(TemplateError, match="Already saved as your 'Play' template"):
        library.add_image(play_image(), Screen.LOBBY, 1080, Button.READY)
    source = tmp_path / "copy.png"
    source.write_bytes(demo_template_path(Screen.LOBBY).read_bytes())
    with pytest.raises(TemplateError, match="Already saved"):
        library.import_file(source, Screen.LOBBY)
    assert len(library.entries) == 1


def test_import_copies_file_without_display_height(library, tmp_path):
    source = tmp_path / "external.png"
    source.write_bytes(demo_template_path(Screen.RESULTS).read_bytes())
    entry = library.import_file(source, Screen.RESULTS)
    assert entry.source_height is None
    source.unlink()
    assert library.status(entry)[0]


def test_remove_deletes_only_owned_files(library, tmp_path):
    owned = library.add_image(play_image(), Screen.LOBBY, 1080)
    foreign_path = tmp_path / "keep-me.png"
    foreign_path.write_bytes(demo_template_path(Screen.LOBBY).read_bytes())
    foreign = TemplateEntry(str(foreign_path), Screen.RESULTS)
    library.entries.append(foreign)
    library.remove(owned)
    library.remove(foreign)
    assert library.entries == []
    assert foreign_path.exists()


def test_load_groups_by_screen_and_reports_problems(library, tmp_path):
    library.add_image(play_image(), Screen.LOBBY, 1080)
    library.add_image(read_image(demo_template_path(Screen.RESULTS)), Screen.RESULTS, 1080)
    library.entries.append(TemplateEntry(str(tmp_path / "gone.png"), Screen.RESULTS))
    groups, problems = library.load()
    assert {s: len(g) for s, g in groups.items()} == {Screen.LOBBY: 1, Screen.RESULTS: 1}
    assert groups[Screen.LOBBY][0].source_height == 1080
    assert len(problems) == 1 and "missing" in problems[0]


def test_status_reports_missing_file(library, tmp_path):
    ok, message = library.status(TemplateEntry(str(tmp_path / "gone.png"), Screen.LOBBY))
    assert not ok and "missing" in message


def image(name):
    return read_image(TEMPLATES_DIR / name)


def test_buttons_are_recorded_and_named(library):
    ready = library.add_image(image("ready.png"), Screen.LOBBY, 540, Button.READY)
    assert (ready.button, ready.label) == (Button.READY, "Ready")
    groups, _ = library.load()
    assert [t.name for t in groups[Screen.LOBBY]] == ["Ready"]


def test_play_and_ready_can_both_belong_to_the_lobby(library):
    library.add_image(image("play.png"), Screen.LOBBY, 540, Button.PLAY)
    library.add_image(image("ready.png"), Screen.LOBBY, 540, Button.READY)
    assert library.conflicts() == []


@pytest.mark.parametrize("size", [(236, 60), (354, 90)])  # the same button captured at another size
def test_the_same_button_cannot_be_saved_for_two_screens(library, size):
    library.add_image(image("play.png"), Screen.LOBBY, 540, Button.PLAY)
    resized = cv2.resize(image("play.png"), size, interpolation=cv2.INTER_LINEAR)
    with pytest.raises(TemplateError, match="looks the same as your 'Play' template"):
        library.add_image(resized, Screen.RESULTS, 540)
    assert len(library.entries) == 1


def test_different_buttons_are_not_conflicts(library):
    library.add_image(image("play.png"), Screen.LOBBY, 540, Button.PLAY)
    library.add_image(image("play_again.png"), Screen.RESULTS, 540)
    library.add_image(image("matchmaking.png"), Screen.MATCHMAKING, 540)
    assert library.conflicts() == []


def test_conflicts_in_existing_settings_are_reported(library, tmp_path):
    """Entries saved by an older version, or edited by hand, are checked as well."""
    for name, screen in (("a.png", Screen.LOBBY), ("b.png", Screen.RESULTS)):
        path = tmp_path / name
        path.write_bytes((TEMPLATES_DIR / "play.png").read_bytes())
        library.entries.append(TemplateEntry(str(path), screen, 540))
    [message] = library.conflicts()
    assert "'a'" in message and "'b'" in message and "wrong screen" in message


def test_profile_round_trip(library, tmp_path):
    library.add_image(image("play.png"), Screen.LOBBY, 1080, Button.PLAY)
    library.add_image(image("ready.png"), Screen.LOBBY, 1080, Button.READY)
    library.add_image(image("play_again.png"), Screen.RESULTS, 1440)
    assert library.export_profile(tmp_path / "profile") == 3

    other = TemplateLibrary(tmp_path / "elsewhere", [])
    added, problems = other.import_profile(tmp_path / "profile" / PROFILE_FILE)
    assert problems == []
    assert [(e.screen, e.button, e.source_height) for e in added] == [
        (Screen.LOBBY, Button.PLAY, 1080),
        (Screen.LOBBY, Button.READY, 1080),
        (Screen.RESULTS, Button.PLAY_AGAIN, 1440),
    ]
    assert all(Path(e.path).parent == tmp_path / "elsewhere" for e in added)
    assert other.load()[1] == []


def test_export_refuses_a_folder_that_is_not_empty(library, tmp_path):
    library.add_image(image("play.png"), Screen.LOBBY, 1080, Button.PLAY)
    folder = tmp_path / "existing"
    folder.mkdir()
    (folder / PROFILE_FILE).write_text("someone else's profile")
    with pytest.raises(TemplateError, match="empty folder"):
        library.export_profile(folder)
    assert (folder / PROFILE_FILE).read_text() == "someone else's profile"
    assert sorted(p.name for p in folder.iterdir()) == [PROFILE_FILE]


def test_profile_import_skips_bad_entries(library, tmp_path):
    folder = tmp_path / "profile"
    folder.mkdir()
    (folder / "play.png").write_bytes((TEMPLATES_DIR / "play.png").read_bytes())
    records = [
        {"path": "play.png", "screen": "lobby", "button": "play", "source_height": 540},
        {"path": "../outside.png", "screen": "results"},  # outside the profile folder
        {"path": "play.png", "screen": "results", "button": "play"},  # button not on that screen
        {"path": "missing.png", "screen": "loading"},
    ]
    (folder / PROFILE_FILE).write_text(json.dumps({"version": 1, "templates": records}))
    added, problems = library.import_profile(folder / PROFILE_FILE)
    assert [e.button for e in added] == [Button.PLAY]
    assert len(problems) == 3


def test_profile_import_reads_subfolders_and_skips_what_is_already_there(library, tmp_path):
    folder = tmp_path / "profile"
    (folder / "buttons").mkdir(parents=True)
    (folder / "buttons" / "play.png").write_bytes((TEMPLATES_DIR / "play.png").read_bytes())
    (tmp_path / "outside.png").write_bytes((TEMPLATES_DIR / "ready.png").read_bytes())
    records = [
        {"path": "buttons/play.png", "screen": "lobby", "button": "play", "source_height": 540},
        {"path": "../outside.png", "screen": "lobby", "button": "ready"},
    ]
    (folder / PROFILE_FILE).write_text(json.dumps({"version": 1, "templates": records}))

    added, problems = library.import_profile(folder / PROFILE_FILE)
    assert [(e.button, e.source_height) for e in added] == [(Button.PLAY, 540)]
    assert len(problems) == 1 and "outside the profile folder" in problems[0]

    added, problems = library.import_profile(folder / PROFILE_FILE)
    assert added == [] and "Already saved" in problems[0]
    assert len(library.entries) == 1


def test_profile_import_rejects_other_files(library, tmp_path):
    bad = tmp_path / PROFILE_FILE
    bad.write_text("[1, 2]")
    with pytest.raises(TemplateError, match="not a LOOP profile"):
        library.import_profile(bad)
