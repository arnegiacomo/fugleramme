"""Settings store invariants (#2): defaults, validation/clamping, atomic
persistence, and reload-on-change so hand edits and admin writes coexist."""

from __future__ import annotations

import json

from fugleramme.fonts import DEFAULT_FONT, DEFAULT_LABEL_SIZE
from fugleramme.languages import NONE, SCIENTIFIC
from fugleramme.settings import Settings, SettingsStore


def test_defaults_when_file_absent(tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    assert store.get() == Settings()


def test_update_persists_and_clamps(tmp_path):
    path = tmp_path / "settings.json"
    store = SettingsStore(path)

    saved = store.update(
        web_resolution="1440p", rotation="90", lookback_hours="6", kiosk_refresh_seconds="0"
    )
    assert saved.web_resolution == "1440p"
    assert saved.rotation == 90  # arrives as a form string
    assert saved.lookback_hours == 6
    assert saved.kiosk_refresh_seconds == 1  # clamped up to the floor

    # Written to disk and reloaded identically by a fresh store.
    assert json.loads(path.read_text())["rotation"] == 90
    assert SettingsStore(path).get() == saved


def test_invalid_values_fall_back_to_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"web_resolution": "9000p", "rotation": 45, "lookback_hours": "abc"})
    )
    settings = SettingsStore(path).get()
    assert settings.web_resolution == "1080p"
    assert settings.rotation == 0  # 45 is not a quarter turn
    assert settings.lookback_hours == 24


def test_reload_picks_up_external_edit(tmp_path):
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    store.update(lookback_hours=12)

    # Simulate a hand edit landing on disk after the store loaded.
    path.write_text(json.dumps({"lookback_hours": 48}))
    assert store.get().lookback_hours == 48


def test_style_default_empty_means_whichever_is_present(tmp_path):
    # Empty is the "unset" sentinel; names.resolve settles it at render time.
    assert SettingsStore(tmp_path / "s.json").get().style == ""


def test_style_persists(tmp_path):
    path = tmp_path / "s.json"
    saved = SettingsStore(path).update(style="classic")
    assert saved.style == "classic"
    assert json.loads(path.read_text())["style"] == "classic"
    assert SettingsStore(path).get() == saved


def test_style_migrates_from_the_old_sources_list(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"sources": ["gould", "vonwright"]}))
    store = SettingsStore(path)
    assert store.get().style == "gould"
    # The write drops `sources` for good; a stale name is names.resolve's problem.
    store.update(style="classic")
    assert "sources" not in json.loads(path.read_text())


def test_style_invalid_falls_back_to_empty(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"style": 7}))
    assert SettingsStore(path).get().style == ""


def test_label_font_and_size_fall_back_to_defaults(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(
        json.dumps({"label_font": "comic-sans", "label_size": "huge", "show_names": "off"})
    )
    settings = SettingsStore(path).get()
    assert settings.label_font == DEFAULT_FONT
    assert settings.label_size == DEFAULT_LABEL_SIZE
    assert settings.show_names is False


def test_language_codes_are_kept_by_shape_not_by_availability(tmp_path):
    path = tmp_path / "s.json"
    # Any locale-code shape is kept: which ones BirdNET-Go serves is a render-time
    # question (like `style`), so a container that is down can't reset the setting.
    path.write_text(json.dumps({"primary_language": "NB", "secondary_language": "pt-br"}))
    settings = SettingsStore(path).get()
    assert settings.primary_language == "nb"
    assert settings.secondary_language == "pt-br"


def test_bad_languages_fall_back_and_a_primary_is_always_set(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"primary_language": "", "secondary_language": "norwegian"}))
    settings = SettingsStore(path).get()
    assert settings.primary_language == SCIENTIFIC  # required; empty means scientific
    assert settings.secondary_language == NONE


def test_oriented_swaps_only_for_quarter_turns():
    assert Settings(rotation=0).oriented((800, 480)) == (800, 480)
    assert Settings(rotation=180).oriented((800, 480)) == (800, 480)
    assert Settings(rotation=90).oriented((800, 480)) == (480, 800)
    assert Settings(rotation=270).oriented((800, 480)) == (480, 800)
    # Idempotent regardless of input order.
    assert Settings(rotation=0).oriented((480, 800)) == (800, 480)


def test_web_size_from_resolution_and_rotation():
    assert Settings(web_resolution="1080p").web_size() == (1920, 1080)
    assert Settings(web_resolution="720p").web_size() == (1280, 720)
    assert Settings(web_resolution="1080p", rotation=90).web_size() == (1080, 1920)
