"""Settings store invariants (#2): defaults, validation/clamping, atomic
persistence, and reload-on-change so hand edits and admin writes coexist."""

from __future__ import annotations

import json

from fugleramme.fonts import DEFAULT_FONT, DEFAULT_LABEL_SIZE
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


def test_sources_default_empty_means_all(tmp_path):
    # Empty is the "all present" sentinel; names.resolve expands it at render time.
    assert SettingsStore(tmp_path / "s.json").get().sources == ()


def test_sources_persist_and_dedupe(tmp_path):
    path = tmp_path / "s.json"
    saved = SettingsStore(path).update(sources=["gould", "vonwright", "gould"])
    assert saved.sources == ("gould", "vonwright")
    assert json.loads(path.read_text())["sources"] == ["gould", "vonwright"]
    assert SettingsStore(path).get() == saved


def test_sources_invalid_falls_back_to_empty(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"sources": [1, "gould", None, ""]}))
    # Non-string / empty entries are dropped, not coerced.
    assert SettingsStore(path).get().sources == ("gould",)


def test_label_font_and_size_fall_back_to_defaults(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(
        json.dumps({"label_font": "comic-sans", "label_size": "huge", "show_names": "off"})
    )
    settings = SettingsStore(path).get()
    assert settings.label_font == DEFAULT_FONT
    assert settings.label_size == DEFAULT_LABEL_SIZE
    assert settings.show_names is False


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
