import json

import pytest

from loop.capture import Region
from loop.config import Mode, Settings, TemplateEntry, load_settings, save_settings, settings_path
from loop.screens import ACTIONABLE, Button, Screen


def test_round_trip(tmp_path):
    path = tmp_path / "settings.json"
    original = Settings(
        mode=Mode.LIVE,
        threshold=0.91,
        scan_interval_ms=1200,
        cooldown_s=4.5,
        region=Region(-1920, 0, 800, 600),
        monitor=2,
        templates=[
            TemplateEntry("C:/t/a.png", Screen.LOBBY, 1080),
            TemplateEntry("C:/t/b.png", Screen.LOADING),
        ],
        actions={Screen.LOBBY},
        demo_clicks_enabled=True,
        emergency_hotkey="Ctrl+Alt+End",
        log_expanded=False,
    )
    save_settings(original, path)
    assert load_settings(path) == original


def test_defaults():
    s = Settings()
    assert s.mode is Mode.DEMO
    assert s.actions == set(ACTIONABLE)
    assert s.demo_clicks_enabled is False


def test_live_interaction_is_never_restored(tmp_path):
    path = tmp_path / "settings.json"
    save_settings(Settings(mode=Mode.INTERACTION), path)
    assert json.loads(path.read_text())["mode"] == "interaction"
    assert load_settings(path).mode is Mode.LIVE


def test_missing_file_gives_defaults(tmp_path):
    assert load_settings(tmp_path / "nope.json") == Settings()


def test_out_of_range_values_are_clamped(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"threshold": 5, "scan_interval_ms": 1, "cooldown_s": 999, "monitor": -3}))
    s = load_settings(path)
    assert s.threshold == 0.99
    assert s.scan_interval_ms == 100
    assert s.cooldown_s == 30.0
    assert s.monitor == 1


def test_wrong_types_fall_back_per_field(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "mode": "turbo",
                "threshold": "high",
                "scan_interval_ms": True,
                "region": {"left": 0, "top": 0, "width": -5, "height": 10},
                "templates": [
                    {"path": "ok.png", "screen": "results", "source_height": 1440},
                    {"path": "from-phase-2.png", "screen": "skip", "source_height": 1080},
                    {"path": "bad-screen.png", "screen": "unknown"},
                    {"path": "bad-height.png", "screen": "lobby", "source_height": -1},
                    "old-style.png",
                    None,
                ],
                "actions": ["lobby", "loading", "continue", "nonsense"],
                "demo_clicks_enabled": "yes",
                "emergency_hotkey": "",
            }
        )
    )
    s = load_settings(path)
    defaults = Settings()
    assert s.mode is Mode.DEMO
    assert s.threshold == defaults.threshold
    assert s.scan_interval_ms == defaults.scan_interval_ms
    assert s.region is None
    assert s.templates == [TemplateEntry("ok.png", Screen.RESULTS, 1440)]
    assert s.actions == {Screen.LOBBY}  # loading has no button; nonsense is ignored
    assert s.demo_clicks_enabled is False
    assert s.emergency_hotkey == defaults.emergency_hotkey


def test_non_finite_numbers_fall_back_to_defaults(tmp_path):
    # Python's json module reads NaN and Infinity, so a hand-edited file can contain them.
    path = tmp_path / "settings.json"
    path.write_text('{"threshold": NaN, "scan_interval_ms": NaN, "cooldown_s": Infinity}')
    s = load_settings(path)
    defaults = Settings()
    assert s.threshold == defaults.threshold
    assert s.scan_interval_ms == defaults.scan_interval_ms
    assert s.cooldown_s == defaults.cooldown_s


def test_unhashable_values_are_ignored(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"mode": ["live"], "actions": [["lobby"], {"x": 1}, "results"]}))
    s = load_settings(path)
    assert s.mode is Mode.DEMO
    assert s.actions == {Screen.RESULTS}


def test_corrupt_file_is_backed_up(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json")
    assert load_settings(path) == Settings()
    assert not path.exists()
    assert (tmp_path / "settings.json.bak").read_text() == "{not json"


def test_default_location_uses_appdata(isolated_app_data):
    save_settings(Settings(threshold=0.7))
    assert settings_path() == isolated_app_data / "settings.json"
    assert load_settings().threshold == 0.7


def test_template_entries_name_their_button():
    old = TemplateEntry.from_dict({"path": "p.png", "screen": "lobby", "source_height": 1080})
    assert old.button is Button.PLAY  # saved before Ready existed
    results = TemplateEntry.from_dict({"path": "r.png", "screen": "results"})
    assert results.button is Button.PLAY_AGAIN
    ready = TemplateEntry.from_dict({"path": "q.png", "screen": "lobby", "button": "ready"})
    assert TemplateEntry.from_dict(ready.to_dict()) == ready
    waiting = TemplateEntry.from_dict({"path": "w.png", "screen": "loading"})
    assert waiting.button is None and waiting.label == "Loading"


@pytest.mark.parametrize(
    "data",
    [
        {"path": "x.png", "screen": "results", "button": "ready"},
        {"path": "x.png", "screen": "loading", "button": "play"},
        {"path": "x.png", "screen": "unknown"},
        {"path": "x.png", "screen": "lobby", "button": "start"},
    ],
)
def test_inconsistent_template_entries_are_rejected(data):
    with pytest.raises(ValueError):
        TemplateEntry.from_dict(data)
