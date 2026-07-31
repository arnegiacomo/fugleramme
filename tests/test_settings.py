"""Settings store invariants (#2): defaults, validation/clamping, atomic
persistence, and reload-on-change so hand edits and admin writes coexist."""

from __future__ import annotations

import json

from fugleramme.settings import Settings, SettingsStore


def test_defaults_when_file_absent(tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    assert store.get() == Settings()


def test_update_persists_and_clamps(tmp_path):
    path = tmp_path / "settings.json"
    store = SettingsStore(path)

    saved = store.update(panel="13.3", orientation="portrait", lookback_hours="6", kiosk_refresh_seconds="0")
    assert saved.panel == "13.3"
    assert saved.orientation == "portrait"
    assert saved.lookback_hours == 6
    assert saved.kiosk_refresh_seconds == 1  # clamped up to the floor

    # Written to disk and reloaded identically by a fresh store.
    assert json.loads(path.read_text())["orientation"] == "portrait"
    assert SettingsStore(path).get() == saved


def test_invalid_values_fall_back_to_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"panel": "9.9", "orientation": "sideways", "lookback_hours": "abc"}))
    settings = SettingsStore(path).get()
    assert settings.panel == "7.3"
    assert settings.orientation == "landscape"
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


def test_oriented_swaps_only_for_portrait():
    assert Settings(orientation="landscape").oriented((800, 480)) == (800, 480)
    assert Settings(orientation="portrait").oriented((800, 480)) == (480, 800)
    # Idempotent regardless of input order.
    assert Settings(orientation="landscape").oriented((480, 800)) == (800, 480)


def test_resolution_from_panel_and_orientation():
    assert Settings(panel="7.3").resolution() == (800, 480)
    assert Settings(panel="13.3").resolution() == (1600, 1200)
    assert Settings(panel="7.3", orientation="portrait").resolution() == (480, 800)
