"""Mode invariants. The keys matter more than the pixels: a key that moves on
every detection would spend the day refreshing e-ink, and a key that never moves
would freeze the frame."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest
from PIL import Image

from fugleramme import fake, modes
from fugleramme.api import ApiSource
from fugleramme.languages import namer
from fugleramme.picks import Picks
from fugleramme.settings import Settings

NOW = datetime.now().astimezone()
BLACKBIRD, TIT = "Turdus merula", "Parus major"


def _row(id_: int, name: str, ago_hours: float) -> fake.Detection:
    return fake.Detection(id_, NOW - timedelta(hours=ago_hours), name, 0.9, False)


def _heard(source: ApiSource, rows: list, row: fake.Detection) -> None:
    """A new detection reaches a running fake, and the source is asked again
    rather than answering from its few seconds of memory."""
    rows.insert(0, row)
    source._cache.clear()


@pytest.fixture
def images(tmp_path):
    """Two species with artwork, in a style of their own."""
    style = tmp_path / "classic"
    (style / "birds").mkdir(parents=True)
    for key in ("turdus-merula", "parus-major"):
        Image.new("RGBA", (120, 90), (40, 40, 40, 255)).save(style / "birds" / f"{key}.png")
    (style / "perches").mkdir()
    Image.new("RGBA", (80, 60), (20, 20, 20, 255)).save(style / "perches" / "twig.png")
    return tmp_path


def _ctx(source, images, tmp_path, mode, **overrides):
    settings = Settings(mode=mode, **overrides)
    return modes.context(
        source,
        images,
        Picks(tmp_path / "artwork.json"),
        settings,
        namer("sci", "", tmp_path),
        (400, 300),
        textured=False,
    )


def test_every_mode_is_offered_and_the_default_is_the_collage():
    assert modes.DEFAULT_MODE == "collage"
    assert list(modes.MODES) == ["collage", "latest", "arrival"]
    assert [k for k, m in modes.MODES.items() if m.windowed] == ["collage"]
    assert modes.mode_of("gone") is modes.MODES["collage"]


@pytest.mark.parametrize("mode", list(modes.MODES))
def test_every_mode_draws_something(tmp_path, images, source, mode):
    detections = source(rows=[_row(2, TIT, 2), _row(1, BLACKBIRD, 1)])
    page = modes.render(_ctx(detections, images, tmp_path, mode))
    assert np.asarray(page).std() > 1


@pytest.mark.parametrize("mode", list(modes.MODES))
def test_an_empty_record_falls_back_to_the_perch(tmp_path, images, source, mode):
    page = modes.render(_ctx(source(rows=[]), images, tmp_path, mode))
    assert np.asarray(page).std() > 1  # the branch, not bare paper


def test_the_latest_bird_holds_the_page_while_the_same_bird_calls(tmp_path, images, detector):
    rows = [_row(1, BLACKBIRD, 2)]
    url, _httpd = detector(rows=rows)
    detections = ApiSource(url)
    before = modes.state_key(_ctx(detections, images, tmp_path, "latest"))

    _heard(detections, rows, _row(2, BLACKBIRD, 1))
    assert modes.state_key(_ctx(detections, images, tmp_path, "latest")) == before


def test_the_latest_bird_changes_the_page_when_the_species_changes(tmp_path, images, detector):
    rows = [_row(1, BLACKBIRD, 2)]
    url, _httpd = detector(rows=rows)
    detections = ApiSource(url)
    before = modes.state_key(_ctx(detections, images, tmp_path, "latest"))

    _heard(detections, rows, _row(2, TIT, 1))
    assert modes.state_key(_ctx(detections, images, tmp_path, "latest")) != before


def test_the_latest_bird_skips_a_species_it_cannot_draw(tmp_path, images, source):
    (images / "classic" / "birds" / "parus-major.png").unlink()
    detections = source(rows=[_row(2, TIT, 1), _row(1, BLACKBIRD, 2)])
    assert modes.state_key(_ctx(detections, images, tmp_path, "latest"))[-1][0] == BLACKBIRD


def test_the_collage_holds_the_page_when_a_bird_already_on_it_calls_again(
    tmp_path, images, detector
):
    """species_since ranks by count, so re-hearing a bird can overtake another
    and reorder the window. The set is the same, so the page must be too."""
    rows = [_row(3, BLACKBIRD, 1), _row(2, TIT, 2), _row(1, TIT, 2)]
    url, _httpd = detector(rows=rows)
    detections = ApiSource(url)
    before = modes.state_key(_ctx(detections, images, tmp_path, "collage"))

    for id_ in (4, 5):
        _heard(detections, rows, _row(id_, BLACKBIRD, 0))

    assert detections.species_since()[0][0] == BLACKBIRD  # the ranking did flip
    assert modes.state_key(_ctx(detections, images, tmp_path, "collage")) == before


def test_the_newest_arrival_is_the_latest_first_ever(tmp_path, images, source):
    detections = source(rows=[_row(3, BLACKBIRD, 1), _row(2, TIT, 100), _row(1, BLACKBIRD, 200)])
    assert modes.state_key(_ctx(detections, images, tmp_path, "arrival"))[-1][0] == TIT


def test_only_the_collage_reads_the_lookback_window(tmp_path, images, source):
    detections = source(rows=[_row(2, BLACKBIRD, 1), _row(1, TIT, 400)])
    for mode, sensitive in (("collage", True), ("latest", False), ("arrival", False)):
        short = modes.state_key(_ctx(detections, images, tmp_path, mode, lookback_hours=24))
        long = modes.state_key(_ctx(detections, images, tmp_path, mode, lookback_hours=720))
        assert (short != long) is sensitive


def test_the_key_carries_what_the_page_is_drawn_from(tmp_path, images, source):
    detections = source(rows=[_row(1, BLACKBIRD, 1)])
    base = _ctx(detections, images, tmp_path, "latest")
    for change in ({"show_names": False}, {"label_font": "bitter"}, {"label_size": "large"}):
        assert modes.state_key(
            _ctx(detections, images, tmp_path, "latest", **change)
        ) != modes.state_key(base)


def test_switching_mode_changes_the_page(tmp_path, images, source):
    detections = source(rows=[_row(2, TIT, 2), _row(1, BLACKBIRD, 1)])
    keys = {modes.state_key(_ctx(detections, images, tmp_path, m)) for m in modes.MODES}
    assert len(keys) == len(modes.MODES)


def test_a_render_is_cached_until_its_key_moves(tmp_path, images, source):
    detections = source(rows=[_row(1, BLACKBIRD, 1)])
    ctx = _ctx(detections, images, tmp_path, "latest")
    assert modes.png_bytes(ctx) is modes.png_bytes(ctx)
    assert modes.png_bytes(_ctx(detections, images, tmp_path, "arrival")) != modes.png_bytes(ctx)
