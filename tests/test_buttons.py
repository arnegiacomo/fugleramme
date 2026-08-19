"""What each button does. The GPIO side is Pi-only, so what is testable here is
the mapping from a press to a settings write - and that it persists."""

from __future__ import annotations

import pytest

from fugleramme.buttons import changes_for, pins_for, press
from fugleramme.modes import MODES
from fugleramme.settings import Settings, SettingsStore


@pytest.fixture
def images_dir(tmp_path):
    for style in ("classic", "custom", "modern"):
        (tmp_path / style / "birds").mkdir(parents=True)
        # An empty style is not offered.
        (tmp_path / style / "birds" / "turdus-merula.png").write_bytes(b"x")
    return tmp_path


def test_the_13_3_moves_button_c():
    assert pins_for("inky.inky_el133uf1") == (5, 6, 25, 24)
    assert pins_for("inky.inky_ac073tc1a") == (5, 6, 16, 24)


def test_a_walks_the_modes_and_wraps(images_dir):
    settings = Settings()
    seen = []
    for _ in range(len(MODES) + 1):
        settings = Settings(mode=changes_for("A", settings, images_dir)["mode"])
        seen.append(settings.mode)
    assert seen == list(MODES)[1:] + list(MODES)[:2]


def test_a_restarts_the_walk_from_an_unknown_mode(images_dir):
    assert changes_for("A", Settings(mode="gone"), images_dir) == {"mode": next(iter(MODES))}


def test_b_toggles_names(images_dir):
    assert changes_for("B", Settings(show_names=True), images_dir) == {"show_names": False}
    assert changes_for("B", Settings(show_names=False), images_dir) == {"show_names": True}


def test_c_turns_the_picture_clockwise(images_dir):
    # Clockwise on the glass counts settings.rotation (counter-clockwise) down.
    settings = Settings()
    seen = []
    for _ in range(4):
        settings = Settings(rotation=changes_for("C", settings, images_dir)["rotation"])
        seen.append(settings.rotation)
    assert seen == [270, 180, 90, 0]


def test_d_walks_the_styles_and_wraps(images_dir):
    settings = Settings()  # unset, so the first press starts the cycle
    seen = []
    for _ in range(4):
        settings = Settings(style=changes_for("D", settings, images_dir)["style"])
        seen.append(settings.style)
    assert seen == ["classic", "custom", "modern", "classic"]


def test_d_restarts_the_cycle_from_a_stale_style(images_dir):
    assert changes_for("D", Settings(style="gould"), images_dir) == {"style": "classic"}


def test_d_does_nothing_with_no_artwork(tmp_path):
    assert changes_for("D", Settings(), tmp_path) is None


def test_a_press_persists(tmp_path, images_dir):
    store = SettingsStore(tmp_path / "settings.json")
    press("B", store, images_dir)
    assert store.get().show_names is False
    assert SettingsStore(tmp_path / "settings.json").get().show_names is False
