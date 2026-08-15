"""Mode invariants. The keys matter more than the pixels: a key that moves on
every detection would spend the day refreshing e-ink, and a key that never moves
would freeze the frame."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from PIL import Image

from fugleramme import modes
from fugleramme.db import Database
from fugleramme.featured import Featured
from fugleramme.languages import namer
from fugleramme.picks import Picks
from fugleramme.settings import Settings

NOW = datetime.now(UTC)


def _db(path, detections):
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE label_types (id INTEGER PRIMARY KEY, name TEXT);"
        "CREATE TABLE labels (id INTEGER PRIMARY KEY, scientific_name TEXT, label_type_id INTEGER);"
        "CREATE TABLE detections (id INTEGER PRIMARY KEY, label_id INTEGER, "
        "detected_at INTEGER, confidence REAL, clip_name TEXT);"
        "CREATE TABLE detection_reviews (id INTEGER PRIMARY KEY, detection_id INTEGER, verified TEXT);"
        "INSERT INTO label_types VALUES (1,'species');"
        "INSERT INTO labels VALUES (10,'Turdus merula',1),(11,'Parus major',1);"
    )
    conn.executemany("INSERT INTO detections VALUES (?, ?, ?, ?, ?)", detections)
    conn.commit()
    conn.close()
    return Database(path)


def _row(id_, label_id, ago_hours):
    return (id_, label_id, int((NOW - timedelta(hours=ago_hours)).timestamp()), 0.9, None)


@pytest.fixture
def images(tmp_path):
    """Two species with artwork, in a style of their own."""
    style = tmp_path / "classic"
    style.mkdir()
    for key in ("turdus-merula", "parus-major"):
        Image.new("RGBA", (120, 90), (40, 40, 40, 255)).save(style / f"{key}.png")
    (style / "perches").mkdir()
    Image.new("RGBA", (80, 60), (20, 20, 20, 255)).save(style / "perches" / "twig.png")
    return tmp_path


def _ctx(db, images, tmp_path, mode, commit=False, **overrides):
    settings = Settings(mode=mode, **overrides)
    return modes.context(
        db,
        images,
        Picks(tmp_path / "artwork.json"),
        Featured(tmp_path / "featured.json"),
        settings,
        namer("sci", "", tmp_path),
        (400, 300),
        textured=False,
        commit=commit,
    )


def test_every_mode_is_offered_and_the_default_is_the_collage():
    assert modes.DEFAULT_MODE == "collage"
    assert list(modes.MODES) == ["collage", "latest", "daily", "arrival"]
    assert [k for k, m in modes.MODES.items() if m.windowed] == ["collage"]
    assert modes.mode_of("gone") is modes.MODES["collage"]


@pytest.mark.parametrize("mode", list(modes.MODES))
def test_every_mode_draws_something(tmp_path, images, mode):
    db = _db(tmp_path / "b.db", [_row(1, 10, 1), _row(2, 11, 2)])
    page = modes.render(_ctx(db, images, tmp_path, mode))
    assert np.asarray(page).std() > 1


@pytest.mark.parametrize("mode", list(modes.MODES))
def test_an_empty_record_falls_back_to_the_perch(tmp_path, images, mode):
    db = _db(tmp_path / "b.db", [])
    page = modes.render(_ctx(db, images, tmp_path, mode))
    assert np.asarray(page).std() > 1  # the branch, not bare paper


def test_the_latest_bird_holds_the_page_while_the_same_bird_calls(tmp_path, images):
    db = _db(tmp_path / "b.db", [_row(1, 10, 2)])
    before = modes.state_key(_ctx(db, images, tmp_path, "latest"))

    conn = sqlite3.connect(tmp_path / "b.db")
    conn.execute("INSERT INTO detections VALUES (?, ?, ?, ?, ?)", _row(2, 10, 1))
    conn.commit()
    conn.close()
    db.close()

    assert modes.state_key(_ctx(db, images, tmp_path, "latest")) == before


def test_the_latest_bird_changes_the_page_when_the_species_changes(tmp_path, images):
    db = _db(tmp_path / "b.db", [_row(1, 10, 2)])
    before = modes.state_key(_ctx(db, images, tmp_path, "latest"))

    conn = sqlite3.connect(tmp_path / "b.db")
    conn.execute("INSERT INTO detections VALUES (?, ?, ?, ?, ?)", _row(2, 11, 1))
    conn.commit()
    conn.close()
    db.close()

    assert modes.state_key(_ctx(db, images, tmp_path, "latest")) != before


def test_the_latest_bird_skips_a_species_it_cannot_draw(tmp_path, images):
    (images / "classic" / "parus-major.png").unlink()
    db = _db(tmp_path / "b.db", [_row(1, 10, 2), _row(2, 11, 1)])
    assert modes.state_key(_ctx(db, images, tmp_path, "latest"))[-1][0] == "Turdus merula"


def test_the_collage_holds_the_page_when_a_bird_already_on_it_calls_again(tmp_path, images):
    """species_since ranks by count, so re-hearing a bird can overtake another
    and reorder the window. The set is the same, so the page must be too."""
    db = _db(tmp_path / "b.db", [_row(1, 11, 2), _row(2, 11, 2), _row(3, 10, 1)])
    before = modes.state_key(_ctx(db, images, tmp_path, "collage"))

    conn = sqlite3.connect(tmp_path / "b.db")
    conn.executemany(
        "INSERT INTO detections VALUES (?, ?, ?, ?, ?)", [_row(n, 10, 0) for n in (4, 5)]
    )
    conn.commit()
    conn.close()
    db.close()

    assert db.species_since()[0][0] == "Turdus merula"  # the ranking did flip
    assert modes.state_key(_ctx(db, images, tmp_path, "collage")) == before


def test_the_bird_of_the_day_ignores_todays_calls(tmp_path, images):
    """Its tally is the record as of midnight, so a bird calling all afternoon
    does not re-render its own page."""
    db = _db(tmp_path / "b.db", [_row(1, 10, 30), _row(2, 11, 30)])
    before = modes.state_key(_ctx(db, images, tmp_path, "daily"))

    conn = sqlite3.connect(tmp_path / "b.db")
    conn.executemany(
        "INSERT INTO detections VALUES (?, ?, ?, ?, ?)",
        [_row(n, 10, 0) for n in range(3, 12)],
    )
    conn.commit()
    conn.close()
    db.close()

    assert modes.state_key(_ctx(db, images, tmp_path, "daily")) == before


def test_the_kiosk_never_advances_the_bird_of_the_day(tmp_path, images):
    db = _db(tmp_path / "b.db", [_row(1, 10, 30), _row(2, 11, 30)])
    modes.state_key(_ctx(db, images, tmp_path, "daily"))
    assert not (tmp_path / "featured.json").exists()

    modes.state_key(_ctx(db, images, tmp_path, "daily", commit=True))
    assert (tmp_path / "featured.json").exists()


def test_the_newest_arrival_is_the_latest_first_ever(tmp_path, images):
    db = _db(tmp_path / "b.db", [_row(1, 10, 200), _row(2, 11, 100), _row(3, 10, 1)])
    assert modes.state_key(_ctx(db, images, tmp_path, "arrival"))[-1][0] == "Parus major"


def test_only_the_collage_reads_the_lookback_window(tmp_path, images):
    db = _db(tmp_path / "b.db", [_row(1, 10, 1), _row(2, 11, 40)])
    for mode, sensitive in (("collage", True), ("latest", False), ("arrival", False)):
        short = modes.state_key(_ctx(db, images, tmp_path, mode, lookback_hours=24))
        long = modes.state_key(_ctx(db, images, tmp_path, mode, lookback_hours=72))
        assert (short != long) is sensitive


def test_the_key_carries_what_the_page_is_drawn_from(tmp_path, images):
    db = _db(tmp_path / "b.db", [_row(1, 10, 1)])
    base = _ctx(db, images, tmp_path, "latest")
    for change in ({"show_names": False}, {"label_font": "bitter"}, {"label_size": "large"}):
        assert modes.state_key(_ctx(db, images, tmp_path, "latest", **change)) != modes.state_key(
            base
        )


def test_switching_mode_changes_the_page(tmp_path, images):
    db = _db(tmp_path / "b.db", [_row(1, 10, 1), _row(2, 11, 2)])
    keys = {modes.state_key(_ctx(db, images, tmp_path, m)) for m in modes.MODES}
    assert len(keys) == len(modes.MODES)


def test_a_render_is_cached_until_its_key_moves(tmp_path, images):
    db = _db(tmp_path / "b.db", [_row(1, 10, 1)])
    ctx = _ctx(db, images, tmp_path, "latest")
    assert modes.png_bytes(ctx) is modes.png_bytes(ctx)
    assert modes.png_bytes(_ctx(db, images, tmp_path, "arrival")) != modes.png_bytes(ctx)
