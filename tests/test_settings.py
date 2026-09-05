"""Settings store invariants (#2): defaults, validation/clamping, atomic
persistence, and reload-on-change so hand edits and admin writes coexist."""

from __future__ import annotations

import json

import pytest

from fugleramme.config import DEFAULT_DETECTOR_URL
from fugleramme.languages import NONE, SCIENTIFIC
from fugleramme.render.fonts import DEFAULT_FONT, DEFAULT_LABEL_SIZE
from fugleramme.settings import (
    ALL_TIME,
    LOOKBACK_OPTIONS,
    Settings,
    SettingsStore,
    lookback_order,
)


def test_defaults_when_file_absent(tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    assert store.get() == Settings()


def test_update_persists_and_clamps(tmp_path):
    path = tmp_path / "settings.json"
    store = SettingsStore(path)

    saved = store.update(web_resolution="1440p", rotation="90", lookback_hours="9000")
    assert saved.web_resolution == "1440p"
    assert saved.rotation == 90  # arrives as a form string
    assert saved.lookback_hours == 720  # clamped down to the ceiling

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


def test_the_kiosk_takes_its_shape_from_the_panel_and_only_its_height_from_the_setting():
    """The layout is packed into whatever rectangle it is given, so a kiosk of a
    different aspect than the glass is a different page, not a scaled one."""
    for panel in ((1600, 1200), (800, 480)):
        for size in ("720p", "1440p"):
            w, h = Settings(web_resolution=size).web_size(panel)
            assert h == {"720p": 720, "1440p": 1440}[size]
            assert w / h == pytest.approx(panel[0] / panel[1], abs=0.002)

    assert Settings(web_resolution="1080p").web_size((1600, 1200)) == (1440, 1080)


def test_rotation_turns_the_kiosk_render_without_shrinking_it():
    """Sizing after the turn would spend 44% fewer pixels on a portrait frame
    for the same setting."""
    landscape = Settings(web_resolution="1080p").web_size((1600, 1200))
    portrait = Settings(web_resolution="1080p", rotation=90).web_size((1600, 1200))
    assert portrait == landscape[::-1] == (1080, 1440)


def test_all_time_is_a_lookback_the_admin_offers(tmp_path):
    assert (ALL_TIME, "All time") in LOOKBACK_OPTIONS
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"lookback_hours": ALL_TIME}))
    assert SettingsStore(path).get().lookback_hours == ALL_TIME


def test_all_time_sorts_as_the_longest_window():
    hours = [h for h, _ in LOOKBACK_OPTIONS]
    assert sorted(hours, key=lookback_order) == sorted(h for h in hours if h) + [ALL_TIME]


def test_a_negative_lookback_clamps_to_all_time(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"lookback_hours": -5}))
    assert SettingsStore(path).get().lookback_hours == ALL_TIME


def test_the_detector_url_is_kept_by_shape(tmp_path):
    path = tmp_path / "settings.json"
    assert SettingsStore(path).update(detector_url="https://pi.local:8090/").detector_url == (
        "https://pi.local:8090"  # the trailing slash goes, so paths join cleanly
    )
    for bad in ("pi.local:8090", "ftp://pi", "", 8090):
        path.write_text(json.dumps({"detector_url": bad}))
        assert SettingsStore(path).get().detector_url == DEFAULT_DETECTOR_URL


def test_a_launch_default_only_fills_in_what_the_file_does_not_say(tmp_path):
    """The systemd unit passes no flags, so an existing settings.json must keep
    working; --detector is only for a file that names none."""
    path = tmp_path / "settings.json"
    flagged = Settings(detector_url="http://elsewhere:8090")

    assert SettingsStore(path, flagged).get().detector_url == "http://elsewhere:8090"

    path.write_text(json.dumps({"detector_url": "http://saved:8090"}))
    assert SettingsStore(path, flagged).get().detector_url == "http://saved:8090"


def test_detector_connection_round_trips(tmp_path):
    path = tmp_path / "s.json"
    saved = SettingsStore(path).update(
        detector_url="http://birdnet.local:8080/",
        detector_username="birdnet",
        detector_password="hunter2",
    )
    assert saved.detector_url == "http://birdnet.local:8080"  # trailing slash dropped
    assert saved.detector_username == "birdnet"
    assert saved.detector_password == "hunter2"
    assert SettingsStore(path).get() == saved


def test_a_detector_url_that_is_not_one_falls_back(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"detector_url": "birdnet.local", "detector_username": 7}))
    settings = SettingsStore(path).get()
    assert settings.detector_url == DEFAULT_DETECTOR_URL
    assert settings.detector_username == ""


def test_the_launch_flag_only_fills_in_a_url_the_file_lacks(tmp_path):
    path = tmp_path / "s.json"
    flagged = Settings(detector_url="http://flag:8090")
    assert SettingsStore(path, flagged).get().detector_url == "http://flag:8090"

    path.write_text(json.dumps({"detector_url": "http://saved:8090"}))
    assert SettingsStore(path, flagged).get().detector_url == "http://saved:8090"
